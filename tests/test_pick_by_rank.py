"""Among a session's marks, a run's executor and reviewer follow the matrix's rank for the role,
then what their providers have left; the writer's own model last.

The matrix every pick reads is the one the models screen or `ak models` last computed and stored in
`state/matrix.json` (`matrix.refresh`), computed again only once a board answered
anew or the config's models or the harnesses installed changed; `matrix.rank` reads each
configured model's place for a role off it, rated once per stored lineup as the models screen
rates it (`matrix.answer`), at the effort the config runs it at there, None where no row is it.
`usage.pick_order` puts the role's pick among the marks first, then the others by quality,
budget only among models ranked alike or by nothing,
a model on credits after every one with a window left, and a spent model out; the reviewer's
rank is the review score's.

Offline: the boards answered by bytes, the catalogs and installed harnesses faked
(tests/test_model_rows.py), or an invented lineup stored (tests/test_matrix_lineup.py's);
fake meters, a throwaway HOME.
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
from agentkit import boards, config, matrix, quality, usage
import test_model_rows as rows_test
from test_matrix_lineup import aa


def meters(**used):
    """Fake providers, each with one weekly meter `used` percent in."""
    return {name: {"meters": [{"name": "weekly_all", "used": pct, "pace": pct - 50, "elapsed": 50,
                               "window_secs": 604800, "resets_at": time.time() + 302400}],
                   "resets": 0} for name, pct in used.items()}


class PickByRank(Sandbox):
    def setUp(self):
        super().setUp()
        rows_test.prepare(self)

    def test_the_lineup_is_stored_once_and_computed_again_only_on_news(self):
        _, lineup = matrix.refresh(self.cfg, now=10000)
        held = json.loads(matrix.cache_path().read_text())["matrix"]
        self.assertEqual((held["computed_at"], held["lineup"]), (10000, lineup))
        self.assertEqual(matrix.stored()["config"], matrix.config_key(self.cfg))
        with patch.object(matrix, "lineup", side_effect=AssertionError("computed again")):
            again = matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR - 1)
        self.assertEqual(again[1], lineup)
        # a board answering anew, or a model added, computes it again
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR)
        self.assertEqual(matrix.stored()["computed_at"], 10000 + boards.FRESH_FOR)
        self.cfg["models"]["astra"]["effort"] = "max"
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 1)
        self.assertEqual(matrix.stored()["computed_at"], 10000 + boards.FRESH_FOR + 1)
        # and so does a harness back from a moment missing in an upgrade swap, even one back
        # while the catalogs were read
        present, catalog = config.harness_present.side_effect, config.catalog.side_effect
        opus = self.cfg["models"]["opus"]["harness"]
        config.harness_present.side_effect = lambda harness: harness != opus and present(harness)
        def back(harness, cfg=None):
            config.harness_present.side_effect = present
            return catalog(harness)
        config.catalog.side_effect = back
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 2)
        config.catalog.side_effect = catalog
        self.assertNotIn(opus, matrix.stored()["harnesses"])
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 3)
        self.assertIn(opus, matrix.stored()["harnesses"])


# Execute's quality here: 100 less how far the two shares are behind the best's, in hundredths.
# Bolt is farthest above the full lineup's line; two marks tie, so the cheaper picks.
ROWS = [("claude-opus-5-5", "Claude Opus 5.5", "high", 0.60, 4.0),        # 100
        ("claude-opus-5-5", "Claude Opus 5.5", "low", 0.50, 2.0),         # 90
        ("gpt-6-astra", "GPT 6 Astra", "high", 0.58, 1.0),                # 98
        ("bolt-2", "Bolt 2", "high", 0.59, 1.5)]                          # 99
OFFERS = {"claude": [{"id": "claude-opus-5-5", "efforts": ["low", "high"]},
                     {"id": "claude-fable-5-1", "efforts": ["high"]}],
          "codex": [{"id": "gpt-6-astra", "efforts": ["high"]}]}


class RankByTheAnswer(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        self.stack.enter_context(patch.object(usage, "readiness", side_effect=lambda cfg, read: read))
        for name in ("opus", "astra", "fable"):
            self.cfg["models"][name]["effort"] = "high"
        self.providers = meters(anthropic=10, openai=90)
        self.lineup = matrix.lineup({"artificialanalysis.ai": {"rows": [
            aa(f"{release}-{effort}", name, effort, release, share, share, cost)
            for release, name, effort, share, cost in ROWS]}}, OFFERS)

    def store(self):
        matrix.cache_path().write_text(json.dumps({"matrix": {"lineup": self.lineup}}))

    def pick(self):
        return usage.pick_order(self.cfg, self.providers, ["opus", "astra", "fable"], quiet=True)

    # nothing ak shows or picks credits speed or cost while the result got worse. [14 Oct]
    def test_the_pick_is_recomputed_among_the_marked_rows(self):
        self.assertEqual(matrix.rank(self.cfg, "execute", ["opus", "fable"]),
                         {"opus": None, "fable": None})          # nothing stored yet
        self.assertEqual(self.pick(), ["opus", "fable", "astra"])     # budget alone
        self.store()
        pick = matrix.answer(self.lineup)["execute"]["pick"]
        self.assertEqual(pick["release"], "bolt-2")
        ranks = matrix.rank(self.cfg, "execute", ["opus", "astra", "fable"])
        self.assertIsNone(ranks["fable"])                         # no row is Fable 5.1
        self.assertEqual(self.pick(), ["astra", "opus", "fable"])
        # A third priced mark moves the line: its farthest row wins, then quality ranks.
        next(row for row in self.lineup if row["release"] == "bolt-2")["yours"] = [{
            key: self.cfg["models"]["fable"][key] for key in ("harness", "model")}]
        self.store()
        self.assertEqual(self.pick(), ["fable", "opus", "astra"])

    def test_a_model_run_at_a_lower_effort_ranks_by_that_effort_s_quality(self):
        self.store()
        self.cfg["models"]["opus"]["exec_effort"] = "low"
        opus = matrix.rank(self.cfg, "execute", ["opus", "astra"])["opus"]
        self.assertEqual(opus[:3], (1, False, 0.0))               # the cheaper wins among two rows
        self.assertAlmostEqual(opus[3], -90)
        self.cfg["models"]["opus"]["exec_effort"] = "max"         # an effort no row is
        self.assertIsNone(matrix.rank(self.cfg, "execute", ["opus"])["opus"])

    def test_new_measurements_reprice_the_same_stored_lineup(self):
        next(row for row in self.lineup if row["release"] == "bolt-2")["yours"] = [{
            key: self.cfg["models"]["fable"][key] for key in ("harness", "model")}]
        self.store()
        names = ["opus", "astra", "fable"]
        with patch.object(matrix, "_task_usage", return_value={}) as measured:
            before = matrix.rank(self.cfg, "execute", names)
            measured.return_value = {"opus": {"high": {"executor": .01}},
                                     "astra": {"high": {"executor": .5}}}
            after = matrix.rank(self.cfg, "execute", names)
        self.assertEqual((before["fable"][0], after["opus"][0]), (0, 0))
        self.assertEqual((before["opus"][0], after["fable"][0]), (1, 1))

    def test_the_role_pick_ranks_first_rated_once(self):
        self.store()
        with patch.object(quality, "rated", wraps=quality.rated) as rated:
            matrix._answered.cache_clear()
            matrix._listed.cache_clear()
            ranks = matrix.rank(self.cfg, "execute", ["opus", "astra"])
            self.assertEqual([ranks[name][:3] for name in ("astra", "opus")],
                             [(0, False, 0.0), (1, False, 0.0)])
            self.assertEqual(self.pick(), ["astra", "opus", "fable"])
            self.assertEqual(self.pick(), ["astra", "opus", "fable"])
        # once per stored lineup for the rank, and once for the model list (matrix.off)
        self.assertEqual(rated.call_count, 2 * len(quality.ROLES))


if __name__ == "__main__":
    unittest.main()
