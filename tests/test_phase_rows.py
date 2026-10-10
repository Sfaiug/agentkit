"""history.db holds one row per phase of every run: each step a process ran, open while it
runs and ended when it closes, and each wait it counted, whole; in order, beside the cumulative
columns they add up to.  A run with no row keeps no phases.  The scoreboard shows, per change
merged in the week, the median hours in model turns, in ak's own work, waiting and with its
seat between its runs, every run of the change grouped by its PR or the run it continues, each
second of a run's phase rows in one part.  Offline: a temporary HOME.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, history, run, scoreboard

NOW = 1_800_000_000
HOUR = 3600
PR = "https://github.com/acme/widget/pull/7"


class PhaseRows(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-phase-rows-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.root))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        history._OPEN.clear()
        history.start_run("r1", repo="/home/fixture/code/acme", started_at=100)

    def test_each_step_and_wait_is_one_row_in_order_adding_up_to_the_columns(self):
        history.open_step("r1", "executor", 100)
        self.assertEqual(history.phases("r1"),
                         [{"phase": "executor", "started_at": 100, "ended_at": 100}])
        history.open_step("r1", "done-when", 160)          # the executor's row ends, the check's opens
        history.close_step("r1", 190, keep=True)            # a checkpoint moves the end, adds no row
        history.add_wait("r1", "slot", 30, 250)             # a wait is whole, ended when counted
        history.open_step("r1", "reviewer", 250)
        self.assertEqual(history.close_step("r1", 310), "reviewer")
        history.finish_run("r1", final_state="pass", finished_at=310)
        self.assertEqual(history.phases("r1"), [
            {"phase": "executor", "started_at": 100, "ended_at": 160},
            {"phase": "done-when", "started_at": 160, "ended_at": 250},
            {"phase": "slot wait", "started_at": 220, "ended_at": 250},
            {"phase": "reviewer", "started_at": 250, "ended_at": 310}])
        row = history.get("r1")
        self.assertEqual((row["executor_seconds"], row["done_when_seconds"], row["reviewer_seconds"],
                          row["slot_wait_seconds"]), (60, 90, 60, 30))
        self.assertIsNone(history.close_step("r1", 400))     # nothing open: nothing written
        self.assertEqual(len(history.phases("r1")), 4)

    def test_a_wait_counted_poll_by_poll_is_one_row_each_poll_moving_its_end(self):
        counted = (200, time.monotonic())
        for at in (230, 260, 290):
            with patch.object(time, "time", return_value=at):
                counted = gate.count_wait("r1", "slot", counted)
        self.assertEqual(history.phases("r1"),
                         [{"phase": "slot wait", "started_at": 200, "ended_at": 290}])

    def test_a_loop_dying_before_its_first_checkpoint_leaves_no_endless_row(self):
        history.open_step("r1", "executor", 100)
        history._OPEN.clear()                               # the loop died, killed or out of memory
        history.open_step("r1", "executor", 90000)          # a resume: a new attempt's step
        history.close_step("r1", 90020)
        history.finish_run("r1", final_state="pass", finished_at=90020)
        self.assertEqual(history.phases("r1"), [
            {"phase": "executor", "started_at": 100, "ended_at": 100},     # counted nothing, as its column
            {"phase": "executor", "started_at": 90000, "ended_at": 90020}])
        self.assertEqual(history.get("r1")["executor_seconds"], 20)

    def test_a_run_with_no_row_keeps_no_phases(self):
        history.open_step("r2", "executor", 100)
        history.close_step("r2", 160)
        history.add_wait("r2", "slot", 30, 200)
        self.assertEqual(history.phases("r2"), [])
        history.open_step("r1", "merge", 100)
        history.start_run("r1", repo="/home/fixture/.agentkit/tmp/sandbox")     # a sandbox's row goes
        self.assertEqual((history.get("r1"), history.phases("r1")), (None, []))


class TimeSplit(PhaseRows):
    """The scoreboard's split of a merged change's hours."""

    def setUp(self):
        super().setUp()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("RUNS", "REPO"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.object(scoreboard.time, "time", return_value=NOW))
        stack.enter_context(patch.object(config, "session_records", return_value={}))

    def ended(self, run_id, change, started, finished, state, *phases):
        """A run's row and its phase rows, each `(name, start, end)` in hours from NOW."""
        history.start_run(run_id, repo="/home/fixture/code/acme", started_at=NOW + started * HOUR,
                          change=change)
        for name, start, end in phases:
            if name.endswith(" wait"):
                history.add_wait(run_id, name[:-5], (end - start) * HOUR, NOW + end * HOUR,
                                 began=NOW + start * HOUR)
            else:
                history.open_step(run_id, name, NOW + start * HOUR)
                history.close_step(run_id, NOW + end * HOUR)
        history.finish_run(run_id, final_state=state, finished_at=NOW + finished * HOUR,
                           changed_lines=0 if state == "pass" else None)

    def test_a_merged_changes_hours_are_split_over_every_run_of_it_each_second_once(self):
        # a PR reviewed twice: the first run failed, the seat held it two hours, the second
        # merged from its place in the landing line, where its slot wait after the wake, its
        # lander's wait and its delivery all fall inside the line wait
        self.ended("a", PR, -10, -8, "fail", ("executor", -10, -9), ("slot wait", -9, -8.75),
                   ("reviewer", -8.75, -8.25), ("done-when", -8.25, -8))
        self.ended("b", PR, -6, -1, "pass", ("executor", -6, -5.5), ("reviewer", -5.5, -5.25),
                   ("merge wait", -4, -1), ("slot wait", -4, -3.875), ("lander wait", -3.5, -3.25),
                   ("merge", -2, -1.25))
        # merged alone after four hours parked on a spent quota window, which is in no part
        self.ended("solo", "solo", -9, -8, "exhausted", ("executor", -9, -8))
        self.ended("solo", "solo", -4, -3, "pass", ("executor", -4, -3.5),
                   ("done-when", -3.5, -3.25), ("suite wait", -3.25, -3))
        self.ended("open", "open", -3, -2, "fail", ("executor", -3, -2))          # merged nothing
        self.assertEqual(scoreboard.split_hours(history.get("b")), {"model": 0.75, "ak": 0.75, "waiting": 2.25})
        [this_week, before] = scoreboard.compute(NOW)["merged"]
        self.assertEqual({part: round(value, 3) for part, value in this_week.items()},
                         {"model": 1.875, "ak": 0.625, "waiting": 1.375, "seat": 1.0})
        self.assertIsNone(before)
        with patch.object(scoreboard.terminal, "content_width", return_value=300):
            self.assertIn("merged    median hours per merged change: 1.9 in model turns, 0.6 ak's own "
                          "work, 1.4 waiting, 1.0 with its seat between runs", "\n".join(scoreboard.render()))

    def test_a_change_whose_run_ended_before_any_step_counts_with_that_run_at_zero(self):
        # a review run its fetch ended in error right after its launch receipt, relaunched by its seat
        self.ended("early", PR, -5, -4.5, "error")
        self.ended("late", PR, -3, -1, "pass", ("executor", -3, -2))
        self.assertEqual(scoreboard.split_hours(history.get("early")), {"model": 0.0, "ak": 0.0, "waiting": 0.0})
        self.assertEqual(scoreboard.compute(NOW)["merged"][0],
                         {"model": 1.0, "ak": 0.0, "waiting": 0.0, "seat": 1.5})

    def test_a_step_closed_after_the_clock_stepped_back_ends_where_its_column_is_counted(self):
        # a checkpoint at 1 h, the wall clock steps back 60 s, the step closes 30 s later
        history.start_run("back", repo="/home/fixture/code/acme", started_at=NOW - 3 * HOUR, change="back")
        history.open_step("back", "executor", NOW - 3 * HOUR)
        history.close_step("back", NOW - 2 * HOUR, keep=True)
        history.close_step("back", NOW - 2 * HOUR - 30)
        history.finish_run("back", final_state="pass", finished_at=NOW - HOUR, changed_lines=0)
        self.assertEqual([(row["started_at"], row["ended_at"]) for row in history.phases("back")],
                         [(NOW - 3 * HOUR, NOW - 2 * HOUR)])
        self.assertEqual(history.get("back")["executor_seconds"], HOUR)
        self.assertEqual(scoreboard.split_hours(history.get("back")), {"model": 1.0, "ak": 0.0, "waiting": 0.0})
        self.assertIsNotNone(scoreboard.compute(NOW)["merged"][0])

    def test_a_wait_counted_past_its_row_by_a_clock_correction_keeps_its_change(self):
        # a slot wait counted 600 monotonic seconds while the wall clock, stepped back 10 s,
        # moved 590 between its row's ends; then a step ran
        history.start_run("stepped", repo="/home/fixture/code/acme", started_at=NOW - 3 * HOUR,
                          change="stepped")
        history.add_wait("stepped", "slot", 600, NOW - 3 * HOUR + 590, began=NOW - 3 * HOUR)
        history.open_step("stepped", "executor", NOW - 2 * HOUR)
        history.close_step("stepped", NOW - HOUR)
        history.finish_run("stepped", final_state="pass", finished_at=NOW - HOUR, changed_lines=0)
        self.assertEqual({part: round(value, 3) for part, value in
                          scoreboard.split_hours(history.get("stepped")).items()},
                         {"model": 1.0, "ak": 0.0, "waiting": 0.164})
        self.assertIsNotNone(scoreboard.compute(NOW)["merged"][0])

    def test_a_change_with_a_run_from_before_the_phase_rows_is_not_recorded(self):
        # its step columns count seconds no step row holds: a run from before the rows, or one that began
        # before them and ended after, with rows for its later part only
        self.ended("spanning", "spanning", -6, -1, "pass", ("merge wait", -2, -1))
        history.add_seconds("spanning", "executor", HOUR)
        self.assertIsNone(scoreboard.split_hours(history.get("spanning")))
        self.assertIsNone(scoreboard.compute(NOW)["merged"][0])
        history.start_run("old", repo="/home/fixture/code/acme", started_at=NOW - 2 * HOUR, change="old")
        history.add_seconds("old", "executor", HOUR)
        history.finish_run("old", final_state="pass", finished_at=NOW - HOUR, changed_lines=0)
        self.assertIsNone(scoreboard.compute(NOW)["merged"][0])

    def test_a_runs_row_names_its_change_by_the_pull_request_however_its_url_is_spelled(self):
        for state, change in (({"run_id": "r1", "repo": "/x/acme", "review_pr": PR}, "acme/widget#7"),
                              ({"run_id": "r2", "repo": "/x/acme",
                                "review_pr": "https://github.com/Acme/widget/pull/7/"}, "acme/widget#7"),
                              ({"run_id": "r3", "repo": "/x/acme", "change": "r1"}, "r1"),
                              ({"run_id": "r4", "repo": "/x/acme"}, "r4")):
            run.history_start(state)
            self.assertEqual(history.get(state["run_id"])["change"], change)


if __name__ == "__main__":
    unittest.main(verbosity=2)
