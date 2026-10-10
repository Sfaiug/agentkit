"""history.db holds one row per phase of every run: each step a process ran, open while it
runs and ended when it closes, and each wait it counted, whole; in order, beside the cumulative
columns they add up to.  A run with no row keeps no phases.  The scoreboard shows, per change
merged in the week, the median hours in model turns, in ak's own work, waiting and with its
seat between its runs, every run of the change grouped by its PR or the run it continues.
Offline: a temporary HOME.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, run, scoreboard

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
                         [{"phase": "executor", "started_at": 100, "ended_at": None}])
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

    def ended(self, run_id, change, started, finished, *, merged, waits=(), **steps):
        history.start_run(run_id, repo="/home/fixture/code/acme", started_at=NOW + started * HOUR,
                          change=change)
        for step, value in steps.items():
            history.add_seconds(run_id, step, value * HOUR)
        for wait, value in waits:
            history.add_wait(run_id, wait, value * HOUR, NOW + finished * HOUR)
        history.finish_run(run_id, final_state="pass" if merged else "fail",
                           finished_at=NOW + finished * HOUR, changed_lines=0 if merged else None)

    def test_a_merged_changes_hours_are_split_over_every_run_of_it(self):
        # a PR reviewed twice: the first run failed, the seat held it two hours, the second merged
        self.ended("a", PR, -10, -8, merged=False, executor=1, reviewer=0.5, waits=[("slot", 1 / 6)])
        self.ended("b", PR, -6, -1, merged=True, executor=0.5, reviewer=0.25,
                   waits=[("merge", 1), ("lander", 1 / 3)])
        self.ended("solo", "solo", -3, -2, merged=True, executor=0.5)
        self.ended("open", "open", -3, -2, merged=False, executor=4)          # merged nothing
        [this_week, before] = scoreboard.compute(NOW)["merged"]
        self.assertEqual({part: round(value, 3) for part, value in this_week.items()},
                         {"model": 1.375, "ak": 1.875, "waiting": 0.75, "seat": 1.0})
        self.assertIsNone(before)
        with patch.object(scoreboard.terminal, "content_width", return_value=300):
            self.assertIn("merged    median hours per merged change: 1.4 in model turns, 1.9 ak's own "
                          "work, 0.8 waiting, 1.0 with its seat between runs", "\n".join(scoreboard.render()))

    def test_a_runs_row_names_its_change(self):
        for state, change in (({"run_id": "r1", "repo": "/x/acme", "review_pr": PR}, PR),
                              ({"run_id": "r2", "repo": "/x/acme", "change": "r1"}, "r1"),
                              ({"run_id": "r3", "repo": "/x/acme"}, "r3")):
            run.history_start(state)
            self.assertEqual(history.get(state["run_id"])["change"], change)


if __name__ == "__main__":
    unittest.main(verbosity=2)
