"""A board's name that is the model with a qualifier in brackets matches the model, its effort
read among the bracket's words.

Artificial Analysis names a model's variants `Acme 5 (Max, Default Fallback)`: one word of the
bracket is the effort and the rest qualifies the model.  `split_effort` reads the effort off the
bracket and keeps the other words on the name; a model no board names exactly, nor as a stem it
extends with a version, matches the one board name that is the model with a qualifier, so the
variant's numbers reach the matrix row.  Where the board names the model exactly too, the exact
name wins; two qualified names stand for nothing, and the config entry's `benchmark` still names
one.  An Arena row naming a harness other than Arena's own, in its name or key, is no row: it
measures the model inside another program, and as a qualified name it would stand for the model.

Offline: the boards' rows and Arena's dataset pages are handed in, the harness manifests, catalogs and the installed
harnesses are faked, and the config is the sandbox's.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, config, matrix
from test_model_matrix import ARENA, Boards

NAMES = ("Acme 5 (Max, Default Fallback)", "Acme 5 (Low, Default Fallback)", "Acme 4 (high)",
         "Acme 4 (Non-reasoning, High)", "Beta 2 (Fast, max)", "Beta 2 (Slow, max)")
CATALOGS = {"claude": [{"id": "acme-5", "efforts": ["low", "high", "max"]},
                       {"id": "acme-4", "efforts": ["none", "high"]},
                       {"id": "beta-2", "efforts": ["max"]}]}


def board(names):
    """A board's rows off its model names, each valued by its place in `names`."""
    return [{"model": model, "effort": effort, "values": {"aa.score": n}}
            for n, (model, effort) in enumerate(map(boards.split_effort, names), 1)]


def index(rows):
    return {matrix.normal(row["model"]): [r for r in rows if matrix.normal(r["model"])
                                          == matrix.normal(row["model"])] for row in rows}


class QualifiedNames(Sandbox):
    def test_the_effort_is_one_word_of_the_bracket_and_the_others_stay_on_the_name(self):
        self.assertEqual(boards.split_effort("Acme 5 (Max, Default Fallback)"),
                         ("Acme 5 (Default Fallback)", "max"))
        self.assertEqual(boards.split_effort("Acme 5 (Daybreak Blue, xhigh)"),
                         ("Acme 5 (Daybreak Blue)", "xhigh"))
        self.assertEqual(boards.split_effort("Acme 4 (Non-reasoning, High)"), ("Acme 4 (High)", "none"))
        self.assertEqual(boards.split_effort("Acme 5 (Max, Default Fallback) (0813)"),
                         ("Acme 5 (Default Fallback) (0813)", "max"))
        self.assertEqual(boards.split_effort("Acme 5 (max)"), ("Acme 5", "max"))      # as before
        self.assertEqual(boards.split_effort("Acme 5 (0813)"), ("Acme 5 (0813)", None))

    def test_the_one_qualified_name_matches_the_model_the_board_has_no_other_name_for(self):
        held = index(board(NAMES))
        self.assertEqual([(row["model"], row["effort"]) for row in matrix.found(held, "acme-5")],
                         [("Acme 5 (Default Fallback)", "max"), ("Acme 5 (Default Fallback)", "low")])
        found = matrix.found(held, "acme-5")
        self.assertEqual(matrix.placed(found, "low", None, {})[0]["values"], {"aa.score": 2})
        self.assertIsNone(matrix.placed(found, "high", None, {}))   # no index says what high loses
        # the exact name wins over a qualified one
        self.assertEqual([row["values"] for row in matrix.found(held, "acme-4")], [{"aa.score": 3}])
        # two qualified names stand for nothing; the config's benchmark still names one
        self.assertEqual(matrix.found(held, "beta-2"), [])
        self.assertEqual([row["values"] for row in matrix.found(held, "beta-2", "Beta 2 (Slow)")],
                         [{"aa.score": 6}])

    def test_the_variant_s_numbers_reach_the_model_s_row(self):
        self.stack.enter_context(patch.object(config, "manifests", return_value=[("claude", {})]))
        self.stack.enter_context(patch.object(config, "harness_present", return_value=True))
        self.stack.enter_context(patch.object(config, "catalog", side_effect=CATALOGS.__getitem__))
        self.cfg["models"] = {"acme": {"harness": "claude", "model": "acme-5", "effort": "max",
                                       "provider": "anthropic"}}
        boards = {"artificialanalysis.ai": {"rows": board(NAMES)},
                  "arena.ai": {"rows": board(["Acme 5 (max)"])}}
        rows = {matrix.row_label(row): row
                for row in matrix.rows(self.cfg, boards, matrix.present())}
        self.assertEqual(rows["acme @ max"]["matched"], {
            "artificialanalysis.ai": {"model": "Acme 5 (Default Fallback)", "effort": "max"},
            "arena.ai": {"model": "Acme 5", "effort": "max"}})
        self.assertEqual(rows["acme @ max"]["values"]["aa.score"], 1)
        self.assertEqual(rows["acme-5 @ low"]["values"]["aa.score"], 2)
        self.assertNotIn("acme-5 @ high", rows)       # no board lists it, no role runs it
        self.assertEqual(rows["acme-4 @ high"]["values"]["aa.score"], 3)
        self.assertEqual(rows["beta-2"]["matched"], {})       # one row at none, nothing matched

    def test_an_arena_row_run_inside_another_harness_is_not_read(self):
        self.stack.enter_context(patch.object(boards, "fetch_bytes", Boards()))
        with patch.dict(ARENA, agent=[
                ("Zeta 6 (xHigh, Codex Harness)", "overall", 0.5),
                ("Zeta 6 Max Code", "overall", 0.45, {"model_key": "zeta-6-max-code-codex-harness"}),
                ("Zeta 6 (xHigh)", "overall", 0.4, {"model_key": "zeta-6-xhigh-arena-harness"})]):
            rows = boards.collect(now=10000)["arena.ai"]["rows"]
        self.assertEqual([row["values"] for row in rows if row["model"].startswith("Zeta 6")],
                         [{"arena.agent": 0.4}])
        self.assertEqual(matrix.found(index(rows), "zeta-6"), [rows[0]])   # Arena's own harness


if __name__ == "__main__":
    unittest.main()
