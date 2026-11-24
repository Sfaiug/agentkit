"""A screen sits on its terminal's own background where the terminal says one (the owner, 20 Nov
2026): no cell of it, text or blank, is filled but a row the highlight is on, and that on a
selection as far from the terminal's own as the theme's is from the theme's (22 Nov 2026), or as
much of that way as leaves the theme's dim text 3 to 1 of contrast on it: none of it where the
text has less on the terminal's own.  Where the terminal says none, every cell is painted the
theme's background.  Text of no colour is in the theme's text, and the terminal is its own again
once ak leaves.

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

DARK, LIGHT = "#203040", "#e8e4d8"     # terminals' own backgrounds, neither theme's
MID = "#526274"     # ... and one the black theme's dim text does not read on
SIZE = (100, 30)
OPENED = 1000.0     # the moment ak's motion stands at as a screen opens
# a breath, which takes two seconds, in quarters, long after the screen opened: each a frame
MOMENTS = [OPENED + 10 + quarter / 4 for quarter in range(1, 9)]


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


# How a screen looks: what fills a cell off the highlight, text of no colour, what fills the
# highlight.  Black's, painted where the terminal says no background of its own ...
BLACK = ({sgr("000000", "48")}, sgr("e2e8ef"), {sgr("08305d", "48")})
# ... and on a terminal that says one, where nothing fills a cell off the highlight: on DARK and
# LIGHT, the selection as near the theme's as its dim text reads on; on MID, where it reads on
# none, the terminal's own; and DARK in 256 colours, each the nearest of them
ON_DARK = (set(), sgr("e2e8ef"), {sgr("234366", "48")})
ON_LIGHT = (set(), sgr("181c22"), {sgr("c6d2d8", "48")})
ON_MID = (set(), sgr("e2e8ef"), {sgr("526274", "48")})
ON_DARK_IN_256 = (set(), "38;5;254", {"48;5;23"})


def fills(shown):
    """What fills a look's cell, in any of SGR's forms, reverse video among them: nothing where
    the terminal's own background shows."""
    return {part for part in shown if part == "7" or part.startswith("48;") or part.isdigit()
            and int(part) in (*range(40, 48), *range(100, 108))}


def contrast(shown):
    """WCAG's contrast of a look's text with what fills its cell, both in 24-bit colour."""
    low, high = sorted(sum(share * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
                           for share, c in zip((0.2126, 0.7152, 0.0722), channels))
                       for channels in ([int(part) / 255 for part in code.split(";")[2:]]
                                        for code in sorted(shown - ATTRIBUTES)))
    return (high + 0.05) / (low + 0.05)


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
        """Every cell of the terminal, to its last column and row, filled as `theme` fills one off
        the highlight or on it, and with nothing else: `rows`, a capture's looks, else the
        terminal's now.  On the highlight's row a cell reversed is the highlight's too, as a
        build lights the cell the keys are on (tests/test_key_no_name_has_a_colour.py).  Where
        nothing fills a cell, tmux keeps none past the last a row wrote or filled: the rest of
        that row is the terminal's own."""
        rows = rows or looks(term.screen(colours=True, blank=True))
        self.assertGreaterEqual(len(rows), SIZE[1])
        for number, line in enumerate(rows[:SIZE[1]], 1):
            wide = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char, _ in line)
            lit = (theme[2], {*theme[0], "7"}) if plain(line).startswith("›") else (theme[2],)
            off = {char for char, shown in line if fills(shown) not in (theme[0], *lit)}
            self.assertEqual((wide if theme[0] else SIZE[0], off), (SIZE[0], set()),
                             f"row {number}: {plain(line)!r}")

    def assert_named(self, rows, theme):
        """A seat's name off the highlight: in the theme's text, filled as a cell there is."""
        self.assertEqual(set(look(rows, "delta", on="idle")) - (ATTRIBUTES - {"7"}),
                         {theme[1], *theme[0]})

    def test_the_ak_screen_and_its_breath_are_on_the_terminal_s_own(self):
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

    def test_c_and_subscriptions_are_on_the_terminal_s_own(self):
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
        menu.keys("Enter")
        self.rest(menu, "+ add a subscription", OPENED + 30)
        self.assert_painted(menu, ON_DARK)

    def test_the_popup_over_a_seat_is_on_the_terminal_s_own_its_padding_too(self):
        popup = self.open("attach", "--overlay",
                          env={"AGENTKIT_SESSION": "acme", "AGENTKIT_PADDING": "1"})
        rows = self.rest(popup, "esc leave", OPENED + 10)
        self.assertEqual(plain(rows[0]).strip(), "")      # the padding, above the header
        self.assert_painted(popup, ON_DARK)

    def test_on_a_light_terminal_it_is_on_the_terminal_s_own(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_LIGHT, rows)
        self.assert_named(rows, ON_LIGHT)

    def test_a_terminal_dim_text_does_not_read_on_is_sat_on_its_highlight_its_own(self):
        menu = self.open(background=MID)
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_MID, rows)
        self.assert_named(rows, ON_MID)

    def test_in_256_colours_it_is_on_the_terminal_s_own(self):
        menu = self.open(env={"COLORTERM": "", "AGENTKIT_TERMFEATURES": ""})
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, ON_DARK_IN_256, rows)
        self.assert_named(rows, ON_DARK_IN_256)

    def test_the_highlight_hides_nothing_on_it(self):
        # a seat's number, dim: the faintest text a row keeps
        for background in (DARK, LIGHT):
            with self.subTest(background=background):
                menu = self.open(background=background)
                rows = self.rest(menu, "esc leave", OPENED + 10)
                self.assertGreaterEqual(contrast(look(rows, "1", on="working")), 3)
        # ... and a working seat's dot at its breath's dimmest, half way to a background the
        # theme's selection is as far from as its accent is from that
        menu = self.open(background="#3d4345")
        dot = look(self.rest(menu, "esc leave", OPENED + 11), "●", on="working")
        self.assertEqual(fills(dot), {sgr("3d4346", "48")})
        self.assertEqual(dot - fills(dot) - ATTRIBUTES, {sgr("4573a2")})

    def test_a_screen_read_a_line_at_a_time_is_on_black(self):
        forget(self.home)       # it cannot ask: in the theme kept, black where none is
        menu = self.open("-c", 'printf "\\033\\n" | "$0" --dry-run; exec sleep 86400', AK,
                         program="sh")
        menu.wait("esc leave", 60)
        self.assert_painted(menu, BLACK)
        self.assert_named(looks(menu.screen(colours=True, blank=True)), BLACK)

    def restarted(self, menu, background=None):
        """The looks of the first frame `menu`, at rest, shows once an install starts it again,
        its terminal's background `background` by then: what it writes from taking the screen to
        the end of that update."""
        drawn, sent = time.time(), self.home.root / f"sent{menu.pane}"   # it started before it drew
        done = self.home.tmux("pipe-pane", "-t", menu.pane, f"cat >{shlex.quote(str(sent))}",
                              server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        if background:
            done = self.home.tmux("set-option", "-g", "window-style", f"bg={background}",
                                  server=SERVER)
            self.assertEqual(done.code, 0, done.err)
        while time.time() < int(drawn) + 1:     # an install, in whole seconds, past its start
            time.sleep(0.05)
        self.home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")
        deadline = time.monotonic() + 60
        while True:
            said = sent.read_bytes() if sent.exists() else b""
            enter = said.find(b"\x1b[?1049h")
            release = said.find(b"\x1b[?2026l", enter) if enter >= 0 else -1
            if release >= 0:
                return looks(said[enter:release].decode())
            self.assertLess(time.monotonic(), deadline, "never took the screen again")
            time.sleep(0.05)

    def test_a_restart_on_a_light_terminal_puts_its_frame_back_on_the_terminal_s_own(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        # the frame it left up, written again as it takes the screen: first out
        self.assert_named(self.restarted(menu), ON_LIGHT)

    def test_a_restart_on_a_terminal_whose_background_changed_shows_no_highlight_of_the_old(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        first = self.restarted(menu, background="#101820")
        self.assertEqual(fills(look(first, "acme", on="working")), {sgr("174373", "48")})

    def test_what_the_shell_writes_after_ak_is_in_the_terminal_s_own_colours(self):
        shell = self.open("-c", '"$0"; echo after ak', AK, program="sh")
        self.rest(shell, "esc leave", OPENED + 10)
        shell.keys("Escape")
        shell.wait("after ak", 30)
        rows = looks(shell.screen(colours=True, blank=True))
        self.assertEqual(look(rows, "after ak"), set())


if __name__ == "__main__":
    unittest.main()
