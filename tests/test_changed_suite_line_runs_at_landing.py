"""A branch that rewrites its `tests:` line lands only if that new line passes too.

Landing runs the target's own suite, so a change cannot loosen its checks; but a line that
cannot run, once on the target, refuses every later change. The lander runs the rewritten
line beside the target's, on the tree that lands.

Offline: real git and gate commands in an acme sandbox, as `test_lander` sets them up.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import ONCE, SUITE, LanderFixture
from agentkit import land, record, run


class ChangedSuiteLine(LanderFixture, unittest.TestCase):
    def ran(self):
        return [cmd for cmds, _, _ in self.checks for cmd in cmds]

    def test_a_rewritten_line_that_fails_goes_back_to_the_branch(self):
        broken = ".venv/bin/acme -m pytest"
        first = self.member(**{"AGENTS.md": f"---\ntests: {broken}\n---\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn(broken, self.wait(first)["fix"]["line"])
        self.assertIn(SUITE, self.ran())

    def test_a_rewritten_line_that_passes_lands_after_both_ran(self):
        tighter = f"{SUITE} && test -f work.txt"
        first = self.member(**{"AGENTS.md": f"---\ntests: {tighter}\n---\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertIn(SUITE, self.ran())
        self.assertIn(tighter, self.ran())

    def test_a_rewritten_line_with_an_odd_quote_still_runs(self):
        broken = "false # don't skip this"
        first = self.member(**{"AGENTS.md": f"---\ntests: {broken}\n---\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn(broken, self.wait(first)["fix"]["line"])

    def test_a_line_changed_inside_quotes_is_rewritten(self):
        self.advance(**{"AGENTS.md": "---\ntests: test 'a b' = 'a b'\n---\n"})
        rewritten = "test 'a  b' = 'a b'"
        first = self.member(**{"AGENTS.md": f"---\ntests: {rewritten}\n---\n"})
        run.git(self.repo, "checkout", "ak/fix-api")
        checks = land._landing_checks(first, record.read_state(first), self.repo, "main")
        self.assertIn(rewritten, checks)

    def test_a_line_left_alone_runs_once(self):
        first = self.member(**{"AGENTS.md": f"---\ntests:   {SUITE}\n---\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("land", self.wait(first))
        self.assertEqual(sorted(self.ran()), sorted([ONCE, SUITE]))


if __name__ == "__main__":
    unittest.main()
