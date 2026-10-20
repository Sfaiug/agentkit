"""A row of the matrix takes each board's row at its effort, else the nearest above, each of its
measures adding what Artificial Analysis's intelligence index loses between the two efforts
(nothing from that board where the index is missing at either), else the nearest below as it
is, never credited upward.  A board row naming no effort stands at the model's highest effort
with an index, or at every effort where it has none; a board name ending in an effort word is
the model at that effort; a price is read only off a board's row at the row's own effort.
Boards made by hand, the catalog faked, a throwaway HOME."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards, config, matrix

AA, ARENA, LIVEBENCH = boards.BOARDS
INTEL, COST = matrix.INTEL, matrix.COST
CATALOG = [{"id": "acme-5", "efforts": ["low", "medium", "high", "xhigh", "max"]},
           {"id": "acme-9", "efforts": ["high", "max"]}]


def board_row(model, effort=None, **values):
    return {"model": model, "effort": effort, "values": values}


BOARDS = {
    AA: {"rows": [board_row("Acme 5", "max", **{INTEL: 60, COST: 5.0, "aa.score": 0.6}),
                  board_row("Acme 5", "high", **{INTEL: 56, COST: 2.0}),
                  board_row("Acme 5", "medium", **{INTEL: 53, COST: 1.0}),
                  board_row("Acme 5", "low", **{INTEL: 50, COST: 0.5})]},
    # Arena's name ends in its effort; LiveBench names none, so it stands at max, the highest
    # effort Artificial Analysis has an index for
    ARENA: {"rows": [board_row("acme-5-xhigh", **{"arena.agent_bash_reliability": 0.2})]},
    LIVEBENCH: {"rows": [board_row("acme-5", **{"livebench.coding": 90, boards.TASK_COST: 3.0}),
                         board_row("acme-9", **{"livebench.coding": 70,
                                                boards.TASK_COST: 1.5})]}}


class NearestEffort(Sandbox):
    def test_a_row_reads_its_effort_else_the_nearest_above_less_the_index_else_below(self):
        self.stack.enter_context(patch.object(config, "catalog", return_value=CATALOG))
        provider = config.model(self.cfg, "opus")["provider"]
        self.cfg["models"] = {"acme": {"harness": "acme", "model": "acme-5", "effort": "medium",
                                       "provider": provider}}
        table = {matrix.row_label(row): row for row in matrix.rows(self.cfg, BOARDS, ["acme"])}
        self.assertEqual(list(table), ["acme-5 @ max", "acme-5 @ xhigh", "acme-5 @ high",
                                       "acme @ medium", "acme-5 @ low", "acme-9"])
        top = table["acme-5 @ max"]
        # max: Artificial Analysis's row and LiveBench's at it, prices and all; Arena's below
        # it as it is
        self.assertEqual(top["values"], {INTEL: 60, COST: 5.0, "aa.score": 0.6,
                                         "livebench.coding": 90, boards.TASK_COST: 3.0,
                                         "arena.agent_bash_reliability": 0.2})
        self.assertEqual(top["drops"], {})
        self.assertEqual(top["matched"], {AA: {"model": "Acme 5", "effort": "max"},
                                          ARENA: {"model": "acme-5-xhigh", "effort": "xhigh"},
                                          LIVEBENCH: {"model": "acme-5", "effort": None}})
        # xhigh: Arena's own row; the others above it, where the index has no xhigh, say nothing
        self.assertEqual(table["acme-5 @ xhigh"]["values"], {"arena.agent_bash_reliability": 0.2})
        # high: its own Artificial Analysis row, LiveBench's max row 60 less 56 of the index
        # further behind and never its price, and Arena's xhigh above it nothing, the index
        # missing there
        high = table["acme-5 @ high"]
        self.assertEqual(high["values"], {INTEL: 56, COST: 2.0, "livebench.coding": 90})
        self.assertEqual(high["drops"], {"livebench.coding": 4})
        self.assertEqual(table["acme-5 @ low"]["drops"], {"livebench.coding": 10})
        # a model Artificial Analysis has no index for: its one row stands at every effort
        self.assertEqual(table["acme-9"]["values"], {"livebench.coding": 70, boards.TASK_COST: 1.5})

    def test_only_a_lower_effort_is_read_as_it_is(self):
        rows = [board_row("Acme 5", "low", **{"aa.score": 1})]
        self.assertEqual(matrix.placed(rows, "max", "low", {"low": 50, "max": 60}),
                         (rows[0], 0.0))
        self.assertIsNone(matrix.placed([], "max", None, {}))


if __name__ == "__main__":
    unittest.main()
