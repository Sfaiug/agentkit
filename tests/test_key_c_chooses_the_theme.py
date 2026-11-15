"""`c` chooses the theme, black or white: its row `Theme` names both, the one in force marked, and
the one marked there is kept in config.toml and is every screen's from then on, whatever the
terminal's own background.

The owner (12 Nov 2026): "I want in the config there to be 2 themes. One white and one black."
A config.toml that names no theme, or another word, is in the one that fits the terminal: black
here, a terminal that sets no background.  Black-box: the program AK_BIN names runs in a person's
terminal of 24-bit colour (tests/fixtures/akterm.py) over one working seat
(tests/fixtures/akseat.py), each cell judged by how it looks (tests/fixtures/aklooks.py), every
cell of a screen on the theme's background, or a row the highlight is on whole on its selection,
as tests/test_key_a_screen_is_painted.py judges it.
"""

import sys
from pathlib import Path
import time
import tomllib
import unicodedata
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SIZE = (100, 40)     # tall enough for every row of `c`
BLACK, WHITE, ACCENT = "000000", "ffffff", "0067c6"     # backgrounds, and white's accent
SELECTION = {BLACK: "08305d", WHITE: "dcecff"}          # ... and each one's selection
CONFIG = ".agentkit/config.toml"


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def off(rows, rgb):
    """The first row of the screen that is not every cell on `rgb` or its selection, its number
    and text, else None."""
    if len(rows) < SIZE[1]:
        return len(rows) + 1, "(missing)"
    grounds = {sgr(rgb, "48"), sgr(SELECTION[rgb], "48")}
    for number, line in enumerate(rows[:SIZE[1]], 1):
        wide = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char, _ in line)
        if wide != SIZE[0] or any(not grounds & set(shown) for _, shown in line):
            return number, plain(line)
    return None


def theme_row(screen):
    return next((line.rstrip() for line in screen.split("\n") if "Theme" in line), None)


def pointed(screen):
    """The highlighted row."""
    return next((line for line in screen.split("\n") if line.startswith("› ")), None)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CChoosesTheTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        cls.config = (home.path / CONFIG).read_text()

    def kept(self, theme=None):
        """config.toml as installed, naming `theme` where given."""
        self.home.write(CONFIG, (f'theme = "{theme}"\n' if theme else "") + self.config)

    def named(self):
        return tomllib.loads((self.home.path / CONFIG).read_text()).get("theme")

    def open(self, *args, env=None):
        term = Terminal(self.home, *args, size=SIZE, env={"COLORTERM": "truecolor", **(env or {})})
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        return term

    def painted(self, term, rgb, shown=None):
        """The screen's looks once it shows `shown` and every cell of it is on `rgb`."""
        deadline = time.monotonic() + 30
        while True:
            screen = term.screen()
            rows = looks(term.screen(colours=True, blank=True))
            wrong = off(rows, rgb)
            if (shown is None or shown in screen) and not wrong:
                return rows
            self.assertLess(time.monotonic(), deadline,
                            f"never all on {rgb} showing {shown!r}: row {wrong}\n{screen}")
            time.sleep(0.05)

    def config_screen(self):
        menu = self.open()
        menu.wait("esc leave", 60)
        menu.keys("c")
        menu.wait(lambda text: theme_row(text) and "esc back" in text, 60)
        return menu

    def test_c_marks_the_theme_it_is_in_and_keeps_the_one_marked(self):
        self.kept()
        menu = self.config_screen()
        self.painted(menu, BLACK, "  Theme       ● black   ○ white")
        while "Theme" not in (row := pointed(menu.screen())):
            menu.keys("Down")
            menu.wait(lambda text: pointed(text) not in (None, row), 30)
        menu.keys("Right", "Space")
        rows = self.painted(menu, WHITE, "› Theme       ○ black   ● white")
        self.assertIn(sgr(ACCENT), look(rows, "›"))
        self.assertEqual(self.named(), "white")

        lines = menu.screen().split("\n")
        row = next(number for number, line in enumerate(lines, 1) if "Theme" in line)
        column = lines[row - 1].index("black") + 2
        menu.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        menu.wait("Theme       ● black   ○ white")
        menu.type(f"\x1b[<35;1;{SIZE[1]}M")   # the pointer off it, which lights what it is on
        self.painted(menu, BLACK, "Theme       ● black   ○ white")
        self.assertEqual(self.named(), "black")

    def test_a_theme_kept_is_every_screen_s_the_bar_s_and_the_popup_s(self):
        self.kept("white")
        self.painted(self.open(), WHITE, "esc leave")

        bar = self.open("orch", "acme")
        done = self.home.ak("orch", "why", "acme")      # a look at the seat dresses its bar
        self.assertEqual(done.code, 0, done.err)
        wanted, deadline = {sgr(WHITE), sgr(ACCENT, "48")}, time.monotonic() + 30
        while True:     # judged as it settles, as tests/test_key_themes.py judges a bar
            last = looks(bar.screen(colours=True).rstrip("\n"))[-2:]
            shown = (set(look(last, "● working")) - ATTRIBUTES
                     if any("● working" in plain(line) for line in last) else None)
            if shown == wanted or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        self.assertEqual(shown, wanted)

        popup = self.open("attach", "--overlay", env={"AGENTKIT_SESSION": "acme"})
        self.painted(popup, WHITE, "esc leave")

    def test_another_word_is_the_theme_the_terminal_fits(self):
        self.kept("blue")
        menu = self.config_screen()
        self.painted(menu, BLACK, "  Theme       ● black   ○ white")


if __name__ == "__main__":
    unittest.main()
