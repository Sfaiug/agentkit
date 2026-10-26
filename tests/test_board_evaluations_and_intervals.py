"""The boards give what the role formula prices and rates with: every number of an Artificial
Analysis record's Intelligence Index evaluations, under each evaluation's slug, so one task of a
role's own test has a cost; Arena's agent board as `arena.agent`; and each Arena column's 95%
interval beside it, off a rating board's `rating_lower`/`rating_upper` and an agent board's
`score_ci_lower`/`score_ci_upper`, so a lead can be told from chance.

Offline: the pages and dataset pages are handed in through `boards.fetch_bytes`, the models
invented, and a throwaway HOME holds the cache.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import boards
from test_model_matrix import AA, ARENA, Boards

EVALUATIONS = [{"slug": "acme-briefcase", "name": "Acme Briefcase", "score": 0.61,
                "costPerTask": 1.25, "timePerTask": 312, "isAgentic": True},
               {"slug": "acme-terminal", "score": 0.4, "costPerTask": None}]


class EvaluationsAndIntervals(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(boards, "fetch_bytes", Boards()))

    def rows(self, board):
        return {(row["model"], row["effort"]): row["values"]
                for row in boards.collect(now=10000)[board]["rows"]}

    def test_each_evaluation_s_numbers_are_columns_under_its_slug(self):
        record = {"name": "Zeta 3 (max)", "intelligenceIndex": 50,
                  "intelligenceIndexEvaluations": EVALUATIONS}
        with patch.object(sys.modules["test_model_matrix"], "AA", [*AA, record]):
            values = self.rows("artificialanalysis.ai")[("Zeta 3", "max")]
        self.assertEqual(values, {"aa.intelligenceIndex": 50,
                                  "aa.intelligenceIndexEvaluations.acme-briefcase.score": 0.61,
                                  "aa.intelligenceIndexEvaluations.acme-briefcase.costPerTask": 1.25,
                                  "aa.intelligenceIndexEvaluations.acme-briefcase.timePerTask": 312,
                                  "aa.intelligenceIndexEvaluations.acme-terminal.score": 0.4})

    def test_arena_s_agent_board_and_every_column_s_interval(self):
        with patch.dict(ARENA, agent=[("Zeta 3 (max)", "overall", 0.42,
                                       {"score_ci_lower": 0.38, "score_ci_upper": 0.46})],
                        webdev=[("Zeta 3 (max)", "overall", 1500.0,
                                 {"rating_lower": 1490.5, "rating_upper": 1509.5}),
                                ("Zeta 2", "overall", 1400.0)]):
            rows = self.rows("arena.ai")
        self.assertEqual(rows[("Zeta 3", "max")],
                         {"arena.agent": 0.42, "arena.agent.lower95ci": 0.38,
                          "arena.agent.upper95ci": 0.46, "arena.webdev": 1500.0,
                          "arena.webdev.lower95ci": 1490.5, "arena.webdev.upper95ci": 1509.5})
        self.assertEqual(rows[("Zeta 2", None)], {"arena.webdev": 1400.0})   # none given, none read


if __name__ == "__main__":
    unittest.main()
