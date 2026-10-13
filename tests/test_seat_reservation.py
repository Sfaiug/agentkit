"""A seat's own pull request's review is parked while an older live change holds its lines.

Before any reviewer is picked, the review runs the lease scan itself (`run.park_own_review`):
a diff that cannot merge with an older live change is stopped there, its branch kept, waiting
on that change (`leases.park`), and the tick starts the review again once the change has
landed (`leases.restart`).  Another's review, and one past its reviewer turn, are only written
down.  Offline: the lease stage (`fixtures.leases`), a fake launch.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import config, leases, run
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"


class SeatReservation(LiveRuns):
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

    def test_the_own_review_is_parked_before_its_reviewer_turn_and_starts_again_once_the_older_landed(self):
        self.review(YOUNGER)
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
        state = self.state(YOUNGER)
        self.assertEqual((state["state"], state["lease_wait"]),
                         ("stopped", {"on": OLDER, "files": ["api.py"], "since": 2000}))
        self.assertTrue(self.logs[-1].endswith("to start again once the older has landed or is over"))
        holder = config.RUNS / OLDER
        record.save_state(holder, {**record.read_state(holder), "state": "pass", "merged": True})
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append(argv)):
            leases.restart(log=self.logs.append, now=3000)
        self.assertEqual(launched, [["--review-pr", URL]])
        self.assertTrue(record.read_state(config.RUNS / self.state(YOUNGER)["lease_restarted"])["own_pr"])

    def test_anothers_review_and_a_review_past_its_reviewer_turn_are_only_written_down(self):
        theirs, reviewing, second = "20260101-1000-theirs", "20260101-1100-reviewing", "20260101-1200-second"
        self.review(theirs, own=False)
        self.review(reviewing, step="reviewer")
        self.review(second, rounds=1, step="executor")
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual({name: each["waits_on"] for name, each in found.items()},
                         {theirs: OLDER, reviewing: OLDER, second: OLDER})
        self.assertEqual([self.state(name)["state"] for name in found], ["running"] * 3)
        self.assertEqual([line.endswith("the younger is only written down") for line in self.logs],
                         [True] * 3)

    def test_the_review_runs_the_scan_itself_and_its_save_raises_the_stop(self):
        parked, clear = self.review(YOUNGER), self.review("20260101-1100-clear", line=15)
        with self.assertRaises(record.StopRequested):
            run.park_own_review(self.repo, parked, dict(record.read_state(parked)), self.logs.append)
        self.assertEqual(self.state(YOUNGER)["lease_wait"]["on"], OLDER)
        run.park_own_review(self.repo, clear, dict(record.read_state(clear)), self.logs.append)
        self.assertEqual(self.state(clear.name)["state"], "running")        # nothing in its way


if __name__ == "__main__":
    unittest.main(verbosity=2)
