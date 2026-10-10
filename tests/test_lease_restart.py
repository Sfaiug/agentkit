"""A run stopped waiting on an older run's change starts again once that run has landed:
its task, naming its repository, as a new run of its seat (`leases.restart`), claimed on the
stopped run before the launch so none starts twice and a stop, a seat's close or a closed seat
calls it off; until then the stopped run is going and its seat's wait follows the restart.
Offline: the lease stage (`fixtures.leases`), a fake launch.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, TASK, YOUNGER, LiveRuns
from agentkit import config, leases, run, stop, watch
from agentkit import record


class LeaseRestart(LiveRuns):
    def land(self, name):
        holder = config.RUNS / name
        record.save_state(holder, {**record.read_state(holder), "state": "pass", "merged": True})

    def started_again(self):
        """The runs started again for the younger one."""
        return sorted(d for d in config.RUNS.iterdir()
                      if ((record.read_state(d) or {}).get("restarted") or {}).get("run") == YOUNGER)


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
        self.assertEqual((fresh / "task.md").read_text(),      # its task, naming the repository
                         TASK.replace("repo: acme", f"repo: {self.repo}"))
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

    def calls_off(self, end):
        """Stopped waiting, then ended by `end`: once the holder lands, nothing starts again."""
        self.collide(session="seat-a")
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        self.assertTrue(stop.stoppable(self.state(YOUNGER)))
        with patch.object(config, "current_session", return_value=None), \
                redirect_stdout(io.StringIO()):
            end()
        state = self.state(YOUNGER)
        self.assertEqual((state["state"], state["error"]), ("stopped", "stopped by the user"))
        self.assertFalse(run.going(state))
        self.land(OLDER)
        with patch.object(run, "spawn_bg", side_effect=AssertionError("started again")):
            leases.restart(log=self.logs.append, now=3000)
        self.assertEqual(self.started_again(), [])

    def test_the_owners_stop_calls_the_restart_off(self):
        self.calls_off(lambda: stop.cmd_stop([YOUNGER]))

    def test_closing_its_seat_calls_the_restart_off(self):
        self.calls_off(lambda: stop.release_session("seat-a"))

    def test_a_task_naming_no_repository_or_a_relative_one_names_the_absolute_one_started_again(self):
        for task in ("# Change line 5\n", "---\nbase: main\nrepo: ./acme\n---\n# Change line 5\n"):
            with self.subTest(task=task[:12]):
                self.setUp()
                self.collide()
                (config.RUNS / YOUNGER / "task.md").write_text(task)
                leases.scan(self.repo, now=2000)
                self.land(OLDER)
                with patch.object(run, "preflight"), patch.object(run, "spawn_bg"):
                    leases.restart(log=self.logs.append, now=3000)
                text = (self.started_again()[0] / "task.md").read_text()
                self.assertEqual((text.count("repo:"), text.endswith("# Change line 5\n")), (1, True))
                self.assertIn(f"\nrepo: {self.repo}\n---\n", text)

    def test_the_restart_is_claimed_before_the_launch_and_a_closed_seat_gets_none(self):
        self.collide(session="seat-a")
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        self.land(OLDER)
        with patch.object(watch, "seat_closed", return_value=True), \
                patch.object(run, "launch_for_seat", side_effect=AssertionError("started again")):
            leases.restart(log=self.logs.append, now=3000)          # the seat is closed: none
        self.assertTrue(leases.parked(self.state(YOUNGER)))
        claimed = []

        def launch(directory, state, origin, **_kw):
            claimed.append(self.state(YOUNGER).get("lease_restarted") == directory.name)
            raise config.Error("a stop would find it started again already")

        with patch.object(watch, "seat_closed", return_value=False), \
                patch.object(run, "launch_for_seat", side_effect=launch):
            leases.restart(log=self.logs.append, now=3100)
        self.assertEqual(claimed, [True])                            # named before the launch
        self.assertFalse(stop.stoppable(self.state(YOUNGER)))        # nothing left to call off

    def test_a_parked_fix_runs_receipt_rides_into_its_restart(self):
        self.collide(session="seat-a")
        directory = config.RUNS / YOUNGER
        (directory / "task.md").write_text(TASK)
        (directory / run.REGRESSION).parent.mkdir(parents=True)
        (directory / run.REGRESSION).write_text("exit 1\n")
        record.save_state(directory, {**record.read_state(directory), "first": True,
                                      "followup": {"run": "run-0", "text": "api.py:1 - a defect"},
                                      "base_proof": "regression.sh"})
        leases.scan(self.repo, now=2000)
        self.land(OLDER)
        with patch.object(watch, "seat_closed", return_value=False), \
                patch.object(run, "preflight"), patch.object(run, "spawn_bg"):
            leases.restart(log=self.logs.append, now=3000)
        fresh, = self.started_again()
        state = record.read_state(fresh)
        self.assertEqual(state["followup"], {"run": "run-0", "text": "api.py:1 - a defect"})
        self.assertEqual((state["base_proof"], state["first"]), ("regression.sh", True))
        self.assertEqual((fresh / run.REGRESSION).read_text(), "exit 1\n")

    def test_a_holder_that_ended_with_nothing_landed_frees_the_wait_too(self):
        self.collide()
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        record.save_state(config.RUNS / OLDER, {**self.state(OLDER), "state": "fail"})
        with patch.object(run, "preflight"), patch.object(run, "spawn_bg"):
            leases.restart(log=self.logs.append, now=3000)
        fresh, = self.started_again()
        self.assertEqual(record.read_state(fresh)["restarted"]["why"], f"{OLDER} is over")


if __name__ == "__main__":
    unittest.main()
