"""A screen pass looks at every run once, however many of its rows ask.

A seat's row whose run waits in a landing line found its place by listing and statting every
run, and one owed a merge's ending asked whether its turn may end the same way, twice where the
seat owes work: an open screen on a host whose runs move every second spent a quarter of a core
while nobody touched it.  A look begins by opening the runs' directory, so the kernel counts them
(inotify): over as many reads, every seat's run waiting to land and half of them owed an ending
look less than twice as often as one seat's run waiting.  Counted, since the CPU time they spend
over a minute follows the host's load as much: with the host busy over only the first of two
minutes, the second spent 3.5 times the first.
Black-box, on tests/test_key_idle_screen_reads_only_what_changed.py's open screen.
"""

import ctypes
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import BOUND, SEATS, OpenScreen, row

READS = 20
IN_CLOSE_NOWRITE, IN_OPEN = 0x10, 0x20      # <sys/inotify.h>


def opened(directory, during):
    """How often that directory, none of its entries, was opened while `during()` ran.  Its closes
    are watched too: the kernel folds an unread event into the same one just before it."""
    libc = ctypes.CDLL(None)
    watch = libc.inotify_init1(os.O_NONBLOCK)
    try:
        libc.inotify_add_watch(watch, os.fsencode(directory), IN_OPEN | IN_CLOSE_NOWRITE)
        during()
        events = os.read(watch, 1 << 20)      # more than a full queue of them holds
    finally:
        os.close(watch)
    count, at = 0, 0
    while at < len(events):
        _, mask, _, name = struct.unpack_from("iIII", events, at)    # struct inotify_event
        count += bool(mask & IN_OPEN) and not name
        at += 16 + name
    return count


class ScreenPassLooksAtEveryRunOnce(OpenScreen):
    def busy_reads(self):
        """READS reads by the screen, each on a run's move as on a busy host: it touches the mark
        every open screen reads again on, and the line of a plan done beside it shows once that
        read has landed.  Only the first can have begun before what `line_up` wrote."""
        plan = self.home.path / ".agentkit/state/plan-acme-00.md"
        for _ in range(READS):
            lines = plan.read_text().splitlines(True)
            self.home.write(plan, "".join([lines[0], *lines]))
            (self.home.path / ".agentkit/state/runs-moved").touch()
            self.menu.wait(row("acme-00", f"{len(lines)} of {len(lines) + 1}"), bound=BOUND)

    def looks(self):
        return opened(self.home.path / ".agentkit/runs", self.busy_reads)

    def test_every_seat_waiting_to_land_and_owed_an_ending_looks_less_than_twice_one_waiting(self):
        self.line_up(SEATS[-1:])
        light = self.looks()
        self.line_up()
        self.assertLess(self.looks(), 2 * light)


if __name__ == "__main__":
    unittest.main()
