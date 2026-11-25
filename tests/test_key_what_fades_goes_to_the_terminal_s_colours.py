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

    def fill(self, menu, row, but):
        """Each fill on `row`, its three channels, once they are not `but`, the fills before."""
        deadline = time.monotonic() + 30
        while (found := {part for _, shown in looks(menu.screen(colours=True, blank=True))[row]
                         for part in painted.fills(shown)}) == but:
            self.assertLess(time.monotonic(), deadline, f"row {row} stayed on {but}")
            time.sleep(0.05)
        return [bytes(map(int, part.split(";")[2:])) for part in found]

    def test_a_highlight_left_fades_to_the_terminal_s_own(self):
        menu = self.open()
        rows = self.rest(menu, "esc leave", painted.OPENED + 10)
        left = [plain(line).startswith("›") for line in rows].index(True)
        menu.keys("Down")
        menu.wait(lambda shown: not shown.split("\n")[left].startswith("›"), 60)
        self.at(painted.OPENED + 10.1)      # part way through the fade, which began at + 10
        (part_way,) = self.fill(menu, left, {painted.sgr(LIT.hex(), "48")})
        for channel, own, lit in zip(part_way, OWN, LIT):
            self.assertTrue(min(own, lit) <= channel <= max(own, lit), part_way.hex())
        self.assertNotIn(part_way, (OWN, LIT))
        self.at(painted.OPENED + 20)
        self.assertEqual(self.fill(menu, left, {painted.sgr(part_way.hex(), "48")}), [])


if __name__ == "__main__":
    unittest.main()
