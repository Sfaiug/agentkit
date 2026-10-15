"""A run started from an older branch is parked only for lines it changes itself.

A `from:` run records main's tip at launch as its base while its checkout starts at the
branch, cut before main moved; its lease is what it changed on top of where its checkout
meets that base, so main's later commits are nobody's diff.  Offline: the lease stage
(`fixtures.leases`), a real repository with one checkout per run.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import LiveRuns, OLDER, YOUNGER
from agentkit import leases


class LeaseFromBranch(LiveRuns):
    def test_a_from_run_collides_only_where_its_own_change_meets_the_others(self):
        cut = self.base                                         # the branch is cut here ...
        self.edit(self.repo, "api.py", 5, "main's line 5", commit=True)     # ... and main moves on
        moved = self.git(self.repo, "rev-parse", "HEAD")
        relaunched = self.run_on(OLDER, 900, base=moved, at=cut)
        younger = self.run_on(YOUNGER, 1000, base=moved)
        self.edit(relaunched, "api.py", 15, "the branch's line 15", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        self.assertEqual(leases.scan(self.repo, now=2000), {})
        self.edit(relaunched, "api.py", 25, "the branch's line 25")
        self.edit(younger, "api.py", 25, "younger's line 25")
        self.assertEqual(leases.scan(self.repo, now=2100), {
            YOUNGER: {"waits_on": OLDER, "files": ["api.py"], "since": 2100}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
