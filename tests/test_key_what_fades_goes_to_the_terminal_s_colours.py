"""A highlight that leaves a row fades to the terminal's own background where the look reads
there: part way the row is on a colour between the rule's highlight and the terminal's own, and
at the end on none.  The owner, 20 Nov 2026: ak "just sits on top of" the terminal's background.
Black-box, on tests/test_key_a_screen_is_painted.py's terminal, seats and injected clock; Go's
ak does not claim it."""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.aklooks import looks, plain
import test_key_a_screen_is_painted as painted

OWN, LIT = (bytes.fromhex(rgb) for rgb in (painted.DARK[1:], painted.ON_DARK[2]))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhatFadesGoesToTheTerminalsOwn(unittest.TestCase):
    setUpClass = classmethod(painted.AScreenIsPainted.setUpClass.__func__)
    at, open, rest = (getattr(painted.AScreenIsPainted, name) for name in ("at", "open", "rest"))

    def fill(self, menu, row, *but):
        """The three channels of the 24-bit colour every cell of `row` is on, to the terminal's
        last column, none where they are on the terminal's own, once that is none of `but`: what
        the row is on before the frame asked for, which a busy host draws late and tmux may be
        read part way through (Terminal.wait)."""
        deadline = time.monotonic() + 30
        while True:
            cells = [painted.fills(shown)
                     for _, shown in looks(menu.screen(colours=True, blank=True))[row]]
            # to the last column: tmux keeps no cell past a row's text
            cells += [set()] * (painted.SIZE[0] - len(cells))
            rgb = bytes(int(channel) for part in cells[0] for channel in part.split(";")[2:])
            if rgb not in but and cells == [painted.fill(rgb.hex() or None)] * len(cells):
                return rgb
            self.assertLess(time.monotonic(), deadline, f"row {row} stayed on {cells}")
            time.sleep(0.05)

    def test_a_highlight_left_fades_to_the_terminal_s_own(self):
        menu = self.open()
        rows = self.rest(menu, "esc leave", painted.OPENED + 10)
        left = [plain(line).startswith("›") for line in rows].index(True)
        menu.keys("Down")
        # each read once the screen rests: a fill the row only passes through is not one it is on
        self.rest(menu, lambda shown: not shown.split("\n")[left].startswith("›"),
                  painted.OPENED + 10.1)    # part way through the fade, which began at + 10
        # the highlight until that frame is drawn, and none: a draw writes a row, then its fill
        part_way = self.fill(menu, left, LIT, b"")
        for channel, own, lit in zip(part_way, OWN, LIT):
            self.assertTrue(min(own, lit) <= channel <= max(own, lit), part_way.hex())
        self.assertNotIn(part_way, (OWN, LIT))
        self.rest(menu, "esc leave", painted.OPENED + 20)
        self.assertEqual(self.fill(menu, left, part_way), b"")


if __name__ == "__main__":
    unittest.main()
