"""A row's quality is 100 less the weighted mean of its points behind the best over the role's
measures it has, each by its weight in `quality.ROLES`, and its error the same weights'
combination of the measures' errors."""

import math
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import quality

F, A, T = "aa.frontierCode20", "arena.agent", "aa.terminalBench40"     # execute's: 0.4 0.4 0.2


def row(release, **values):
    return {"release": release, "effort": "high", "values": {quality.INTEL: 50, **values}}


def share(p, n):
    return 100 * math.sqrt(p * (1 - p) / n)


BEST = row("acme-5", **{F: 0.6, A: 0.5, T: 0.5})                         # 0 0 0
BOLT = row("bolt-2", **{F: 0.5, A: 0.45, A + ".lower95ci": 0.43, A + ".upper95ci": 0.47,
                        T: 0.2})                                         # 10 5 30
CRUX = row("crux-1", **{F: 0.4, T: 0.4})                                 # 20 and 10, no A


def rated(*rows):
    return {one["release"]: one for one in quality.rated(list(rows), "execute")}


class QualityWeightedMean(unittest.TestCase):
    def test_quality_and_error_weigh_each_measure_by_its_weight(self):
        bolt = rated(BEST, BOLT)["bolt-2"]
        self.assertAlmostEqual(bolt["quality"], 100 - (0.4 * 10 + 0.4 * 5 + 0.2 * 30))
        self.assertAlmostEqual(bolt["se"], math.hypot(0.4 * share(0.5, 132), 0.4 * 4 / 3.92,
                                                      0.2 * share(0.2, 66)))

    def test_a_row_is_weighed_over_the_measures_it_has(self):
        crux = rated(BEST, CRUX)["crux-1"]                # one complete row: nothing estimated
        self.assertEqual(set(crux["measures"]), {F, T})
        self.assertAlmostEqual(crux["quality"], 100 - (0.4 * 20 + 0.2 * 10) / 0.6)
        self.assertAlmostEqual(crux["se"], math.hypot(0.4 * share(0.4, 132),
                                                      0.2 * share(0.4, 66)) / 0.6)


if __name__ == "__main__":
    unittest.main()
