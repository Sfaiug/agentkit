"""A warm popup's first frame is the reader's last read (`agentkit/warm.py`).

The warm server's reader reads the seats as the main screen does (`menu.rows`) whenever what a
read reads changes (`menu.Live.recorded`), no sooner than its CPU share allows, and frames each
read onto the server's pipe; a menu the server forks draws the last one at once and reads again
behind it.  Nothing here forks: the reader runs in this process on a fake clock and fake CPU
times until its server is gone, and the menu in a HOME of its own.
"""

import os
import pickle
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, warm
from fixtures.sandbox import Sandbox

READ = [[{"name": "fix-api"}], [("acme", [menu.Task(1, "moving", "acme-run")])]]


class Clock:
    """`time` as the reader sees it: its own sleeps move it, and a read's CPU is `cpu`."""

    def __init__(self):
        self.now, self.cpu = 0.0, 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def times(self):
        return (self.cpu, 0.0, 0.0, 0.0, 0.0)


class Reader(unittest.TestCase):
    def test_a_read_lands_on_news_once_its_cpu_share_allows_and_ends_with_its_server(self):
        clock, read_at = Clock(), []
        # news at 1 and at 5; the server gone at 8
        recorded = lambda: "a" if clock.now < 1 else "b" if clock.now < 5 else "c"

        def rows(_cfg):
            read_at.append(clock.now)
            clock.cpu += 2 * warm.DUTY          # a read's CPU: two seconds of its share
            return READ[0], [], READ[1]

        reads, written = os.pipe()
        self.addCleanup(os.close, reads)
        with patch.object(warm, "time", clock), patch.object(warm.os, "times", clock.times), \
                patch.object(warm.os, "getppid", lambda: 4242 if clock.now < 8 else 1), \
                patch.object(warm.os, "nice"), patch.object(config, "load", return_value={}), \
                patch.object(menu, "Live", lambda _cfg: SimpleNamespace(recorded=recorded)), \
                patch.object(menu, "rows", rows), \
                patch.object(warm.os, "_exit", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                warm._read(written)
        os.close(written)
        self.assertEqual(read_at, [0.0, 2.0, 5.0])  # news at 1 waits for its share, at 2
        heard, frames = b"", []
        while chunk := os.read(reads, 1 << 16):
            heard += chunk
        while heard:
            end = 4 + int.from_bytes(heard[:4], "big")
            frames.append(pickle.loads(heard[4:end]))
            heard = heard[end:]
        self.assertEqual(frames, [READ] * 3)
        self.assertEqual(frames[0][1][0][1][0].run, "acme-run")   # a task's run comes too


class Primed(Sandbox):
    def test_a_forked_menu_draws_the_last_read_first_and_reads_again_behind_it(self):
        reads = []
        read = lambda _live, look=False: reads.append(
            (look, threading.current_thread() is threading.main_thread()))
        with patch.object(warm, "_PRIMED", pickle.loads(pickle.dumps(READ))), \
                patch.object(menu, "STIR", 0.01), patch.object(menu.Live, "read", read):
            live, shown = menu.Live(self.cfg), []
            live.watch(shown)
            self.assertEqual(shown, READ)
            deadline = time.monotonic() + 30
            while not reads:
                self.assertLess(time.monotonic(), deadline, "never read again")
                time.sleep(0.01)
            live.close()
            live.watcher.join(30)
        self.assertEqual(reads[0], (True, False))   # looked at too, off the thread that draws
        again = menu.Live(self.cfg)
        self.addCleanup(again.close)
        again.watcher = object()                    # no thread: its read is this test's
        with patch.object(menu.Live, "read") as read_now:
            again.watch([])                         # the next menu's read is its own, at once
        read_now.assert_called_once_with(look=True)


if __name__ == "__main__":
    unittest.main()
