"""A tick starts the automatic collection at most once a day and writes down when it started.

Collection scans old state across HOME and /tmp, so the tick hands it to a collector of its own
and moves on; `state/gc.json`'s `started_at` is the day's mark, and `state/gc.log` is the trail
a person reads.  A mark less than a day old holds the next collection off, so ticks every few
minutes cost one scan a day; a mark a day old, from a clock that ran ahead, or no number at all
holds nothing off.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import json
from pathlib import Path
import re
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home

SERVICE = ("systemctl", "systemd-run", "loginctl", "journalctl")
STARTED = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d gc: automatic collection started")


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Scheduled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        cls.before = time.time()
        cls.first = home.tick()
        cls.after = time.time()
        cls.stamp, cls.log = cls.mark(), cls.trail()

    @classmethod
    def mark(cls):
        path = cls.home.path / ".agentkit" / "state" / "gc.json"
        return json.loads(path.read_text()) if path.exists() else None

    @classmethod
    def trail(cls):
        path = cls.home.path / ".agentkit" / "state" / "gc.log"
        return path.read_text().splitlines() if path.exists() else []

    def ticked(self, started_at):
        self.home.write(".agentkit/state/gc.json", {"started_at": started_at})
        before, earlier = time.time(), self.trail()
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        lines = self.trail()
        self.assertEqual(lines[:len(earlier)], earlier)
        return before, self.mark(), lines[len(earlier):]

    def test_a_tick_with_no_collection_on_record_starts_one_and_writes_down_when(self):
        self.assertEqual(self.first.code, 0, self.first.err)
        at = self.stamp["started_at"]
        self.assertIn(type(at), (int, float))
        self.assertTrue(self.before <= at <= self.after, at)

    def test_the_collection_says_in_its_log_that_it_started(self):
        self.assertTrue(self.log, "no gc.log")
        self.assertRegex(self.log[0], f"^{STARTED.pattern}$")

    def test_with_no_user_manager_the_collection_asks_no_service_tool(self):
        for name in SERVICE:
            self.assertEqual(self.home.calls(name), [], name)

    def test_a_second_tick_the_same_day_starts_none(self):
        stamp, log = self.mark(), self.trail()
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.mark(), stamp)
        self.assertEqual(self.trail(), log)

    def test_a_mark_less_than_a_day_old_holds_the_next_collection_off(self):
        for hours in (1, 23):
            with self.subTest(hours=hours):
                at = time.time() - hours * 3600
                _, stamp, logged = self.ticked(at)
                self.assertEqual(stamp, {"started_at": at})
                self.assertEqual(logged, [])

    def test_a_mark_a_day_old_from_the_future_or_no_number_holds_nothing_off(self):
        for why, at in (("a day old", time.time() - 25 * 3600),
                        ("from the future", time.time() + 3600), ("no number", "today")):
            with self.subTest(why):
                before, stamp, logged = self.ticked(at)
                self.assertTrue(logged, "nothing logged")
                self.assertRegex(logged[0], f"^{STARTED.pattern}$")
                self.assertEqual([line for line in logged if STARTED.fullmatch(line)], logged[:1])
                self.assertIn(type(stamp["started_at"]), (int, float))
                self.assertTrue(before <= stamp["started_at"] <= time.time(), stamp)


if __name__ == "__main__":
    unittest.main()
