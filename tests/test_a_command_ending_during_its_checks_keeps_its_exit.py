"""A command that ends while the watchdog's checks run keeps its own exit.

Past the silence limit `worker.limited` asks whether a declared bound holds the command, and for
a turn on a machine that question goes over ssh, which can take longer than the command has left.
Stopping one that ended meanwhile would read its finished work as a silence kill.
"""

from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import worker


class ACommandEndingDuringItsChecksKeepsItsExit(unittest.TestCase):
    def test_a_command_that_ends_while_its_bound_is_asked_for_is_not_stopped(self):
        with tempfile.TemporaryDirectory(prefix="checks-") as tmp:
            ended = Path(tmp, "ended")

            def declared(_pid):
                """No bound, said only once the command has ended."""
                while not ended.exists():
                    time.sleep(0.05)
                time.sleep(1)
                return False

            code, _, killed = worker.limited(["sh", "-c", f"sleep 0.5; touch '{ended}'"], None,
                                             silence=0.2, activity=Path(tmp, "events"),
                                             declared=declared)
        self.assertEqual((code, killed), (0, False))


if __name__ == "__main__":
    unittest.main()
