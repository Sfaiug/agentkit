"""A seat whose harness exited while tmux kept its pane is reopened in that same pane.

ak's seats run under `remain-on-exit`, so a harness that quits or crashes leaves its session,
window and pane where they were, the pane dead.  `ak orch NAME` then starts the harness again in
that pane, on the conversation the record holds, rather than opening a second session beside
it: the seat's name, window and pane id, which the menu, the status bar and ak's own typing
address it by, all stay.  The harness that died is forgotten with it, including the terminal it
read its input from.  A pane still alive is only attached.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, against a seat as ak's launch leaves
one (tests/fixtures/akseat.py).
"""

import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

CONVERSATION = "3a5c7e9b-1d2f-4a6c-8e0b-2d4f6a8c0e1b"
PANE = "#{window_id}\t#{pane_id}\t#{@ak_harness_pane}"
OLD_TTY = "/dev/pts/acme-old"   # the input terminal the dead harness's wrapper named


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ReopenDeadPane(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.seat = Seat(self.home, "acme", record={"conversation": CONVERSATION})

    def ask(self, *args):
        done = self.home.tmux(*args)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def pane(self, field):
        return self.ask("display-message", "-p", "-t", self.seat.pane, field).strip()

    def kill_harness(self):
        """End the pane's process, as a harness that quit, and wait for tmux to see it."""
        self.ask("set-option", "-p", "-t", self.seat.pane, "@ak_input_tty", OLD_TTY)
        pid = int(self.pane("#{pane_pid}"))
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 30
        while self.pane("#{pane_dead}") != "1":
            self.assertLess(time.monotonic(), deadline, "the pane never died")
            time.sleep(0.05)
        return pid

    def test_a_dead_pane_is_respawned_in_place_on_its_conversation(self):
        where, dead = self.pane(PANE), self.kill_harness()
        done = self.home.ak("orch", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], "orch: resuming acme on opus in the same "
                                                   f"window (conversation {CONVERSATION})")
        self.assertEqual(self.ask("list-sessions", "-F", "#{session_name}"), "acme\n")
        self.assertEqual(self.ask("list-panes", "-s", "-t", "=acme", "-F", PANE), where + "\n")
        self.assertEqual(where.split("\t")[1:], [self.seat.pane] * 2)
        self.assertNotEqual(self.pane("#{pane_pid}"), str(dead))
        self.assertNotEqual(self.pane("#{@ak_input_tty}"), OLD_TTY)

    def test_a_dry_run_says_so_and_leaves_the_pane_dead(self):
        dead = self.kill_harness()
        done = self.home.ak("orch", "acme", "--dry-run")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], "orch: resuming acme on opus in the same "
                                                   f"window (conversation {CONVERSATION})")
        self.assertEqual((self.pane("#{pane_dead}"), self.pane("#{pane_pid}")), ("1", str(dead)))

    def test_a_live_pane_is_attached_and_never_respawned(self):
        alive = self.pane("#{pane_pid}")
        done = self.home.ak("orch", "acme")
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(done.out.startswith(f"orch: attaching to acme in {self.seat.cwd} ("),
                        done.out)
        self.assertEqual((self.pane("#{pane_dead}"), self.pane("#{pane_pid}")), ("0", alive))


if __name__ == "__main__":
    unittest.main()
