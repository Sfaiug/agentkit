"""A login removed on `Subscriptions` fades out where its card stood before it goes: `− remove`
under `Claude II`, Claude's second login, and `Remove` picked, part way through `motion.LEAVES`
the card's question stands on its row in an ink between its own and the screen's background;
past it the Subscriptions page is up without `Claude II`, Claude's first login on it, and
config.toml lists that login alone.  At 8 colours nothing fades: the first screen after the
pick is that page.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) on the
injected motion clock (tests/fixtures/clock.py), each update it writes read by `pipe-pane`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, clock, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import look, plain, settled
from fixtures.akterm import SERVER, Terminal
import test_key_a_seats_row_fades_out as seats
from test_key_a_seats_row_fades_out import between, rgb
import test_key_removed_subscription_signs_out as subscriptions
from test_key_removed_subscription_signs_out import MAIN_KEYS, PAGE, lines, row_at, title

LEAVES = 0.2                    # motion.LEAVES
OPENED, PICKED = 1000.0, 1010.0     # the page up; `Remove` picked, the card at rest
ASKED = "Remove Claude II?"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ARemovedLoginFadesOut(unittest.TestCase):
    to = subscriptions.Subscriptions.to
    at, shows, updates = (seats.ARemovedPastSessionFadesOut.at,
                          seats.ARemovedPastSessionFadesOut.shows,
                          seats.ARemovedPastSessionFadesOut.updates)

    def removing(self, env):
        """`Remove` picked on `Claude II`'s card in a terminal with `env`: the screen's looks as
        the pick found them, at rest."""
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        akconfig.write(self.home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "a1"]}})
        clock.standing(self.home, "AK_MOTION_CLOCK", 0.0)
        self.term = Terminal(self.home, size=(100, 30), env=env)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.to("Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE)
        self.at(OPENED)
        self.to("Claude II")
        self.term.keys("Right", "Right", "Enter")          # `− remove`, last on its line
        self.term.wait("› ✓ Keep")
        self.term.keys("Down")
        self.term.wait("› × Remove")
        self.at(PICKED)
        before = settled(self.term, ASKED)
        self.raw = self.home.root / "raw"
        self.raw.touch()
        self.home.tmux("pipe-pane", "-t", self.term.pane, f"cat >{self.raw}", server=SERVER)
        self.term.type("\r")
        return before

    def gone(self, screen):
        """Whether `screen` is the Subscriptions page without `Claude II`, Claude's first login
        on it."""
        return (title(screen) == PAGE and row_at(screen, "Claude II") is None
                and row_at(screen, "Claude") is not None)

    def test_the_card_fades_out_and_then_the_login_is_gone(self):
        before = self.removing({"COLORTERM": "truecolor"})
        row = next(n for n, line in enumerate(before) if ASKED in plain(line))
        ink, ground = rgb(look([before[row]], ASKED)), rgb(look(before, "config"), 48)
        self.term.wait(lambda _: any(ASKED in update for update in self.updates()))
        self.at(PICKED + LEAVES / 2)
        self.shows(lambda rows: plain(rows[row]) == plain(before[row])
                   and between(rgb(look([rows[row]], ASKED)), ink, ground))
        self.at(PICKED + LEAVES + 0.05)
        self.term.wait(self.gone)
        self.assertEqual(akconfig.read(self.home)["providers"]["anthropic"]["accounts"],
                         ["default"])

    def test_at_eight_colours_the_first_screen_after_the_pick_is_the_page(self):
        self.removing({"TERM": "xterm", "COLORTERM": ""})
        self.term.wait(self.gone)
        self.assertTrue(self.gone(self.updates()[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
