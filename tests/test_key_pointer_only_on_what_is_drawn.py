"""The pointer lights, and a click acts on, only what is drawn under it, on every screen.

The owner (27 Oct 2026): "only when I am with the cursor and press on the thing should it
respond, not when im next to it".  A thing is there from its first drawn cell to its last:
blank cells beside it -- a meter's padding, the gap between a model's label and its marks, a
row's empty rest -- are on nothing, so the pointer there lights nothing, the keys' highlight
not drawn as off every row, and a click there does nothing.  Black-box: the program `AK_BIN`
names runs in a person's terminal (tests/fixtures/akterm.py) over live seats
(tests/fixtures/akseat.py), with no colour, so a row's `›` and the keys' `[ ]` round a mark are
the highlight; whether a click opened a seat is read from the clients tmux holds.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
NOW = int(time.time())


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def lit_none(screen):
    """No row has the highlight: the pointer is on nothing, and once drawn so."""
    return not any(line.startswith("›") for line in lines(screen))


def point(col, row):
    return f"\x1b[<35;{col};{row}M"


def click(col, row):
    return f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m"


def attached(home):
    """The sessions of ak's own tmux server a client is attached to."""
    return home.tmux("list-clients", "-F", "#{client_session}").out.split()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OnlyWhatIsDrawn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "atoll-fix", screen="claude-prompt-pane.txt", record={"created": NOW - 900})
        Seat(home, "atoll-ask", screen="claude-prompt-pane.txt", record={"created": NOW - 600})
        home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": 79}]}}})

    def setUp(self):
        self.term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.addCleanup(self.leave)
        # the menu's own probe redraws each usage row once it is read, a moment after the menu
        # opens: read the screen after it, so no row a test compares changes under it
        self.shown = lines(self.term.wait(lambda screen: KEYS in lines(screen)
                                          and "› 1  atoll-fix  " in screen
                                          and "no reading yet" not in screen))

    def leave(self):
        for name in attached(self.home):
            self.home.tmux("detach-client", "-s", f"={name}")
        self.term.keys("Escape")
        self.term.keys("Escape")
        self.term.exit_code()

    def test_a_seat_row_is_its_text_never_the_blank_past_it(self):
        row = next(n for n, line in enumerate(self.shown) if "  atoll-ask  " in line)
        past = len(self.shown[row]) + 10
        self.term.type(point(past, row + 1))
        self.term.wait(lit_none)
        self.term.type(click(past, row + 1))
        name = self.shown[row].index("atoll-ask") + 1
        self.term.type(point(name, row + 1))       # read after the click: it opened nothing
        self.term.wait("› 2  atoll-ask  ")
        self.assertEqual(attached(self.home), [])
        self.term.type(click(name, row + 1))
        deadline = time.monotonic() + 30
        while not attached(self.home):
            self.assertLess(time.monotonic(), deadline, "the click on its name opened nothing")
            time.sleep(0.05)
        self.assertEqual(attached(self.home), ["atoll-ask"])

    def test_a_meter_is_its_bar_and_words_never_its_padding(self):
        row = next(n for n, line in enumerate(self.shown) if "Claude" in line and "▰" in line)
        under = next(n for n in range(row, len(self.shown)) if not self.shown[n])
        self.assertEqual(self.shown[under], "")     # where the detail line goes
        past = self.shown[row].index("21% left") + len("21% left") + 1
        self.term.type(point(past, row + 1))
        self.assertEqual(lines(self.term.wait(lit_none))[under], "")
        self.term.type(point(self.shown[row].index("▰") + 1, row + 1))
        self.term.wait(lambda screen: lines(screen)[under] == "  Claude")

    def test_on_c_the_gap_between_a_label_and_its_marks_is_on_nothing(self):
        self.term.keys("c")
        shown = lines(self.term.wait(lambda screen: "› Fable 5.1" in screen))
        config = (self.home.path / ".agentkit" / "config.toml").read_bytes()
        row = next(n for n, line in enumerate(shown) if line.startswith("  GPT-6-Astra "))
        gap = len("  GPT-6-Astra") + 2
        self.assertEqual(shown[row][gap - 1], " ")
        self.term.type(point(gap, row + 1))
        after = lines(self.term.wait(lit_none))
        self.assertFalse([line for line in after if re.search(r"\[.\]", line)], "a mark lit")
        self.term.type(click(gap, row + 1))
        # a key after the click goes on from where the keys left the highlight, on Fable 5.1
        self.term.keys("Down")
        after = lines(self.term.wait("› Opus 5.5"))
        # the model rows, the keys' highlight taken off: only they hold a mark, never the
        # meters over them, whose readings come in on their own
        def marks(shown):
            return [re.sub(r"[›\[\]]", " ", line) for line in shown if re.search("[●○■□]", line)]
        self.assertEqual(marks(after), marks(shown))
        self.assertEqual((self.home.path / ".agentkit" / "config.toml").read_bytes(), config)


if __name__ == "__main__":
    unittest.main()
