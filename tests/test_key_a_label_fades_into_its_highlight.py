"""A label on the highlight comes up out of the highlight: a page that comes up with a highlighted
row has, at its first moment, every cell of that row's label in the highlight's colour, part way
each channel of it between the highlight's and the settled text's, and at rest the settled
text's, on the highlight all the while.

Black-box: the program `AK_BIN` names, in a person's terminal of 24-bit colour
(tests/fixtures/akterm.py) in ak's black theme, opens `c`'s Models, its harnesses the fakes of
tests/fixtures/fakeadapter.py.  Its motion clock injected (`AK_MOTION_CLOCK`) and held at each
moment, so every frame then is the same, however late the host draws it.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import looks, plain
from fixtures.akterm import Terminal
import test_key_a_screen_is_painted as painted

LABEL = "Claude Code"
_, TEXT, LIT = painted.BLACK      # the black theme's text and highlight
OPENED = 1000.0


def rgb(shown, ground):
    """A look's colour of `ground`, 38 its text's or 48 its background's, as `RRGGBB`: none
    unset."""
    return next((bytes(int(channel) for channel in part.split(";")[2:]).hex() for part in shown
                 if part.startswith(f"{ground};2;")), None)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ALabelFadesIntoItsHighlight(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                   "astra": {"harness": "codex", "effort": "high"}})
        self.clock = self.home.root / "clock"
        self.at(OPENED)
        self.term = Terminal(self.home, size=(100, 30), env={
            "COLORTERM": "truecolor", "AK_MOTION_CLOCK": str(self.clock)})

    def at(self, seconds):
        """ak's motion at `seconds` from now on, its clock's file swapped whole."""
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def label(self, test):
        """The text's and background's colours of each cell of the highlighted row's label once
        `test` of them holds: tmux may be read part way through a frame."""
        deadline = time.monotonic() + 30
        while True:
            rows = looks(self.term.screen(colours=True))
            row = next((line for line in rows if plain(line).startswith(f"› {LABEL}")), [])
            cells = [(rgb(shown, 38), rgb(shown, 48)) for _, shown in row[2:2 + len(LABEL)]]
            if cells and test(cells):
                return cells
            self.assertLess(time.monotonic(), deadline, f"never so: {cells}")
            time.sleep(0.05)

    def test_a_label_comes_up_out_of_its_highlight(self):
        self.term.wait("esc leave")
        self.term.keys("c", "j", "j")
        self.term.wait("› Models")
        self.term.keys("Enter")
        first = self.label(lambda cells: True)
        self.assertEqual(first, [(LIT, LIT)] * len(LABEL))
        self.at(OPENED + 0.05)          # part way through the page's coming up
        part_way = self.label(lambda cells: all(ink != LIT for ink, _ in cells))
        for ink, back in part_way:
            self.assertEqual(back, LIT)
            self.assertNotEqual(ink, TEXT)
            for channel, lit, text in zip(*map(bytes.fromhex, (ink, LIT, TEXT))):
                self.assertTrue(min(lit, text) <= channel <= max(lit, text), ink)
        self.at(OPENED + 10)
        rest = self.label(lambda cells: all(map(tuple.__ne__, cells, part_way)))
        self.assertEqual(rest, [(TEXT, LIT)] * len(LABEL))


if __name__ == "__main__":
    unittest.main()
