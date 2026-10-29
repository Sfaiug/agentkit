"""What `ak models` rates each role on is pinned here, so it changes only with a visible test
change: the roles, each role's measures in order with the kind of number each is and its weight,
the cost of a role's task (`quality`), how many tasks or questions a measure's error counts, and
that every measure says what it tests in plain words and has a name on the models screen."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import menu, quality

# what `quality` rates each role on, and the cost of its task
QUALITY = {
    "orchestrate": (("aa.automationBenchPartialScore", "share", 0.35),
                    ("arena.agent", "share", 0.3), ("aa.omniscience", "percent", 0.2),
                    ("aa.briefcaseBreakdown.overall.elo", "rating", 0.15)),
    "execute": (("aa.frontierCode20", "share", 0.4), ("arena.agent", "share", 0.4),
                ("aa.terminalBench40", "share", 0.2)),
    "review": (("aa.frontierCode20", "share", 0.8), ("aa.omniscience", "percent", 0.2)),
}
COSTS = {"orchestrate": "aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask",
         "execute": "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask",
         "review": "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask"}
TASKS = {"aa.automationBenchPartialScore": 657, "aa.frontierCode20": 132, "aa.terminalBench40": 66}
OMNISCIENCE_QUESTIONS = 3000


class MatrixMeasures(unittest.TestCase):
    def test_the_roles_and_their_measures_are_the_pinned_ones(self):
        self.assertEqual({role: tuple(measure[:3] for measure in measures)
                          for role, measures in quality.ROLES.items()}, QUALITY)
        self.assertEqual(list(quality.ROLES), list(QUALITY))
        self.assertEqual(quality.COSTS, COSTS)
        self.assertEqual(quality.TASKS, TASKS)
        self.assertEqual(quality.OMNISCIENCE[-1], OMNISCIENCE_QUESTIONS)
        self.assertEqual(set(menu.MEASURES), {column for measures in QUALITY.values()
                                              for column, _, _ in measures})
        for measures in quality.ROLES.values():
            for column, kind, _, why in measures:
                self.assertRegex(column, r"^(aa|arena)\.[A-Za-z0-9_.]+$")
                self.assertIn(kind, quality.SCALES)
                self.assertTrue(why and why[0].islower() and not why.endswith("."), why)


if __name__ == "__main__":
    unittest.main()
