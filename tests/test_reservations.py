"""A run whose change cannot merge with an older live run's waits: stopped before its review
with its branch kept, and started again on the newest base once the older has landed.

The scan the tick runs, and ak's commit step runs itself, parks the younger run
(`leases.park`): its record reads `stopped`, waiting on the holder, its checkout and branch
stay as they are.  Once the holder has landed or is over, the tick's restart pass launches
the task again as a new run of the same seat, named on the stopped run and never twice, even
when that launch was refused.  Until then the stopped run is going: a seat's wait on it holds,
and goes on with the run started again.  A younger run past its executor turn, or one that
reached its review while the scan ran, and a pull request's review are only written down.  A
scan that cannot finish costs the commit step nothing.  Offline: the lease stage
(`fixtures.leases`), a fake launch.
"""

from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import LiveRuns
from agentkit import config, leases, run, watch
from agentkit import record

OLDER, YOUNGER = "20260101-0900-older", "20260101-1000-younger"
TASK = "---\nrepo: acme\n---\n# Change line 5\n\nChange it.\n\n## Done when\n```bash\ntrue\n```\n"


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

    def land(self, name):
        holder = config.RUNS / name
        record.save_state(holder, {**record.read_state(holder), "state": "pass", "merged": True})

    def started_again(self):
        """The runs started again for the younger one."""
        return sorted(d for d in config.RUNS.iterdir()
                      if ((record.read_state(d) or {}).get("restarted") or {}).get("run") == YOUNGER)

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
        self.assertIn("the younger is stopped, its branch kept, to start again once the older "
                      "has landed", self.logs[-1])
        # a stopped run holds no diff: the next scan clears the record, and stops nothing again
        self.assertEqual(leases.scan(self.repo, self.logs.append, now=2300), {})
        self.assertEqual(self.state(YOUNGER)["finished_at"], state["finished_at"])

    def test_a_run_past_its_executor_turn_is_only_written_down(self):
        self.collide(step="reviewer", rounds=1)
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
        self.assertEqual(self.state(YOUNGER)["state"], "running")
        self.assertIn("the younger lands after the older", self.logs[-1])

    def test_a_pull_requests_review_is_only_written_down(self):
        self.collide(step="done-when")
        directory = config.RUNS / YOUNGER
        record.save_state(directory, {**record.read_state(directory),
                                      "review_pr": "https://github.com/acme/acme/pull/7"})
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
        self.assertEqual(self.state(YOUNGER)["state"], "running")

    def test_a_run_that_reached_its_review_during_the_scan_is_not_stopped(self):
        self.collide(step="done-when")
        directory, real = config.RUNS / YOUNGER, leases.tree

        def tree_while_the_loop_moves_on(worktree, artifacts, log=lambda _: None):
            record.save_state(directory, {**record.read_state(directory), "step": "reviewer"})
            return real(worktree, artifacts, log)

        with patch.object(leases, "tree", tree_while_the_loop_moves_on):
            leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(self.state(YOUNGER)["state"], "running")
        self.assertIn("the younger lands after the older", self.logs[-1])

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

    def test_the_tick_starts_the_task_again_once_the_holder_has_landed(self):
        self.collide(session="seat-a")
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        self.assertEqual(self.state(YOUNGER)["state"], "stopped")
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append((d, argv))):
            leases.restart(log=self.logs.append, now=3000)                  # the holder still going
            self.assertEqual(launched, [])
            self.land(OLDER)
            leases.restart(log=self.logs.append, now=3200)
            leases.restart(log=self.logs.append, now=3300)                  # never twice
        self.assertEqual(len(launched), 1)
        fresh, argv = launched[0]
        self.assertEqual(argv, [str(fresh / "task.md")])
        self.assertTrue(fresh.name.endswith("-younger") and fresh.name != YOUNGER, fresh.name)
        self.assertEqual((fresh / "task.md").read_text(), TASK)
        state = record.read_state(fresh)
        self.assertEqual((state["state"], state["launched_session"]), ("queued", "seat-a"))
        self.assertEqual(state["restarted"], {"run": YOUNGER, "why": f"{OLDER} has landed"})
        self.assertEqual(self.state(YOUNGER)["lease_restarted"], fresh.name)
        self.assertIn(f"its earlier attempt is kept on branch ak/{YOUNGER}",
                      (fresh / "log.txt").read_text())
        self.assertIn(f"{YOUNGER} started again as {fresh.name}: {OLDER} has landed", self.logs[-1])

    def test_a_restart_whose_launch_was_refused_is_not_launched_again(self):
        self.collide()
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        self.land(OLDER)
        with patch.object(run, "preflight", side_effect=config.Error("the launch was refused")), \
                patch.object(run, "spawn_bg", side_effect=AssertionError("launched")):
            for now in (3000, 3060, 3120):                                  # three ticks
                leases.restart(log=self.logs.append, now=now)
        again = self.started_again()
        self.assertEqual(len(again), 1, again)
        self.assertEqual(self.state(YOUNGER)["lease_restarted"], again[0].name)
        self.assertEqual(record.read_state(again[0])["state"], "error")      # its own ending, told
        self.assertIn(f"WARN {YOUNGER} could not start again as {again[0].name}: "
                      "the launch was refused", self.logs)

    def test_a_wait_on_a_stopped_run_goes_on_with_the_run_started_again(self):
        self.collide()
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        wait = {"kind": "run", "on": YOUNGER}
        self.assertTrue(run.going(self.state(YOUNGER)))                   # its seat is working
        self.assertEqual(watch.wait_fact(wait), (False, ""))
        self.land(OLDER)
        with patch.object(run, "preflight"), patch.object(run, "spawn_bg"):
            leases.restart(log=self.logs.append, now=3000)
        fresh, = self.started_again()
        self.assertFalse(run.going(self.state(YOUNGER)))
        self.assertEqual(watch.wait_fact(wait), (False, ""))
        record.save_state(fresh, {**record.read_state(fresh), "state": "pass", "verdict": "PASS",
                                  "merged": True})
        self.assertEqual(watch.wait_fact(wait), (True, f"run {fresh.name} ended PASS, merged"))

    def test_a_holder_that_ended_with_nothing_landed_frees_the_wait_too(self):
        self.collide()
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        holder = config.RUNS / OLDER
        record.save_state(holder, {**record.read_state(holder), "state": "fail"})
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append(d)):
            leases.restart(log=self.logs.append, now=3000)
        self.assertEqual(len(launched), 1)
        self.assertEqual(record.read_state(launched[0])["restarted"]["why"], f"{OLDER} is over")


if __name__ == "__main__":
    unittest.main()
