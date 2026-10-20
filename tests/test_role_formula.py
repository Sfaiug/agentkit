"""A role's score is 100 less the mean of the points a row is behind the best on each board over
the role's measures (`matrix.ROLES`), all weighted alike, given at least half of them: a percent
in percentage points, a share in hundredths, a rating as how far under half its wins against the
best would be.  The best is the whole board's, models nobody here runs included; a measure read
off a higher effort adds what the intelligence index lost on the way down
(tests/test_nearest_effort.py), and one the board never ran the model on counts as the board's
typical gap, the median over its rows.  The cheapest row within `within` of the best is
recommended, and the table says how.  Rows and boards are made by hand."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import boards, matrix, terminal

AA, ARENA, LIVEBENCH = boards.BOARDS
TB, OMNI, DEEPSEC = "aa.terminalBench40", "aa.omniscience", "aa.deepsecBench"
FACTS, STYLE = "arena.text_factuality.coding", "arena.text_style_control.coding"


def board_row(model, effort=None, **values):
    return {"model": model, "effort": effort, "values": values}


def row(effort, values, drops=None):
    return {"harness": "acme", "model": "acme-5", "effort": effort, "name": None, "roles": [],
            "values": values, "drops": drops or {}, "matched": {}}


def perfect(**values):
    """`values` as the bests of boards whose every row is the best."""
    return {column: {"best": value, "typical": 0} for column, value in values.items()}


class Points(unittest.TestCase):
    def test_each_measure_is_the_points_behind_its_whole_boards_best(self):
        # the best of each board is a model nobody here runs
        held = {LIVEBENCH: {"rows": [board_row("Other", **{"livebench.coding": 90,
                                                            "livebench.long_agentic": 60,
                                                            "livebench.reasoning": 80})]},
                ARENA: {"rows": [board_row("Other", **{"arena.agent_bash_reliability": 0.2,
                                                       "arena.webdev": 1800, FACTS: 1600,
                                                       STYLE: 1600})]},
                AA: {"rows": [board_row("Other", "max", **{OMNI: 46, DEEPSEC: 0.48}),
                              board_row("Worse", "max", **{OMNI: 26, DEEPSEC: 0.1})]}}
        best = matrix.bests(held)
        # the board's typical gap is the median of its rows' points behind
        self.assertEqual(best[OMNI], {"best": 46, "typical": 10})
        self.assertEqual(best[DEEPSEC], {"best": 0.48, "typical": 19})
        mine = row("max", {"livebench.coding": 80, "livebench.long_agentic": 60,
                           "arena.agent_bash_reliability": 0.1, "arena.webdev": 1400,
                           "livebench.reasoning": 70, FACTS: 1600, STYLE: 1600, OMNI: 36,
                           DEEPSEC: 0.27, "aa.someOtherNumber": 3})
        matrix.scored([mine], best)
        # execute: 10 percentage points, none, 10 hundredths, and 400 rating points behind,
        # which wins 1 in 11 against the best: 50 less 9.09 points; Terminal-Bench, which no
        # board has, counts for nothing
        self.assertEqual(mine["scores"]["execute"]["measures"], 4)
        self.assertAlmostEqual(mine["scores"]["execute"]["score"],
                               100 - (10 + 0 + 10 + 100 * (0.5 - 1 / 11)) / 4)
        # review: 10 points of reasoning, two ratings level, 10 points of the Omniscience
        # Index and 21 hundredths of DeepsecBench
        self.assertEqual(mine["scores"]["review"]["measures"], 5)
        self.assertAlmostEqual(mine["scores"]["review"]["score"], 100 - (10 + 0 + 0 + 10 + 21) / 5)
        # one of orchestrate's four measures is under half of them
        self.assertIsNone(mine["scores"]["orchestrate"])
        # a measure read off a higher effort adds what the index lost on the way down
        mine["drops"] = {"livebench.coding": 4.0}
        matrix.scored([mine], best)
        self.assertAlmostEqual(mine["scores"]["execute"]["score"],
                               100 - (14 + 0 + 10 + 100 * (0.5 - 1 / 11)) / 4)
        # a measure the board never ran the model on counts as the board's typical gap, and
        # not among the measures the row has
        untested = row("max", {**mine["values"]})
        del untested["values"][DEEPSEC]
        matrix.scored([untested], best)
        self.assertEqual(untested["scores"]["review"]["measures"], 4)
        self.assertAlmostEqual(untested["scores"]["review"]["score"],
                               100 - (10 + 0 + 0 + 10 + 19) / 5)
        self.assertEqual(matrix.scored([], best), [])


LIVEBENCH_MAX = {"livebench.coding": 90, "livebench.long_agentic": 60}
# max, and high and medium reading LiveBench's max row 4 and 7 points down the index
TABLE = [row(effort, {**LIVEBENCH_MAX, TB: tb, matrix.COST: cost},
             {column: drop for column in LIVEBENCH_MAX})
         for effort, drop, tb, cost in (("max", 0, 0.6, 5), ("high", 4, 0.55, 2),
                                        ("medium", 7, 0.52, 1))]
matrix.scored(TABLE, perfect(**LIVEBENCH_MAX, **{TB: 0.6}))


class Band(unittest.TestCase):
    def test_the_cheapest_within_the_band_of_the_best_is_recommended(self):
        scores = [row["scores"]["execute"]["score"] for row in TABLE]
        self.assertEqual(scores[0], 100)
        self.assertAlmostEqual(scores[1], 100 - (4 + 4 + 5) / 3)
        self.assertAlmostEqual(scores[2], 100 - (7 + 7 + 8) / 3)
        # max and high are within 5 of the best, and high's index run cost 2 to max's 5
        self.assertEqual([matrix.row_label(row) for row in matrix.recommended(TABLE, 5)["execute"]],
                         ["acme-5 @ high"])
        self.assertEqual([matrix.row_label(row) for row in matrix.recommended(TABLE, 8)["execute"]],
                         ["acme-5 @ medium"])

    def test_the_table_says_how_a_row_is_scored(self):
        with patch.object(terminal, "width", return_value=100):
            lines = [terminal.plain(line) for line in
                     matrix.render(TABLE, {}, band=5).splitlines()]
        self.assertEqual(lines[0].split(), ["model", "harness", "id", "orch", "exec", "review",
                                            "cost", "$/task"])
        self.assertRegex(lines[1], r"^- +acme +acme-5 @ max +- +100 of 3 +- +5 +-$")
        text = "\n".join(lines)
        self.assertIn("recommended: execute acme-5 @ high (96 of 3)", text)
        self.assertIn("a row's quality for a role is 100 less the mean of the points it is behind",
                      text)
        self.assertIn("a measure the board never ran the model on counts as the board's typical gap",
                      text)


if __name__ == "__main__":
    unittest.main()
