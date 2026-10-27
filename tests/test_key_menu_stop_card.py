"""`x` in the popup over a seat asks under that seat's row whether to stop it: Esc keeps it, and
`Stop` ends its tmux session and marks it stopped by its owner, so it leaves the list for past
sessions: the popup over it goes at once, and the seat behind it ends a moment later.

Stopping ends the terminal a conversation lives in, so it is the one key on the menu that asks
first, says what goes with it and where the seat goes, and stands on Keep until told otherwise.
The mark is what keeps a stopped seat closed: nothing brings back a seat its owner stopped.
Black-box: ak runs in a terminal of tests/fixtures/akterm.py over real seats of
tests/fixtures/akseat.py, judged by what the terminal shows, tmux's sessions and the seat's
file under HOME.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

KEYS = "  ↑↓←→ move   ⏎ choose   n new   x stop   c config   esc leave"
CARD = ["  Stop atoll-fix and everything it runs?",
        "  No runs stop with it; the session moves to past sessions, p, where it reopens where"
        " it stopped.",
        "› ✓ Keep",
        "  ✗ Stop"]
NOW = int(time.time())


class StopCard(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        Seat(self.home, "atoll-fix", screen="claude-working-pane.txt",
             record={"created": NOW - 900})
        Seat(self.home, "atoll-ask", screen="claude-prompt-pane.txt",
             record={"created": NOW - 600})
        self.menu = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                             env={"AGENTKIT_SESSION": "atoll-fix"})
        self.menu.wait(lambda screen: "› 1  atoll-fix  " in screen and "● working" in screen)

    def alive(self, name):
        return self.home.tmux("has-session", "-t", f"={name}").code == 0

    def seat_file(self, name):
        path = self.home.path / ".agentkit" / "state" / f"seat-{name}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def asked(self):
        """The menu with the card open under atoll-fix, once the card has counted its runs and
        is drawn to its last line."""
        self.menu.keys("x")
        return self.menu.wait(lambda screen: all(line in screen.splitlines() for line in CARD)
                              ).splitlines()

    def test_x_asks_under_the_row_standing_on_keep_and_esc_keeps_the_seat(self):
        lines = self.asked()
        at = lines.index(CARD[0])
        self.assertEqual(lines[at:at + len(CARD)], CARD)
        self.assertRegex(lines[at - 2], r"^  1  atoll-fix  ")
        self.assertEqual(lines[at - 1], "")
        below = next(i for i, line in enumerate(lines) if line.startswith("  2  atoll-ask  "))
        self.assertGreater(below, at + len(CARD) - 1, "atoll-ask's row is not below the card")
        self.assertEqual([line for line in lines if line][-1], "  esc back")

        self.menu.keys("Escape")
        screen = self.menu.wait(KEYS)
        self.assertNotIn(CARD[0], screen)
        self.assertIn("› 1  atoll-fix  ", screen)
        self.assertTrue(self.alive("atoll-fix"))
        self.assertNotIn("stopped_at", self.seat_file("atoll-fix"))

    def test_stop_ends_the_seat_marks_it_stopped_by_its_owner_and_offers_the_past(self):
        self.asked()
        self.menu.keys("j")
        self.menu.wait("› ✗ Stop")
        self.menu.keys("Enter")
        self.assertEqual(self.menu.exit_code(), 0)
        deadline = time.monotonic() + 30
        while (self.alive("atoll-fix") or "stopped_at" not in self.seat_file("atoll-fix")) \
                and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.alive("atoll-fix"))
        self.assertTrue(self.alive("atoll-ask"))
        seat = self.seat_file("atoll-fix")
        self.assertIsInstance(seat.get("stopped_at"), (int, float))
        self.assertIs(seat.get("closed_by_owner"), True)
        # the record stays: the past screen reopens the seat from it
        self.assertTrue((self.home.path / ".agentkit/state/session-atoll-fix.json").is_file())


if __name__ == "__main__":
    unittest.main()
