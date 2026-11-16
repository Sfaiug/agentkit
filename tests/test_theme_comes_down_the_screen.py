"""A theme chosen on `c` comes down the screen from its top row to its last in 0.35 s, every row
whole in one of the two themes at every frame, so each one reads.

The owner (12 Nov 2026), of the two themes: "And work with transitions as well, like glowing
effect, rainbow effect, for progress and animations when selection things."  Mixing every colour
from one theme to the other would pass through a grey half way that is both a row's text and its
background; instead the rows above a line are in the new theme and those from it down are the
screen as it was, in the old, the line reaching the last row 0.35 s on.  A key ends it on its
last frame.

Black-box: the program AK_BIN names runs in a person's terminal of 24-bit colour that sets no
background (tests/fixtures/akterm.py) over one working seat (tests/fixtures/akseat.py), each cell
judged by how it looks (tests/fixtures/aklooks.py).  Its clock injected: `AK_MOTION_CLOCK` names
a file of seconds that stands still until the test moves it, so each frame is read off the screen
at the moment set, however late the host's load makes it.
"""

import sys
from pathlib import Path
import time
import tomllib
import unicodedata
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SIZE = (100, 40)
BLACK, WHITE, TEXT = "000000", "ffffff", "181c22"    # the backgrounds, and white's text
GROUNDS = {BLACK: {BLACK, "08305d"}, WHITE: {WHITE, "dcecff"}}   # ... each with its selection
HALF = SIZE[1] // 2
CONFIG = ".agentkit/config.toml"


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def grounds(line):
    """The background of each cell of a line of `looks`, as RGB, None where it has none."""
    return [next((part for part in shown if part.startswith("48;2;")), None) for _, shown in line]


def themes(rows):
    """The theme each row of the screen is whole in, BLACK or WHITE, or None for a row that is
    not: a cell of each, one on no background or another, or a row not drawn across."""
    found = []
    for line in rows[:SIZE[1]]:
        wide = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char, _ in line)
        backs = set(grounds(line))
        found.append(next((theme for theme, own in GROUNDS.items()
                           if wide == SIZE[0] and backs <= {sgr(rgb, "48") for rgb in own}),
                          None))
    return found + [None] * (SIZE[1] - len(found))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ThemeComesDownTheScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        cls.config = (home.path / CONFIG).read_text()

    def setUp(self):
        self.home.write(CONFIG, self.config)        # no theme named: black, as the terminal is
        self.clock = self.home.root / "clock"
        self.at(1000)
        self.menu = menu = Terminal(self.home, size=SIZE, env={
            "COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock)})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait("esc leave", 60)
        menu.keys("c")
        menu.wait(lambda text: "Theme" in text and "esc back" in text, 60)
        self.at(1001)                               # the page has come up
        while not (row := self.pointed()).startswith("› Theme"):
            menu.keys("Down")
            menu.wait(lambda text: self.pointed(text) != row, 30)
        self.shows([BLACK] * SIZE[1])

    def at(self, seconds):
        """ak's motion at `seconds` from now on: its clock's file swapped whole, never read half
        written."""
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def pointed(self, screen=None):
        """The highlighted row."""
        return next((line for line in (screen or self.menu.screen()).split("\n")
                     if line.startswith("› ")), "")

    def shows(self, wanted):
        """The screen's looks once each row is whole in the theme `wanted` names for it; on
        every look on the way no cell is on a background but the themes' and their selections'.
        """
        allowed = {sgr(rgb, "48") for own in GROUNDS.values() for rgb in own}
        deadline = time.monotonic() + 30
        while True:
            rows = looks(self.menu.screen(colours=True, blank=True))
            stray = next(((number, plain(line)) for number, line in enumerate(rows[:SIZE[1]], 1)
                          if set(grounds(line)) - allowed), None)
            self.assertIsNone(stray, "a cell on a background of neither theme")
            if themes(rows) == wanted:
                return rows
            self.assertLess(time.monotonic(), deadline,
                            f"never {wanted}: {themes(rows)}\n{self.menu.screen()}")
            time.sleep(0.05)

    def named(self):
        return tomllib.loads((self.home.path / CONFIG).read_text()).get("theme")

    def test_white_comes_down_over_black_and_black_back_over_white(self):
        self.menu.keys("Right", "Space")            # white, chosen at 1001
        self.shows([WHITE] + [BLACK] * (SIZE[1] - 1))
        self.assertEqual(self.named(), "white")
        self.at(1001.175)
        self.shows([WHITE] * HALF + [BLACK] * (SIZE[1] - HALF))
        self.at(1001.35)
        rows = self.shows([WHITE] * SIZE[1])
        self.assertIn(sgr(TEXT), look(rows, "agentkit"))

        self.menu.keys("Left", "Space")             # black again, at 1001.35
        self.shows([BLACK] + [WHITE] * (SIZE[1] - 1))
        self.assertEqual(self.named(), "black")
        self.at(1001.525)
        self.shows([BLACK] * HALF + [WHITE] * (SIZE[1] - HALF))
        self.at(1001.7)
        self.shows([BLACK] * SIZE[1])

    def test_a_key_ends_it_on_its_last_frame(self):
        self.menu.keys("Right", "Space")
        self.shows([WHITE] + [BLACK] * (SIZE[1] - 1))
        self.at(1001.175)
        self.shows([WHITE] * HALF + [BLACK] * (SIZE[1] - HALF))
        self.menu.keys("Up")                        # the clock still half way
        self.shows([WHITE] * SIZE[1])


if __name__ == "__main__":
    unittest.main()
