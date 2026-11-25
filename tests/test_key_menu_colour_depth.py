"""The menu draws in the look's own colours or the eight basic ones, and in none under NO_COLOR.

The look's own where COLORTERM or tmux says so, or where the terminal's entry counts 256 colours
or more, as xterm-256color's does: no fixed colour of 256 is drawn anywhere.  Where the entry
counts eight, as a plain xterm's does, the eight basic colours, in every frame.  NO_COLOR turns
colour off everywhere,
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

    def test_xterm_256color_without_colorterm_draws_the_looks_own(self):
        screen = self.menu(TERM="xterm-256color")
        self.assertEqual(ink(look(screen, "›")), {"1", "38;2;77;163;255"})
        self.assertEqual({c for c in colours(screen) if not re.fullmatch(r"[34]8;2;[\d;]+", c)},
                         set())

    def test_plain_xterm_draws_only_the_eight_basic_colours(self):
        screen = self.menu(TERM="xterm")
        self.assertEqual(look(screen, "›"), {"1", "36"})
        drawn = colours(screen)
        self.assertEqual({c for c in drawn if not re.fullmatch(r"[34][0-7]", c)}, set())

    def test_every_later_frame_keeps_the_depth_of_the_first(self):
        menu = Terminal(self.home, size=(100, 40), env={"TERM": "xterm"})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        settled(menu, lambda text: "! needs you" in text and "esc leave" in text)
        menu.resize(90, 40)     # a whole new frame, every cell of it drawn again
        screen = settled(menu, lambda text: "─" * 90 in text and "─" * 91 not in text
                         and "esc leave" in text)
        self.assertEqual(look(screen, "›"), {"1", "36"})
        self.assertEqual({c for c in colours(screen) if not re.fullmatch(r"[34][0-7]", c)}, set())

    def test_true_colour_tmux_reports_is_drawn_though_colorterm_does_not_say_it(self):
        screen = self.menu(TERM="xterm", AGENTKIT_TERMFEATURES="RGB")
        self.assertEqual(ink(look(screen, "›")), {"1", "38;2;77;163;255"})

    def test_no_color_draws_no_colour_even_on_a_true_colour_terminal(self):
        screen = self.menu(NO_COLOR="1", COLORTERM="truecolor")
        self.assertEqual(colours(screen), set())
        rows = [plain(line).rstrip() for line in screen]
        self.assertEqual(rows[1], "─" * 100)
        self.assertIn("› 1  acme  Opus 5.5 xhigh  ! needs you", rows)
        self.assertIn(KEYS, rows)

    def test_no_color_leaves_the_help_without_a_mark_of_style(self):
        for env, internal in (({"COLORTERM": "truecolor"}, {"38;2;134;141;151"}),
                              ({"NO_COLOR": "1", "COLORTERM": "truecolor"}, set())):
            with self.subTest(env=env):
                term = Terminal(self.home, "--help", size=(100, 50), env=env)
                self.assertEqual(term.exit_code(), 0)
                screen = looks(term.screen(colours=True))
                self.assertEqual(look(screen, "internal:"), internal)


if __name__ == "__main__":
    unittest.main()
