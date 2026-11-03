"""Another tick pages once when ticks stop ending, and an ending tick says once they are back.

Black-box against AK_BIN, with a throwaway HOME and sink.py's loopback webhook. Held locks
belong to this test, never a process; ending ticks run offline in home.tick()'s box.
"""

import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import boxable, Home
from fixtures.fakegh import OFFLINE, GitHub
from fixtures.sink import Sink

LOCK = ".agentkit/state/watch.tick.lock"
MINUTE = 60


class TicksStopped(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(Home())
        akconfig.write(self.home, ["opus"])
        self.home.env["AGENTKIT_DISCORD_USER_ID"] = "42"
        self.sink = self.enterContext(Sink(self.home))

    def held_for(self, minutes):
        lock = self.home.write(LOCK, "4242\n", ago=minutes * MINUTE + 30)
        held = self.enterContext(lock.open("a+"))
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return held

    def run_tick(self, *, ends=False):
        before = time.time()
        done = self.home.tick() if ends else self.home.ak("watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        return before, time.time()

    def assert_page(self, since, bounds, reason):
        ages = range(int(bounds[0] - since) // MINUTE,
                     int(bounds[1] - since) // MINUTE + 1)
        self.assertTrue(self.sink.pages(), "no stop page reached the owner")
        self.assertIn(self.sink.pages()[0],
                      [f"🔴 ak ticks stopped ending · {reason.format(age)} <@42>"
                       for age in ages])
        self.assertEqual(self.sink.requests[0].json["allowed_mentions"], {"users": ["42"]})

    def test_a_holder_over_an_hour_pages_once_even_as_it_keeps_running(self):
        self.held_for(61)
        lock = self.home.path / LOCK
        since = lock.stat().st_mtime
        self.assert_page(since, self.run_tick(), "pid 4242 has held the lock for {} min")
        page, = self.sink.pages()
        # Let the same holder stand longer without waiting three real minutes.
        later = since - 3 * MINUTE
        os.utime(lock, (later, later))
        self.run_tick()
        self.assertEqual(self.sink.pages(), [page])

    def test_the_real_thirty_six_minute_tick_would_not_page(self):
        self.held_for(36)
        self.run_tick()
        self.assertEqual(self.sink.pages(), [])

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_tick_that_ends_says_back_once_without_a_mention_and_a_new_stop_pages(self):
        held = self.held_for(61)
        since = (self.home.path / LOCK).stat().st_mtime
        self.run_tick()
        held.close()
        GitHub(self.home).reply("", err=OFFLINE, code=1)
        bounds = self.run_tick(ends=True)
        page, back = self.sink.pages()
        # The tick's record, not host load, tells when it ended.
        tick = json.loads((self.home.path / ".agentkit/state/watch.json").read_text())["tick"]
        self.assertTrue(bounds[0] <= tick["ended_at"] <= bounds[1])
        minutes = int(tick["ended_at"] - since) // MINUTE
        duration = re.fullmatch(r"ak ticks end again after (\d+) h(?: (\d+) min)?", back)
        self.assertIsNotNone(duration, back)
        self.assertEqual(int(duration[1]) * 60 + int(duration[2] or 0), minutes)
        self.assertEqual(self.sink.requests[1].json["allowed_mentions"], {"parse": []})
        self.run_tick(ends=True)
        self.assertEqual(self.sink.pages(), [page, back])
        self.held_for(61)
        self.run_tick()
        self.assertEqual(len(self.sink.pages()), 3)

    def failing_ticks(self, started, ended=90):
        state = self.home.ticked(ago=ended * MINUTE + 30)
        since = json.loads(state.read_text())["tick"]["ended_at"]
        self.home.write(LOCK, "4242\n", ago=started * MINUTE + 30)
        GitHub(self.home).reply("", err=OFFLINE, code=1)
        return since

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_recent_starts_without_an_end_for_ninety_minutes_page_then_say_back(self):
        since = self.failing_ticks(started=3)
        # Refuse every attempt to save watch.json, so these ticks leave no ended record.
        obstacle = self.home.path / ".agentkit/state/watch.tmp"
        obstacle.mkdir()
        for _ in range(2):
            before = time.time()
            done = self.home.tick()
            self.assertNotEqual(done.code, 0, done.out + done.err)
            self.assert_page(since, (before, time.time()), "no tick has ended for {} min")
            self.assertEqual(len(self.sink.pages()), 1)
        obstacle.rmdir()
        self.assert_page(since, self.run_tick(ends=True), "no tick has ended for {} min")
        self.assertEqual(len(self.sink.pages()), 2)
        self.assertTrue(self.sink.pages()[1].startswith("ak ticks end again after "))
        self.run_tick(ends=True)
        self.assertEqual(len(self.sink.pages()), 2)

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_no_recent_start_is_a_cron_or_host_gap_and_pages_nothing(self):
        self.failing_ticks(started=90)
        self.run_tick(ends=True)
        self.assertEqual(self.sink.pages(), [])

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_no_previous_start_is_no_evidence_that_ticks_stopped_ending(self):
        self.failing_ticks(started=3)
        (self.home.path / LOCK).unlink()
        self.run_tick(ends=True)
        self.assertEqual(self.sink.pages(), [])

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_thirty_six_minutes_without_an_end_is_below_the_page_floor(self):
        self.failing_ticks(started=3, ended=36)
        self.run_tick(ends=True)
        self.assertEqual(self.sink.pages(), [])

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_a_first_tick_has_no_stop_to_page(self):
        GitHub(self.home).reply("", err=OFFLINE, code=1)
        self.run_tick(ends=True)
        self.assertEqual(self.sink.pages(), [])


if __name__ == "__main__":
    unittest.main()
