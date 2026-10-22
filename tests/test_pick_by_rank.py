"""Among a session's marks, a run's executor and reviewer follow the matrix's rank for the role,
then what their providers have left; the writer's own model last.

The matrix every pick reads is the one `ak models` or the tick last computed and stored in
`state/matrix.json` (`matrix.refresh`), computed again only once a board answered
anew or the config's models or the harnesses installed changed; `matrix.rank` reads each
configured model's place for a role off it, None where the boards have nothing on it.
`usage.pick_order` puts the ranked models first: those within `within` of the best of them, the
cheapest first, then the others by quality, budget only among models ranked alike or by nothing,
a model on credits after every one with a window left, and a spent model out; the reviewer's
rank is the review score's.

Offline: the boards answered by bytes, the catalogs and installed harnesses faked
(tests/test_model_rows.py), fake meters, a throwaway HOME.
"""

import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, config, matrix, staffing, usage, watch
import test_model_matrix as boards_test
import test_model_rows as rows_test

# Artificial Analysis rows with the index per effort, Terminal-Bench, which builds, and two
# measures of review
OPUS = {"terminalBench40": 0.6, "deepsecBench": 0.27, "omniscience": 46}
MORE = [{"name": "Claude Opus 5.5 (max)", **OPUS, "intelligenceIndex": 58},
        {"name": "Claude Opus 5.5 (xhigh)", **OPUS, "intelligenceIndex": 56,
         "intelligenceIndexCostPerTask": {"cost": {"total": 2.5}}},
        {"name": "GPT 6 Astra (max)", "terminalBench40": 0.25, "intelligenceIndex": 53}]

def meters(**used):
    """Fake providers, each with one weekly meter `used` percent in."""
    return {name: {"meters": [{"name": "weekly_all", "used": pct, "pace": pct - 50, "elapsed": 50,
                               "window_secs": 604800, "resets_at": time.time() + 302400}],
                   "resets": 0} for name, pct in used.items()}


class PickByRank(Sandbox):
    def setUp(self):
        super().setUp()
        rows_test.prepare(self)
        self.stack.enter_context(patch.object(boards_test, "TABLE", boards_test.TABLE.replace(
            "gpt-6-astra,93.7,", "gpt-6-astra,93.7,40.0")))
        boards_test.AA[:] = [entry for entry in boards_test.AA
                                     if not entry["name"].startswith(("Claude Opus 5.5", "GPT 6 Astra"))] + MORE
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        self.stack.enter_context(patch.object(usage, "readiness", side_effect=lambda cfg, read: read))
        self.cfg["defaults"]["workers"] = ["astra", "opus", "fable"]
        self.cfg["defaults"]["reviewers"] = ["astra", "opus", "fable"]
        self.cfg["models"]["astra"]["effort"] = "max"          # the effort the boards scored

    def test_the_matrix_is_stored_once_and_computed_again_only_on_news(self):
        _, table = matrix.refresh(self.cfg, now=10000)
        held = json.loads(matrix.cache_path().read_text())["matrix"]
        self.assertEqual(held["computed_at"], 10000)
        # xhigh as good as max, and priced
        self.assertEqual(matrix.row_label(matrix.recommended(held["rows"])["execute"][0]),
                         "opus @ xhigh")
        self.assertEqual(matrix.stored()["config"], matrix.config_key(self.cfg))
        # scores stored under another scoring rule are read scored afresh, by a pick as well
        stale = json.loads(matrix.cache_path().read_text())
        for held in stale["matrix"]["rows"]:
            held["scores"] = {role: {"score": 100.0, "measures": 1} for role in matrix.ROLES}
        matrix.cache_path().write_text(json.dumps(stale))
        self.assertEqual(matrix.rank(self.cfg, "execute")["astra"][0], 1)
        with patch.object(matrix, "rows", side_effect=AssertionError("computed again")):
            again = matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR - 1)
        self.assertEqual([(matrix.row_label(row), row["scores"]) for row in again[1]],
                         [(matrix.row_label(row), row["scores"]) for row in table])
        # a board answering anew, or a model added, computes it again
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR)
        self.assertEqual(matrix.stored()["computed_at"], 10000 + boards.FRESH_FOR)
        self.cfg["models"]["astra"]["effort"] = "xhigh"
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 1)
        self.assertEqual(matrix.stored()["computed_at"], 10000 + boards.FRESH_FOR + 1)
        # and so does a harness back from a moment missing in an upgrade swap, even one back
        # while the catalogs were read
        present, catalog = config.harness_present.side_effect, config.catalog.side_effect
        opus = self.cfg["models"]["opus"]["harness"]
        config.harness_present.side_effect = lambda harness: harness != opus and present(harness)
        def back(harness):
            config.harness_present.side_effect = present
            return catalog(harness)
        config.catalog.side_effect = back
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 2)
        config.catalog.side_effect = catalog
        self.assertIsNone(matrix.rank(self.cfg, "execute")["opus"])
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 3)
        self.assertIsNotNone(matrix.rank(self.cfg, "execute")["opus"])
        # the tick never reads the boards: the models screen and `ak models` do, when asked
        self.assertNotIn("the boards pass did not run",
                         {what for what, _, _ in watch.local_passes({}, False, print)})

    def test_each_configured_model_s_place_for_a_role_is_read_off_the_stored_matrix(self):
        self.assertEqual(matrix.rank(self.cfg, "execute"),
                         {name: None for name in config.offered(self.cfg)})   # nothing computed yet
        matrix.refresh(self.cfg, now=10000)
        ranks = matrix.rank(self.cfg, "execute")
        scores = {(row["model"], row["effort"]): row["scores"]["execute"] for row in matrix.stored()["rows"]}
        # opus @ xhigh is as good as the best: first by what a task of Artificial Analysis's
        # index run cost at xhigh, then its quality; astra @ max is under the best by more than
        # `within`: after every row as good, by quality
        self.assertEqual(ranks["opus"], (0, 0, 2.5, -scores[("claude-opus-5-5", "xhigh")]["score"]))
        self.assertEqual(ranks["astra"], (1, 0, 0.0, -scores[("gpt-6-astra", "max")]["score"]))
        self.assertLess(scores[("gpt-6-astra", "max")]["score"], 100 - matrix.within(self.cfg))
        self.assertIsNone(ranks["fable"])                     # no board has Fable 5.1
        self.assertIsNone(ranks["gemini"])
        self.assertEqual(matrix.rank(self.cfg, "review")["opus"][0], 0)
        # the row at the effort the config runs the model at in that role
        self.cfg["models"]["opus"]["review_effort"] = "max"
        matrix.refresh(self.cfg, now=10001)
        scores = {(row["model"], row["effort"]): row["scores"]["review"] for row in matrix.stored()["rows"]}
        self.assertNotEqual(scores[("claude-opus-5-5", "max")], scores[("claude-opus-5-5", "xhigh")])
        self.assertEqual(matrix.rank(self.cfg, "review")["opus"][3], -scores[("claude-opus-5-5", "max")]["score"])

    def test_the_pick_follows_the_rank_then_the_budget_and_skips_the_spent(self):
        providers = meters(anthropic=80, openai=10, meta=10, google=10, xai=10, mimo=10)
        # nothing computed yet: budget order, as before
        self.assertEqual(usage.pick_order(self.cfg, providers, quiet=True), ["astra", "opus", "fable"])
        matrix.refresh(self.cfg, now=10000)
        # ranked models first, as good as the best before the rest, whatever the budget; fable,
        # which no board has, after them
        self.assertEqual(usage.pick_order(self.cfg, providers, quiet=True), ["opus", "astra", "fable"])
        self.assertEqual(usage.pick_order(self.cfg, providers, role="reviewer", quiet=True),
                         ["opus", "astra", "fable"])
        # the pair: the top-ranked executor, reviewed by the top-ranked other model
        self.assertEqual(staffing.pick_models(self.cfg, providers, None, None, lambda _: None),
                         ("opus", "astra"))
        # a spent model is out, whatever its rank
        providers = meters(anthropic=100, openai=10, meta=10, google=10, xai=10, mimo=10)
        self.assertEqual(usage.pick_order(self.cfg, providers, quiet=True), ["astra"])
        # budget decides among models ranked by nothing
        self.cfg["defaults"]["workers"] = ["fable", "gemini", "grok"]
        providers = meters(anthropic=10, openai=10, meta=10, google=90, xai=40, mimo=10)
        self.assertEqual(usage.pick_order(self.cfg, providers, quiet=True), ["fable", "grok", "gemini"])


if __name__ == "__main__":
    unittest.main()
