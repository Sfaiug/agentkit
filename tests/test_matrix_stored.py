"""The matrix the models screen reads is the one it or `ak models` last computed and stored in
`state/matrix.json` (`matrix.refresh`), computed again only once a board answered anew or the
config's models or the harnesses installed changed; a lineup an earlier build stored still
matches the board's rows by their name until then.  The model list (`matrix.off`) rates one
stored lineup once, however often a run picks, and no rating reorders the pick: with no draw,
as here, it keeps the order marked (`usage.pick_order`).

Offline: the boards answered by bytes, the catalogs and installed harnesses faked
(tests/test_model_rows.py), or an invented lineup (tests/test_matrix_lineup.py's); fake meters,
a throwaway HOME.
"""

from contextlib import redirect_stdout
import io
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
from test_key_models_answer import boards as answer_boards
import test_model_rows as rows_test
from test_matrix_lineup import aa


class MatrixStored(Sandbox):
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
        config.harness_present.side_effect = (
            lambda harness, *a, **kw: harness != opus and present(harness, *a, **kw))
        def back(harness, cfg=None):
            config.harness_present.side_effect = present
            return catalog(harness)
        config.catalog.side_effect = back
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 2)
        config.catalog.side_effect = catalog
        self.assertNotIn(opus, matrix.stored()["harnesses"])
        matrix.refresh(self.cfg, now=10000 + boards.FRESH_FOR + 3)
        self.assertIn(opus, matrix.stored()["harnesses"])


# release, name, effort, the board's two shares, board dollars
ROWS = [("claude-opus-5-5", "Claude Opus 5.5", "high", 0.60, 4.0),
        ("claude-opus-5-5", "Claude Opus 5.5", "low", 0.50, 2.0),
        ("gpt-6-astra", "GPT 6 Astra", "high", 0.58, 1.0),
        ("bolt-2", "Bolt 2", "high", 0.59, 1.5)]
OFFERS = {"claude": [{"id": "claude-opus-5-5", "efforts": ["low", "high"]},
                     {"id": "claude-fable-5-1", "efforts": ["high"]}],
          "codex": [{"id": "gpt-6-astra", "efforts": ["high"]}]}


class AStoredLineup(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        for name in ("opus", "astra", "fable"):
            self.cfg["models"][name]["effort"] = "high"
        self.lineup = matrix.lineup({"artificialanalysis.ai": {"rows": [
            aa(f"{release}-{effort}", name, effort, release, share, share, cost)
            for release, name, effort, share, cost in ROWS]}}, OFFERS)

    def test_a_lineup_an_earlier_build_stored_still_matches_by_the_boards_name(self):
        # its `name` the board's and no `board_name`: Opus's dated release matches by name alone
        old = [{**{key: value for key, value in row.items() if key != "board_name"},
                "release": row["release"] + "-20261101", "name": row["board_name"]}
               for row in self.lineup]
        measured = ({}, {"opus": {"high": {"executor": (.01, 1, .01)}}})
        found = matrix.answer(old, cfg=self.cfg, task_usage=measured)["execute"]
        self.assertEqual([row["cost_rule"] for row in found["rated"] if row["release"] ==
                          "claude-opus-5-5-20261101" and row["effort"] == "high"], ["measured"])

    def test_the_model_list_rates_a_stored_lineup_once_however_often_a_run_picks(self):
        matrix.cache_path().write_text(json.dumps({"matrix": {"lineup": self.lineup}}))
        week = {"name": "weekly_all", "pace": 0, "elapsed": 50, "window_secs": 604800,
                "resets_at": time.time() + 302400}
        providers = {"anthropic": {"meters": [{**week, "used": 50}], "resets": 0},
                     "openai": {"meters": [{**week, "used": 10}], "resets": 0}}
        with patch.object(quality, "rated", wraps=quality.rated) as rated:
            matrix._listed.cache_clear()
            for _ in range(2):
                # Astra rated above Opus, with more of its week left: still after it, as marked
                self.assertEqual(usage.pick_order(self.cfg, providers, ["opus", "astra"],
                                                  quiet=True), ["opus", "astra"])
        self.assertEqual(rated.call_count, len(quality.ROLES))

    def test_models_json_does_not_mix_lineups_when_another_refresh_overwrites_matrix_json(self):
        cfg = {**self.cfg, "companies": ["Acme"]}
        held = answer_boards()

        def showing(model, at):
            return {key: {**board, "fetched_at": at,
                          "rows": [row for row in board["rows"] if row["model"] == model]}
                    for key, board in held.items()}

        first, second = showing("Acme Max 5", 10000), showing("Acme Mid 5", 10001)
        refresh = matrix.refresh

        def refresh_then_publish_another(cfg, **kwargs):
            found = refresh(cfg, **kwargs)
            with patch.object(matrix, "collect", return_value=second):
                refresh(cfg, refresh=True, now=10001)
            return found

        with (patch.object(config, "load", return_value=cfg),
              patch.object(matrix, "present", return_value=[]),
              patch.object(matrix, "collect", return_value=first),
              patch.object(matrix, "refresh", side_effect=refresh_then_publish_another),
              redirect_stdout(io.StringIO()) as out):
            self.assertEqual(matrix.main(["--json"]), 0)
        self.assertEqual({row["release"] for row in json.loads(out.getvalue())["execute"]["front"]},
                         {"acme-max-5"})


if __name__ == "__main__":
    unittest.main()
