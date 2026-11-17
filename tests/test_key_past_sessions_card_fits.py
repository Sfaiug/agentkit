"""Past sessions' `x` asks on a card its screen fits to the terminal it is in now: on one too
short for the page and the card, the card's top and the rows round it give way, never its
answers, its key line or the heading, and a click answers on the row its answer shows.
Black-box: ak in a person's terminal (tests/fixtures/akterm.py) on past sessions as
tests/test_key_menu_past.py opens them, shrunk to 30 by 10 before `x`, or narrowed to 30 by
16 under its card, whose rows are then laid out anew.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from test_key_menu_past import HARNESS, Stopped


def asked(screen):
    """The card on a screen nothing has scrolled off: the heading first, both answers, the
    card's keys last."""
    lines = screen.rstrip().split("\n")
    return ("past sessions" in lines[0] and "esc back" in lines[-1]
            and all(any(answer in line for line in lines) for answer in ("✓ Keep", "× Remove")))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ACardFitsAShortTerminal(unittest.TestCase):
    def test_its_answers_show_and_a_click_on_remove_removes(self):
        home = Home()
        self.addCleanup(home.close)
        seats = Stopped(home, HARNESS)
        seats.to_past()
        seats.menu.resize(30, 10)
        seats.menu.wait(lambda screen: "past sessions" in screen and "esc back" in screen
                        and len(screen.rstrip().split("\n")) <= 10)
        seats.menu.keys("x")
        lines = seats.menu.wait(asked).split("\n")
        row = next(n for n, line in enumerate(lines, 1) if "× Remove" in line)
        column = lines[row - 1].index("×") + 1
        seats.menu.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        seats.menu.wait(lambda screen: not seats.state("session-beta.json").exists())

    def test_narrowed_under_it_its_rows_fit_the_new_width(self):
        home = Home()
        self.addCleanup(home.close)
        seats = Stopped(home, HARNESS)
        seats.to_past()
        seats.menu.keys("x")
        seats.menu.wait(asked)
        seats.menu.resize(30, 16)
        seats.menu.wait(lambda screen: asked(screen) and len(screen.rstrip().split("\n")) <= 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
