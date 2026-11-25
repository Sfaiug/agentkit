"""A screen sits on its terminal's own background where the look reads there
(tests/test_the_look_reads.py): no cell sets a background but its highlight's, whose row is
banded to the layout's last column.  Elsewhere -- where the look does not read, ak cannot ask or
reads a line at a time -- every cell of it, text or blank, is on the theme's background,
or a row the highlight is on whole on its selection (tests/test_key_one_highlight.py), text of
no colour in the theme's text, and the terminal its own again once ak leaves.

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
from fixtures.akterm import SERVER, Terminal, forget

DARK, LIGHT, GREY = "#203040", "#e8e4d8", "#808080"     # terminals' own, neither theme's
# a theme's background, text and selection
BLACK, WHITE = ("000000", "e2e8ef", "08305d"), ("ffffff", "181c22", "dcecff")
# ... and the look on DARK and LIGHT, where it reads: on none, and the highlight the rule gives
ON_DARK, ON_LIGHT = (None, "e2e8ef", "234365"), (None, "181c22", "c6d2d8")
SIZE = (100, 30)
OPENED = 1000.0     # the moment ak's motion stands at as a screen opens
# a breath, which takes two seconds, in quarters, long after the screen opened: each a frame
MOMENTS = [OPENED + 10 + quarter / 4 for quarter in range(1, 9)]


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


def fill(rgb):
    """What fills a cell on `rgb`: nothing for one on the terminal's own, where `rgb` is None."""
    return {sgr(rgb, "48")} if rgb else set()


def fills(shown):
    """What fills a look's cell, in any of SGR's forms, reverse among them."""
    return {part for part in shown if part == "7" or part.startswith("48;") or part.isdigit()
            and int(part) in (*range(40, 48), *range(100, 108))}


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
        """`args` on a true-colour terminal of that background, or none, ak's motion at OPENED."""
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

    def assert_painted(self, term, theme, rows=None, banded=False):
        """Every cell of the terminal, to its last column and row, on the theme's background or
        its selection: `rows`, a capture's looks, else the terminal's now.  None but the row the
        highlight is on, its `›`'s, is on the selection; with `banded` all of that row is, else a
        cell of it may be reversed, as a build lights one (tests/test_key_no_name_has_a_colour.py).
        On the terminal's own, theme[0] None, tmux keeps no cell past a row's text."""
        rows = rows or looks(term.screen(colours=True, blank=True))
        lit = [plain(line).lstrip().startswith("›") for line in rows]
        self.assertGreaterEqual(len(rows), SIZE[1])
        self.assertTrue(any(lit) or not banded)
        for number, line in enumerate(rows[:SIZE[1]], 1):
            wide = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char, _ in line)
            band = lit[number - 1] and banded
            grounds = [fill(theme[2])] if band else [fill(theme[0]), *(
                [fill(theme[2]), {"7", *fill(theme[0])}] if lit[number - 1] else [])]
            off = {char for char, shown in line if fills(shown) not in grounds}
            self.assertEqual((wide if theme[0] or band else SIZE[0], off), (SIZE[0], set()),
                             f"row {number}: {plain(line)!r}")

    def assert_named(self, rows, theme):
        """A seat's name in the theme's text, on its background."""
        self.assertEqual(set(look(rows, "delta", on="idle")) - ATTRIBUTES,
                         {sgr(theme[1]), *fill(theme[0])})

    def test_the_ak_screen_and_its_breath_are_on_the_terminal_s_own(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_DARK, rows, banded=True)
        self.assert_named(rows, ON_DARK)
        for moment in MOMENTS:
            last = menu.screen(colours=True, blank=True)
            self.at(moment)
            deadline = time.monotonic() + 30
            while (shown := menu.screen(colours=True, blank=True)) == last:
                self.assertLess(time.monotonic(), deadline, f"ak drew no frame at {moment}")
                time.sleep(0.05)
            with self.subTest(moment=moment):
                self.assert_painted(menu, ON_DARK, looks(shown), banded=True)

    def test_c_and_subscriptions_are_on_the_terminal_s_own(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        self.assert_painted(menu, ON_DARK, banded=True)
        menu.keys("c")
        self.rest(menu, lambda text: "› " in text and "Subscriptions" in text, OPENED + 20)
        self.assert_painted(menu, ON_DARK)
        menu.keys("a")      # a card: its answers lit, the page's highlight away
        self.rest(menu, lambda text: "› ✓ Keep" in text and "esc back" in text, OPENED + 25)
        self.assert_painted(menu, ON_DARK)
        menu.keys("Escape")
        menu.wait(lambda text: "✓ Keep" not in text and "Subscriptions" in text, 30)

        def pointed(text):    # the highlighted row
            return next((line for line in text.split("\n") if line.startswith("› ")), None)
        while "Subscriptions" not in (row := pointed(menu.screen())):
            menu.keys("Down")
            menu.wait(lambda text: pointed(text) not in (None, row), 30)
        menu.keys("Enter")
        self.rest(menu, "+ add a subscription", OPENED + 30)
        self.assert_painted(menu, ON_DARK)

    def test_the_popup_over_a_seat_is_on_black_its_padding_too(self):
        forget(self.home)       # it cannot ask, as tmux answers no popup: black where none is kept
        popup = self.open("attach", "--overlay", background=None,
                          env={"AGENTKIT_SESSION": "acme", "AGENTKIT_PADDING": "1"})
        rows = self.rest(popup, "esc leave", OPENED + 10)
        self.assertEqual(plain(rows[0]).strip(), "")      # the padding, above the header
        self.assert_painted(popup, BLACK)

    def test_on_a_light_terminal_it_is_on_the_terminal_s_own(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_LIGHT, rows, banded=True)
        self.assert_named(rows, ON_LIGHT)

    def test_where_the_look_does_not_read_it_is_painted_in_its_theme(self):
        menu = self.open(background=GREY)       # white's dim text has too little on it
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, WHITE, rows, banded=True)
        self.assert_named(rows, WHITE)

    def test_a_screen_read_a_line_at_a_time_is_on_black(self):
        forget(self.home)       # it cannot ask: in the theme kept, black where none is
        menu = self.open("-c", 'printf "\\033\\n" | "$0" --dry-run; exec sleep 86400', AK,
                         program="sh")
        menu.wait("esc leave", 60)
        self.assert_painted(menu, BLACK)
        self.assert_named(looks(menu.screen(colours=True, blank=True)), BLACK)

    def test_a_restart_on_a_light_terminal_puts_its_frame_back_on_the_terminal_s_own(self):
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
