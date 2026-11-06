"""Once the week's line is in, a tick tells the `audit` seat a stall's line, each stall once.

A stall is work that waits while nothing moves it, judged against its own pace: here the run
first in line for a slot has waited two hours while the queue is polled, where the last firsts
let in waited a quarter of an hour.  While this week's line is not yet delivered, the stall's
waits behind it.  Once it is, a tick that finds the stall writes its line to state/stuck.json,
logs `stuck: <line>`, and the line goes into the audit seat at its quiet prompt, as the week's
goes; later ticks while the same stall runs tell nothing new.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, each tick in the box `home.tick()`
builds, before a seat of tests/fixtures/akseat.py, judged by what its pane received, what the
ticks printed and state/stuck.json.  The queue is ak's own file, polled before each tick as its
first polls it, the wait's clock set back two hours, not waited out.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

FIRST, BEHIND = "20261105-0900-fix-api", "20261105-0901-fix-web"
WAITED = 7200               # first in line two hours,
PACE = [600, 900, 1200]     # where the last firsts let in waited 15 minutes at the median
TICKS = 4       # past the busy one: a line may take a tick to type and another to confirm


def stuck_lines(done):
    return [line for line in done.out.splitlines() if line.startswith("stuck: ")]


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AuditStallLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"], audit=True)
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.seat = Seat(home, "audit", screen="claude-working-pane.txt")
        cls.since = time.time() - WAITED
        cls.busy = cls.tick()       # the week's line is written; the seat, working, takes none
        cls.waiting = cls.read("stuck.json"), cls.seat.lines()
        cls.seat.show("claude-prompt-pane.txt")
        cls.ticks = []
        while len(cls.ticks) < TICKS and not any(map(stuck_lines, cls.ticks)):
            cls.ticks.append(cls.tick())
        cls.told = cls.read("stuck.json")
        cls.later = [cls.tick(), cls.tick()]

    @classmethod
    def tick(cls):
        """One tick, its queue polled just before as its first polls it: the same wait."""
        cls.home.write(".agentkit/runs/.slots.queue", {
            "at": time.time(), "running": 1, "queue": [FIRST, BEHIND], "since": cls.since,
            "took": PACE, "last_in": cls.since, "turns": []})
        return cls.home.tick()

    @classmethod
    def read(cls, name):
        try:
            return json.loads((cls.home.path / ".agentkit" / "state" / name).read_text())
        except FileNotFoundError:
            return {}

    def test_every_tick_succeeds(self):
        for done in (self.busy, *self.ticks, *self.later):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_while_the_week_s_line_waits_the_stall_s_waits_behind_it(self):
        self.assertEqual(stuck_lines(self.busy), [], self.busy.out)
        self.assertEqual((self.waiting[0].get("line"), self.waiting[1]), (None, []))

    def test_once_the_week_s_line_is_in_a_tick_logs_the_stall_s_line_and_keeps_it(self):
        line = self.told.get("line", "")
        self.assertIn(FIRST, line)
        self.assertEqual([said for done in self.ticks for said in stuck_lines(done)],
                         [f"stuck: {line}"], [done.out for done in self.ticks])

    def test_the_seat_takes_the_week_s_line_then_the_stall_s(self):
        self.assertEqual(self.seat.wait_lines(2),
                         [self.read("audit.json").get("line"), self.told.get("line")])

    def test_a_later_tick_while_the_stall_runs_tells_nothing_new(self):
        for done in self.later:
            self.assertEqual(stuck_lines(done), [], done.out)
        self.assertEqual(self.read("stuck.json").get("line"), self.told.get("line"))
        self.assertEqual(len(self.seat.lines()), 2, self.seat.lines())


if __name__ == "__main__":
    unittest.main()
