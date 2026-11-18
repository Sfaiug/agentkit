"""A line waits for company three times as long as its own check takes, at most two hours.

On a busy host a whole suite waits for company (tests/test_key_the_suite_runs_once_for_a_batch.py)
until the line's longest-ready member has been in line three times as long as the suite's last
green check took, or two hours where that is less.  A red check leaves that length as it was,
and a suite with no green check on record does not wait: its first check measures it.

Black-box, as that key and with its fixtures: the program `AK_BIN` names checks a landing line
through tests/fixtures/akline.py on a host whose readings (AK_HOST_READINGS) leave no room for
all the suite's pieces at once, the clock moved by putting the members' joins back, and the
suite's last green check put on record as taking as long as each case needs, or read there.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line
import test_key_the_suite_runs_once_for_a_batch as batch

MINUTE = 60
HOUR = 3600


class ALineWaitsForCompanyByItsOwnChecksLength(unittest.TestCase):
    # that key's line, through its module: its tests are not this file's
    join, later, change, land, checked = (vars(batch.TheSuiteRunsOnceForABatch)[name]
                                          for name in ("join", "later", "change", "land",
                                                       "checked"))

    def setUp(self):
        self.line = Line({"t/ok.sh": "test ! -f red.txt\n"})
        self.addCleanup(self.line.close)
        self.line.home.env.pop("AK_MAX_RUNS")

    def after(self, seconds):
        """What a pass on the busy host checks of a member, alone in line, joined `seconds`
        ago."""
        self.join()
        self.later(seconds)
        self.land(batch.BUSY)
        return self.checked()

    def test_a_two_minute_suite_waits_six_minutes(self):
        self.line.measured(2 * MINUTE)
        self.assertEqual(self.after(5 * MINUTE), (0, [False]), self.line.runs())
        self.later(2 * MINUTE)
        self.land(batch.BUSY)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_forty_minute_suite_waits_two_hours(self):
        self.line.measured(40 * MINUTE)
        self.assertEqual(self.after(2 * HOUR - 10 * MINUTE), (0, [False]), self.line.runs())

    def test_a_three_hour_suite_waits_two_hours(self):
        self.line.measured(3 * HOUR)
        self.assertEqual(self.after(2 * HOUR), (1, [True]), self.line.runs())

    def test_a_red_check_leaves_the_wait_its_green_one_set(self):
        self.line.measured(40 * MINUTE)
        self.join({"red.txt": "x\n"})
        self.land(batch.IDLE)
        self.assertIn("fix", self.line.verdict(1))
        self.join()
        self.later(2 * HOUR - 10 * MINUTE)
        self.land(batch.BUSY)
        self.assertEqual(self.checked(), (1, [False, False]), self.line.runs())
        self.later(10 * MINUTE)
        self.land(batch.BUSY)
        self.assertEqual(self.checked(), (2, [False, True]), self.line.runs())

    def test_a_suite_never_measured_is_checked_at_once_and_so_measured(self):
        self.assertEqual(self.after(0), (1, [True]), self.line.runs())
        self.assertGreater(json.loads(self.line.cost.read_text())["green_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
