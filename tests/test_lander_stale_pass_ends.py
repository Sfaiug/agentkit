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
    def line(self):
        # One check fits, so the pass narrows: the deepest stack (red, behind broken),
        # then the middle one, which is green, then broken's own
        members = [self.member("first", joined=1),
                   self.member("middle", joined=2, **{"middle.txt": "m\n"}),
                   self.member("broken", joined=3, **{"broken.txt": "b\n"}),
                   self.member("last", joined=4, **{"last.txt": "l\n"})]
        self.advance()
        return members

    def checked_with_a_change_during(self, number, changed):
        inner = self.check

        def check(cmds, *args, **kw):
            answer = inner(cmds, *args, **kw)
            if len(self.checks) == number:
                with record.record(changed) as current:
                    current["error"] = "its seat pushed a new head"
            return answer

        with patch.object(gate, "derived_heavy_limit", return_value=1), \
                patch.object(gate, "run_done_when", side_effect=check):
            land.check_line(self.turn)

    def test_a_change_during_a_narrowing_check_starts_no_further_check(self):
        *ahead, last = self.line()
        self.checked_with_a_change_during(1, last)
        self.assertEqual(len(self.checks), 1)
        for directory in ahead:
            self.assertEqual(set(self.wait(directory)), {"line", "joined"})
        self.wake.assert_not_called()

    def test_a_change_during_the_first_check_starts_no_check_of_main(self):
        # a red first stack would have main's own suite run before any blame
        broken = self.member("broken", joined=1, **{"broken.txt": "b\n"})
        self.advance()
        self.checked_with_a_change_during(1, broken)
        self.assertEqual(len(self.checks), 1)
        self.wake.assert_not_called()

    def test_a_change_before_a_verdict_writes_none_and_stops(self):
        *ahead, last = self.line()
        self.checked_with_a_change_during(2, last)
        self.assertEqual(len(self.checks), 2)
        for directory in ahead:
            self.assertEqual(set(self.wait(directory)), {"line", "joined"})
        self.wake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
