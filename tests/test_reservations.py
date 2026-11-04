"""A colliding build reaches its commit step without waiting on the older run.

Offline: two worktrees on fixtures.live_runs, with commit_leftovers marking that the
commit step reached it. Neither run owns a real process to stop.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.live_runs import OLDER, YOUNGER, LiveRuns
from agentkit import config, gitcall, run, record


class Step:
    """The record and commit step of a loop, without a real process."""

    scratch, every = False, []

    def __init__(self, run_dir, log):
        self.run_dir, self.log, self.steps, self.artifacts = run_dir, log, [], set()
        self.state = record.read_state(run_dir)
        self.wt = Path(self.state["worktree"])

    def step(self, name):
        self.steps.append(name)
        self.state["step"] = name
        record.save_state(self.run_dir, self.state)


class Reservations(LiveRuns):
    def test_the_commit_step_keeps_a_colliding_build_going(self):
        self.collide()
        lp = Step(config.RUNS / YOUNGER, self.logs.append)

        class Reached(Exception):
            pass

        with patch.object(gitcall, "commit_leftovers", side_effect=Reached):
            with self.assertRaises(Reached):
                run.verify_work(lp)
        self.assertEqual(lp.steps, ["done-when"])
        for name in (OLDER, YOUNGER):
            self.assertEqual(self.state(name)["state"], "running")
            self.assertNotIn("lease_wait", self.state(name))


if __name__ == "__main__":
    unittest.main()
