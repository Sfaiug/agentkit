"""A repair of the target owes the target's suite as it is declared now, once.

A flaky test's repair names the target's suite as its check, in the words the target declared
it in when the flake was seen. When the target's `tests:` line changes before the repair lands,
its copy keeps the old spelling, and landing would run the suite in both: 43 minutes of every
place on 11 Nov 2026, for a repair started the minute the line changed.

Offline: real git and gate commands in an acme sandbox, as `test_lander` sets them up.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import ONCE, SUITE, LanderFixture
from agentkit import land, record, run

NOW = "test ! -f broken.txt && test -f base.txt"


class EarlierSpelling(LanderFixture, unittest.TestCase):
    def ran(self):
        return [cmd for cmds, _, _ in self.checks for cmd in cmds]

    def repair(self, based_on_the_move=False):
        """A repair whose task names the suite as the target declared it before it moved."""
        directory = self.member(once=SUITE)
        self.advance(**{"AGENTS.md": f"---\ntests: {NOW}\n---\n"})
        with record.record(directory) as current:
            current["repair"] = {"target": "main", "command": "tests/test_api.py"}
            if based_on_the_move:
                current["base_sha"] = run.git(self.repo, "rev-parse", "main")
        return directory

    def test_a_repair_runs_the_suite_once_as_the_target_declares_it(self):
        first = self.repair()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(self.ran(), [NOW])

    def test_a_repair_whose_base_already_declares_the_new_line_runs_it_once_too(self):
        """Started as the target moved, or rebased onto it since: its base says the new words."""
        first = self.repair(based_on_the_move=True)
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(self.ran(), [NOW])

    def test_a_line_that_was_never_the_suite_still_runs_besides_it(self):
        first = self.member()
        self.advance(**{"AGENTS.md": f"---\ntests: {NOW}\n---\n"})
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(sorted(self.ran()), sorted([ONCE, NOW]))


if __name__ == "__main__":
    unittest.main()
