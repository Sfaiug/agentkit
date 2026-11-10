"""ak draws a state, the accent and dim text in the owner's palette, and in no other colour.

The owner's eight colours, each with the text that reads on it, and the grey kept from before
(10 Nov 2026): `working` and the highlight's `›` blue, `needs you` yellow -- orange on a light
background, as yellow cannot be read on white -- `done` green, `out of usage` red, `idle` and
the key line's keys grey.  A seat's bar opens with its state as a chip: its colour under the
text that reads on it.  Black-box: the program AK_BIN names runs in a person's terminal of
24-bit colour (tests/fixtures/akterm.py) over tests/fixtures/akseat.py's seats, each cell judged
by how it looks (tests/fixtures/aklooks.py), never by the bytes that drew it.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

# each colour of the owner's palette, and the text that reads on it
PALETTE = {"0067c6": "ffffff", "be222a": "ffffff", "de6800": "2e1500", "f6c400": "3d2e00",
           "007e46": "ffffff", "007974": "ffffff", "7c44c3": "ffffff", "ad326e": "ffffff"}
GREY = "6c7086"
WORDS = ("● working", "! needs you", "✓ done", "○ idle", "○ out of usage")
STILL = 3      # seconds a cell keeps its look to be at rest: past a breath, which takes two


def fg(rgb):
    return "38;2;" + ";".join(str(int(rgb[at:at + 2], 16)) for at in (0, 2, 4))


def bg(rgb):
    return "48" + fg(rgb)[2:]


BLUE, RED, ORANGE, YELLOW, GREEN = map(fg, ("0067c6", "be222a", "de6800", "f6c400", "007e46"))
OWNERS = {ground(rgb) for rgb in (*PALETTE, *PALETTE.values(), GREY) for ground in (fg, bg)}


def colours(shown):
    """The colours of a look, its text's and its background's, in any of SGR's forms."""
    return set(shown) - ATTRIBUTES


def colour(shown):
    """The one colour of a look: none, or a background too, fails the test."""
    [found] = colours(shown)
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Palette(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        Seat(home, "beta", screen="claude-question-pane.txt")
        Seat(home, "gamma")
        home.write(".agentkit/state/plan-gamma.md", "- [x] Shipped it\n")
        Seat(home, "delta")
        Seat(home, "omega")
        home.write(".agentkit/state/seat-omega.json", {"usage_wait": {
            "reason": "anthropic out of usage until 2026-10-21 09:00", "until": time.time() + 3600,
            "since": time.time() - 60, "continue": True}})
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(home, "--help").exit_code()

    def screen(self, background=None):
        """The ak screen on a true-colour terminal of that background, or of none: its looks
        once it shows every seat's word, then each cell's look where it kept it for STILL
        seconds, else None, as what breathes or pulses never rests."""
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        menu = Terminal(self.home, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait(lambda text: all(word in text for word in WORDS) and "esc leave" in text, 60)
        time.sleep(STILL)       # what moves as the screen opens has moved on
        captures, began = [], time.monotonic()
        while not captures or time.monotonic() - began < STILL:
            captures.append(looks(menu.screen(colours=True)))
            time.sleep(0.05)
        rest = [[cell if all(len(line) > at and line[at] == cell for line in rows) else None
                 for at, cell in enumerate(rows[0])] for rows in zip(*captures)]
        return captures[-1], rest

    def test_on_a_dark_background_each_state_is_its_colour_of_the_palette(self):
        screen, _ = self.screen()
        self.assertEqual(colour(look(screen, "›")), BLUE)
        for word, rgb, seat in (("working", BLUE, "acme"), ("! needs you", YELLOW, "beta"),
                                ("✓ done", GREEN, "gamma"), ("○ idle", fg(GREY), "delta"),
                                ("○ out of usage", RED, "omega")):
            with self.subTest(word):
                self.assertEqual(colour(look(screen, word, on=seat)), rgb)
        for key in ("↑↓←→", "esc"):
            self.assertEqual(colour(look(screen, key, on="esc leave")), fg(GREY))

    def test_on_a_light_background_needs_you_is_orange_and_the_rest_as_on_a_dark_one(self):
        screen, _ = self.screen("#ffffff")
        self.assertEqual(colour(look(screen, "›")), BLUE)
        for word, rgb, seat in (("working", BLUE, "acme"), ("! needs you", ORANGE, "beta"),
                                ("✓ done", GREEN, "gamma"), ("○ idle", fg(GREY), "delta"),
                                ("○ out of usage", RED, "omega")):
            with self.subTest(word):
                self.assertEqual(colour(look(screen, word, on=seat)), rgb)

    def test_at_rest_no_cell_is_drawn_in_a_colour_outside_the_palette(self):
        for background in (None, "#ffffff"):
            with self.subTest(background=background):
                _, rest = self.screen(background)
                drawn = {part for line in rest for cell in line if cell for part in colours(cell[1])}
                self.assertTrue(drawn)
                self.assertEqual(drawn - OWNERS, set())

    def test_a_seats_bar_draws_its_chip_in_the_text_that_reads_on_its_colour(self):
        for seat, word, rgb in (("acme", "● working", "0067c6"),
                                ("beta", "! needs you", "f6c400")):
            with self.subTest(word):
                term = Terminal(self.home, "orch", seat, size=(100, 30),
                                env={"COLORTERM": "truecolor"})
                self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
                done = self.home.ak("orch", "why", seat)      # a look at the seat dresses its bar
                self.assertEqual(done.code, 0, done.err)
                term.wait(lambda text: word in "\n".join(text.rstrip("\n").split("\n")[-2:]))
                bar = looks(term.screen(colours=True).rstrip("\n"))[-2:]
                self.assertEqual(colours(look(bar, word)), {fg(PALETTE[rgb]), bg(rgb)})


if __name__ == "__main__":
    unittest.main()
