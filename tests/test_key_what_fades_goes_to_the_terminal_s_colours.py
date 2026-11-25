"""A highlight that leaves a row fades to the terminal's own background where the look reads
there: part way the row is on a colour between the rule's highlight and the terminal's own, and
at the end on none.  The owner, 20 Nov 2026: ak "just sits on top of" the terminal's background.
Black-box, on tests/test_key_a_screen_is_painted.py's terminal, seats and injected clock; Go's
ak does not claim it."""

import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.aklooks import looks, plain
from fixtures.akseat import _cells
import test_key_a_screen_is_painted as painted

OWN, LIT = (bytes.fromhex(rgb) for rgb in (painted.DARK[1:], painted.ON_DARK[2]))
HOLD, RELEASE = b"\x1b[?2026h", b"\x1b[?2026l"      # an update's ends: a terminal shows it whole
MARK = b"\0"        # ... and nothing for this


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhatFadesGoesToTheTerminalsOwn(unittest.TestCase):
    setUpClass = classmethod(painted.AScreenIsPainted.setUpClass.__func__)
    at, open, rest = (getattr(painted.AScreenIsPainted, name) for name in ("at", "open", "rest"))

    def fill(self, menu, row, but):
        """The three channels of the 24-bit colour every cell of `row` is on, to the terminal's
        last column, none where they are on the terminal's own, once that is not `but`: what the
        row was on before the frame asked for, which a busy host draws late.  As an update left
        it, whole: tmux may be read part way through one (Terminal.wait), so a read counts where
        what the terminal had been sent had ended its last update, and a mark written after the
        read was all it was sent since."""
        deadline = time.monotonic() + 30
        while True:
            before = self.sent.read_bytes()
            line = looks(menu.screen(colours=True, blank=True))[row]
            Path(self.tty).write_bytes(MARK)
            menu.wait(lambda _: MARK in self.sent.read_bytes()[len(before):])
            whole = (before.rfind(HOLD) < before.rfind(RELEASE)
                     and self.sent.read_bytes() == before + MARK)
            cells = [painted.fills(shown) for _, shown in line]
            # to the last column: tmux keeps no cell past a row's text
            cells += [set()] * (painted.SIZE[0] - _cells(plain(line)))
            rgb = bytes(int(channel) for part in cells[0] for channel in part.split(";")[2:])
            if whole and rgb != but and cells == [painted.fill(rgb.hex() or None)] * len(cells):
                return rgb
            self.assertLess(time.monotonic(), deadline,
                            f"row {row} stayed on {cells}, read whole: {whole}")
            time.sleep(0.05)

    def test_a_highlight_left_fades_to_the_terminal_s_own(self):
        menu = self.open()
        # what the terminal is sent from here on, and where a mark for it is written (`fill`)
        self.sent = self.home.root / "sent"
        self.sent.touch()
        self.tty = menu._ask("pipe-pane", "-t", menu.pane, f"cat >{shlex.quote(str(self.sent))}",
                             ";", "display-message", "-p", "-t", menu.pane, "#{pane_tty}").strip()
        rows = self.rest(menu, "esc leave", painted.OPENED + 10)
        left = [plain(line).startswith("›") for line in rows].index(True)
        menu.keys("Down")
        # each read once the screen rests: a fill the row only passes through is not one it is on
        self.rest(menu, lambda shown: not shown.split("\n")[left].startswith("›"),
                  painted.OPENED + 10.1)    # part way through the fade, which began at + 10
        part_way = self.fill(menu, left, LIT)       # the highlight until that frame is drawn
        for channel, own, lit in zip(part_way, OWN, LIT):
            self.assertTrue(min(own, lit) <= channel <= max(own, lit), part_way.hex())
        self.assertNotIn(part_way, (b"", OWN, LIT))
        self.rest(menu, "esc leave", painted.OPENED + 20)
        self.assertEqual(self.fill(menu, left, part_way), b"")


if __name__ == "__main__":
    unittest.main()
