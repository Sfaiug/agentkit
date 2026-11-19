"""A run's record from before a number was added holds ak's default of it, whatever the host
says now (`record.policy_of`): one keeping its numbers keeps those it has, and one from before
records kept any stays on the host's for the numbers there were then."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, record

KEPT = {"review_rounds": 4, "executor_lines": 200, "orchestrator_lines": 25}


class OldRecord(unittest.TestCase):
    def test_each_old_record_holds_extra_rounds_default_over_the_host_s(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"], settings={"review_rounds": 5, "extra_rounds": 0})
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True):
                self.assertEqual(record.policy_of({"policy": KEPT}), {**KEPT, "extra_rounds": 2})
                self.assertEqual(record.policy_of({}), {"review_rounds": 5, "executor_lines": 300,
                                                        "orchestrator_lines": 50, "extra_rounds": 2})


if __name__ == "__main__":
    unittest.main()
