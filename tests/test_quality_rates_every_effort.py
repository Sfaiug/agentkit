"""`quality.rated` rates every effort of every model on a role's measures, and a missing score
never helps it: a measure is measured, carried from another effort of the release (from above
growing by what the intelligence index loses, never shrinking; else from below as it is) or
estimated from the rows measured on every measure, plus one standard error.  `quality.pick` is
the cheapest row with a cost within `within` of the best quality."""

import math
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import quality

F, T, W = "aa.frontierCode", "aa.terminalBench40", "arena.webdev"
I, C = quality.INTEL, quality.COSTS["execute"]


def row(release, effort, **values):
    names = {"F": F, "T": T, "W": W, "I": I, "C": C}
    return {"release": release, "effort": effort,
            "values": {names[key]: value for key, value in values.items()}}


ROWS = [row("acme-5", "high", I=50, F=0.6, T=0.5, W=1400, C=2.0),     # 0 0 0, the best
        row("acme-5", "low", I=45, T=0.4, C=0.5),                     # F, W from high, +5
        row("bolt-2", "high", I=40, F=0.5, T=0.3, W=1400, C=1.0),     # 10 20 0
        row("bolt-2", "low", I=42, F=0.5, W=1400),                    # T from high, never less
        row("crux-1", "high", I=35, F=0.55, T=0.45),                  # W estimated
        row("dune-3", "max", F=0.3, T=0.3),                           # no index: 30 20
        row("dune-3", "high", I=30, W=1400),                          # F, T from medium
        row("dune-3", "medium", I=25, F=0.2, T=0.2),                  # 40 30, W from high +5
        row("echo-1", "none", F=0.9, T=0.5),                          # above the best, no index
        row("fizz-1", "high", I=20, T=0.1)]                           # one measure: not rated


def found(rated, release, effort):
    return next(r for r in rated if (r["release"], r["effort"]) == (release, effort))


def points(rated, release, effort):
    return {column: (round(m["points"], 6), m["how"])
            for column, m in found(rated, release, effort)["measures"].items()}


# complete rows acme-5 high (0 0 0) and bolt-2 high (10 20 0, gaps 0 10 -10): offsets F 0,
# T 5, W -5; spreads F 0, T and W √50
CRUX_W = (5 - 0 + 5 - 5) / 2 - 5 + math.sqrt(50 + (math.sqrt(0 + 50) / 2) ** 2)


class QualityRatesEveryEffort(unittest.TestCase):
    def setUp(self):
        self.rated = quality.rated(ROWS, "execute")

    def test_a_measure_is_measured_carried_or_estimated(self):
        self.assertEqual(points(self.rated, "acme-5", "high"),
                         {F: (0, "measured"), T: (0, "measured"), W: (0, "measured")})
        self.assertEqual(points(self.rated, "acme-5", "low"),
                         {F: (5, "carried"), T: (10, "measured"), W: (5, "carried")})
        self.assertEqual(points(self.rated, "bolt-2", "low")[T], (20, "carried"))
        self.assertEqual(points(self.rated, "crux-1", "high"),
                         {F: (5, "measured"), T: (5, "measured"), W: (round(CRUX_W, 6), "estimated")})

    def test_from_above_only_when_both_have_the_index_else_from_below(self):
        self.assertEqual(points(self.rated, "dune-3", "high"),
                         {F: (40, "carried"), T: (30, "carried"), W: (0, "measured")})
        self.assertEqual(points(self.rated, "dune-3", "medium")[W], (5, "carried"))
        self.assertEqual(points(self.rated, "dune-3", "max")[W], (0, "carried"))

    def test_the_best_is_of_rows_with_the_index(self):
        self.assertEqual(points(self.rated, "echo-1", "none")[F], (-30, "measured"))

    def test_quality_and_cost(self):
        self.assertAlmostEqual(found(self.rated, "acme-5", "low")["quality"], 100 - 20 / 3)
        self.assertAlmostEqual(found(self.rated, "crux-1", "high")["quality"],
                               100 - (10 + CRUX_W) / 3)
        self.assertEqual([found(self.rated, release, effort)["cost"] for release, effort
                          in (("acme-5", "high"), ("bolt-2", "high"), ("crux-1", "high"))],
                         [2.0, 1.0, None])
        self.assertNotIn("fizz-1", {r["release"] for r in self.rated})

    def test_under_two_complete_rows_nothing_is_estimated(self):
        alone = quality.rated([ROWS[0], ROWS[4]], "execute")
        self.assertEqual(points(alone, "crux-1", "high"), {F: (5, "measured"), T: (5, "measured")})
        self.assertAlmostEqual(found(alone, "crux-1", "high")["quality"], 95)

    def test_pick_is_the_cheapest_within_of_the_best(self):
        rated = [r for r in self.rated if r["release"] != "echo-1"]     # above 100, unpriced
        self.assertEqual(quality.pick(rated, 5), found(rated, "acme-5", "high"))
        self.assertEqual(quality.pick(rated, 10), found(rated, "acme-5", "low"))
        self.assertIsNone(quality.pick(self.rated, 5))
        same = [{"quality": 90, "cost": 1.0}, {"quality": 95, "cost": 1.0}, {"quality": 99, "cost": None}]
        self.assertEqual(quality.pick(same, 10), same[1])
        self.assertIsNone(quality.pick([{"quality": 99, "cost": None}], 10))


if __name__ == "__main__":
    unittest.main()
