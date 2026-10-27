"""A suite already on the suite helper takes the local turns free now, never waiting for them
nor passing an older waiter. Offline: gate turns are lock files in a temporary home.
"""

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from agentkit import gate, host


class Turn:
    def __init__(self, count):
        self.slots = [None] * count
        self.pieces, self.waited, self.released = count, False, False

    def take(self, stopped):
        return True

    def give(self, slot):
        pass

    def alone(self):
        self.slots = self.slots[:1]

    def release(self):
        self.slots = []
        self.released = True


class SuiteOnBoth(unittest.TestCase):
    turn = fixture.SuiteHelper.turn

    def setUp(self):
        self.acquire = gate._acquire_gate_turn
        fixture.SuiteHelper.setUp(self)

    def test_local_admission_takes_free_turns_without_waiting_or_passing_an_older_waiter(self):
        for held, older in ((0, False), (2, False), (0, True)):
            with self.subTest(held=held, older=older), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": ""}))
                stack.enter_context(patch.object(gate, "_run_readings", return_value={}))
                stack.enter_context(patch.object(host, "kept_cpu", return_value=None))
                stack.enter_context(patch.object(gate, "derived_heavy_limit", return_value=2))
                stack.enter_context(patch.object(gate, "_gate_waiter_before", return_value=older))
                stack.enter_context(patch.object(gate.time, "sleep", side_effect=AssertionError(
                    "a suite already on the helper must not wait for local turns")))
                for i in range(held):
                    holder = stack.enter_context(gate.gate_lock(None, i).open("a"))
                    fcntl.flock(holder, fcntl.LOCK_EX)
                hold = self.acquire(None, self.root / "gate.log", None, fixture.SUITE,
                                    self.repo, context={"repo": str(self.repo)}, wait=False)
                if not held and not older:
                    self.assertEqual(len(hold.slots), 2)
                    hold.release()
                else:
                    self.assertIsNone(hold)
                self.assertEqual(gate._heavy_running(), held)


if __name__ == "__main__":
    unittest.main()
