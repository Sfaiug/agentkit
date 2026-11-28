"""A reset spent on `Subscriptions` glides its meter to the new reading before its light crosses.

The owner, 24 Nov 2026: a spent reset fills the bar and a light passes along it, like a seat
that is done.  Login I, highlighted, 20% left and holding a reset, its adapter answering a reset
spent with the week unused, the page back at `BACK`:
- at `BACK + GLIDE / 2`: login I's line says `N% left` above 20 and under 100, its bar the
  length a page opened on that `N` draws;
- at `BACK + GLIDE + SWEEP / 2`: its line says `100% left` and differs from the same line once
  the clock is past `BACK + GLIDE + SWEEP`, in its colours alone and inside its bar alone;
- past that, the line is the one a page opened afresh on that home shows.

Each moment is judged in a draw made with the clock held there (a reading of login II landing
then), never a frame between.  Black-box on tests/test_key_a_spent_reset_lights_its_meter.py's
helpers.  Fails against `/bin/false`.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
import test_key_a_meter_glides_on_subscriptions as glides
import test_key_a_spent_reset_lights_its_meter as lights

BACK, GLIDE, SWEEP = lights.BACK, glides.GLIDE, lights.SWEEP
WEEK_REFILLED = {"code": "reset", "available": 0,
                 "meters": [{"name": "weekly", "used": 0, "window_secs": 604800}]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SpentResetFillsItsMeter(unittest.TestCase):
    light = lights.SpentResetLightsItsMeter
    home, read, at, opened, rows, written, line, spend, held, afresh = (
        light.home, light.read, light.at, light.opened, light.rows, light.written, light.line,
        light.spend, light.held, light.afresh)

    def test_a_spent_reset_glides_its_meter_before_the_light_crosses(self):
        home, term = self.spend(WEEK_REFILLED, "Claude I · 100% left", one=20)
        mid = self.held(home, term, BACK + GLIDE / 2, 71, one=100)
        lit = self.held(home, term, BACK + GLIDE + SWEEP / 2, 72, one=100)
        rest = self.held(home, term, BACK + GLIDE + SWEEP + 0.05, 73, one=100)

        found = glides.FIRST.search(glides.CSI.sub("", mid))
        self.assertIsNotNone(found, mid)
        shown = int(found[2])
        self.assertGreater(shown, 20)
        self.assertLess(shown, 100)
        fresh = self.opened(self.home(shown, 71))
        self.assertEqual(found[1], glides.FIRST.search(self.line(fresh, "Claude I"))[1])
        self.assertEqual(mid, self.line(fresh, "Claude I", colours=True))

        self.assertIn("100% left", glides.CSI.sub("", lit))
        cells, still = lights.drawn(lit), lights.drawn(rest)
        self.assertEqual([char for char, _ in cells], [char for char, _ in still])
        moved = {n for n, (one, other) in enumerate(zip(cells, still)) if one != other}
        self.assertTrue(moved)
        self.assertLessEqual(moved, set(lights.bar(rest)))
        self.assertEqual(rest, self.afresh(home, term))


if __name__ == "__main__":
    unittest.main(verbosity=2)
