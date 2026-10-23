"""A working seat's `●` breathes while the menu sits untouched; an idle seat's mark holds still.

The breath is how a person sees, without reading a word, which seats a model is working in, so
only those cells may move: every working dot in step, the rest of its row and an idle seat's row
as they were, whichever row the highlight is on.  Black-box: ak runs in a terminal of its own, in
colour, beside two seats whose panes show a working claude and one at its prompt; what moves is
read from the terminal's cells and their colours, sampled with no key pressed.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

WORKING, IDLE = ("s-work", "s-also"), "s-idle"
TOKEN = re.compile(r"\x1b\[([0-9;:]*)m|(.)")


def cells(line):
    """A captured line's cells, each its character and the style it is drawn in."""
    style, drawn = {}, []
    for code, char in TOKEN.findall(line):
        if char:
            drawn.append((char, tuple(sorted(style.items()))))
            continue
        params = (code or "0").split(";")
        while params:
            param = params.pop(0)
            if param in ("", "0"):
                style.clear()
            elif param in ("38", "48"):
                kind = params.pop(0)
                style[param] = ";".join([kind, *(params.pop(0) for _ in
                                                 range(1 if kind == "5" else 3))])
            elif param in ("39", "49"):
                style.pop(param[0] + "8", None)
            elif param == "22":
                style.pop("1", None)
                style.pop("2", None)
            else:
                style[param] = True
    return drawn


def mark(row):
    """Where a seat's state mark is on its row."""
    return next(at for at, (char, _) in enumerate(row) if char in "●○")


def colour(row):
    return dict(row[mark(row)][1]).get("38")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WorkingDot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        made = int(time.time()) - 600   # rows go in the order their seats were made
        for number, (name, screen) in enumerate(((WORKING[0], "claude-working-pane.txt"),
                                                 (WORKING[1], "claude-working-pane.txt"),
                                                 (IDLE, "claude-prompt-pane.txt"))):
            Seat(home, name, screen=screen, record={"created": made + number})

    def menu(self):
        """The menu once each seat's row says what its pane shows."""
        term = Terminal(self.home, size=(100, 30))
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        term.wait(lambda screen: f"› 1  {WORKING[0]}  Opus 5.5  ● working" in screen
                  and f"2  {WORKING[1]}  Opus 5.5  ● working" in screen
                  and f"3  {IDLE}  Opus 5.5  ○ idle" in screen)
        return term

    def watch(self, term, bound=15):
        """Each seat's row, as cells, in frame after frame with no key pressed, until the first
        working dot has been drawn in three colours."""
        frames, deadline = [], time.monotonic() + bound
        while len({colour(frame[WORKING[0]]) for frame in frames}) < 3:
            if time.monotonic() > deadline:
                raise AssertionError(f"{WORKING[0]}'s dot took the colours "
                                     f"{[colour(frame[WORKING[0]]) for frame in frames]}")
            rows = {}
            for line in term.screen(colours=True).split("\n"):
                drawn = cells(line)
                text = "".join(char for char, _ in drawn)
                # a whole row: a redraw writes a line at a time, and a capture can land inside one
                if text.rstrip().endswith((" working", " idle")):
                    rows.update((name, drawn) for name in (*WORKING, IDLE) if name in text.split())
            if len(rows) == 3:
                frames.append(rows)
            time.sleep(0.05)
        return frames

    def leave(self, term):
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)

    def test_a_working_dot_changes_colour_and_nothing_else_on_its_row_moves(self):
        term = self.menu()
        frames = self.watch(term)
        for name in WORKING:
            first = frames[0][name]
            for frame in frames:
                row = frame[name]
                self.assertEqual(row[mark(row)][0], "●")
                self.assertEqual(row[:mark(row)] + row[mark(row) + 1:],
                                 first[:mark(first)] + first[mark(first) + 1:])
        self.leave(term)

    def test_working_dots_breathe_in_step(self):
        term = self.menu()
        for frame in self.watch(term):
            self.assertEqual(colour(frame[WORKING[0]]), colour(frame[WORKING[1]]))
        self.leave(term)

    def test_an_idle_seats_mark_holds_still_with_the_highlight_on_it_or_not(self):
        term = self.menu()
        for highlighted in (False, True):
            if highlighted:
                term.keys("Down", "Down")
                term.wait(f"› 3  {IDLE}  Opus 5.5  ○ idle")
            frames = self.watch(term)
            self.assertEqual(frames[0][IDLE][0][0] == "›", highlighted)
            for frame in frames:
                self.assertEqual(frame[IDLE], frames[0][IDLE])
        self.leave(term)


if __name__ == "__main__":
    unittest.main()
