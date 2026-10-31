"""What a seat started by hand in a side session ends at the next tick once ak holds no record of
that seat, though it ignores the hangup and left the session's tree; one whose seat has a
session in tmux runs on.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and each
side session starts through a seat's own tmux shim (tests/fixtures/shims.py) on the Home's real
tmux, its pane ignoring HUP and leaving a `sleep 600` in a session of its own, its parent gone,
which writes its pid down.  The whole file runs in one box (`rerun_boxed`): the tick must see it.
"""

from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import BOXED, REAL_TMUX, SOCKET, Home, rerun_boxed
from fixtures.shims import Shims

SLEEP = 'echo $$ >"$0.tmp" && mv "$0.tmp" "$0" && exec sleep 600'
PANE = "trap '' HUP; (setsid sh -c {sleep} {pid} </dev/null >/dev/null 2>&1 &); exec sleep 3600"


@unittest.skipUnless(BOXED and REAL_TMUX, "no tmux, or no bwrap able to box the test here")
class ForgottenSeatProcesses(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        shims = Shims(self.home)
        done = self.home.tmux("new-session", "-d", "-s", "beta", "sleep 3600")
        self.assertEqual(done.code, 0, done.err)
        for name, seat in (("serve", "gone"), ("watch", "beta")):
            pid = shlex.quote(str(self.home.root / seat))
            done = shims.run("tmux", "-L", SOCKET, "new-session", "-d", "-s", name,
                             PANE.format(sleep=shlex.quote(SLEEP), pid=pid), seat=seat)
            self.assertEqual(done.code, 0, done.err)

    def running(self, seat):
        """Whether the `sleep 600` that seat's side session left runs: an exited one reads empty."""
        try:
            pid = (self.home.root / seat).read_text().strip()
            return Path(f"/proc/{pid}/cmdline").read_bytes() == b"sleep\x00600\x00"
        except OSError:
            return False

    def until(self, done, what):
        deadline = time.monotonic() + 30
        while not done():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    def test_the_next_tick_ends_what_a_forgotten_seat_left_and_spares_a_held_one_s(self):
        self.until(lambda: self.running("gone") and self.running("beta"), "a session left none")
        done = self.home.ak("watch")
        self.assertEqual(done.code, 0, done.err)
        self.until(lambda: not self.running("gone"), "the tick left a forgotten seat's running")
        self.assertTrue(self.running("beta"), "the tick ended what a held seat started")


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
