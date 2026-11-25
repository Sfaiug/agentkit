"""On `c`, on Subscriptions with an act picked, and with a card up over either, a menu in its own
window on a terminal the look reads on (tests/test_the_look_reads.py) fills only the highlight:
some cell is on it -- the keys' mark, the act, the card's answer -- every cell that sets a
background sets that one, and none is reversed.  The ak screen is
tests/test_key_a_screen_is_painted.py's; this key stays out of go/keys.txt, for Go's ak to port.

The owner, 20 Nov 2026: ak "just sits on top of" the terminal's background; of the highlight
there, 22 Nov: "Follow the terminal".  Black-box: the program AK_BIN names runs in a person's
terminal of 24-bit colour (tests/fixtures/akterm.py) whose own background is DARK, over a seat
and faked harnesses (tests/fixtures/fakeadapter.py) whose usage was read just now, so no row
has anything new to say.  ak's motion clock is injected (`AK_MOTION_CLOCK`) and moved past
each screen's motion, and each screen is read cell by cell, trailing blanks too, once it rests.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import looks, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_a_screen_is_painted import DARK, ON_DARK, OPENED, SIZE, fills, sgr

LIT = frozenset({sgr(ON_DARK[2], "48")})        # the highlight on DARK


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CAndACardShowTheTerminalsOwn(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, {"fable": "claude", "astra": "codex"})
        week = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800}], "error": None}
        home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            "anthropic": week, "openai": week}})
        Seat(home, "acme", model="fable")
        # The terminals' tmux keeps the background a test sets only while it is up, and a
        # terminal left open keeps it up.
        Terminal(home, "--help").exit_code()
        done = home.tmux("set-option", "-g", "window-style", f"bg={DARK}", server=SERVER)
        self.assertEqual(done.code, 0, done.err)
        self.clock, self.moment = home.root / "clock", OPENED
        self.clock.write_text(repr(OPENED))
        self.term = Terminal(home, size=SIZE, env={"COLORTERM": "truecolor",
                                                   "AK_MOTION_CLOCK": str(self.clock)})
        self.addCleanup(home.tmux, "kill-session", "-t", self.term.pane, server=SERVER)

    def rest(self, keys, shown):
        """The screen `keys` lead to, once it shows `shown` and rests, ak's motion moved past
        it, each line to its last column."""
        self.term.keys(*keys)
        self.term.wait(shown, 60)
        self.moment += 10
        new = self.clock.with_name("clock.new")     # swapped whole, never read half written
        new.write_text(repr(self.moment))
        new.replace(self.clock)
        settled(self.term, shown, bound=60)
        return looks(self.term.screen(colours=True, blank=True))

    def assert_only_lit(self, name, rows):
        """Some cell of `rows` sets a background, and every one that does sets the highlight
        alone: failing, the rows that set another say so."""
        with self.subTest(name):
            cells = [(plain(line), frozenset(fills(shown))) for line in rows for _, shown in line]
            self.assertEqual({fill for _, fill in cells} - {frozenset()}, {LIT},
                             {text for text, fill in cells if fill - LIT})

    def test_c_subscriptions_and_a_card_over_each_fill_only_the_highlight(self):
        self.rest((), "esc leave")
        self.assert_only_lit("c", self.rest(("c",), "› Fable 5.1"))
        self.assert_only_lit("a card over c", self.rest(("a",), "› ✓ Keep"))
        self.rest(("Escape",), "a apply")
        self.rest(("Down", "Down", "Down"), "› Subscriptions")     # past 6 Astra and Models
        self.rest(("Enter",), "› Claude")
        self.assert_only_lit("Subscriptions, an act picked", self.rest(("Right",), "⏎ remove"))
        self.assert_only_lit("a card over Subscriptions", self.rest(("Enter",), "› ✓ Keep"))


if __name__ == "__main__":
    unittest.main()
