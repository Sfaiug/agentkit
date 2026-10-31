"""A screen pass looks at every run once, however many of its rows ask.

A seat's row whose run waits in a landing line found its place by listing and statting every
run, and one owed a merge's ending asked whether its turn may end the same way, twice where the
seat owes work: an open screen on a host whose runs move every second spent a quarter of a core
while nobody touched it.  What a minute of the screen costs is its CPU time, the children's it
reaped included (/proc/<pid>/stat), with a run moving every second; every seat's run waiting to
land and half of them owed an ending cost less than twice what one seat's run waiting does.
Black-box, on tests/test_key_idle_screen_reads_only_what_changed.py's open screen.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import MINUTE, SEATS, OpenScreen


class ScreenPassLooksAtEveryRunOnce(OpenScreen):
    def cpu(self):
        """Clock ticks the screen has run, and the children it reaped."""
        fields = Path(f"/proc/{self.pid}/stat").read_text().rpartition(")")[2].split()
        return sum(map(int, fields[11:15]))      # utime, stime, cutime, cstime

    def busy_minute(self):
        """What the screen runs over a minute in which runs move every second, as on a busy
        host: each move touches the mark every open screen reads again on."""
        self.quiet(self.held())
        moved, start = self.home.path / ".agentkit/state/runs-moved", self.cpu()
        for _ in range(MINUTE):
            moved.touch()
            time.sleep(1)
        return self.cpu() - start

    def test_every_seat_waiting_to_land_and_owed_an_ending_costs_less_than_twice_one_waiting(self):
        self.line_up(SEATS[-1:])
        light = self.busy_minute()
        self.line_up()
        self.assertLess(self.busy_minute(), 2 * light)


if __name__ == "__main__":
    unittest.main()
