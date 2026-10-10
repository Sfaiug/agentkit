"""history.db holds one row per phase of every run: each step a process ran, open while it
runs and ended when it closes, and each wait it counted, whole; in order, beside the cumulative
columns they add up to.  A run with no row keeps no phases.  Offline: a temporary HOME.
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
from agentkit import config, gate, history


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
