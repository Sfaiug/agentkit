"""A landing's conflicts with the target spend a budget of their own, never the red checks'.

The lander marks a member's conflict with the target's tip (`conflict`), and the member counts
it in `landing_conflicts`, apart from `landing_reds`: a run whose red checks spent their three
fixes still gets a conflict fixer, and only a fourth conflict ends the landing, saying so.
Offline: the lander-wake stage (`test_lander_wakes.LanderWakes`).
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import test_lander_wakes
from test_merge_step import conflict
from agentkit import record, roundloop, run


class LandingConflictBudget(test_lander_wakes.LanderWakes):
    def spent(self, **counts):
        self.lp.state.update(counts)
        conflict(self.owner, self.wt)
        wait = self.park()
        self.assertTrue(wait["fix"]["conflict"])

    def test_a_conflict_after_the_reds_spent_their_fixes_still_gets_its_fixer(self):
        self.spent(landing_reds=roundloop.CONFLICT_ROUNDS)
        self.assertEqual(run.cmd_resume([self.directory.name]), 0)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual((state["landing_reds"], state["landing_conflicts"]),
                         (roundloop.CONFLICT_ROUNDS, 1))
        self.assertEqual(self.events, [("rebase-fixer", 3), ("reviewer", "round-3")])

    def test_a_fourth_conflict_ends_the_landing_and_says_so(self):
        self.spent(landing_conflicts=roundloop.CONFLICT_ROUNDS)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertTrue(state["merge_failed"])
        self.assertIn("landing conflicted with the target four times", state["merge_note"])
        self.assertNotIn("landing_conflicts", state)
        self.assertEqual(self.events, [])


# the stage's own tests run in their own file
for _name in dir(test_lander_wakes.LanderWakes):
    if _name.startswith("test_"):
        setattr(LandingConflictBudget, _name, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
