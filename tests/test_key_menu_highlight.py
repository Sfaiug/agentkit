"""The menu's highlight starts on the first seat, and keys, the wheel, the pointer and the page
arrows move it; `q` is no key there.

The highlighted row is the seat Enter opens and `x` stops, and the one row whose line is open
under it, so where it starts and what moves it is what a person's hand relies on.  The approved
screen says so (docs/cli-design.md, AGENTS.md): the row the owner points at, with the pointer or
↑/↓, opens one line under itself, and more seats than fit turn pages with ←/→, the usage staying
on top and the keys at the bottom.  Black-box: the program `AK_BIN` names runs in a person's
terminal (tests/fixtures/akterm.py) over live seats (tests/fixtures/akseat.py), and the pointer
and the wheel are typed as the SGR sequences a terminal sends for them.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

PROJECT = "atoll"
ROW = re.compile(r"([› ]) +\d+  (\S+)  ")
PAGE = re.compile(r"  ←  (\d+) / (\d+)  →   ↑↓←→ move   ⏎ choose")
SUBSCRIPTIONS = ("Claude", "ChatGPT", "Gemini", "Grok", "MiMo", "Muse")
WORDS = {"acme": "working", "beta": "needs you", "fix-api": "idle"}
# Seen only on its screen, a Claude chooser is asked by the line it waits on.
QUESTION = "Enter to select · ↑/↓ to navigate · Esc to cancel"
START = ["› acme", "  beta", "  fix-api"]
ON_BETA = ["  acme", "› beta", QUESTION, "  fix-api"]
POINT = "\x1b[<35;8;{row}M"           # the pointer moved, no button down, at column 8 of a row
WHEEL_DOWN = "\x1b[<65;10;10M"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def last(shown):
    """The key line's row: it is drawn last."""
    return max(i for i, line in enumerate(shown) if line)


def body(shown):
    """The lines between the project's heading and the key line: `› name` for the highlighted
    seat's row, `  name` for another seat's, and a line opened under a row as it reads."""
    if PROJECT not in shown:
        return None
    return [f"{row[1]} {row[2]}" if row else line.strip()
            for line in filter(None, shown[shown.index(PROJECT) + 1:last(shown)])
            for row in [ROW.match(line)]]


def row_of(shown, name):
    return next(i for i, line in enumerate(shown) if (row := ROW.match(line)) and row[2] == name)


def page(shown):
    found = PAGE.match(shown[last(shown)]) if any(shown) else None
    return found and (int(found[1]), int(found[2]))


def checkout(home):
    path = home.path / "code" / PROJECT
    path.mkdir(parents=True)
    done = home.run("git", "init", "-q", str(path))
    assert done.code == 0, done.err
    return path


class Menu(unittest.TestCase):
    def open(self, size, ready):
        """The menu in a person's terminal once `ready` holds of its screen; it is left with
        Esc when the test ends."""
        term = Terminal(self.home, size=size)
        self.addCleanup(term.exit_code)
        self.addCleanup(term.keys, "Escape")
        term.wait(lambda screen: ready(lines(screen)))
        return term

    def shows(self, term, want):
        """The screen's lines once its body reads `want`: keys reach the menu a moment after
        they are typed."""
        try:
            return lines(term.wait(lambda screen: body(lines(screen)) == want))
        except AssertionError:
            self.assertEqual(body(lines(term.screen())), want)
            return lines(term.screen())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Highlight(Menu):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        atoll = checkout(home)
        for name, screen, crew in (("acme", "claude-working-pane.txt", "opus"),
                                   ("beta", "claude-question-pane.txt", "opus"),
                                   ("fix-api", "claude-prompt-pane.txt", "astra")):
            Seat(home, name, screen=screen, cwd=atoll,
                 record={"repo": str(atoll), "workers": [crew]})

    def menu(self):
        # the first frame is the records as they stand; each seat's word comes with its look
        def ready(shown):
            rows = {row[2]: line for line in shown if (row := ROW.match(line))}
            return all(word in rows.get(name, "") for name, word in WORDS.items())
        return self.open((100, 30), ready)

    def test_the_menu_opens_on_the_first_seat_with_no_line_open(self):
        self.shows(self.menu(), START)

    def test_keys_and_the_wheel_move_the_highlight_and_open_its_line_alone(self):
        term = self.menu()
        self.shows(term, START)
        term.keys("j")
        self.shows(term, ON_BETA)
        term.keys("Up")
        self.shows(term, ["› acme", "Opus 5.5 ⚒◎", "  beta", "  fix-api"])
        # k on the first row stays there, or ↓ would not land on beta
        term.keys("k", "Down")
        self.shows(term, ON_BETA)
        term.type(WHEEL_DOWN)
        self.shows(term, ["  acme", "  beta", "› fix-api", "GPT-6-Astra ⚒◎"])
        # ↓ and the wheel on the last row stay there, or k would not land on beta
        term.keys("Down")
        term.type(WHEEL_DOWN)
        term.keys("k")
        self.shows(term, ON_BETA)

    def test_the_pointer_on_a_row_highlights_it_and_on_the_key_line_none(self):
        term = self.menu()
        start = self.shows(term, START)
        term.type(POINT.format(row=row_of(start, "beta") + 1))
        self.shows(term, ON_BETA)
        term.type(POINT.format(row=last(start) + 1))
        after = self.shows(term, ["  acme", "  beta", "  fix-api"])
        self.assertEqual(after[last(after)], start[last(start)])

    def test_q_is_no_key_it_neither_leaves_nor_changes_the_menu(self):
        term = self.menu()
        start = self.shows(term, START)
        # a key that shows after it: had q left or opened anything, j would not move the row
        term.keys("q", "j")
        after = self.shows(term, ON_BETA)
        self.assertFalse(term.status.exists(), "the menu ended on q")
        self.assertEqual(after[last(after)], start[last(start)])
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Pages(Menu):
    SEATS = [f"atoll-{number:02d}" for number in range(1, 14)]

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        atoll = checkout(home)
        for name in cls.SEATS:
            Seat(home, name, cwd=atoll, record={"repo": str(atoll)})

    def on(self, term, number, pages):
        """The screen once its key line says it is page `number`."""
        return lines(term.wait(lambda screen: page(lines(screen)) == (number, pages)))

    def holds(self, shown, first):
        """The seats a page lists, after checking it is laid out as the first page is: the
        usage on top, the project's heading first under it, the key line last, and the
        highlight on the page's first seat with no line open."""
        self.assertEqual(shown[first.index(PROJECT)], PROJECT, "\n".join(shown))
        self.assertEqual(last(shown), last(first), "\n".join(shown))
        for name in SUBSCRIPTIONS:
            self.assertIn(name, "\n".join(shown[1:first.index(PROJECT)]))
        rows = body(shown)
        self.assertEqual([row[:2] for row in rows], ["› "] + ["  "] * (len(rows) - 1))
        return [row[2:] for row in rows]

    def test_arrows_turn_the_pages_under_the_usage_and_above_the_keys(self):
        term = self.open((100, 16), page)
        pages = page(lines(term.screen()))[1]
        self.assertGreater(pages, 1)
        first = self.on(term, 1, pages)
        held = {1: self.holds(first, first)}
        for number in range(2, pages + 1):
            term.keys("Right")
            held[number] = self.holds(self.on(term, number, pages), first)
        self.assertEqual([name for number in sorted(held) for name in held[number]], self.SEATS)
        # → on the last page stays there, or ← would not land on the page before it
        term.keys("Right", "Left")
        for number in range(pages - 1, 0, -1):
            if number < pages - 1:
                term.keys("Left")
            self.assertEqual(self.holds(self.on(term, number, pages), first), held[number])


if __name__ == "__main__":
    unittest.main()
