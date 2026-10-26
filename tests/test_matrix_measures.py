"""What `ak models` scores each role on is pinned here, so it changes only with a visible test
change and the owner's yes (AGENTS.md, Owner rules): the roles, each role's measures in order
with the kind of number each is, the cost of a role's task (`quality`), and that every measure
says what it tests in plain words."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import matrix, quality

MEASURES = {
    "orchestrate": (("arena.agent_task_outcome_explicit", "share"),
                    ("arena.agent_steerability", "share"),
                    ("livebench.long_agentic", "percent"),
                    ("aa.briefcaseBreakdown.overall.elo", "rating")),
    "execute": (("livebench.coding", "percent"), ("livebench.long_agentic", "percent"),
                ("arena.agent_bash_reliability", "share"), ("arena.webdev", "rating"),
                ("aa.terminalBench40", "share")),
    "review": (("livebench.reasoning", "percent"), ("arena.text_factuality.coding", "rating"),
               ("arena.text_style_control.coding", "rating"), ("aa.deepsecBench", "share"),
               ("aa.omniscience", "percent")),
}
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
        for roles, pinned in ((matrix.ROLES, MEASURES), (quality.ROLES, QUALITY)):
            self.assertEqual({role: tuple((column, kind) for column, kind, _ in measures)
                              for role, measures in roles.items()}, pinned)
            self.assertEqual(list(roles), list(pinned))
        self.assertEqual(quality.COSTS, COSTS)
        for measures in (*matrix.ROLES.values(), *quality.ROLES.values()):
            for column, kind, why in measures:
                self.assertRegex(column, r"^(aa|arena|livebench)\.[A-Za-z0-9_.]+$")
                self.assertIn(kind, quality.SCALES)
                self.assertTrue(why and why[0].islower() and not why.endswith("."), why)


if __name__ == "__main__":
    unittest.main()
