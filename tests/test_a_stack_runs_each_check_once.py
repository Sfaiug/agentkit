"""A check of stacked changes runs each command its members owe once on the tested tree.

A change that rewrites the `tests:` line makes that line every later stack's own, besides the
target's. A member behind it with a `# once` check of its own brought the rewritten line along
a second time: on 11 Nov 2026 a 21-minute suite ran twice on one tree in one check.

Offline: real git and gate commands in an acme sandbox, as `test_lander` sets them up.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import ONCE, SUITE, LanderFixture
from agentkit import gate, land

NOW = "test ! -f broken.txt && test -f base.txt"


class EachCheckOnce(LanderFixture, unittest.TestCase):
    def test_a_rewritten_suite_line_runs_once_for_the_stack_behind_it(self):
        head = self.member("acme-suite", **{"AGENTS.md": f"---\ntests: {NOW}\n---\n"})
        tail = self.member("acme-client", joined=2, once="true", **{"client.txt": "client\n"})
        self.advance()
        with patch.object(gate, "derived_heavy_limit", return_value=1):    # one whole check fits
            land.check_line(self.turn)
        for member in (head, tail):
            self.assertIn("land", self.wait(member))
        ran = [cmd for cmds, _, _ in self.checks for cmd in cmds]
        self.assertEqual(sorted(ran), sorted([ONCE, "true", NOW, SUITE]))


if __name__ == "__main__":
    unittest.main()
