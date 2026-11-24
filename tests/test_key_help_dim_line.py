"""On a person's terminal `ak --help` draws its `internal:` line dim, and only that line.

The listing's rows are the verbs a seat uses; the verbs ak runs for itself share one line, drawn
dim so the eye passes over it.  The dim is the black theme's own colour alone, never faint as
well, on a terminal of any name, and none at all under NO_COLOR.
Black-box: the program `AK_BIN` names runs on a terminal from tests/fixtures/akterm.py, whose
screen is read cell by cell, colours and all.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

INTERNAL = "internal:  orch  worker  hand-in  watch  update  macbridge  attach  doctor  move  standby"
COLOURED = "\x1b[39m"   # the terminal ends a line in a colour alone by ending the colour alone
GREY = "\x1b[38;2;134;141;151m"      # the black theme's dim, #868d97


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

    def test_a_terminal_of_any_name_draws_the_internal_line_in_the_palette_grey(self):
        for name in ("xterm-256color", "xterm"):    # its entry counts 256 colours, and eight
            with self.subTest(TERM=name):
                self.assertEqual(self.styled_lines(TERM=name), [GREY + INTERNAL + COLOURED])

    def test_no_color_draws_every_line_plain(self):
        self.assertEqual(self.styled_lines(NO_COLOR="1"), [])


if __name__ == "__main__":
    unittest.main()
