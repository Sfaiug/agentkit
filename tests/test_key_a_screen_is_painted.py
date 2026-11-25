"""The ak screen sits on its terminal's own background where the look reads there
(tests/test_the_look_reads.py): no cell of it sets a background but its highlighted row's, on
the rule's highlight from its first column to the layout's last.  Elsewhere -- where the look
does not read, over a seat, or read a line at a time -- it is painted in its theme, as before:
every cell of it, text or blank, on the theme's background, or a row the highlight is on on its
selection (tests/test_key_one_highlight.py), text of no colour in the theme's text.  The
terminal is its own again once ak leaves.

The owner (12 Nov 2026): two themes, white and black, seen through everywhere ak is visual.
Black-box: the program AK_BIN names runs in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py) whose own background, set by its panes' `window-style`, which tmux
answers OSC 11 with, is neither theme's, over a working seat and an idle one
(tests/fixtures/akseat.py), each cell judged by how it looks (tests/fixtures/aklooks.py).  Its
clock injected as tests/test_key_themes.py injects it, so each frame of a breath is drawn at a
moment the test sets, however busy the host: a working seat's tip of its line breathes with its
`●`, in one phase (tests/test_line_tip_breathes.py).
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
# ... and on DARK and LIGHT, where the look reads: on none, and the highlight the rule gives
ON_DARK, ON_LIGHT = (None, "e2e8ef", "234366"), (None, "181c22", "c6d2d8")
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
    """What fills a look's cell, in any of SGR's forms, reverse among them: none on the
    terminal's own."""
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
        """Every cell of the terminal, to its last column and row, on the theme's background or
        its selection: `rows`, a capture's looks, else the terminal's now."""
        rows = rows or looks(term.screen(colours=True, blank=True))
        grounds = {sgr(theme[0], "48"), sgr(theme[2], "48")}
        self.assertGreaterEqual(len(rows), SIZE[1])
        for number, line in enumerate(rows[:SIZE[1]], 1):
            wide = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char, _ in line)
            off = {char for char, shown in line if not grounds & set(shown)}
            self.assertEqual((wide, off), (SIZE[0], set()), f"row {number}: {plain(line)!r}")

    def assert_on_its_own(self, rows, theme):
        """No cell of `rows`, a capture's looks, sets a background but the highlighted row's, its
        `›`'s, on the theme's selection from its first column to the layout's last, here the
        terminal's: tmux keeps no cell past the text of another row."""
        self.assertGreaterEqual(len(rows), SIZE[1])
        lit = [plain(line).startswith("›") for line in rows[:SIZE[1]]]
        self.assertEqual(lit.count(True), 1)
        for number, (line, band) in enumerate(zip(rows, lit), 1):
            off = {char for char, shown in line if fills(shown) != fill(theme[2] if band else None)}
            self.assertEqual(off, set(), f"row {number}: {plain(line)!r}")
        band = rows[lit.index(True)]
        self.assertEqual(sum(2 if unicodedata.east_asian_width(char) in "WF" else 1
                             for char, _ in band), SIZE[0], plain(band))

    def assert_named(self, rows, theme):
        """A seat's name in the theme's text, on its background."""
        self.assertEqual(set(look(rows, "delta", on="idle")) - ATTRIBUTES,
                         {sgr(theme[1]), *fill(theme[0])})

    def test_the_ak_screen_and_its_breath_are_on_the_terminal_s_own(self):
        menu = self.open()
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_on_its_own(rows, ON_DARK)
        self.assert_named(rows, ON_DARK)
        for moment in MOMENTS:
            last = menu.screen(colours=True, blank=True)
            self.at(moment)
            deadline = time.monotonic() + 30
            while (shown := menu.screen(colours=True, blank=True)) == last:
                self.assertLess(time.monotonic(), deadline, f"ak drew no frame at {moment}")
                time.sleep(0.05)
            with self.subTest(moment=moment):
                self.assert_on_its_own(looks(shown), ON_DARK)

    def test_a_working_seat_s_tip_breathes_with_its_dot(self):
        plan = self.home.write(".agentkit/state/plan-acme.md", "- [x] start\n- [ ] finish\n")
        self.addCleanup(plan.unlink)
        menu = self.open()
        dots = set()
        for moment in (OPENED + 10, OPENED + 11):       # half a breath apart
            row = next(row for row in self.rest(menu, "esc leave", moment)
                       if "acme" in plain(row) and "1 of 2" in plain(row))
            dot = next(shown for char, shown in row if char == "●")
            self.assertEqual(next(shown for char, shown in reversed(row) if char in "━╸"), dot)
            dots.add(dot)
        self.assertEqual(len(dots), 2, "the dot did not breathe")

    def test_the_popup_over_a_seat_is_on_black_its_padding_too(self):
        popup = self.open("attach", "--overlay",
                          env={"AGENTKIT_SESSION": "acme", "AGENTKIT_PADDING": "1"})
        rows = self.rest(popup, "esc leave", OPENED + 10)
        self.assertEqual(plain(rows[0]).strip(), "")      # the padding, above the header
        self.assert_painted(popup, BLACK)

    def test_on_a_light_terminal_it_is_on_the_terminal_s_own(self):
        menu = self.open(background=LIGHT)
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_on_its_own(rows, ON_LIGHT)
        self.assert_named(rows, ON_LIGHT)

    def test_where_the_look_does_not_read_it_is_painted_in_its_theme(self):
        menu = self.open(background=GREY)       # white's dim text has too little on it
        self.rest(menu, "esc leave", OPENED + 10)
        rows = looks(menu.screen(colours=True, blank=True))
        self.assert_painted(menu, WHITE, rows)
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
