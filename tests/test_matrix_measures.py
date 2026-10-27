"""What `ak models` rates each role on is pinned here, so it changes only with a visible test
change: the roles, each role's measures in order
with the kind of number each is, the cost of a role's task (`quality`), and that every measure
says what it tests in plain words."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import quality

# what `quality` rates each role on, and the cost of its task
QUALITY = {
    "orchestrate": (("aa.briefcaseBreakdown.overall.elo", "rating"), ("aa.gdpval", "rating"),
                    ("arena.agent", "share"), ("aa.omniscience", "percent"), ("aa.lcr", "share")),
    "execute": (("aa.frontierCode", "share"), ("aa.terminalBench40", "share"),
                ("arena.webdev", "rating")),
    "review": (("aa.deepsecBench", "share"), ("aa.omniscience", "percent"),
               ("aa.gdpPdfAllPass", "share"), ("aa.frontierCode", "share"), ("aa.lcr", "share")),
}
COSTS = {"orchestrate": "aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask",
         "execute": "aa.intelligenceIndexEvaluations.terminalbench-4-0.costPerTask",
         "review": "aa.intelligenceIndexEvaluations.gdp-pdf.costPerTask"}


class MatrixMeasures(unittest.TestCase):
    def test_the_roles_and_their_measures_are_the_pinned_ones(self):
        self.assertEqual({role: tuple((column, kind) for column, kind, _ in measures)
                          for role, measures in quality.ROLES.items()}, QUALITY)
        self.assertEqual(list(quality.ROLES), list(QUALITY))
        self.assertEqual(quality.COSTS, COSTS)
        for measures in quality.ROLES.values():
            for column, kind, why in measures:
                self.assertRegex(column, r"^(aa|arena)\.[A-Za-z0-9_.]+$")
                self.assertIn(kind, quality.SCALES)
                self.assertTrue(why and why[0].islower() and not why.endswith("."), why)


if __name__ == "__main__":
    unittest.main()
