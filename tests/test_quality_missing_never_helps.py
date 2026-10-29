"""A measure no effort of a row's release has counts in `quality.rated` as far behind as the
row's furthest-behind measure, measured or carried, with that one's error, so a missing score
never helps: a row never rates above the weighted mean of what it has, and no row needs another
measured on every measure.  A measure no row of the index has counts for no row."""

import math
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import quality

F, T, A = "aa.frontierCode20", "aa.terminalBench40", "arena.agent"
WEIGHTS = {F: 0.4, T: 0.2, A: 0.4}                                       # execute's


def row(release, effort, **values):
    names = {"F": F, "T": T, "A": A, "I": quality.INTEL}
    return {"release": release, "effort": effort,
            "values": {names[key]: value for key, value in values.items()}}


def share(p, n):
    return 100 * math.sqrt(p * (1 - p) / n)


ACME = row("acme-5", "high", I=50, F=0.6, T=0.5, A=0.5)                 # 0 0 0, the best
BOLT = row("bolt-2", "high", I=40, F=0.5, T=0.3)                        # 10 20, A as T
CRUX_HIGH = row("crux-1", "high", I=40, F=0.5, T=0.45)                  # 10 5, A as F
CRUX_LOW = row("crux-1", "low", I=30, T=0.4)                            # F carried 20, T 10
ECHO = row("echo-1", "high", I=45, F=0.6, A=0.5)                        # T as F or A
DUNE = row("dune-3", "high", F=0.2, T=0.4, A=0.1)                       # no index


def found(rated, release, effort="high"):
    return next(r for r in rated if (r["release"], r["effort"]) == (release, effort))


def counted(one, column):
    measure = one["measures"][column]
    return measure["how"], round(measure["points"], 6)


class QualityMissingNeverHelps(unittest.TestCase):
    def setUp(self):
        self.rated = quality.rated([ACME, BOLT, CRUX_HIGH, CRUX_LOW], "execute")

    def test_a_missing_measure_counts_as_the_row_s_furthest_behind_with_its_error(self):
        bolt, low = found(self.rated, "bolt-2"), found(self.rated, "crux-1", "low")
        self.assertEqual(counted(bolt, A), ("missing", 20))
        self.assertEqual(bolt["measures"][A]["parts"], bolt["measures"][T]["parts"])
        self.assertEqual((counted(low, F), counted(low, A)), (("carried", 20), ("missing", 20)))
        self.assertEqual(low["measures"][A]["parts"], low["measures"][F]["parts"])
        self.assertAlmostEqual(bolt["quality"], 100 - (0.4 * 10 + 0.2 * 20 + 0.4 * 20))

    def test_its_error_counts_once_in_that_measure_s_part(self):
        bolt = found(self.rated, "bolt-2")
        parts = {("bolt-2", "high", F): 0.4 * share(0.5, 132),
                 ("bolt-2", "high", T): (0.2 + 0.4) * share(0.3, 66)}
        self.assertEqual(bolt["parts"].keys(), parts.keys())
        for score, part in parts.items():
            self.assertAlmostEqual(bolt["parts"][score], part)
        self.assertAlmostEqual(bolt["se"], math.hypot(*parts.values()))

    def test_a_row_never_rates_above_the_weighted_mean_of_what_it_has(self):
        for one in quality.rated([ACME, BOLT, CRUX_HIGH, CRUX_LOW, ECHO, DUNE], "execute"):
            has = {column: measure["points"] for column, measure in one["measures"].items()
                   if measure["how"] != "missing"}
            mean = sum(WEIGHTS[column] * points for column, points in has.items()) / sum(
                WEIGHTS[column] for column in has)
            self.assertLessEqual(one["quality"], 100 - mean + 1e-9, one["release"])

    def test_no_row_measured_on_every_measure_is_needed(self):
        rated = quality.rated([BOLT, ECHO], "execute")              # T's best is bolt-2's
        self.assertEqual(counted(found(rated, "bolt-2"), A), ("missing", 10))
        self.assertEqual(counted(found(rated, "echo-1"), T), ("missing", 0))
        self.assertAlmostEqual(found(rated, "bolt-2")["quality"], 92)

    def test_a_measure_no_row_of_the_index_has_counts_for_no_row(self):
        rated = quality.rated([BOLT, CRUX_HIGH, DUNE], "execute")    # A on dune-3 alone
        self.assertEqual([set(one["measures"]) for one in rated], [{F, T}] * 3)
        self.assertAlmostEqual(found(rated, "bolt-2")["quality"], 100 - 0.2 * 15 / 0.6)


if __name__ == "__main__":
    unittest.main()
