"""While another tick holds the tick lock, `ak watch` does nothing, says who holds it, exits 0.

The tick is a cron line every three minutes whatever the last one is doing, and two at once
would read the same panes and type into the same seats.  So a tick that finds the lock held
leaves everything as it was, asks nothing of GitHub or a harness and exits 0, a normal event
for cron; it names the holder's pid and how long it has held the lock, and from 30 minutes
calls it hung for the person reading the log.  `ak doctor` names the holder in its `tick`
line, beside the size of the tick's log, and calls a lock nobody holds free whatever its file
says.  The holder here is this test: it flocks state/watch.tick.lock as a tick does, writes a
pid into it and back-dates the file, whose mtime is when that tick began.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import fcntl
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REFUSED, Home

LOCK = ".agentkit/state/watch.tick.lock"
# half a minute past each whole minute: ak reads the age a moment after the test sets it
MINUTE = 60
SLACK = 30
RUNNING = "tick already running (pid 4242, for {} min)\n"
HUNG = ("WARN the tick holding the lock has been running for {} min; look at it, and kill it if "
        "it is hung\n")
DOCTOR = "tick  lock held by pid 4242 for {} min · watch.log 0.0 MB of 5 MB"


def said(minutes):
    """What a tick that read the lock as held `minutes` prints."""
    return RUNNING.format(minutes) + (HUNG.format(minutes) if minutes >= 30 else "")


class HeldLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.lock = cls.home.write(LOCK, "4242\n")
        cls.held = cls.lock.open("a+")
        cls.addClassCleanup(cls.held.close)
        fcntl.flock(cls.held, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def held_for(self, minutes):
        self.home.write(LOCK, "4242\n", ago=minutes * MINUTE + SLACK)

    def aged(self, run):
        """What `run` returns, and each whole minute the lock was held while it ran: ak reads
        its own clock, which a black-box test cannot hold, so a slow start may read a later one."""
        began = self.lock.stat().st_mtime
        before = time.time()
        result = run()
        return result, range(int(before - began) // MINUTE, int(time.time() - began) // MINUTE + 1)

    def tick(self):
        """`ak watch`, and each refused host tool it called."""
        before = {name: len(self.home.calls(name)) for name in REFUSED}
        done = self.home.ak("watch")
        return done, {name: self.home.calls(name)[count:] for name, count in before.items()
                      if self.home.calls(name)[count:]}

    def test_a_tick_while_another_holds_the_lock_says_so_does_nothing_and_exits_0(self):
        self.held_for(5)
        stamp = self.lock.stat().st_mtime
        (done, called), ages = self.aged(self.tick)
        self.assertEqual((done.code, done.err), (0, ""))
        self.assertIn(done.out, [said(age) for age in ages])
        self.assertEqual(called, {})
        self.assertEqual((self.lock.read_text(), self.lock.stat().st_mtime), ("4242\n", stamp))
        self.assertFalse((self.home.path / ".agentkit/state/watch.json").exists())
        self.assertEqual(self.home.tmux("list-sessions").out, "")

    def test_under_thirty_minutes_the_holder_is_not_called_hung(self):
        for minutes in (0, 29):
            with self.subTest(minutes=minutes):
                self.held_for(minutes)
                (done, _), ages = self.aged(self.tick)
                self.assertEqual(done.code, 0)
                self.assertIn(done.out, [said(age) for age in ages])

    def test_from_thirty_minutes_the_holder_is_called_hung_and_the_tick_still_exits_0(self):
        for minutes in (30, 40):
            with self.subTest(minutes=minutes):
                self.held_for(minutes)
                (done, called), ages = self.aged(self.tick)
                self.assertEqual(done.code, 0)
                self.assertIn(done.out, [said(age) for age in ages])
                self.assertEqual(called, {})

    def test_doctor_names_the_holder_and_how_long_it_has_held_the_lock(self):
        self.held_for(40)
        done, ages = self.aged(lambda: self.home.ak("doctor"))
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue({DOCTOR.format(age) for age in ages} & set(done.out.splitlines()),
                        done.out)


class FreeLock(unittest.TestCase):
    def test_doctor_calls_a_lock_an_ended_tick_left_free_and_reads_the_log_s_size(self):
        with Home() as home:
            akconfig.write(home, ["opus", "astra"])
            home.write(LOCK, "4242\n", ago=40 * MINUTE + SLACK)
            log = home.path / ".agentkit/tmp/watch.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_bytes(b"x" * (3 * 1024 * 1024 // 2))
            done = home.ak("doctor")
            self.assertEqual(done.code, 0, done.err)
            self.assertIn("tick  lock free · watch.log 1.5 MB of 5 MB", done.out.splitlines())
            # asking who holds it is no taking of it
            self.assertEqual((home.path / LOCK).read_text(), "4242\n")


if __name__ == "__main__":
    unittest.main()
