"""The landing line hands a member its conflict with the target at once, not after the pass.

A member whose reviewed head cannot be rebased onto the target's tip, a member whose pull
request moved past its reviewed head, and one whose AGENTS.md outgrows the ceiling with no
stack ahead answer for themselves alone: the lander writes the verdict and wakes the member
before it starts the checks of the members behind it, so the fix runs beside those checks.
Offline: the lander's sandbox (`test_lander.LanderFixture`).
"""

from pathlib import Path
import sys
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_lander import LanderFixture
from agentkit import land, record


class ConflictReportedAtOnce(LanderFixture, unittest.TestCase):
    conflicted = None

    def check(self, cmds, cwd, log_path, *args, **kw):
        # what the line had told the conflicted member when a check behind it started
        if self.conflicted:
            self.seen.append((record.read_state(self.conflicted)["waiting_on"].get("fix"),
                              [call.args[0] for call in self.wake.call_args_list]))
        return super().check(cmds, cwd, log_path, *args, **kw)

    def test_a_conflicted_member_is_woken_before_the_checks_behind_it_start(self):
        self.seen = []
        self.conflicted = self.member("fix-api", joined=1, **{"base.txt": "branch\n"})
        behind = self.member("add-docs", joined=2, **{"docs.txt": "docs\n"})
        self.advance(**{"base.txt": "target\n"})
        land.check_line(self.turn)
        self.assertTrue(self.seen, "the member behind was never checked")
        fix, woken = self.seen[0]
        self.assertIn("rebase of origin/main failed", (fix or {}).get("line", ""))
        self.assertEqual(woken, [self.conflicted.name])
        self.assertIn("land", self.wait(behind))
        self.assertEqual([call.args[0] for call in self.wake.call_args_list],
                         [self.conflicted.name, behind.name])

    def test_a_member_that_integrates_cleanly_takes_one_checkout_not_two(self):
        members = [self.member(f"add-{name}", joined=joined, **{f"{name}.txt": "new\n"})
                   for joined, name in enumerate(("docs", "tests", "notes"), 1)]
        self.advance(**{"other.txt": "target\n"})
        scratch = land._scratch
        with mock.patch.object(land, "_scratch", wraps=scratch) as checkouts:
            land.check_line(self.turn)
        self.assertEqual(checkouts.call_count, len(members))
        for member in members:
            self.assertIn("land", self.wait(member))


if __name__ == "__main__":
    unittest.main(verbosity=2)
