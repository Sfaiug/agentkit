"""A card's answer fades where the highlight left it only while the card is up: `a apply to all
sessions` on `c` asks on a card at the page's foot, and `✓ Keep` answered, the page's key line
comes back on that answer's row with nothing fading over it -- part way through `motion.LEAVES`
every row but the one the highlight comes back to stands as it does at rest -- while on the card,
the highlight moved from `✓ Keep` to `× Apply`, `✓ Keep` still fades.  The owner, 10 Nov 2026:
"Every single page must be color consistent, and also while you are at it make it animation
consistent."

Black-box: the program `AK_BIN` names, in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py) over a seat as ak leaves it (tests/fixtures/akseat.py), its motion
clock injected (`AK_MOTION_CLOCK`) and held at each moment the screen is judged at, so every
frame then is the same, read once the highlight coming in has moved on to that moment and the
screen rests, however late the host draws it.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ATTRIBUTES, look, looks, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_defaults_apply_to_all import CALM, KEYS, MODELS, key_line

LEAVES = 0.2                    # motion.LEAVES
OPENED, ASKED = 1000.0, 1010.0  # `c` up and at rest; the card up, and at rest from here on
REST = ASKED + 10               # past every motion


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClosedCardsAnswerDoesNotFade(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, MODELS, workers=["fable"], reviewers=["astra"])
        Seat(self.home, "acme-api", model="fable", record=CALM)
        self.clock = self.home.root / "clock"
        self.at(0.0)
        self.term = Terminal(self.home, size=(100, 40), env={
            "COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock)})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("c config")
        self.term.keys("c")
        self.term.wait(lambda screen: key_line(screen) == KEYS)
        self.at(OPENED)
        self.term.keys("a")
        self.term.wait("› ✓ Keep")
        self.at(ASKED)
        self.card = settled(self.term, "› ✓ Keep")
        self.keep = next(n for n, line in enumerate(self.card) if "✓ Keep" in plain(line))

    def at(self, seconds):
        """ak's motion at `seconds` from now on, its clock's file swapped whole."""
        self.clock.with_suffix(".new").write_text(repr(seconds))
        self.clock.with_suffix(".new").replace(self.clock)

    def leaving(self, shown):
        """The screen's looks part way through `motion.LEAVES` of the draw that showed `shown`
        at ASKED, then once past every motion: each once the highlight it brings, on the row
        that `›` marks, looks unlike the read before, and then rests -- however late the host
        draws, nothing older."""
        reads = [settled(self.term, shown)]
        lit = next(n for n, line in enumerate(reads[0]) if "›" in plain(line))
        for moment in (ASKED + LEAVES / 2, REST):
            self.at(moment)
            self.term.wait(lambda _: looks(self.term.screen(colours=True))[lit] != reads[-1][lit])
            reads.append(settled(self.term, shown))
        return reads[1:]

    def test_keep_answered_the_page_fades_nothing_over_its_row(self):
        self.term.keys("Enter")
        # the header's HH:MM is the wall's clock, which no motion clock holds
        during, after = ([[("0" if n == 0 and char.isdigit() else char, cell) for char, cell in row]
                          for n, row in enumerate(rows)]
                         for rows in self.leaving(lambda screen: key_line(screen) == KEYS))
        self.assertEqual(plain(after[self.keep]).rstrip(), KEYS)
        lit, = (n for n, line in enumerate(after) if "›" in plain(line))
        for n, (row, rested) in enumerate(zip(during, after)):
            if n != lit:
                with self.subTest(row=plain(rested).rstrip()):
                    self.assertEqual(row, rested)

    def test_on_the_card_the_answer_left_still_fades(self):
        self.term.keys("Down")
        during, after = self.leaving("› × Apply")
        self.assertEqual(plain(during[self.keep]).rstrip(), plain(after[self.keep]).rstrip())
        self.assertNotEqual(*(look([rows[self.keep]], "✓ Keep") - ATTRIBUTES
                              for rows in (during, after)))


if __name__ == "__main__":
    unittest.main()
