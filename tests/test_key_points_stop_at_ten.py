"""The models screen's `within` runs from 0 to 10 points, its knob ten cells, one a point: full
up to `within`, then open.  → at 10 and ← at 0 change nothing and save nothing; a config.toml
`within` over 10 is refused as one under 0 is.  A fractional `within` fills its whole points and
says its number as it is; on 40 cells the knob stays whole on the legend's first line.

Black-box, as tests/test_key_models_answer.py: the program `AK_BIN` names in a terminal, its
harnesses fakes listing invented models, the boards held as just asked with invented rows;
judged by the screen, config.toml and `ak models --json`.  Fails against /bin/false.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV, boards, lines

MODELS = {"mid": {"harness": "claude", "model": "acme-mid-5", "effort": "low"},
          "bolt": {"harness": "codex", "model": "bolt-3", "effort": "low"}}
AT_FIVE = "  as good    ‹ ▰▰▰▰▰▱▱▱▱▱ ›  within 5 points of the best, then the cheapest"


class PointsStopAtTen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n")

    def setUp(self):
        self.home.write(".agentkit/state/boards.json", boards())

    def models(self, within, width=100):
        """`r` on `c` at `within`, in a window of its own, once the answer is drawn."""
        akconfig.write(self.home, MODELS, settings={"within": within})
        term = Terminal(self.home, size=(width, 60), env=ENV)
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        return term, lines(term.wait("comparing all 4 models"))

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_right_stops_at_ten_and_left_at_zero(self):
        term, _ = self.models(9)
        term.keys("Right")
        shown = lines(term.wait("within 10 points"))
        self.assertIn("  as good    ‹ ▰▰▰▰▰▰▰▰▰▰ ›  within 10 points of the best, then the cheapest",
                      shown)
        self.assertEqual(akconfig.read(self.home)["within"], 10)
        term.keys("Right", "Left")      # a step past 10 counted would leave this at 10
        term.wait("within 9 points")
        self.assertEqual(akconfig.read(self.home)["within"], 9)

        term, _ = self.models(0)
        term.keys("Left", "Right")
        shown = lines(term.wait("within 1 points"))
        self.assertIn("  as good    ‹ ▰▱▱▱▱▱▱▱▱▱ ›  within 1 points of the best, then the cheapest",
                      shown)
        self.assertEqual(akconfig.read(self.home)["within"], 1)

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_the_knob_is_ten_cells_a_point_never_broken(self):
        self.assertIn(AT_FIVE, self.models(5)[1])
        self.assertIn("  as good    ‹ ▰▰▰▰▰▱▱▱▱▱ ›  within 5.5", self.models(5.5, width=40)[1])

    def test_a_config_over_ten_is_refused(self):
        path = akconfig.write(self.home, MODELS, settings={"within": 11})
        done = self.home.ak("models", "--json")
        self.assertEqual(done.code, 2, done.err)
        self.assertEqual(done.err, f"ak models: {path}: "
                                   "within must be a number of points from 0 to 10 (got 11)\n")


if __name__ == "__main__":
    unittest.main()
