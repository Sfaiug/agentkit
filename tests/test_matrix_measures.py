"""What `ak models` scores each role on is pinned here, so it changes only with a visible test
change and the owner's yes (AGENTS.md, Owner rules): the roles, each role's measures in order,
and that every measure says why in plain words."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import matrix

MEASURES = {
    "orchestrate": ("arena.agent", "arena.agent_steerability",
                    "aa.evaluations.artificial_analysis_agentic_index", "livebench.long_horizon"),
    "execute": ("aa.evaluations.artificial_analysis_coding_index",
                "aa.evaluations.artificial_analysis_agentic_index", "livebench.coding", "livebench.long_horizon"),
    "review": ("aa.evaluations.artificial_analysis_intelligence_index",
               "aa.evaluations.artificial_analysis_coding_index", "livebench.reasoning"),
}


class MatrixMeasures(unittest.TestCase):
    def test_the_roles_and_their_measures_are_the_pinned_ones(self):
        self.assertEqual({role: tuple(column for column, _ in columns)
                          for role, columns in matrix.ROLES.items()}, MEASURES)
        self.assertEqual(list(matrix.ROLES), list(MEASURES))
        for columns in matrix.ROLES.values():
            for column, why in columns:
                self.assertRegex(column, r"^(aa|arena|livebench)\.[a-z0-9_.]+$")
                self.assertTrue(why and why[0].islower() and not why.endswith("."), why)

    def test_a_score_rests_on_the_pinned_measures_alone(self):
        row = {"harness": "h", "model": "m", "effort": None, "name": None, "matched": {},
               "values": {"aa.evaluations.artificial_analysis_coding_index": 50, "aa.evaluations.hle": 90,
                          "livebench.coding": 80}}
        other = {**row, "values": {"aa.evaluations.artificial_analysis_coding_index": 100, "aa.evaluations.hle": 10,
                                   "livebench.coding": 100}}
        matrix.scored([row, other])
        self.assertEqual(row["scores"]["execute"], {"score": 65.0, "measures": 2})   # hle is none of it
        self.assertEqual(row["scores"]["review"], {"score": 50.0, "measures": 1})
        self.assertIsNone(row["scores"]["orchestrate"])


if __name__ == "__main__":
    unittest.main()
