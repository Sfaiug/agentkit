"""A pass stops checking once the line changes under it, so the next pass sees it as it is.

Offline: local Git and real suites, with isolated state and fake wakes, as in test_lander.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lander as fixture
from agentkit import gate, land, record


class StalePassEnds(fixture.LanderFixture, unittest.TestCase):
    def test_a_pass_whose_line_changed_stops_checking(self):
        # One check fits, so the pass narrows: the deepest stack (red, behind broken),
        # then the middle one, which is green.  A seat changes the last member's record
        # during that check: no verdict of this pass can be written any more.
        first = self.member("first", joined=1)
        middle = self.member("middle", joined=2, **{"middle.txt": "m\n"})
        broken = self.member("broken", joined=3, **{"broken.txt": "b\n"})
        last = self.member("last", joined=4, **{"last.txt": "l\n"})
        self.advance()
        inner = self.check

        def check(cmds, *args, **kw):
            answer = inner(cmds, *args, **kw)
            if len(self.checks) == 2:
                with record.record(last) as current:
                    current["error"] = "its seat pushed a new head"
            return answer

        with patch.object(gate, "derived_heavy_limit", return_value=1), \
                patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn)
        self.assertEqual(len(self.checks), 2)
        for directory in (first, middle, broken):
            self.assertNotIn("land", self.wait(directory))
            self.assertNotIn("fix", self.wait(directory))
        self.wake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
