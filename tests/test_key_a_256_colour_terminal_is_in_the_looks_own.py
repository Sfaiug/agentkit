"""A terminal whose entry counts 256 colours is drawn in the look's own, wherever ak draws it.

Over ssh a terminal's name (TERM) arrives and COLORTERM does not.  A seat's tmux tells every
terminal it takes true colour (`orch.tmux_conf`), so the menu over a seat (Ctrl-b m) draws the
look's own colours; the menu in the whole window draws them too where the entry counts 256 or
more, and the eight basic colours where it counts eight.  Black-box, through
tests/fixtures/akterm.py: a seat ak opens, a fake `claude` in it, and both menus on
xterm-256color, neither with a COLORTERM.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import colours, ink, look, settled
from fixtures.akterm import Terminal

KEY = {"38;2;134;141;151"}      # the key line's `esc`, in the black theme's dim


def drawn(term):
    """How the menu on `term` draws `esc`, and the fixed colours anywhere on its screen."""
    screen = settled(term, "esc leave")
    return (ink(look(screen, "esc", on="esc leave")),
            {c for c in colours(screen) if re.fullmatch(r"[34]8;5;\d+", c)})


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class LooksOwn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.fake("claude", "#!/bin/sh\nexec sleep 600\n")
        # its tmux starts here, and what that starts with is its popup's: no NO_COLOR, which is
        # the Home's for a piped run
        opened = cls.home.ak("orch", "acme", "--model", "opus", "--workers", "opus", tty=True,
                             env={"NO_COLOR": None})
        assert opened.code == 0, opened.err

    def test_the_menu_in_the_whole_window_and_the_one_over_a_seat_draw_the_looks_own(self):
        whole = Terminal(self.home, env={"TERM": "xterm-256color"})
        seat = Terminal(self.home, "orch", "acme", env={"TERM": "xterm-256color"})
        seat.wait("Ctrl-b m")               # its bar is up: the seat has the keys
        seat.keys("C-b", "m")
        self.assertEqual([drawn(whole), drawn(seat)], [(KEY, set()), (KEY, set())])

    def test_a_plain_xterm_draws_only_the_eight_basic_colours(self):
        screen = settled(Terminal(self.home, env={"TERM": "xterm"}), "esc leave")
        self.assertEqual({c for c in colours(screen) if not re.fullmatch(r"[34][0-7]", c)}, set())


if __name__ == "__main__":
    unittest.main()
