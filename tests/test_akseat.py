"""The answer key's seats and terminals are tmux as ak and a person meet it.

A seat test reads what ak typed from the pane that received it, and a screen test reads what a
terminal shows; both hold only if tests/fixtures/akseat.py and akterm.py do.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

PROMPT = "one\n\n❯ \n── footer\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Seats(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_a_seat_is_marked_and_shows_its_screen_at_its_size(self):
        seat = Seat(self.home, "acme", screen="claude-working-pane.txt")
        self.assertEqual(self.home.tmux("show-options", "-v", "-t", "=acme:", "@ak_orch").out,
                         "1\n")
        self.assertIn("esc to interrupt", seat.capture())
        seat.show("x" * 150 + "\n" + PROMPT)
        self.assertEqual(self.home.tmux("display-message", "-p", "-t", seat.pane,
                                        "#{pane_width}").out, "150\n")

    def test_typing_shows_in_the_composer_and_each_entered_line_is_kept(self):
        seat = Seat(self.home, "acme", screen=PROMPT)
        self.home.tmux("send-keys", "-t", seat.pane, "-l", "ship it")
        self.home.tmux("send-keys", "-t", seat.pane, "Enter")
        self.home.tmux("send-keys", "-t", seat.pane, "-l", "and")
        self.home.tmux("send-keys", "-t", seat.pane, "BSpace", "Enter")
        self.assertEqual(seat.wait_lines(2), ["ship it", "an"])
        self.assertEqual(seat.typed(), "ship it\rand\x7f\r")

    def test_a_paste_is_one_line_however_it_arrives_and_a_draft_outlives_a_frame(self):
        seat = Seat(self.home, "acme", screen=PROMPT)
        self.home.tmux("set-buffer", "-b", "clip", "first\nsecond")
        self.home.tmux("paste-buffer", "-p", "-b", "clip", "-t", seat.pane)
        self.home.tmux("send-keys", "-t", seat.pane, "Enter")
        self.assertEqual(seat.wait_lines(1), ["first\nsecond"])
        for chunk in ("\x1b[20", "0~draft\x1b[201~"):   # a paste mark split across reads
            self.home.tmux("send-keys", "-t", seat.pane, "-l", chunk)
            while not seat.typed().endswith(chunk):
                time.sleep(0.05)
        seat.show("next\n\n❯ \n── footer\n")
        self.assertIn("❯ draft", seat.capture())
        self.home.tmux("send-keys", "-t", seat.pane, "Enter")
        self.assertEqual(seat.wait_lines(2), ["first\nsecond", "draft"])

    def test_a_seat_tmux_lost_is_only_its_record(self):
        seat = Seat(self.home, "acme", alive=False)
        self.assertTrue((self.home.path / ".agentkit/state/session-acme.json").is_file())
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=acme").code, 0)
        self.assertIsNone(seat.pane)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Terminals(unittest.TestCase):
    def test_a_terminal_shows_the_program_and_keeps_its_exit_status(self):
        with Home() as home:
            term = Terminal(home, "--help", size=(100, 50))
            self.assertEqual(term.exit_code(), 0)
            self.assertIn("usage: ak [command]", term.wait("usage:"))
            self.assertEqual(home.tmux("list-sessions").code, 1)   # ak's own server never started


if __name__ == "__main__":
    unittest.main()
