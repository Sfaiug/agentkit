"""`x` exists only in the popup over a seat (`ak attach --overlay`, `Ctrl-b m`), and stops that
seat alone, whichever row is highlighted; the main menu stops no seat.

The owner, 27 Oct 2026: from inside a session `x` only ever applies to that session, and no
screen can close another.  Black-box: the program `AK_BIN` names runs in a person's terminal
(tests/fixtures/akterm.py) or from a pipe, over real seats of tests/fixtures/akseat.py, judged
by what the terminal shows and the sessions tmux holds.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
POPUP_KEYS = "  ↑↓←→ move   ⏎ open   n new   x stop   c config   esc leave"
CLOSE_KEYS = "  ↑↓←→ move   ⏎ open   n new   x close   c config   esc leave"
NOW = int(time.time())
DONE_PLAN = "".join(f"- [x] part {n} · check: `true` · atoll · written 2026-10-02 12:40"
                    f" · done abc1234\n" for n in range(2))


def alive(home, name):
    return home.tmux("has-session", "-t", f"={name}").code == 0


def gone(home, name, bound=30):
    deadline = time.monotonic() + bound
    while alive(home, name) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not alive(home, name)


class XStopsOnlyItsOwnSeat(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        Seat(self.home, "atoll-fix", screen="claude-working-pane.txt",
             record={"created": NOW - 900})
        Seat(self.home, "atoll-ask", screen="claude-prompt-pane.txt",
             record={"created": NOW - 600})

    def popup(self, seat, keys=POPUP_KEYS):
        menu = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"AGENTKIT_SESSION": seat})
        menu.wait(lambda screen: keys in screen.splitlines())
        return menu

    def test_the_main_menu_has_no_x(self):
        menu = Terminal(self.home, size=(100, 30))
        menu.wait("› 1  atoll-fix  ")
        self.assertIn(MAIN_KEYS, menu.wait(MAIN_KEYS).splitlines())
        menu.keys("x", "j")                       # x first: once j has moved, x was read
        screen = menu.wait(lambda screen: "› 2  atoll-ask  " in screen
                           and MAIN_KEYS in screen.splitlines())
        self.assertNotIn("everything it runs?", screen)
        menu.keys("Escape")
        self.assertEqual(menu.exit_code(), 0)
        self.assertTrue(alive(self.home, "atoll-fix"))
        done = self.home.ak(input="x\n\n\n")      # from a pipe, x is no key either
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("not a key: 'x'", done.out)
        self.assertTrue(alive(self.home, "atoll-fix"))

    def test_x_in_a_popup_asks_about_its_own_seat_whichever_row_is_highlighted(self):
        menu = self.popup("atoll-fix")
        menu.keys("j")
        menu.wait("› 2  atoll-ask  ")
        menu.keys("x")
        lines = menu.wait("  Stop atoll-fix and everything it runs?").splitlines()
        at = lines.index("  Stop atoll-fix and everything it runs?")
        self.assertRegex(lines[at - 2], r"^  1  atoll-fix  ")   # the card under its row
        menu.keys("Escape")
        menu.wait("› 1  atoll-fix  ")             # and the highlight on it
        self.assertTrue(alive(self.home, "atoll-fix"))
        menu.keys("x")
        menu.wait("  Stop atoll-fix and everything it runs?")
        menu.keys("j")
        menu.wait("› ✗ Stop")
        menu.keys("Enter")
        self.assertEqual(menu.exit_code(), 0)     # the popup over it goes first
        self.assertTrue(gone(self.home, "atoll-fix"))
        self.assertTrue(alive(self.home, "atoll-ask"))

    def test_x_in_a_popup_over_a_done_seat_closes_it_alone(self):
        self.home.write(".agentkit/state/plan-atoll-ask.md", DONE_PLAN)
        menu = self.popup("atoll-ask", CLOSE_KEYS)
        menu.keys("k")
        menu.wait(lambda screen: "› 1  atoll-fix  " in screen      # the word is its own seat's
                  and CLOSE_KEYS in screen.splitlines())
        menu.keys("x")
        self.assertEqual(menu.exit_code(), 0)
        self.assertTrue(gone(self.home, "atoll-ask"))
        self.assertTrue(alive(self.home, "atoll-fix"))


if __name__ == "__main__":
    unittest.main()
