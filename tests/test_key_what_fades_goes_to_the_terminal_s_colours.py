"""What fades goes to its terminal's own background where the terminal says one, never to a
theme's (the owner, 20 Nov 2026: it "should be used, and ak just sits on top of that"): a page
comes up out of it, all under its rule first written in that colour itself, in 256 colours the
nearest of them; a working seat's `●` breathes half way to it; and the row the highlight left
fades into it, half way there 0.1 s on and filled with nothing 0.2 s on.

Black-box: the program AK_BIN names runs in a person's terminal (tests/fixtures/akterm.py) whose
own background, set by its panes' `window-style`, which tmux answers OSC 11 with, is neither
theme's, over a working seat and an idle one (tests/fixtures/akseat.py), each cell judged by how
it looks (tests/fixtures/aklooks.py).  Its clock injected as tests/test_key_themes.py injects it,
a file of seconds that stands still until the test moves it: each frame of a fade is drawn at a
moment the test sets, however busy the host.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, ink, look, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

OWN = "1f2d41"      # a terminal's own background: half way to it is a whole number each time
MID = "526274"      # ... and one the black theme's dim text does not read on
OPENED = 1000.0     # the moment ak's motion stands at as a screen opens


def sgr(rgb, ground="38"):
    return f"{ground};2;" + ";".join(str(channel) for channel in bytes.fromhex(rgb))


TEXT, ACCENT = sgr("e2e8ef"), sgr("4da3ff")     # the black theme's, which both terminals take
SELECTED = sgr("23436b", "48")      # what fills the highlight on OWN


def colours(shown):
    """A look's colours, its text's and what fills its cell, reverse video among them."""
    return shown - (ATTRIBUTES - {"7"})


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhatFadesGoesToTheTerminalSColours(unittest.TestCase):
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

    def open(self, background=OWN, **env):
        """The ak screen on a true-colour terminal of that background, its motion ten seconds on
        from OPENED: all that moves as it opens has, and a breath is at its colour."""
        done = self.home.tmux("set-option", "-g", "window-style", f"bg=#{background}",
                              server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        self.at(OPENED)
        menu = Terminal(self.home, size=(100, 30), env={
            "COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock), **env})
        self.addCleanup(self.home.tmux, "kill-session", "-t", menu.pane, server=SERVER)
        menu.wait("esc leave", 60)
        self.at(OPENED + 10)
        return menu

    def drawn(self, term, moment):
        """The screen's looks once ak's motion is at `moment`, which changes the frame that is
        up: the one drawn then, at rest."""
        last = term.screen(colours=True)
        self.at(moment)
        deadline = time.monotonic() + 30
        while term.screen(colours=True) == last:
            self.assertLess(time.monotonic(), deadline, f"ak drew no frame at {moment}")
            time.sleep(0.05)
        return settled(term, "esc", bound=60)

    def test_a_page_comes_up_out_of_the_terminal_s_own(self):
        def pointed(text):      # the highlighted row
            return next((line for line in text.split("\n") if line.startswith("› ")), None)
        # the terminal's own background as text shows it, then the theme's text and accent
        for background, env, (own, text, accent) in (
                (OWN, {}, (sgr(OWN), TEXT, ACCENT)), (MID, {}, (sgr(MID), TEXT, ACCENT)),
                (OWN, {"COLORTERM": "", "AGENTKIT_TERMFEATURES": ""},
                 ("38;5;236", "38;5;254", "38;5;75"))):
            with self.subTest(background=background, **env):
                menu = self.open(background, **env)
                menu.keys("c")      # its rows, the ak screen's highlight gone from under them
                row = pointed(menu.wait(lambda text: "Models" in text and pointed(text), 60))
                while "Models" not in row:
                    menu.keys("Down")
                    row = pointed(menu.wait(lambda text: pointed(text) not in (None, row), 30))
                menu.keys("Enter")      # the clock standing, the page's first frame stays up
                rows = settled(menu, "takes it in or out of the config", bound=60)
                # all under its header and rule yet to come up, text of whatever colour
                self.assertEqual({part for line in rows[2:] for _, shown in line
                                  for part in ink(shown) - ATTRIBUTES}, {own})
                rows = self.drawn(menu, OPENED + 20)
                self.assertEqual(ink(look(rows, "Codex")) - ATTRIBUTES, {text})
                self.assertEqual(ink(look(rows, "›")) - ATTRIBUTES, {accent})

    def test_a_working_seat_s_dot_breathes_half_way_to_the_terminal_s_own(self):
        menu = self.open()
        rows = settled(menu, "esc leave", bound=60)
        self.assertEqual(ink(look(rows, "●", on="working")) - ATTRIBUTES, {ACCENT})
        rows = self.drawn(menu, OPENED + 11)    # a breath, which takes two seconds, at its dimmest
        self.assertEqual(ink(look(rows, "●", on="working")) - ATTRIBUTES, {sgr("3668a0")})

    def test_the_row_the_highlight_left_fades_into_the_terminal_s_own(self):
        menu = self.open()
        settled(menu, "esc leave", bound=60)
        menu.keys("Down")       # the clock standing, the row it left is as it was
        rows = settled(menu, lambda text: any("›" in line and "idle" in line
                                              for line in text.split("\n")), bound=60)
        self.assertEqual(colours(look(rows, "acme", on="working")), {TEXT, SELECTED})
        rows = self.drawn(menu, OPENED + 10.1)
        self.assertEqual(colours(look(rows, "acme", on="working")), {TEXT, sgr("213856", "48")})
        rows = self.drawn(menu, OPENED + 10.2)
        self.assertEqual(colours(look(rows, "acme", on="working")), {TEXT})


if __name__ == "__main__":
    unittest.main()
