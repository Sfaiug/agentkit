"""The answer key's seats are tmux as ak meets a harness in one.

A seat test reads what ak typed from the pane that received it, and shows the pane its next
screen; it holds only if tests/fixtures/akseat.py does: the seat's marks and record, a pane the
size its screen was captured at, and a next screen shown behind a draft the pane cannot hold.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

PROMPT = "one\n\n❯ \n── footer\n"
NEXT = "next\n\n❯ \n── footer\n"


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
        seat.show("x" * 150 + "\n" + PROMPT + "\n" * 3)       # three blank rows at its bottom
        self.assertEqual(self.home.tmux("display-message", "-p", "-t", seat.pane,
                                        "#{pane_width} #{pane_height}").out, "150 8\n")

    def test_entered_lines_are_kept_and_a_draft_outlives_the_next_screen(self):
        seat = Seat(self.home, "acme", screen=PROMPT)
        for keys in (["-l", "ship it"], ["Enter"], ["-l", "and"], ["BSpace", "Enter"],
                     ["-l", "draft"]):
            self.home.tmux("send-keys", "-t", seat.pane, *keys)
        self.assertEqual(seat.wait_lines(2), ["ship it", "an"])
        deadline = time.monotonic() + 30     # the draft reaches the pane before its next screen
        while not seat.typed().endswith("draft") and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(seat.typed(), "ship it\rand\x7f\rdraft")
        seat.show(NEXT)
        self.assertEqual(seat.capture().split(), ["next", "❯", "draft", "──", "footer"])

    def test_a_screen_of_combining_and_wide_text_gets_the_pane_it_was_captured_in(self):
        seat = Seat(self.home, "acme", screen="e\u0301" * 20 + "漢字" * 5 + "\n" + PROMPT)
        self.assertEqual(self.home.tmux("display-message", "-p", "-t", seat.pane,
                                        "#{pane_width}").out, "40\n")
        self.assertIn("e\u0301" * 20 + "漢字" * 5, seat.capture())

    def test_a_seat_tmux_lost_is_only_its_record(self):
        seat = Seat(self.home, "acme", alive=False)
        self.assertTrue((self.home.path / ".agentkit/state/session-acme.json").is_file())
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=acme").code, 0)
        self.assertIsNone(seat.pane)

if __name__ == "__main__":
    unittest.main()
