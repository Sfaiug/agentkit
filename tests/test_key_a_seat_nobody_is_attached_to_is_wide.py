"""A seat opens 240 columns by 50 rows while nobody is attached to it, where tmux alone would open
it 80 by 24: a line ak types then shows whole in its harness's input box, where ak reads it back
before it presses Enter (a box that shows half the pane's rows less five scrolls a draft taller
than that).  So does a seat opened on a server that was up before ak's config.
Black-box: the program `AK_BIN` names opens the seats from outside (tests/fixtures/akbin.py),
judged by the size tmux gives their windows.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from test_key_tmux_conf import open_seat


def size(home, name):
    done = home.tmux("display-message", "-p", "-t", f"={name}:", "#{window_width}x#{window_height}")
    assert done.code == 0, done.err
    return done.out.strip()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ASeatNobodyIsAttachedToIsWide(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_a_seat_ak_opens_is_240_by_50(self):
        open_seat(self.home, "acme")
        self.assertEqual(size(self.home, "acme"), "240x50")

    def test_so_is_one_opened_on_a_server_already_up(self):
        Seat(self.home, "acme")     # its server started on no config at all
        open_seat(self.home, "beta")
        self.assertEqual(size(self.home, "beta"), "240x50")


if __name__ == "__main__":
    unittest.main()
