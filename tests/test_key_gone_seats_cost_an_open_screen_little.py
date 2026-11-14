"""Seats whose rows did not change cost an open screen's reads little, however many it lists.

A screen reads again whenever a seat's file changes, which some seat's does every few seconds, and
each read decided every seat it lists again: on a host's screen over 68 seats, most of them gone,
that was most of what its reads spent.  The cost is the screen's own CPU, user and system, without
its children (its tmux calls), its draws and its looks every ten seconds included; its yardstick is
a plain look at every seat's files done in this test's process over the same minute, so a slow or
loaded host raises both.  The screen shows a page of rows, so drawing them does not drown the reads.
Black-box, on tests/test_key_idle_screen_reads_only_what_changed.py's open screen.
"""

import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_idle_screen_reads_only_what_changed import (BOUND, MINUTE, SEATS, OpenScreen, ended,
                                                          row)
import test_key_runs_at_rest_cost_an_open_screen_little as at_rest

LIVE = SEATS[:3]
GONE = [f"acme-past-{n:02}" for n in range(60)]
EVERY = 3         # seconds between two writes of a live seat's file, each a read of the screen's
LOOKS = 360       # what that minute may cost, in plain looks: deciding every seat on every read
                  # costs about 430, deciding the changed ones about 305


class GoneSeatsCostAnOpenScreenLittle(OpenScreen):
    """A screen over three live seats and sixty gone ones, each gone one owing its plan's line,
    and each seat with a run."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        repo, now = home.path / "code" / "acme", int(time.time())
        for n, name in enumerate([*LIVE, *GONE]):
            Seat(home, name, cwd=repo, alive=name in LIVE, record={"created": now - 7200 + n},
                 planned=name in GONE)
            record = ended(n, name, now)
            home.write(f".agentkit/runs/{record['run_id']}/run.json", record)
        cls.menu = Terminal(home, "--client", size=(100, 24))
        cls.menu.wait(lambda screen: any(row(name)(screen) for name in [*LIVE, *GONE]), bound=BOUND)
        cls.pid = cls.screen_pid()
        at_rest.RunsAtRestCostAnOpenScreenLittle.steady.__func__(cls)

    @classmethod
    def cpu(cls):
        """Clock ticks the screen itself has run, user and system, without its children."""
        fields = Path(f"/proc/{cls.pid}/stat").read_text().rpartition(")")[2].split()
        return int(fields[11]) + int(fields[12])

    def busy_minute(self):
        """The screen's own CPU over a still minute in which one live seat's file is written every
        EVERY seconds, each write news the screen reads again on, in plain looks taken meanwhile."""
        path, stop = self.home.path / f".agentkit/state/seat-{LIVE[1]}.json", threading.Event()

        def write():
            while not stop.wait(EVERY):
                os.utime(path)         # as written: what it holds is the screen's own looks'
        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        try:
            looks, start, end = [], self.cpu(), time.monotonic() + MINUTE
            while time.monotonic() < end:
                looks.append(self.plain_look())
                time.sleep(0.5)
            return (self.cpu() - start) / (sum(looks) / len(looks))
        finally:
            stop.set()
            writer.join()

    def plain_look(self):
        """Clock ticks of this thread's CPU reading every seat's files once, as deciding it
        does."""
        start, state = time.thread_time(), self.home.path / ".agentkit/state"
        for name in [*LIVE, *GONE]:
            for kind in ("session-{}.json", "seat-{}.json", "notify-{}.json", "hook-{}.json",
                         "plan-{}.md"):
                try:
                    json.loads((state / kind.format(name)).read_text())
                except (FileNotFoundError, ValueError):
                    pass               # no such file, or a plan
        return (time.thread_time() - start) * os.sysconf("SC_CLK_TCK")

    def test_a_minute_of_reads_costs_less_than_a_few_dozen_plain_looks(self):
        spent = min(self.busy_minute() for _ in range(2))
        self.assertLess(spent, LOOKS, f"a minute costs {spent:.0f} plain looks")


if __name__ == "__main__":
    unittest.main()
