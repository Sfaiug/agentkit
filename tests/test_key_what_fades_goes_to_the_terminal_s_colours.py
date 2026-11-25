"""A highlight that leaves a row fades to the terminal's own background where the look reads
there: part way the row is on a colour between the rule's highlight and the terminal's own, and
at the end on none.  The owner, 20 Nov 2026: ak "just sits on top of" the terminal's background.
Black-box, on tests/test_key_a_screen_is_painted.py's terminal, seats and injected clock; Go's
ak does not claim it."""

import re
import subprocess
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.aklooks import looks, plain
from fixtures.akseat import _cells
from fixtures.akterm import SERVER
import test_key_a_screen_is_painted as painted

OWN, LIT = (bytes.fromhex(rgb) for rgb in (painted.DARK[1:], painted.ON_DARK[2]))
# What tmux's control mode says: an answer to its client, or bytes the terminal was sent ...
SAID = re.compile(rb"^%begin (.*)\n((?:.*\n)*?)%end \1$|^%output \S+ (.*)$", re.M)
# ... where it writes an update's ends so: a terminal shows an update whole
HOLD, RELEASE = rb"\033[?2026h", rb"\033[?2026l"


class Whole:
    """A Terminal's screen as an update left it, whole: tmux may be read part way through one
    (Terminal.wait).  From here on a client in tmux's control mode is told what the terminal, its
    session's one pane, is sent and what tmux answers it, each in the order tmux took it: a read
    counts where what the terminal was sent before it had ended its last update."""

    def __init__(self, case, term):
        # a file in the terminal's own folder takes all of it: tmux stops reading a terminal its
        # client is behind on
        self.told = term.status.with_name("told")
        with self.told.open("wb") as told:
            self.tmux = subprocess.Popen(
                [REAL_TMUX, "-L", SERVER, "-C", "attach-session", "-t", term.pane], bufsize=0,
                stdin=subprocess.PIPE, stdout=told, env=term.home._env(None))
        case.addCleanup(self.tmux.communicate)      # which ends its input, and so it
        # tmux's first answer is to the attaching: from there on it says all the terminal is sent
        term.wait(lambda _: SAID.search(self.told.read_bytes()))

    def screen(self, colours=False, blank=False):
        """As Terminal.screen with these, the first such read tmux answers from here on."""
        at, deadline = self.told.stat().st_size, time.monotonic() + 30
        while time.monotonic() < deadline:
            self.tmux.stdin.write(b"capture-pane -p%s%s\n" % (b"e" * colours, b"N" * blank))
            time.sleep(0.05)
            sent = bytearray()
            for said in SAID.finditer(self.told.read_bytes()):
                if said[1] is None:
                    sent += said[3]
                elif said.start() >= at and sent.rfind(HOLD) < sent.rfind(RELEASE):
                    return said[2].decode()
        raise AssertionError("tmux gave no read of the terminal with its last update ended")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WhatFadesGoesToTheTerminalsOwn(unittest.TestCase):
    setUpClass = classmethod(painted.AScreenIsPainted.setUpClass.__func__)
    at, open, rest = (getattr(painted.AScreenIsPainted, name) for name in ("at", "open", "rest"))

    def fill(self, menu, row, but):
        """The three channels of the 24-bit colour every cell of `row` is on, to the terminal's
        last column, none where they are on the terminal's own, once that is not `but`: what the
        row was on before the frame asked for, which a busy host draws late."""
        deadline = time.monotonic() + 30
        while True:
            line = looks(menu.screen(colours=True, blank=True))[row]
            cells = [painted.fills(shown) for _, shown in line]
            # to the last column: tmux keeps no cell past a row's text
            cells += [set()] * (painted.SIZE[0] - _cells(plain(line)))
            rgb = bytes(int(channel) for part in cells[0] for channel in part.split(";")[2:])
            if rgb != but and cells == [painted.fill(rgb.hex() or None)] * len(cells):
                return rgb
            self.assertLess(time.monotonic(), deadline, f"row {row} stayed on {cells}")
            time.sleep(0.05)

    def test_a_highlight_left_fades_to_the_terminal_s_own(self):
        menu = self.open()
        whole = Whole(self, menu)
        rows = self.rest(menu, "esc leave", painted.OPENED + 10)
        left = [plain(line).startswith("›") for line in rows].index(True)
        menu.keys("Down")
        # each read once the screen rests: a fill the row only passes through is not one it is on
        self.rest(menu, lambda shown: not shown.split("\n")[left].startswith("›"),
                  painted.OPENED + 10.1)    # part way through the fade, which began at + 10
        part_way = self.fill(whole, left, LIT)       # the highlight until that frame is drawn
        for channel, own, lit in zip(part_way, OWN, LIT):
            self.assertTrue(min(own, lit) <= channel <= max(own, lit), part_way.hex())
        self.assertNotIn(part_way, (b"", OWN, LIT))
        self.rest(menu, "esc leave", painted.OPENED + 20)
        self.assertEqual(self.fill(whole, left, part_way), b"")


if __name__ == "__main__":
    unittest.main()
