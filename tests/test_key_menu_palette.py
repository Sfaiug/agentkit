"""The menu draws in the black theme unless the terminal says its background is light.

As it opens, the menu asks the terminal for its background colour (OSC 11).  No answer is a
dark background, and the black theme; an answer whose luma is past half way puts the white theme
in force, the accent, `needs you` and dim notes each its role's colour of that theme.  The
terminal here is tmux, which answers that question only once a background is set for its panes
(`window-style`), so it stands for both a terminal that never answers and one that answers.
Black-box: the menu runs through tests/fixtures/akterm.py, and each cell is judged by how it
looks (tests/fixtures/aklooks.py), never by the bytes that drew it.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import colours, look, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

DARK_ACCENT, DARK_NEEDS, DARK_DIM = "38;2;77;163;255", "38;2;215;146;0", "38;2;134;141;151"
LIGHT_ACCENT, LIGHT_NEEDS, LIGHT_DIM = "38;2;0;103;198", "38;2;142;94;0", "38;2;111;117;126"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Palette(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        # Two seats asking a question: the second `needs you` row is not the highlighted one, so
        # its look is the word's own and not the highlight's.
        now = int(time.time())
        for name, age in (("acme", 1200), ("beta", 600)):
            Seat(cls.home, name, screen="claude-question-pane.txt", record={"created": now - age})
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(cls.home, "--help").exit_code()

    def menu(self, background=None, **env):
        """The menu's looks once it rests, on a terminal of that background or of none."""
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        menu = Terminal(self.home, size=(100, 40), env=env)
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        return settled(menu, lambda text: text.count("! needs you") == 2 and "esc leave" in text)

    def test_with_no_answer_about_the_background_the_menu_is_dark(self):
        screen = self.menu(COLORTERM="truecolor")
        self.assertEqual(look(screen, "›"), {"1", DARK_ACCENT})
        self.assertEqual(look(screen, "! needs you", on="beta"), {"1", DARK_NEEDS})
        self.assertEqual(look(screen, "Opus 5.5", on="beta"), {"2", DARK_DIM})

    def test_on_a_light_background_the_menu_draws_the_white_theme(self):
        for colorterm in ("truecolor", "24bit"):
            with self.subTest(COLORTERM=colorterm):
                screen = self.menu("#ffffff", COLORTERM=colorterm)
                self.assertEqual(look(screen, "›"), {"1", LIGHT_ACCENT})
                self.assertEqual(look(screen, "! needs you", on="beta"), {"1", LIGHT_NEEDS})
                self.assertEqual(look(screen, "Opus 5.5", on="beta"), {"2", LIGHT_DIM})
                self.assertNotIn(DARK_NEEDS, colours(screen))

    def test_a_background_is_light_once_its_luma_is_past_half_way(self):
        for background, needs in (("#808080", LIGHT_NEEDS), ("#7f7f7f", DARK_NEEDS)):
            with self.subTest(background=background):
                screen = self.menu(background, COLORTERM="truecolor")
                self.assertEqual(look(screen, "! needs you", on="beta"), {"1", needs})

    def test_on_256_colours_the_light_needs_you_is_its_nearest_fixed_colour(self):
        self.assertEqual(look(self.menu("#ffffff", TERM="xterm-256color"), "! needs you",
                              on="beta"), {"1", "38;5;94"})


if __name__ == "__main__":
    unittest.main()
