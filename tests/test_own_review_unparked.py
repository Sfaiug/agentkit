"""A pull request's review is never parked, a seat's own included: its work is built already.

An own review whose lines an older live change holds is only written down, like another's
review and one past its reviewer turn, and goes on to its reviewer: the landing line fixes the
conflict once the older change has landed (`leases.before_review`).  Offline: the lease stage
(`fixtures.leases`).
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import config, leases
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"


class OwnReviewUnparked(LiveRuns):
    def setUp(self):
        super().setUp()
        # an older task run still building, which changed line 5
        self.edit(self.run_on(OLDER, 900, step="executor", rounds=0), "api.py", 5, "older's line 5",
                  commit=True)

    def review(self, name, own=True, step=None, rounds=0, line=5):
        """A pull request's review at `step` with `rounds` reviewed, its head changing `line`."""
        worktree = self.run_on(name, 1000, step=step, rounds=rounds, session="seat-b")
        directory = config.RUNS / name
        record.save_state(directory, {**record.read_state(directory), "review_pr": URL, "pr": URL,
                                      "own_pr": own, "launch_opts": {"--review-pr": URL, "--bg": True}})
        self.edit(worktree, "api.py", line, f"the pull request's line {line}", commit=True)
        return directory

    def test_every_review_is_only_written_down_and_goes_on(self):
        mine, theirs, reviewing = YOUNGER, "20260101-1100-theirs", "20260101-1200-reviewing"
        self.review(mine)
        self.review(theirs, own=False)
        self.review(reviewing, step="reviewer")
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual({name: each["waits_on"] for name, each in found.items()},
                         {mine: OLDER, theirs: OLDER, reviewing: OLDER})
        self.assertEqual([self.state(name)["state"] for name in found], ["running"] * 3)
        self.assertNotIn("lease_wait", self.state(mine))
        self.assertEqual([line.endswith("the younger is only written down") for line in self.logs],
                         [True] * 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
