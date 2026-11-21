"""A screen is painted in its theme on the terminal's own background: no cell of it, text or
blank, on a background but those the highlight is on, on the theme's selection
(tests/test_key_one_highlight.py), text of no colour in the theme's text, and the terminal its
own again once ak leaves.  Where the terminal says its background, the theme is drawn between it
and the theme's text, each colour moved as far as its lightness is from the text, so the selection
and a line are not lost on it, and a page comes up out of it; where it says none, the theme's own
colours are drawn on the terminal's own background.

The owner (12 Nov 2026): two themes, white and black, seen through everywhere ak is visual; and
(20 Nov 2026) the terminal's own background "should be used, and ak just sits on top".
Black-box: the program AK_BIN names runs in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py) whose own background, set by its panes' `window-style`, which tmux
answers OSC 11 with, is neither theme's, over a working seat and an idle one
(tests/fixtures/akseat.py), each cell judged by how it looks (tests/fixtures/aklooks.py), and a
page as it comes up by what tmux's `pipe-pane` says it was written in
(tests/test_key_every_screen_comes_up.py).  Its clock injected as tests/test_key_themes.py
injects it, so each frame of a breath is drawn at a moment the test sets, however busy the host.
"""

import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal, forget
from test_key_every_screen_comes_up import inks
from test_key_one_highlight import ground

DARK, LIGHT = "#203040", "#e8e4d8"     # terminals' own backgrounds, neither theme's
# a theme's background, text, selection and border
BLACK, WHITE = ("000000", "e2e8ef", "08305d", "3a3f46"), ("ffffff", "181c22", "dcecff", "b1b8c0")
# ... and on a terminal's own background: the selection and border moved by their share of lightness
ON_DARK, ON_LIGHT = (None, "e2e8ef", "225791", "516275"), (None, "181c22", "c7d3dc", "a1a6a5")
SIZE = (100, 30)
OPENED = 1000.0     # the moment ak's motion stands at as a screen opens
# a breath, which takes two seconds, in quarters, long after the screen opened: each a frame
MOMENTS = [OPENED + 10 + quarter / 4 for quarter in range(1, 9)]


def sgr(rgb, ground="38"):
    """How a cell in that colour looks, its text or its `ground`; None for the terminal's own."""
    return rgb and f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


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
        """`args` run on a true-colour terminal of that background, or one that says none, ak's
        motion at OPENED."""
        option = ["window-style", f"bg={background}"] if background else ["-u", "window-style"]
        done = self.home.tmux("set-option", "-g", *option, server=SERVER)
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
        """No cell of the terminal, to its last row, on a background but the theme's selection:
        `rows`, a capture's looks, else the terminal's now."""
        rows = rows or looks(term.screen(colours=True, blank=True))
        grounds = {None, sgr(theme[2], "48")}
        self.assertGreaterEqual(len(rows), SIZE[1])
        for number, line in enumerate(rows[:SIZE[1]], 1):
            on = {ground(shown) for _, shown in line}
            self.assertEqual(on - grounds, set(), f"row {number}: {plain(line)!r}")

    def assert_named(self, rows, theme):
        """A seat's name in the theme's text and the header's rule in its border, on no
        background."""
        self.assertEqual(set(look(rows, "delta", on="idle")) - ATTRIBUTES, {sgr(theme[1])})
        self.assertEqual(set(look(rows, "─" * 40)) - ATTRIBUTES, {sgr(theme[3])})

    def test_the_ak_screen_and_its_breath_set_no_background(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_DARK, rows)
        self.assert_named(rows, ON_DARK)
        for moment in MOMENTS:
            last = menu.screen(colours=True, blank=True)
            self.at(moment)
            deadline = time.monotonic() + 30
            while (shown := menu.screen(colours=True, blank=True)) == last:
                self.assertLess(time.monotonic(), deadline, f"ak drew no frame at {moment}")
                time.sleep(0.05)
            with self.subTest(moment=moment):
                self.assert_painted(menu, ON_DARK, looks(shown))

    def test_c_and_subscriptions_set_no_background_and_come_up_out_of_the_terminal_s_own(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        menu.keys("c")
        self.rest(menu, lambda text: "› " in text and "Subscriptions" in text, OPENED + 20)
        self.assert_painted(menu, ON_DARK)

        def pointed(text):    # the highlighted row
            return next((line for line in text.split("\n") if line.startswith("› ")), None)
        while "Subscriptions" not in (row := pointed(menu.screen())):
            menu.keys("Down")
            menu.wait(lambda text: pointed(text) not in (None, row), 30)
        written = self.home.root / "written"
        done = self.home.tmux("pipe-pane", "-O", "-t", menu.pane,
                              f"cat >{shlex.quote(str(written))}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        menu.keys("Enter")
        deadline = time.monotonic() + 60
        while not (found := inks(written.read_bytes().decode("utf-8", "replace")
                                 if written.exists() else "", "+ add a subscription")):
            self.assertLess(time.monotonic(), deadline, "Subscriptions was never written")
            time.sleep(0.05)
        # nothing of it to see in its first frame: the terminal's own background is its ink
        self.assertEqual(found[0], tuple(bytes.fromhex(DARK[1:])))
        self.rest(menu, "+ add a subscription", OPENED + 30)
        self.assert_painted(menu, ON_DARK)

    def test_the_popup_over_a_seat_sets_no_background_nor_its_padding(self):
        forget(self.home)       # tmux says no background in a popup: black where none is kept
        popup = self.open("attach", "--overlay", background=None,
                          env={"AGENTKIT_SESSION": "acme", "AGENTKIT_PADDING": "1"})
        rows = self.rest(popup, "esc leave", OPENED + 10)
        self.assertEqual(plain(rows[0]).strip(), "")      # the padding, above the header
        self.assert_painted(popup, BLACK)

    def test_on_a_light_terminal_it_is_in_white(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_LIGHT, rows)
        self.assert_named(rows, ON_LIGHT)

    def test_a_screen_read_a_line_at_a_time_sets_no_background(self):
        forget(self.home)       # it cannot ask: in the theme kept, black where none is
        menu = self.open("-c", 'printf "\\033\\n" | "$0" --dry-run; exec sleep 86400', AK,
                         program="sh")
        menu.wait("esc leave", 60)
        self.assert_painted(menu, BLACK)
        self.assert_named(looks(menu.screen(colours=True, blank=True)), BLACK)

    def test_a_restart_on_a_light_terminal_puts_its_frame_back_in_white(self):
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
        self.assert_named(looks(said[enter:release].decode()), ON_LIGHT)

    def test_what_the_shell_writes_after_ak_is_in_the_terminal_s_own_colours(self):
        shell = self.open("-c", '"$0"; echo after ak', AK, program="sh")
        self.rest(shell, "esc leave", OPENED + 10)
        shell.keys("Escape")
        shell.wait("after ak", 30)
        rows = looks(shell.screen(colours=True, blank=True))
        self.assertEqual(look(rows, "after ak"), set())


if __name__ == "__main__":
    unittest.main()
