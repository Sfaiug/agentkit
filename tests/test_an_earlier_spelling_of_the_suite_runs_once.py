"""A task's `# once` line that is the suite as its base declared it runs as the suite, once.

A flaky test's repair names the target's suite as its check; when the target's `tests:` line
changes before it lands, its copy keeps the old spelling, and landing would run the suite in
both. The lander reads the member's base commit and runs only the target's line now.

Offline: real git and gate commands in an acme sandbox, as `test_lander` sets them up.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import ONCE, SUITE, LanderFixture
from agentkit import land, record

NOW = "test ! -f broken.txt && test -f base.txt"


class EarlierSpelling(LanderFixture, unittest.TestCase):
    def ran(self):
        return [cmd for cmds, _, _ in self.checks for cmd in cmds]

    def test_the_suite_as_the_base_declared_it_runs_once_as_the_target_declares_it(self):
        first = self.member(once=SUITE)
        self.advance(**{"AGENTS.md": f"---\ntests: {NOW}\n---\n"})
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(self.ran(), [NOW])

    def test_a_line_that_was_never_the_suite_still_runs_besides_it(self):
        first = self.member()
        self.advance(**{"AGENTS.md": f"---\ntests: {NOW}\n---\n"})
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(sorted(self.ran()), sorted([ONCE, NOW]))

    def test_without_a_readable_base_the_line_stays_the_tasks_own(self):
        first = self.member(once=SUITE)
        self.advance(**{"AGENTS.md": f"---\ntests: {NOW}\n---\n"})
        for base in (None, "0" * 40):
            with self.subTest(base=base):
                state = {**record.read_state(first), "base_sha": base}
                self.assertEqual(sorted(land._landing_checks(first, state, self.repo, "main")),
                                 sorted([SUITE, NOW]))


if __name__ == "__main__":
    unittest.main()
