"""A run stopped to wait on an older one, once started again, names the run that took its task."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import status


class RestartedRunNamesItsSuccessor(unittest.TestCase):
    def test_a_parked_run_says_its_wait_until_it_is_started_again(self):
        parked = {"state": "stopped", "error": "waits on 20261020-1339-fix-api: both change api.py",
                  "lease_wait": {"on": "20261020-1339-fix-api", "files": ["api.py"], "since": 1.0}}
        self.assertEqual(status.stop_note(parked),
                         "stopped · waits on 20261020-1339-fix-api: both change api.py")
        restarted = {**parked, "lease_restarted": "20261020-1624-fix-docs"}
        self.assertEqual(status.stop_note(restarted), "stopped · started again as 20261020-1624-fix-docs")

    def test_any_other_stop_keeps_its_own_words(self):
        self.assertEqual(status.stop_note({"state": "stopped"}), "stopped · stopped by the user")


if __name__ == "__main__":
    unittest.main()
