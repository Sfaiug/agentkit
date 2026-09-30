"""A `sleep 100` the run-tree test did not start never fails it.

Another suite (test_kill_never_reaches_caller), a seat or a user may have one
running on the same host while tests/test_run_tree.py runs; the run-tree test
counts only the sleepers its own cases started, and never signals this one.
"""

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class ForeignSleeper(unittest.TestCase):
    def test_run_tree_passes_beside_an_unrelated_sleeper(self):
        sleeper = subprocess.Popen(
            ["sleep", "100"], start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(sleeper.wait, timeout=5)
        self.addCleanup(sleeper.kill)
        done = subprocess.run(
            [sys.executable, str(REPO / "tests" / "test_run_tree.py")], cwd=REPO,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=540)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIsNone(sleeper.poll(), "the run-tree test ended a sleeper it did not start")


if __name__ == "__main__":
    unittest.main(verbosity=2)
