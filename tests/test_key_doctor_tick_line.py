"""`ak doctor`'s `tick` line says when the last tick ended, how long it took and its slowest pass.

After the lock comes the end of the last tick watch.json records, as an age, the seconds it took
and its slowest pass with that pass's seconds; last, that git housekeeping has not run in this
home (tests/test_key_housekeeping_hourly.py names when it has).  A tick silent for 30 minutes
is the same hang the overlap line of `ak watch` calls hung, so doctor says that on the line and
exits 1 once everything else has been said; so does a home where no tick has ended.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, whose `ticked`
writes the record: 12.5 s long, its slowest pass `incoming prs` at 9.1 s.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home

MINUTE = 60
HUNG = 30 * MINUTE
LINE = "tick  lock free · {} · watch.log 0.0 MB of 5 MB · git housekeeping has not run yet"
ENDED = "ended {}m ago, took 12.5 s, slowest incoming prs 9.1 s"
SILENT = " · no tick has ended within 30m"
NONE = LINE.format("no tick has ended yet")


class DoctorTickLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])

    def doctor(self, ago):
        """`ak doctor` a tick `ago` seconds after the last one ended, and every line of `tick`
        it may print: ak reads its own clock, so a slow start may read a later minute."""
        before = time.time()
        self.home.ticked(ago=ago)
        done = self.home.ak("doctor")
        ages = range(ago // MINUTE, int(ago + time.time() - before) // MINUTE + 1)
        return done, [LINE.format(ENDED.format(age) + (SILENT if ago >= HUNG else ""))
                      for age in ages]

    def assert_said(self, done, code, lines):
        self.assertEqual(done.code, code, done.out + done.err)
        said = done.out.splitlines()
        self.assertTrue(set(lines) & set(said), done.out)
        # the exit comes after the report: the last line is still the rented machine
        self.assertTrue(said[-1].startswith("rented machines: "), done.out)

    def test_a_tick_ended_a_minute_ago_is_named_and_doctor_exits_0(self):
        done, lines = self.doctor(MINUTE + 30)
        self.assert_said(done, 0, lines)

    def test_a_silence_short_of_the_threshold_exits_0(self):
        done, lines = self.doctor(HUNG - 2 * MINUTE)
        self.assert_said(done, 0, lines)

    def test_a_silence_of_the_threshold_exits_1_saying_so(self):
        done, lines = self.doctor(HUNG)
        self.assert_said(done, 1, lines)

    def test_a_tick_older_than_the_threshold_exits_1_naming_its_age(self):
        done, lines = self.doctor(45 * MINUTE + 30)
        self.assert_said(done, 1, lines)

    def test_no_record_exits_1_saying_no_tick_has_ended(self):
        self.assert_said(self.home.ak("doctor"), 1, [NONE])

    def test_a_record_no_tick_wrote_reads_as_none(self):
        for record in ("soon", {"ended_at": "soon"}, {"ended_at": 1, "started_at": 0}):
            with self.subTest(record=record):
                self.home.write(".agentkit/state/watch.json", {"tick": record})
                self.assert_said(self.home.ak("doctor"), 1, [NONE])


if __name__ == "__main__":
    unittest.main()
