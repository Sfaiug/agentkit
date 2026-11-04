"""A look at every seat reads the runs once, however many endings its seats are owed.

When nothing moves, the clock has the screen look at every seat again (`menu.TICK`) in a thread of
its own, where each merge's ending a seat owing work was owed listed and statted every run twice.
With those seats' runs going, a still minute lists the runs fewer times than the endings owed, by
the kernel's count (inotify).  No CPU time, and no second minute to set it against: what a minute
holds follows the host's load, which only lowers this count.  Black-box, on the idle key's open
screen.
"""

import ctypes
import os
from pathlib import Path
import select
import struct
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import (BOUND, MINUTE, RUNS, SEATS, OpenScreen,
                                                          ended, row)

# A listing opens the directory and closes it: inotify merges an event with the same one before it,
# so the opens of a queue left unread for a minute count only with the closes between them.
IN_OPEN, IN_CLOSE_NOWRITE = 0x20, 0x10
EVENT = struct.Struct("iIII")


def listings(directory, seconds):
    """How often `directory` itself is listed, over that many seconds from its next listing."""
    libc = ctypes.CDLL(None, use_errno=True)
    queue = libc.inotify_init1(os.O_CLOEXEC)
    assert queue >= 0, os.strerror(ctypes.get_errno())
    try:
        watch = libc.inotify_add_watch(queue, os.fsencode(directory), IN_OPEN | IN_CLOSE_NOWRITE)
        assert watch >= 0, os.strerror(ctypes.get_errno())
        assert select.select([queue], [], [], BOUND)[0], "nothing ever listed it"
        time.sleep(seconds)
        events = os.read(queue, 1 << 20)
    finally:
        os.close(queue)
    count, at = 0, 0
    while at < len(events):
        _, mask, _, name = EVENT.unpack_from(events, at)     # a name: what it holds, not itself
        count += bool(mask & IN_OPEN and not name)
        at += EVENT.size + name
    return count


class SeatLookReadsTheRunsOnce(OpenScreen):
    def test_a_still_minute_opens_no_unchanged_notice_and_a_changed_one_shows(self):
        def notice(name, **fields):
            return self.home.write(f".agentkit/state/notify-{name}.json",
                                   {"session": name, "kind": "needs", "text": "Which one?",
                                    "time": time.time(), **fields})

        seat, notices = SEATS[-1], [notice(name) for name in SEATS]
        self.menu.wait(row(seat, "needs you"), bound=BOUND)
        self.quiet(self.held())
        libc = ctypes.CDLL(None, use_errno=True)
        queue = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        self.addCleanup(os.close, queue)
        for path in notices:
            self.assertGreaterEqual(libc.inotify_add_watch(queue, os.fsencode(path), IN_OPEN), 0)
        time.sleep(MINUTE)
        with self.assertRaises(BlockingIOError):      # nothing in the queue: nothing was opened
            os.read(queue, 1 << 16)
        notice(seat, seen=True)
        self.menu.wait(lambda screen: row(seat)(screen) and not row(seat, "needs you")(screen),
                       bound=BOUND)


if __name__ == "__main__":
    unittest.main()
