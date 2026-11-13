"""A tick gives a tmux server that is already up ak's current `Ctrl-b m`, and no more of its
`terminal-features`, however often it ticks.

tmux reads ak's conf when a seat starts its server or opens on it, so a server running a binding
from an older ak -- one whose popup is handed no client name -- kept it until another seat opened,
the installer's update included.  The tick now loads the conf's lines that load again as they
loaded once; `terminal-features` is not one of them, as each load adds it once more.
Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py; this test fails against
`/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

OLD = ("display-popup", "-E", "true")   # an older ak's menu key, as far as this test reads it


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AServerOnAnOlderMenuKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        Seat(home, "acme")      # its server started on no config at all
        bound = home.tmux("bind-key", "m", *OLD)
        assert bound.code == 0, bound.err
        cls.features = cls.terminal_features()
        cls.ticks = [home.tick(), home.tick()]

    @classmethod
    def terminal_features(cls):
        done = cls.home.tmux("show-options", "-s", "terminal-features")
        assert done.code == 0, done.err
        return done.out

    def test_the_ticks_end_well(self):
        for tick in self.ticks:
            self.assertEqual(tick.code, 0, tick.out + tick.err)

    def test_its_ctrl_b_m_opens_the_menu(self):
        done = self.home.tmux("list-keys", "-T", "prefix", "m")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("attach --overlay", done.out)

    def test_its_terminal_features_are_as_they_were(self):
        self.assertEqual(self.terminal_features(), self.features)


if __name__ == "__main__":
    unittest.main()
