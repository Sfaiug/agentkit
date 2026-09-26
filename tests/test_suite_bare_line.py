"""A done-when line that is the declared suite's bare first command runs once, with the suite."""

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run

BARE = "PYTHONUNBUFFERED=1 scripts/run_widget_tests.sh -x -q"
SUITE = f'{BARE} 2>&1 | tee "/tmp/widget-gate-test.log"'


class SuiteBareLine(unittest.TestCase):
    def checkouts(self, suite):
        tmp = tempfile.TemporaryDirectory(prefix="suite-bare-")
        self.addCleanup(tmp.cleanup)
        wt = Path(tmp.name)
        (wt / "AGENTS.md").write_text(f"---\ntests: {suite}\n---\n# acme\n")
        return wt

    def test_bare_first_command_of_a_piped_suite_runs_once(self):
        wt = self.checkouts(SUITE)
        cmds = run.with_suite(["true", BARE], wt)
        self.assertEqual(cmds, ["true", f"{SUITE}  # once"])
        every, once = run.group_commands(cmds)
        self.assertEqual(every, ["true"])
        self.assertEqual(once, [SUITE])

    def test_suite_followed_by_another_check_runs_every_round(self):
        wt = self.checkouts(SUITE)
        line = f"{SUITE} && another-check"
        cmds = run.with_suite(["true", line], wt)
        self.assertEqual(cmds, ["true", line, f"{SUITE}  # once"])
        every, once = run.group_commands(cmds)
        self.assertIn(line, every)
        self.assertEqual(once, [SUITE])

    def test_first_command_containing_a_substitution_still_matches(self):
        bare = ("PYTHONUNBUFFERED=1 scripts/run_widget_tests.sh "
                "$(sed -n '/^WIDGET_TESTS=(/,/^)/p' scripts/widget_gate.sh "
                "| grep -oE '^\\s*tests/[^ ]+' | tr -d ' ') -x -q")
        suite = f'{bare} 2>&1 | tee "/tmp/widget-gate-test.log"'
        wt = self.checkouts(suite)
        cmds = run.with_suite(["true", bare], wt)
        self.assertEqual(cmds, ["true", f"{suite}  # once"])

    def test_bare_line_marked_once_keeps_todays_meaning(self):
        wt = self.checkouts(SUITE)
        line = f"{BARE}  # once"
        cmds = run.with_suite(["true", line], wt)
        self.assertEqual(cmds, ["true", line, f"{SUITE}  # once"])

    def test_bare_line_matching_whitespace_aside_runs_once(self):
        wt = self.checkouts(SUITE)
        cmds = run.with_suite(["true", f"  {BARE}  "], wt)
        self.assertEqual(cmds, ["true", f"{SUITE}  # once"])


if __name__ == "__main__":
    unittest.main()
