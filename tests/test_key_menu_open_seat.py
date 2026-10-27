"""The ak menu opens a seat by a digit, by Enter on the highlighted row or by a click once the
button comes up, handing the terminal to that seat's tmux session on ak's own server; back from
it, the seat just opened is highlighted with its line closed.

The menu is how a person gets into a seat, so which seat a key opens and where the highlight is
when they come back is the whole of finding their way around.  The popup over a seat (`ak attach
--overlay`) is the main screen, its rows, keys and acts, with its highlight starting on the seat
it was opened from, and closes once it has opened a seat; `--dry-run` only says what opening
would do.  Black-box: ak runs in a
terminal of tests/fixtures/akterm.py over real seats of tests/fixtures/akseat.py, and whether it
attached is read from the clients tmux holds, never from the commands ak sent it.
"""

import re
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

KEYS = "  ↑↓←→ move   ⏎ choose   n new   c config   esc leave"
POPUP_KEYS = "  ↑↓←→ move   ⏎ choose   n new   x stop   c config   esc leave"   # x: its own seat's
SHOWS = {"atoll-fix": "Baking…", "atoll-ask": "(shift+tab to cycle) · ← for agents"}
NOW = int(time.time())


def seats(home):
    """atoll-fix made first and working, so it is 1; atoll-ask made after it, idle, 2."""
    Seat(home, "atoll-fix", screen="claude-working-pane.txt", record={"created": NOW - 900})
    Seat(home, "atoll-ask", screen="claude-prompt-pane.txt", record={"created": NOW - 600})


def until(test, what, bound=30):
    deadline = time.monotonic() + bound
    while not (got := test()):
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)
    return got


def attached(home):
    """The sessions of ak's own tmux server a client is attached to."""
    return home.tmux("list-clients", "-F", "#{client_session}").out.split()


def row(screen, name):
    """A seat's row on the menu, counted from 1 as a terminal counts rows, and the line under it."""
    lines = screen.splitlines()
    at = next(i for i, line in enumerate(lines) if re.match(rf"[› ] \d  {name}  ", line))
    return at + 1, lines[at + 1]


def highlighted(number, name, line_open):
    """The menu with that seat highlighted, and a line open under it or none: under it is only
    the next seat's row or nothing."""
    def test(screen):
        return f"› {number}  {name}  " in screen and line_open != bool(
            re.fullmatch(r"(  \d  \S+  .*)?", row(screen, name)[1]))
    return test


class OpensASeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        seats(cls.home)

    def setUp(self):
        self.menu = Terminal(self.home, size=(100, 30))
        self.addCleanup(self.leave)
        self.menu.wait(KEYS)

    def leave(self):
        for name in attached(self.home):
            self.home.tmux("detach-client", "-s", f"={name}")
        self.menu.keys("Escape")
        self.menu.exit_code()

    def opened(self, name):
        """The seat a person now sits in: a client on ak's server, its screen in the terminal."""
        until(lambda: attached(self.home), f"attached {name}")
        self.assertEqual(attached(self.home), [name])
        self.menu.wait(SHOWS[name])

    def came_back(self, number, name):
        """Leave the seat as a person does: the menu is back on it, its line closed."""
        self.home.tmux("detach-client", "-s", f"={name}")
        self.menu.wait(highlighted(number, name, line_open=False))

    def test_a_digit_opens_that_seat_and_back_it_is_highlighted(self):
        self.menu.keys("2")
        self.opened("atoll-ask")
        self.came_back(2, "atoll-ask")

    def test_enter_opens_the_highlighted_seat_and_back_its_line_is_closed(self):
        self.menu.keys("j")
        self.menu.wait("› 2  atoll-ask  ")
        self.menu.keys("k")
        self.menu.wait(highlighted(1, "atoll-fix", line_open=True))
        self.menu.keys("Enter")
        self.opened("atoll-fix")
        self.came_back(1, "atoll-fix")

    def test_a_click_opens_the_seat_only_when_the_button_comes_up(self):
        at, _ = row(self.menu.screen(), "atoll-fix")
        self.menu.type(f"\x1b[<0;8;{at}M")
        # a key after the button went down is answered on the menu: the press opened nothing
        self.menu.keys("j")
        self.menu.wait("› 2  atoll-ask  ")
        self.assertEqual(attached(self.home), [])
        self.menu.type(f"\x1b[<0;8;{at}m")
        self.opened("atoll-fix")
        self.came_back(1, "atoll-fix")


class Overlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        seats(cls.home)

    def popup(self, seat):
        """The menu as the popup over `seat` runs it: the main screen's keys and `x` at its foot."""
        menu = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                        env={"AGENTKIT_SESSION": seat})
        self.assertIn(POPUP_KEYS, menu.wait(POPUP_KEYS).splitlines())
        return menu

    def test_the_popup_closes_once_it_has_opened_a_seat(self):
        menu = self.popup("atoll-fix")
        menu.keys("2")
        until(lambda: attached(self.home), "attached atoll-ask")
        self.assertEqual(attached(self.home), ["atoll-ask"])
        self.home.tmux("detach-client", "-s", "=atoll-ask")
        self.assertEqual(menu.exit_code(), 0)

    def test_the_popup_starts_on_its_own_seat(self):
        menu = self.popup("atoll-ask")
        menu.wait("› 2  atoll-ask  ")
        menu.keys("Escape")
        self.assertEqual(menu.exit_code(), 0)


class DryRun(unittest.TestCase):
    def test_opening_a_live_seat_or_a_lost_one_only_says_what_it_would_do(self):
        with Home() as home:
            Seat(home, "atoll-ask", record={"created": NOW - 900})
            Seat(home, "ghost-a", alive=False, record={"created": NOW - 600})
            menu = Terminal(home, "--dry-run", size=(100, 30))
            menu.wait(KEYS)
            menu.keys("j")
            menu.wait("› 2  ghost-a  ")
            # each number brings the menu straight back: nothing was attached or started
            menu.keys("1")
            menu.wait("› 1  atoll-ask  ")
            menu.keys("2")
            menu.wait("› 2  ghost-a  ")
            self.assertEqual(attached(home), [])
            menu.keys("Escape")
            self.assertEqual(menu.exit_code(), 0)
            said = menu.screen().splitlines()
            self.assertIn("would attach atoll-ask", said)
            self.assertIn("would resume ghost-a", said)
            self.assertNotEqual(home.tmux("has-session", "-t", "=ghost-a").code, 0)
            self.assertEqual(home.calls("claude"), [])


if __name__ == "__main__":
    unittest.main()
