"""`ak models` scores every row per role: a column is the row's share of the best value among
the rows (100 for the best; zero or below is 0 and still counts); a role's score is the mean of
the role's measures the row has, said with how many it rests on (`97 of 3`); a row with none of
a role's measures has no score for it.  The table lists the best rows first with `orch`, `exec`
and `review` per row and says, dim, what each role is scored on.  Rows are made by hand here;
tests/test_model_rows.py scores the rows the boards' answers make."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import matrix, terminal

CODING = "aa.evaluations.artificial_analysis_coding_index"
AGENTIC = "aa.evaluations.artificial_analysis_agentic_index"
INTELLIGENCE = "aa.evaluations.artificial_analysis_intelligence_index"


def row(name, model, effort, **values):
    return {"harness": "acme", "model": model, "effort": effort, "name": name, "matched": {},
            "roles": list(matrix.ROLES) if name else [], "values": values}


class ModelScores(unittest.TestCase):
    def test_a_score_is_the_mean_share_of_the_best_over_the_measures_the_row_has(self):
        best = row("pro", "acme-pro", "max", **{CODING: 60, AGENTIC: 70, INTELLIGENCE: 58},
                   **{"livebench.coding": 96.3, "livebench.long_horizon": 85, "livebench.reasoning": 70,
                      "arena.agent": 0.17, "arena.agent_steerability": 0.2, matrix.SPEED: 95})
        mini = row(None, "acme-mini", None, **{CODING: 25, AGENTIC: 40, INTELLIGENCE: 53},
                   **{"livebench.coding": 93.7, "arena.agent": -0.05, "aa.evaluations.hle": 99})
        matrix.scored([best, mini])
        self.assertEqual(best["scores"], {role: {"score": 100.0, "measures": len(columns)}
                                          for role, columns in matrix.ROLES.items()})
        # execute: coding 25 of 60, agentic 40 of 70, LiveBench coding 93.7 of 96.3, each a share
        # of the best, averaged; the long-horizon suite it has no score on is not counted, and
        # hle, which no role is scored on, is nothing
        self.assertEqual(mini["scores"]["execute"]["measures"], 3)
        self.assertAlmostEqual(mini["scores"]["execute"]["score"],
                               (100 * 25 / 60 + 100 * 40 / 70 + 100 * 93.7 / 96.3) / 3)
        # a net improvement below zero scores 0 and counts; steerability it has none of does not
        self.assertEqual(mini["scores"]["orchestrate"], {"score": 100 * 40 / 70 / 2, "measures": 2})
        # a measure no row has above zero scores 0 and still counts
        table = [{"values": {"arena.agent": -0.1, "livebench.long_horizon": 40}}, {"values": {}}]
        matrix.scored(table)
        self.assertEqual(table[0]["scores"]["orchestrate"], {"score": 50.0, "measures": 2})
        self.assertEqual(table[1]["scores"], {"orchestrate": None, "execute": None, "review": None})
        self.assertEqual(matrix.scored([]), [])

    def test_the_table_lists_the_best_rows_first_with_their_scores(self):
        table = matrix.scored([
            row(None, "acme-mini", None, **{CODING: 30, "livebench.reasoning": 40}),
            row("pro", "acme-pro", "high", **{CODING: 45, matrix.SPEED: 80}),
            row(None, "acme-pro", "max", **{CODING: 60, "livebench.reasoning": 80, matrix.SPEED: 70,
                                             matrix.COST: 4.05}),
            row(None, "acme-old", None)])
        with patch.object(terminal, "width", return_value=100):
            lines = [terminal.plain(line) for line in matrix.render(table, {}).splitlines()]
        self.assertEqual(lines[0].split(), ["model", "harness", "id", "orch", "exec", "review",
                                            "tok/s", "$/task"])
        self.assertRegex(lines[1], r"^- +acme +acme-pro @ max +- +100 of 1 +100 of 2 +70 +4\.05$")
        self.assertRegex(lines[2], r"^pro +acme +acme-pro @ high +- +75 of 1 +75 of 1 +80 +-$")
        self.assertRegex(lines[3], r"^- +acme +acme-mini +- +50 of 1 +50 of 2 +- +-$")
        self.assertRegex(lines[4], r"^- +acme +acme-old +- +- +- +- +-$")
        text = "\n".join(lines)
        self.assertIn("recommended: execute acme-pro @ max (100 of 1) · review acme-pro @ max (100 of 2)", text)
        self.assertIn("a score is the mean share of the best row over the measures", text)
        self.assertIn("execute, 4 measures: aa.evaluations.artificial_analysis_coding_index "
                      "(coding across evaluations)", text)
        self.assertIn("no board row: acme-old", text)
        # the notes stay dim on every line they wrap onto
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "colour_depth", return_value=256):
            notes = matrix.render(table, {}).splitlines()[6:-1 - len(matrix.BOARDS)]
        self.assertGreater(len(notes), 1 + len(matrix.ROLES))
        self.assertEqual([line for line in notes if not line.startswith("\x1b[")], [])


if __name__ == "__main__":
    unittest.main()
