"""`ak models` scores every row per role, on quality and cost alone: a column is the row's share
of the best value among the rows (100 for the best; zero or below is 0 and still counts); a
model's score for a role is the mean share over the role's measures on its row holding the most
of them, and it needs at least half of them; a row's quality is that times what its effort keeps
of it (`kept`): its mean share over the role's measures whose values differ between the model's
efforts, else over the intelligence index, against the model's best effort; a row lacking what
tells the others apart has no score.  It is said with the measures the model's score rests on
(`97 of 3`).  The table lists the best rows first with `orch`, `exec` and `review`, `cost` (what
Artificial Analysis's index run cost) and `$/task` (LiveBench's) per row and says, dim, what each
role is scored on.  Rows are made by hand here; tests/test_model_rows.py scores the rows the
boards' answers make."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import boards, matrix, terminal

CODING = "aa.evaluations.artificial_analysis_coding_index"
AGENTIC = "aa.evaluations.artificial_analysis_agentic_index"
INTELLIGENCE = "aa.evaluations.artificial_analysis_intelligence_index"


def row(name, model, effort, **values):
    return {"harness": "acme", "model": model, "effort": effort, "name": name, "matched": {},
            "roles": list(matrix.ROLES) if name else [], "values": values}


class ModelScores(unittest.TestCase):
    def test_a_score_is_the_mean_share_of_the_best_over_the_measures_the_row_has(self):
        best = row("pro", "acme-pro", "max", **{CODING: 60, AGENTIC: 70, INTELLIGENCE: 58},
                   **{"livebench.coding": 96.3, "livebench.long_agentic": 85, "livebench.reasoning": 70,
                      "arena.agent_task_outcome_explicit": 0.17, "arena.agent_steerability": 0.2})
        mini = row(None, "acme-mini", None, **{CODING: 25, AGENTIC: 40, INTELLIGENCE: 53},
                   **{"livebench.coding": 93.7, "arena.agent_task_outcome_explicit": -0.05, "aa.evaluations.hle": 99})
        # the model's lower efforts: LiveBench's numbers, naming no effort, and the index at that
        # effort; one with nothing that tells it from the others
        high = row(None, "acme-pro", "high", **{INTELLIGENCE: 52, "livebench.coding": 96.3,
                                                "livebench.long_agentic": 85, "livebench.reasoning": 70})
        low = row(None, "acme-pro", "low", **{"livebench.coding": 96.3, "livebench.long_agentic": 85})
        tiny = row(None, "acme-tiny", None, **{CODING: 10})
        matrix.scored([best, mini, high, low, tiny])
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
        # the model's score is its max row's, on every measure; high keeps 52 of 58 of it on the
        # intelligence index, the one measure that tells the efforts apart, for every role
        for role in matrix.ROLES:
            self.assertAlmostEqual(high["scores"][role]["score"], 100 * 52 / 58)
            self.assertEqual(high["scores"][role]["measures"], len(matrix.ROLES[role]))
        # low has nothing that tells it from the others; tiny has under half of any role's measures
        self.assertEqual(low["scores"], {"orchestrate": None, "execute": None, "review": None})
        self.assertEqual(tiny["scores"], {"orchestrate": None, "execute": None, "review": None})
        # a measure no row has above zero scores 0 and still counts
        table = [row(None, "acme-x", None, **{"arena.agent_task_outcome_explicit": -0.1, "livebench.long_agentic": 40}),
                 row(None, "acme-y", None)]
        matrix.scored(table)
        self.assertEqual(table[0]["scores"]["orchestrate"], {"score": 50.0, "measures": 2})
        self.assertEqual(table[1]["scores"], {"orchestrate": None, "execute": None, "review": None})
        self.assertEqual(matrix.scored([]), [])

    def test_the_table_lists_the_best_rows_first_with_their_scores(self):
        table = matrix.scored([
            row(None, "acme-mini", None, **{CODING: 55, "livebench.coding": 88, "livebench.reasoning": 40}),
            row("pro", "acme-pro", "high", **{INTELLIGENCE: 52, "livebench.coding": 90,
                                              "livebench.reasoning": 80, matrix.COST: 2000}),
            row(None, "acme-pro", "max", **{CODING: 60, INTELLIGENCE: 58, "livebench.coding": 90,
                                             "livebench.reasoning": 80, matrix.COST: 4057,
                                             boards.TASK_COST: 4.05}),
            row(None, "acme-old", None)])
        with patch.object(terminal, "width", return_value=100):
            lines = [terminal.plain(line) for line in matrix.render(table, {}, band=15).splitlines()]
        self.assertEqual(lines[0].split(), ["model", "harness", "id", "orch", "exec", "review",
                                            "cost", "$/task"])
        self.assertRegex(lines[1], r"^- +acme +acme-pro @ max +- +100 of 2 +100 of 3 +4057 +4\.05$")
        self.assertRegex(lines[2], r"^- +acme +acme-mini +- +95 of 2 +71 of 2 +- +-$")
        self.assertRegex(lines[3], r"^pro +acme +acme-pro @ high +- +90 of 2 +90 of 3 +2000 +-$")
        self.assertRegex(lines[4], r"^- +acme +acme-old +- +- +- +- +-$")
        text = "\n".join(lines)
        # within 15: the priced row before the unpriced one that scores higher, one row per model
        self.assertIn("recommended: execute pro @ high (90 of 2), as good: acme-mini · "
                      "review pro @ high (90 of 3)", text)
        self.assertIn("a row's quality is its model's score for the role", text)
        self.assertIn("a row within 15 of the best counts as as good", text)
        self.assertIn("execute, 4 measures: aa.evaluations.artificial_analysis_coding_index "
                      "(coding across evaluations)", text)
        self.assertIn("no board row: acme-old", text)
        # the notes stay dim on every line they wrap onto
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "colour_depth", return_value=256):
            notes = matrix.render(table, {}, band=15).splitlines()[6:-1 - len(boards.BOARDS)]
        self.assertGreater(len(notes), 1 + len(matrix.ROLES))
        self.assertEqual([line for line in notes if not line.startswith("\x1b[")], [])


if __name__ == "__main__":
    unittest.main()
