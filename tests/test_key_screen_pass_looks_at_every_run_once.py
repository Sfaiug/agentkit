"""A screen pass looks at every run once, however many of its rows ask.

A seat's row whose run waits in a landing line found its place by listing and statting every
run, and one owed a merge's ending asked whether its turn may end the same way, twice where the
seat owes work: an open screen on a host whose runs move every second spent a quarter of a core
while nobody touched it.  What a minute of the screen costs is its CPU time, the children's it
reaped included (/proc/<pid>/stat), with a run moving every second; every seat's run waiting to
land and half of them owed an ending cost less than twice what one seat's run waiting does.
That time over a wall-clock minute read 1.6 to 3.5 times as much on one tree, so only what the
host's load leaves alone is compared: as many reads each, as a busy host fits fewer into a minute;
no row circling, whose frames go by the clock; and the time against what this test's own look at
the runs takes beside it, as a busy host charges all of it more.
Black-box, on tests/test_key_idle_screen_reads_only_what_changed.py's open screen.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import (BOUND, MINUTE, PLAN, SEATS, OpenScreen,
                                                          row)


class ScreenPassLooksAtEveryRunOnce(OpenScreen):
    def busy_minute(self):
        """What the screen runs over a minute's reads, as on a busy host each on a run's move: it
        touches the mark every open screen reads again on, and a line of a plan done or not beside
        it shows once that read has landed.  In what this process's own look costs after each."""
        self.quiet(self.held())
        state, lines = self.home.path / ".agentkit/state", PLAN.splitlines(True)
        start, beside = self.cpu(), 0
        for n in range(MINUTE):
            shown = lines[(n + 1) % 2:]
            self.home.write(state / "plan-acme-00.md", "".join(shown))
            (state / "runs-moved").touch()
            self.menu.wait(row("acme-00", f"{len(shown) - 1} of {len(shown)}"), bound=BOUND)
            began = time.process_time()
            self.held()
            beside += time.process_time() - began
        return (self.cpu() - start) / beside

    def test_every_seat_waiting_to_land_and_owed_an_ending_costs_less_than_twice_one_waiting(self):
        self.home.tmux("kill-server")     # a seat tmux holds draws its recorded word, asking none
        for seat in SEATS[1::2]:          # the seats with no plan, which would circle once working
            self.home.write(f".agentkit/state/plan-{seat}.md", PLAN)
        self.line_up(SEATS[-1:])
        light = self.busy_minute()
        self.line_up()
        self.assertLess(self.busy_minute(), 2 * light)


if __name__ == "__main__":
    unittest.main()
