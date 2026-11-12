"""A box counts what its processes needed, a process too short-lived for two reads included.

Runs one real box, as tests/test_worker_box.py does, the command the answer key's suite runs:
four chains of short processes on one core, which ask for about four times what they get.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import worker
from test_key_a_suite_records_what_its_short_processes_needed import CHAINS


class ABoxCountsEveryProcessItRan(unittest.TestCase):
    def test_short_processes_sharing_a_core_need_more_than_they_spent(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-box-counts-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        with account_home(root), patch.dict(os.environ, {"HOME": str(root)}):
            env = {key: value for key, value in os.environ.items() if key != "AK_HOST_READINGS"}
            cpu, activity = [], root / "activity"
            with activity.open("wb") as output:
                code, _, killed = worker.boxed([sys.executable, "-c", CHAINS], 600, env=env,
                                               cwd=str(root), activity=activity, output=output,
                                               stderr=subprocess.STDOUT, cpu=cpu)
        text = activity.read_text()
        self.assertEqual((code, killed), (0, False), text)
        spent = float(text.split()[-1])
        self.assertGreater(spent, 0, text)
        self.assertGreaterEqual(cpu[0][0], 2 * spent)


if __name__ == "__main__":
    unittest.main()
