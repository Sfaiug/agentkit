"""A terminal whose entry says it takes true colour gets it, and so does one whose entry does not.

Over ssh a terminal's name (TERM) arrives and COLORTERM does not, so the menu in the whole window
drew the nearest of the colours its name's entry counts while the one over a seat (Ctrl-b m),
whose tmux ak tells that every client takes true colour, drew the look's own: one terminal, two
looks.  The menu asks no terminal either and takes each for what a seat's tmux does, so the two
draw one terminal alike.  Black-box, through tests/fixtures/akterm.py: a seat ak opens, a fake
`claude` in it, and both menus on a terminal of each name, neither with a COLORTERM.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ink, look, settled
from fixtures.akterm import Terminal

# the highlighted row's mark and a key of the key line, in the black theme's accent and dim
OWN = [{"1", "38;2;77;163;255"}, {"38;2;134;141;151"}]


def drawn(term):
    """How the menu on `term` draws its mark and a key."""
    screen = settled(term, "esc leave")
    return [ink(look(screen, "›")), ink(look(screen, "esc", on="esc leave"))]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TrueColour(unittest.TestCase):
    def test_the_menu_in_the_whole_window_and_the_one_over_a_seat_draw_a_terminal_alike(self):
        home = Home()
        self.addCleanup(home.close)
        home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
        # its tmux starts here, and what that starts with is its popup's: no NO_COLOR, which is
        # the Home's for a piped run
        opened = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", tty=True,
                         env={"NO_COLOR": None})
        self.assertEqual(opened.code, 0, opened.err)
        for name in ("xterm-256color", "xterm"):    # its entry counts 256 colours, and eight
            with self.subTest(TERM=name):
                whole = Terminal(home, env={"TERM": name})
                seat = Terminal(home, "orch", "acme", env={"TERM": name})
                seat.wait("Ctrl-b m")               # its bar is up: the seat has the keys
                seat.keys("C-b", "m")
                self.assertEqual([drawn(whole), drawn(seat)], [OWN, OWN])


if __name__ == "__main__":
    unittest.main()
