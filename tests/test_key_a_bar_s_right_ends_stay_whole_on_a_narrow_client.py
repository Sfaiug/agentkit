"""On a client too narrow for anything beside them, a bar's right ends stay whole.

Line two's key, `Ctrl-b m  menu`, and line one's `! 1 needs you` are what a narrow client keeps:
where not one cell of what stands to their left is left, nothing of it is drawn, not a `…`
pushing into their first cell.  Black-box: gh is logged out, as a tick leaves it found, so both
seats of tests/fixtures/akseat.py need you; `AK_BIN`'s `ak orch why` writes their bars, read
on a person's terminal of tests/fixtures/akterm.py attached by `ak orch acme`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

OPENS = 60      # a loaded host makes a first draw slow
KEY = "Ctrl-b m  menu"
OTHER = "! 1 needs you"     # line one's right end, folded: beta needs you too


def bar(screen):
    return [row.rstrip() for row in screen.rstrip("\n").split("\n")[-2:]]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RightEndsStayWhole(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        home.write(".agentkit/state/watch.json", {"gh_out": {"at": time.time() - 300}})
        for name in ("beta", "acme"):
            Seat(home, name)
        for name in ("beta", "acme"):     # acme last, so its bar counts beta's word
            written = home.ak("orch", "why", name)
            assert written.code == 0, written.err
        # A wide terminal shows why beside the key: a bar without that reason has nothing to
        # cut, and the narrow terminals below would pass on it.
        Terminal(home, "orch", "acme", size=(100, 24)).wait(
            lambda screen: len(bar(screen)) == 2 and bar(screen)[1].endswith(KEY)
            and "GitHub is logged out" in bar(screen)[1], bound=OPENS)

    def test_17_and_16_columns_keep_the_key_and_who_else_needs_you_whole(self):
        for width in (17, 16):
            with self.subTest(width):
                # A terminal of its own, opened this narrow: one resized down to it may still
                # show the wider bar it drew before, cut to fit, and that reads the same.
                seat = Terminal(self.home, "orch", "acme", size=(width, 24))
                seat.wait(lambda screen: len(bar(screen)) == 2 and bar(screen)[0].endswith(OTHER)
                          and bar(screen)[1].endswith(KEY), bound=OPENS)


if __name__ == "__main__":
    unittest.main()
