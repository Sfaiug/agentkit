"""On a person's terminal `ak --help` draws its `internal:` line dim, and only that line.

The listing's rows are the verbs a seat uses; the verbs ak runs for itself share one line, drawn
dim so the eye passes over it.  The dim is the palette's own grey at whatever depth the terminal
says it takes: true colour when COLORTERM says so, else the nearest of 256, else the plain dim of
eight colours, and none at all under NO_COLOR.  Black-box: the program `AK_BIN` names runs on a
terminal from tests/fixtures/akterm.py, whose screen is read cell by cell, colours and all.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

INTERNAL = "internal:  orch  worker  hand-in  watch  update  macbridge  attach  doctor  move"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
GREY = "\x1b[38;2;108;112;134m"      # the palette's dim grey, #6c7086
GREY_256 = "\x1b[38;5;243m"          # ... and the nearest of xterm's 256 to it


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OnATerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # A person's terminal sets no NO_COLOR, and the terminal's tmux server takes the Home's
        # environment when it starts; the terminal itself says xterm-256color.

    def styled_lines(self, **env):
        """The listing's lines drawn with any styling, as the terminal holds them."""
        term = Terminal(self.home, "--help", size=(100, 30), env=env)
        self.assertEqual(term.exit_code(), 0)
        self.assertIn(INTERNAL, term.wait(INTERNAL))
        return [line for line in term.screen(colours=True).splitlines() if "\x1b" in line]

    def test_true_colour_draws_the_internal_line_dim_in_the_palette_grey(self):
        self.assertEqual(self.styled_lines(COLORTERM="truecolor"), [DIM + GREY + INTERNAL + RESET])

    def test_256_colours_draw_it_dim_in_the_nearest_grey_they_have(self):
        self.assertEqual(self.styled_lines(COLORTERM=""), [DIM + GREY_256 + INTERNAL + RESET])

    def test_eight_colours_draw_it_plain_dim(self):
        self.assertEqual(self.styled_lines(TERM="xterm", COLORTERM=""), [DIM + INTERNAL + RESET])

    def test_no_color_draws_every_line_plain_even_on_true_colour(self):
        self.assertEqual(self.styled_lines(NO_COLOR="1", COLORTERM="truecolor"), [])


if __name__ == "__main__":
    unittest.main()
