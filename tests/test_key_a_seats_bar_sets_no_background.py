"""A seat's bar sets no background but its chip's: the terminal's own shows through the rest.

The owner (24 Nov 2026), of the two lines tmux shows under a seat: "I want here for the tab in the
session to not have a colored background but be transparant so to have the actual terminal
backgorudn color."  Of the bar's two lines only the state's chip stands on a colour, on-accent on
its state's; no other cell sets a background, and the seat's name sets no colour either, while
what says something by its colour keeps it: the other seats' count is in theirs.  tmux's own
styles for the bar, the message line and the command prompt in the seat are `default`.  Each
holds on a client wide enough for the whole bar and on one that cuts the chip short of the count,
in the dark shades and, once a menu ran on a white terminal, in the light ones.

Black-box: the program AK_BIN names, in a person's terminal of 24-bit colour whose background a
test sets (tests/fixtures/akterm.py), attached by `ak orch` to seats of tests/fixtures/akseat.py
-- acme working, beta and gamma asking -- each cell judged by how it looks
(tests/fixtures/aklooks.py).  The tests run in their order.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

WIDTHS = (120, 25)     # the whole bar, and one whose chip is cut beside the count folded
# role: its colour in the dark shades, and in the light
DARK = {"accent": "4da3ff", "warning": "d79200", "on-accent": "000000"}
LIGHT = {"accent": "0067c6", "warning": "8e5e00", "on-accent": "ffffff"}
# seat: its chip, the chip's role, and line one's right end, in the warning's colour, and folded
SEATS = {"acme": ("● working", "accent", "! 2 other seats need you", "! 2 need you"),
         "beta": ("! needs you", "warning", "! 1 other seat needs you", "! 1 needs you")}
STYLES = ("status-style", "message-style", "message-command-style")
# what stands a cell on a colour: a background in any of SGR's forms, or reverse video
GROUNDS = {"7", *(str(code) for code in (*range(40, 48), *range(100, 108)))}


def fg(rgb):
    return "38;2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def bg(rgb):
    return "48" + fg(rgb)[2:]


def grounds(shown):
    return {part for part in shown if part.startswith("48") or part in GROUNDS}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatsBarSetsNoBackground(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        for name in ("beta", "gamma"):
            Seat(home, name, screen="claude-question-pane.txt")
        for name in ("gamma", "beta", "acme"):    # each word told before a bar counts it
            done = home.ak("orch", "why", name)
            assert done.code == 0, done.err
        cls.terms = {}
        for name in SEATS:
            for width in WIDTHS:
                cls.terms[name, width] = term = Terminal(home, "orch", name, size=(width, 30),
                                                         env={"COLORTERM": "truecolor"})
                cls.addClassCleanup(home.tmux, "kill-session", "-t", term.pane, server=SERVER)

    def bars(self, theme):
        """Each seat's bar on each client, once a look at it has drawn it as `theme` should."""
        for name in SEATS:
            done = self.home.ak("orch", "why", name)
            self.assertEqual(done.code, 0, done.err)
            for width in WIDTHS:
                with self.subTest(name, width=width):
                    deadline = time.monotonic() + 30
                    while (wrong := self.off(bar := self.bar(name, width), name, width, theme)) \
                            and time.monotonic() < deadline:
                        time.sleep(0.2)     # tmux learns the terminal takes true colour as it goes
                    self.assertIsNone(wrong, "\n".join(plain(line) for line in bar))
            for style in STYLES:
                held = self.home.tmux("show-options", "-v", "-t", f"={name}:", style)
                self.assertEqual((held.code, held.out), (0, "default\n"), f"{style}: {held}")

    def bar(self, name, width):
        screen = self.terms[name, width].screen(colours=True, blank=True)
        return looks(screen.rstrip("\n"))[-2:]

    def off(self, bar, name, width, theme):
        """What of `name`'s bar on a client `width` wide is not as `theme` draws it, else None: no
        cell on a background but its chip's, on-accent on its role, through the `…` where the
        client cuts it; its name, where shown, in no colour; the count in the warning's."""
        chip, role, *counts = SEATS[name]
        whole = width == WIDTHS[0]
        count, shown = counts[not whole], plain(bar[0]) if bar else ""
        if len(bar) < 2 or not all(text in shown for text in
                                   ((chip, name, count) if whole else ("…", count))):
            return f"no bar of {name} saying {count!r}"
        start = shown.index(chip[0]) - 1      # the space the chip opens with
        end = start + len(chip) + 2 if whole else shown.index("…") + 1
        for number, line in enumerate(bar):
            if len(line) != width:
                return f"line {number + 1} is {len(line)} cells"
            for at, (_, drawn) in enumerate(line):
                want = {bg(theme[role])} if number == 0 and start <= at < end else set()
                if grounds(drawn) != want:
                    return f"line {number + 1}, cell {at + 1} is on {grounds(drawn) or 'none'}"
        for text, colours in ((shown[start:end], {fg(theme["on-accent"]), bg(theme[role])}),
                              (count, {fg(theme["warning"])}), *[(name, set())] * whole):
            if (drawn := look([bar[0]], text) - ATTRIBUTES) != colours:
                return f"{text!r} is drawn in {drawn or 'no colour'}"
        return None

    def test_a_in_the_dark_shades(self):
        self.bars(DARK)

    def test_b_in_the_light_shades_a_menu_on_a_white_terminal_kept(self):
        done = self.home.tmux("set-option", "-g", "window-style", "bg=#ffffff", server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        menu = Terminal(self.home, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait("esc leave", 60)
        self.bars(LIGHT)


if __name__ == "__main__":
    unittest.main()
