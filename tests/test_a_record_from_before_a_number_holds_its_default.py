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
from agentkit import config, record, transitions

KEPT = {"review_rounds": 4, "executor_lines": 200, "orchestrator_lines": 25}
DEFAULTS = {"extra_rounds": 2, "rescope_findings": 6}     # the numbers added since


class OldRecord(unittest.TestCase):
    def test_each_old_record_holds_the_defaults_of_numbers_added_since_over_the_host_s(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"],
                           settings={"review_rounds": 5, "extra_rounds": 0, "rescope_findings": 0})
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True):
                self.assertEqual(record.policy_of({"policy": KEPT}), {**KEPT, **DEFAULTS})
                self.assertEqual(record.policy_of({}), {"review_rounds": 5, "executor_lines": 300,
                                                        "orchestrator_lines": 50, **DEFAULTS})

    def test_a_record_keeping_no_numbers_reads_the_host_s_first_numbers_alone(self):
        # a host number it holds the default of, gone bad meanwhile, refuses nothing of it
        with Home() as home:
            home.write(".agentkit/config.toml", "review_rounds = 5\nextra_rounds = -1\n"
                                                 "rescope_findings = -1\n")
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True):
                self.assertEqual(record.policy_of({}), {"review_rounds": 5, "executor_lines": 300,
                                                        "orchestrator_lines": 50, **DEFAULTS})
                with self.assertRaises(config.Error):
                    config.host_policy()

    def test_a_record_keeping_no_numbers_says_ak_s_six_reading_no_host_file(self):
        # a review it finished is never lost to a host config gone bad meanwhile
        with Home() as home:
            home.write(".agentkit/config.toml", "executor_lines = -1\n")
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.dict(os.environ, home.env, clear=True):
                self.assertIsNone(transitions.rescope({}, 5))
                self.assertEqual(transitions.rescope({}, 6), "The review left 6 blocking findings, "
                                 "at or past rescope_findings = 6: rescope the task.")


if __name__ == "__main__":
    unittest.main()
