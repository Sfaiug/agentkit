"""A line's suite waits for company only where the host is short of processors for it.

On a busy host, with no room for all a suite's pieces at once, a line's suite waits for company
(tests/test_key_the_suite_runs_once_for_a_batch.py) unless the host had as many processors idle,
on average since a reading a waiting pass kept, as the suite used in its last green whole check.
A mean is never taken over less than a minute: a pass that waits keeps its own reading of the
host, or the one before it where that is younger than a minute and of the same start, or the host
cannot be read.  The two compare exactly, and the waiting pass says the mean to one decimal.
Landing's speed-up stops at this hold, the owner's decision of 24 Nov 2026, kept with its reason
at `land._waits_for_company`.

Black-box, as tests/test_key_a_line_waits_for_company_by_its_own_checks_length.py and with its
fixtures: the program `AK_BIN` names checks a landing line through tests/fixtures/akline.py, on a
host whose readings (AK_HOST_READINGS) leave no room for all the suite's pieces at once, its boot
clock and its processors' idle ticks moved between passes; the suite on record as using two
processors through a green check of 40 minutes.
"""

from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line
import test_key_the_suite_runs_once_for_a_batch as batch

MINUTE = 60
TICKS = 100     # the host's ticks in a second


class ASuiteStartsWhereTheHostHasRoomForItsUse(unittest.TestCase):
    # that key's line, through its module: its tests are not this file's
    join, change, checked = (vars(batch.TheSuiteRunsOnceForABatch)[name]
                             for name in ("join", "change", "checked"))

    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(self.line.close)
        self.line.home.env.pop("AK_MAX_RUNS")
        self.uses(2)
        self.boot_ns, self.idle_ticks = 3600 * 10**9, 7 * 10**6
        self.join()

    def uses(self, cpus):
        """Put on record that the suite used `cpus` processors through its green check."""
        self.line.home.write(self.line.cost.relative_to(self.line.home.path),
                             {"green_seconds": 40 * MINUTE, "green_cpus": cpus})

    def land(self, seconds=0, idle=0, clk_tck=TICKS):
        """What a pass on the busy host says `seconds` after the last, `idle` processors idle on
        average between, the host reading `clk_tck` ticks in a second."""
        self.boot_ns += seconds * 10**9
        self.idle_ticks += int(idle * seconds * TICKS)
        done = self.line.home.ak("run", "--lander", self.line.line, timeout=600, env={
            "AK_HOST_READINGS": json.dumps({**batch.BUSY, "boot_ns": self.boot_ns,
                                            "cpu_idle_ticks": self.idle_ticks,
                                            "clk_tck": clk_tck})})
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def test_three_idle_over_three_minutes_start_it(self):
        self.land()
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())
        self.land(3 * MINUTE, 3)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_one_idle_over_three_minutes_starts_none_and_keeps_its_own_reading(self):
        self.land()
        self.land(3 * MINUTE, 1)
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())
        # 1.75 idle on average since the first reading, 2.5 since the second
        self.land(3 * MINUTE, 2.5)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_pass_half_a_minute_on_starts_none_and_the_first_reading_stays(self):
        self.land()
        self.land(MINUTE // 2, 6)
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())
        # 2.25 idle on average since the first reading, 1.5 since the second
        self.land(3 * MINUTE - MINUTE // 2, 1.5)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_exactly_two_idle_over_exactly_a_minute_start_it(self):
        self.land()
        self.land(MINUTE, 2)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_use_of_2_1_starts_with_exactly_2_1_idle(self):
        self.uses(2.1)
        self.land()
        self.land(MINUTE, Fraction(21, 10))
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_mean_of_2_55_is_said_as_2_6(self):
        self.uses(3)
        self.land()
        self.assertIn("2.6 processors idle on average", self.land(MINUTE, Fraction(51, 20)))
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())

    def test_a_pass_that_cannot_read_the_host_keeps_the_reading_before_it(self):
        self.land()
        self.land(3 * MINUTE, 3, clk_tck=0)
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())
        self.land(3 * MINUTE, 3)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_reading_of_another_start_of_the_host_gives_way_to_its_own(self):
        self.land()
        self.boot_ns, self.idle_ticks = 10**9, 0
        self.land(3 * MINUTE, 3)
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())
        self.land(3 * MINUTE, 3)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())


if __name__ == "__main__":
    unittest.main()
