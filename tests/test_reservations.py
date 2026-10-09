"""A run whose change cannot merge with an older live run's is stopped before its review,
its branch kept, waiting on it.

The scan the tick runs, and ak's commit step runs itself, parks the younger run
(`leases.park`): its record reads `stopped`, waiting on the holder, its checkout and branch
stay as they are, for its task to be made again on the holder's result.  A younger run past
its executor turn, or one that reached its review while the scan ran, a pull request's
review and a job's task are only written down.  A scan that cannot finish costs the commit
step nothing.  Offline: the lease stage (`fixtures.leases`).
"""

from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import LiveRuns
from agentkit import config, leases, run
from agentkit import record

OLDER, YOUNGER = "20260101-0900-older", "20260101-1000-younger"


class Step:
    """The loop at its commit step, as `run.verify_work` reads it: a run's record, its log,
    the step it announces and the save after the scan."""

    scratch, every = False, []

    def __init__(self, run_dir, log):
        self.run_dir, self.log, self.steps, self.artifacts = run_dir, log, [], set()
        self.state = record.read_state(run_dir)
        self.wt = Path(self.state["worktree"])

    def step(self, name):
        self.steps.append(name)
        self.state["step"] = name
        record.save_state(self.run_dir, self.state)

    def save(self):
        record.save_state(self.run_dir, self.state)


class Reservations(LiveRuns):
    def collide(self, step="executor", rounds=0, session=None):
        """An older run that changed line 5, and a younger one changing it too, uncommitted."""
        older = self.run_on(OLDER, 900, step="executor", rounds=0)
        younger = self.run_on(YOUNGER, 1000, step=step, rounds=rounds, session=session)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        self.edit(younger, "api.py", 5, "younger's line 5")
        return older, younger

    def state(self, name):
        return record.read_state(config.RUNS / name)

    def test_the_younger_run_in_its_executor_turn_is_stopped_with_its_branch_kept(self):
        _, younger = self.collide()
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
        state = self.state(YOUNGER)
        self.assertEqual((state["state"], state["stop_kept"]), ("stopped", True))
        self.assertEqual(state["error"], f"waits on {OLDER}: both change api.py")
        self.assertEqual(state["lease_wait"], {"on": OLDER, "files": ["api.py"], "since": 2000})
        self.assertTrue(younger.is_dir())
        self.assertTrue(self.git(self.repo, "rev-parse", "--verify", "-q", f"refs/heads/ak/{YOUNGER}"))
        self.assertEqual(self.git(younger, "status", "--porcelain"), "M api.py")   # its edit, kept
        self.assertEqual(self.state(OLDER)["state"], "running")
        self.assertIn("the younger is stopped, its branch kept, waiting on the older", self.logs[-1])
        # a stopped run holds no diff: the next scan clears the record, and stops nothing again
        self.assertEqual(leases.scan(self.repo, self.logs.append, now=2300), {})
        self.assertEqual(self.state(YOUNGER)["finished_at"], state["finished_at"])

    def test_a_run_past_its_executor_turn_is_only_written_down(self):
        self.collide(step="reviewer", rounds=1)
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
        self.assertEqual(self.state(YOUNGER)["state"], "running")
        self.assertIn("the younger is only written down", self.logs[-1])

    def test_a_pull_requests_review_and_a_jobs_task_are_only_written_down(self):
        self.collide(step="done-when")
        directory = config.RUNS / YOUNGER
        for key, value in (("review_pr", "https://github.com/acme/acme/pull/7"), ("job_id", "job-1")):
            record.save_state(directory, {**record.read_state(directory), "review_pr": None,
                                          "job_id": None, key: value})
            found = leases.scan(self.repo, self.logs.append, now=2000)
            self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
            self.assertEqual(self.state(YOUNGER)["state"], "running", key)

    def test_a_run_that_reached_its_review_during_the_scan_is_not_stopped(self):
        self.collide(step="done-when")
        directory, real = config.RUNS / YOUNGER, leases.tree

        def tree_while_the_loop_moves_on(worktree, artifacts, log=lambda _: None):
            record.save_state(directory, {**record.read_state(directory), "step": "reviewer"})
            return real(worktree, artifacts, log)

        with patch.object(leases, "tree", tree_while_the_loop_moves_on):
            leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(self.state(YOUNGER)["state"], "running")
        self.assertIn("the younger is only written down", self.logs[-1])

    def test_the_commit_step_stops_a_run_the_tick_has_not_seen_yet(self):
        _, younger = self.collide()
        lp = Step(config.RUNS / YOUNGER, self.logs.append)
        with self.assertRaises(record.StopRequested):
            run.verify_work(lp)
        self.assertEqual(lp.steps, ["done-when"])
        state = self.state(YOUNGER)
        self.assertEqual((state["state"], state["lease_wait"]["on"]), ("stopped", OLDER))
        self.assertEqual(self.git(younger, "status", "--porcelain"), "M api.py")   # nothing committed

    def test_a_scan_that_cannot_finish_leaves_the_commit_step_going(self):
        older, _ = self.collide()
        real = leases.live

        def live_then_the_older_ends(repo):
            found = real(repo)
            shutil.rmtree(older)            # its run ended and took its checkout meanwhile
            return found

        class Reached(Exception):
            pass

        lp = Step(config.RUNS / YOUNGER, self.logs.append)
        with patch.object(leases, "live", live_then_the_older_ends), \
                patch.object(run, "commit_leftovers", side_effect=Reached):
            with self.assertRaises(Reached):
                run.verify_work(lp)
        self.assertIn("WARN lease scan of", self.logs[-1])
        self.assertEqual(self.state(YOUNGER)["state"], "running")


if __name__ == "__main__":
    unittest.main()
