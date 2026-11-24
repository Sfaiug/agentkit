"""The menu draws every terminal in true colour, and in none under NO_COLOR.

No terminal is asked how many colours it takes: xterm-256color and a plain xterm, neither with a
COLORTERM, are drawn in the theme's own colours, as a seat's tmux draws every client
(tests/test_key_a_terminal_whose_entry_says_true_colour_gets_it.py).  NO_COLOR turns colour off
everywhere, the help included, and the menu still reads by its shapes: the rule under its
header, the `›` on the highlighted row and the key line.  Black-box: ak runs through
tests/fixtures/akterm.py, and each cell is judged by how it looks (tests/fixtures/aklooks.py),
never by the bytes that drew it.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import colours, ink, look, looks, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"


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

    def test_a_terminal_of_any_name_draws_only_true_colours(self):
        for name in ("xterm-256color", "xterm"):    # its entry counts 256 colours, and eight
            with self.subTest(TERM=name):
                screen = self.menu(TERM=name)
                self.assertEqual(ink(look(screen, "›")), {"1", "38;2;77;163;255"})
                self.assertEqual({c for c in colours(screen)
                                  if not re.fullmatch(r"[34]8;2;\d+;\d+;\d+", c)}, set())

    def test_no_color_draws_no_colour(self):
        screen = self.menu(NO_COLOR="1")
        self.assertEqual(colours(screen), set())
        rows = [plain(line).rstrip() for line in screen]
        self.assertEqual(rows[1], "─" * 100)
        self.assertIn("› 1  acme  Opus 5.5 xhigh  ! needs you", rows)
        self.assertIn(KEYS, rows)

    def test_no_color_leaves_the_help_without_a_mark_of_style(self):
        for env, internal in (({}, {"38;2;134;141;151"}), ({"NO_COLOR": "1"}, set())):
            with self.subTest(env=env):
                term = Terminal(self.home, "--help", size=(100, 50), env=env)
                self.assertEqual(term.exit_code(), 0)
                screen = looks(term.screen(colours=True))
                self.assertEqual(look(screen, "internal:"), internal)


if __name__ == "__main__":
    unittest.main()
