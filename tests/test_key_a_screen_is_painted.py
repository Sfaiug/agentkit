"""A screen is painted in its theme: every cell of it, text or blank, on the theme's background,
text of no colour in the theme's text, and the terminal its own again once ak leaves.

The owner (12 Nov 2026): two themes, white and black, seen through everywhere ak is visual.
Black-box: the program AK_BIN names runs in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py) whose own background, set by its panes' `window-style`, which tmux
answers OSC 11 with, is neither theme's, over a working seat and an idle one
(tests/fixtures/akseat.py), each cell judged by how it looks (tests/fixtures/aklooks.py).  Its
clock injected as tests/test_key_themes.py injects it, so each frame of a breath is drawn at a
moment the test sets, however busy the host.
"""

import shlex
import sys
from pathlib import Path
import time
import unicodedata
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

DARK, LIGHT = "#203040", "#e8e4d8"     # terminals' own backgrounds, neither theme's
BLACK, WHITE = ("000000", "e2e8ef"), ("ffffff", "181c22")     # a theme's background and text
SIZE = (100, 30)
OPENED = 1000.0     # the moment ak's motion stands at as a screen opens
# a breath, which takes two seconds, in quarters, long after the screen opened: each a frame
MOMENTS = [OPENED + 10 + quarter / 4 for quarter in range(1, 9)]


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AScreenIsPainted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        Seat(home, "acme", screen="claude-working-pane.txt")
        Seat(home, "delta")
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(home, "--help").exit_code()
        cls.clock = home.root / "clock"

    def at(self, seconds):
        """ak's motion at `seconds` from now on, its clock's file swapped whole."""
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def open(self, *args, background=DARK, env=None, program=AK):
        """`args` run on a true-colour terminal of that background, ak's motion at OPENED."""
        done = self.home.tmux("set-option", "-g", "window-style", f"bg={background}",
                              server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        self.at(OPENED)
        term = Terminal(self.home, *args, size=SIZE, program=program, env={
            "COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock), **(env or {})})
        self.addCleanup(self.home.tmux, "kill-session", "-t", term.pane, server=SERVER)
        return term

    def rest(self, term, shown, moment):
        """The screen's looks once it shows `shown` with ak's motion at `moment`."""
        term.wait(shown, 60)
        self.at(moment)
        return settled(term, shown, bound=60)

    def assert_painted(self, term, theme, rows=None):
        """Every cell of the terminal, to its last column and row, on the theme's background:
        `rows`, a capture's looks, else the terminal's now."""
        rows = rows or looks(term.screen(colours=True, blank=True))
        self.assertGreaterEqual(len(rows), SIZE[1])
        for number, line in enumerate(rows[:SIZE[1]], 1):
            wide = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char, _ in line)
            off = {char for char, shown in line if sgr(theme[0], "48") not in shown}
            self.assertEqual((wide, off), (SIZE[0], set()), f"row {number}: {plain(line)!r}")

    def assert_named(self, rows, theme):
        """A seat's name in the theme's text, on its background."""
        self.assertEqual(set(look(rows, "delta", on="idle")) - ATTRIBUTES,
                         {sgr(theme[1]), sgr(theme[0], "48")})

    def test_the_ak_screen_and_its_breath_are_on_black(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, BLACK, rows)
        self.assert_named(rows, BLACK)
        for moment in MOMENTS:
            last = menu.screen(colours=True, blank=True)
            self.at(moment)
            deadline = time.monotonic() + 30
            while (shown := menu.screen(colours=True, blank=True)) == last:
                self.assertLess(time.monotonic(), deadline, f"ak drew no frame at {moment}")
                time.sleep(0.05)
            with self.subTest(moment=moment):
                self.assert_painted(menu, BLACK, looks(shown))

    def test_c_and_subscriptions_are_on_black(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        menu.keys("c")
        self.rest(menu, lambda text: "› " in text and "Subscriptions" in text, OPENED + 20)
        self.assert_painted(menu, BLACK)

        def pointed(text):    # the highlighted row
            return next((line for line in text.split("\n") if line.startswith("› ")), None)
        while "Subscriptions" not in (row := pointed(menu.screen())):
            menu.keys("Down")
            menu.wait(lambda text: pointed(text) not in (None, row), 30)
        menu.keys("Enter")
        self.rest(menu, "+ add a subscription", OPENED + 30)
        self.assert_painted(menu, BLACK)

    def test_the_popup_over_a_seat_is_on_black_its_padding_too(self):
        popup = self.open("attach", "--overlay",
                          env={"AGENTKIT_SESSION": "acme", "AGENTKIT_PADDING": "1"})
        rows = self.rest(popup, "esc leave", OPENED + 10)
        self.assertEqual(plain(rows[0]).strip(), "")      # the padding, above the header
        self.assert_painted(popup, BLACK)

    def test_on_a_light_terminal_it_is_on_white(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, WHITE, rows)
        self.assert_named(rows, WHITE)

    def test_a_screen_read_a_line_at_a_time_is_on_black(self):
        menu = self.open("-c", 'printf "\\033\\n" | "$0" --dry-run; exec sleep 86400', AK,
                         program="sh")
        menu.wait("esc leave", 60)
        self.assert_painted(menu, BLACK)
        self.assert_named(looks(menu.screen(colours=True, blank=True)), BLACK)

    def test_a_restart_on_a_light_terminal_puts_its_frame_back_on_white(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        drawn, sent = time.time(), self.home.root / "sent"      # it started before it drew
        done = self.home.tmux("pipe-pane", "-t", menu.pane, f"cat >{shlex.quote(str(sent))}",
                              server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        while time.time() < int(drawn) + 1:     # an install, in whole seconds, past its start
            time.sleep(0.05)
        self.home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")
        deadline = time.monotonic() + 60
        while True:     # the frame it left up, written again as it takes the screen: first out
            said = sent.read_bytes() if sent.exists() else b""
            enter = said.find(b"\x1b[?1049h")
            release = said.find(b"\x1b[?2026l", enter) if enter >= 0 else -1
            if release >= 0:
                break
            self.assertLess(time.monotonic(), deadline, "never took the screen again")
            time.sleep(0.05)
        self.assert_named(looks(said[enter:release].decode()), WHITE)

    def test_what_the_shell_writes_after_ak_is_in_the_terminal_s_own_colours(self):
        shell = self.open("-c", '"$0"; echo after ak', AK, program="sh")
        self.rest(shell, "esc leave", OPENED + 10)
        shell.keys("Escape")
        shell.wait("after ak", 30)
        rows = looks(shell.screen(colours=True, blank=True))
        self.assertEqual(look(rows, "after ak"), set())


if __name__ == "__main__":
    unittest.main()
