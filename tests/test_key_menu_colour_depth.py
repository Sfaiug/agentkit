"""The menu draws in as many colours as the terminal takes, and in none under NO_COLOR.

True colour only where COLORTERM says so; otherwise the terminal's own count: xterm-256color
takes the nearest of its 256 fixed colours and a plain xterm the eight basic ones, so no cell is
drawn in a colour the terminal would show as some other.  NO_COLOR turns colour off everywhere,
even on a true-colour terminal, the help included, and the menu still reads by its shapes: the
rule under its header, the `›` on the highlighted row and the key line.  Black-box: ak runs
through tests/fixtures/akterm.py, and each cell is judged by how it looks
(tests/fixtures/aklooks.py), never by the bytes that drew it.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import colours, look, looks, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEYS = "  ↑↓←→ move   ⏎ choose   n new   c config   esc leave"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ColourDepth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        Seat(cls.home, "acme", screen="claude-question-pane.txt")

    def menu(self, **env):
        """The menu's looks once it rests, on a terminal with that environment."""
        menu = Terminal(self.home, size=(100, 40), env=env)
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        return settled(menu, lambda text: "! needs you" in text and "esc leave" in text)

    def test_xterm_256color_without_colorterm_draws_only_fixed_colours(self):
        screen = self.menu(TERM="xterm-256color")
        self.assertEqual(look(screen, "›"), {"1", "38;5;111"})
        drawn = colours(screen)
        self.assertEqual({c for c in drawn if not re.fullmatch(r"[34]8;5;\d+", c)}, set())

    def test_plain_xterm_draws_only_the_eight_basic_colours(self):
        screen = self.menu(TERM="xterm")
        self.assertEqual(look(screen, "›"), {"1", "36"})
        drawn = colours(screen)
        self.assertEqual({c for c in drawn if not re.fullmatch(r"[34][0-7]", c)}, set())

    def test_no_color_draws_no_colour_even_on_a_true_colour_terminal(self):
        screen = self.menu(NO_COLOR="1", COLORTERM="truecolor")
        self.assertEqual(colours(screen), set())
        rows = [plain(line).rstrip() for line in screen]
        self.assertEqual(rows[1], "─" * 100)
        self.assertIn("› 1  acme  Opus 5.5  ! needs you", rows)
        self.assertIn(KEYS, rows)

    def test_no_color_leaves_the_help_without_a_mark_of_style(self):
        for env, internal in (({"COLORTERM": "truecolor"}, {"2", "38;2;108;112;134"}),
                              ({"NO_COLOR": "1", "COLORTERM": "truecolor"}, set())):
            with self.subTest(env=env):
                term = Terminal(self.home, "--help", size=(100, 50), env=env)
                self.assertEqual(term.exit_code(), 0)
                screen = looks(term.screen(colours=True))
                self.assertEqual(look(screen, "internal:"), internal)


if __name__ == "__main__":
    unittest.main()
