"""Every score `quality.rated` gives carries its standard error in points, and its quality the
root of their squares, each by its weight, over the measures it averages: an interval's width /
3.92, a share of a known number of tasks, Omniscience's right and wrong answers, else the
median error of the rows measured; a carried score adds the shift's error, from how unevenly
the index's evaluations changed between the two efforts; an estimate the error it already
adds.  `quality.tie` is qualities closer than 1.645 errors of their difference, which within a
release counts only what the two efforts do not share; `quality.pick` never reads it."""

import math
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import quality

F, T, A = "aa.frontierCode20", "aa.terminalBench40", "arena.agent"     # 0.4 0.2 0.4
I, C = quality.INTEL, quality.COSTS["execute"]
ALPHA, BETA, OMNI = (quality.EVALUATION + slug + ".score"
                     for slug in ("alpha", "beta", "omniscience"))
NAMES = {"F": F, "T": T, "A": A, "I": I, "C": C, "AL": A + ".lower95ci", "AU": A + ".upper95ci",
         "AB": "aa.automationBenchPartialScore", "alpha": ALPHA, "beta": BETA, "omni": OMNI,
         "B": "aa.briefcaseBreakdown.overall.elo",
         "BL": "aa.briefcaseBreakdown.overall.lower95ci",
         "BU": "aa.briefcaseBreakdown.overall.upper95ci",
         "O": "aa.omniscience", "OA": "aa.omniscienceAccuracy",
         "OH": "aa.omniscienceHallucinationRate"}


def row(release, effort, **values):
    return {"release": release, "effort": effort,
            "values": {NAMES[key]: value for key, value in values.items()}}


ROWS = [row("acme-5", "high", I=50, F=1.0, T=0.5, A=0.5, AL=0.4804, AU=0.5196, alpha=0.5,
            omni=30, C=2.0),
        row("acme-5", "medium", I=50, F=0.96, alpha=0.48, omni=24),    # changes 2, 6: shift 2
        row("acme-5", "low", I=50, F=0.95, alpha=0.49, omni=27, C=0.5),  # changes 1, 3: shift 1
        row("bolt-2", "high", I=40, F=0.9, T=0.4, A=0.50),               # 10 10 0
        row("bolt-2", "low", I=40, F=0.9),                               # no evaluations
        row("dune-3", "high", I=30, F=0.8, T=0.3),                       # A estimated
        row("dune-3", "low", I=30, F=0.7, T=0.3),                        # A estimated
        row("echo-1", "high", F=0.5, T=0.5, beta=0.4, omni=20),          # no index
        row("echo-1", "max", F=0.35, beta=0.2, omni=20)]                 # changes 20, 0: 10

# complete rows acme-5 high (0 0 0) and bolt-2 high (10 10 0): spreads F and T (10/3)/√2, A
# (20/3)/√2
SPREAD_T, SPREAD_A = 10 / 3 / math.sqrt(2), 20 / 3 / math.sqrt(2)
SE_A = 1                                  # an interval 3.92 hundredths wide


def share(p, n):
    return 100 * math.sqrt(p * (1 - p) / n)


def found(rated, release, effort):
    return next(r for r in rated if (r["release"], r["effort"]) == (release, effort))


def errors(rated, release, effort):
    return {column: round(m["se"], 6)
            for column, m in found(rated, release, effort)["measures"].items()}


def rounded(numbers):
    return {column: round(number, 6) for column, number in numbers.items()}


def apart(a, b, error):
    """Whether `tie` says a and b differ by `error` errors' worth exactly: a tie just under
    `quality.Z` of them, none just over."""
    def at(times):
        return quality.tie(dict(a, quality=b["quality"] + quality.Z * error * times), b, "execute")
    return at(0.999) and not at(1.001)


class QualityTies(unittest.TestCase):
    def setUp(self):
        self.rated = quality.rated(ROWS, "execute")

    def test_a_measured_score_carries_its_error(self):
        self.assertEqual(errors(self.rated, "acme-5", "high"),
                         rounded({F: 0, T: share(0.5, 66), A: SE_A}))
        # bolt-2 has no interval on Arena Agent: the median of the rows measured there
        self.assertEqual(errors(self.rated, "bolt-2", "high"),
                         rounded({F: share(0.9, 132), T: share(0.4, 66), A: SE_A}))
        self.assertAlmostEqual(found(self.rated, "acme-5", "high")["se"],
                               math.hypot(0.2 * share(0.5, 66), 0.4 * SE_A))

    def test_each_board_s_interval_and_omniscience_s_answers(self):
        rows = [row("acme-5", "high", I=50, B=1000, BL=980.4, BU=1019.6, AB=0.5, A=0.5, AL=0.48,
                    AU=0.5192, O=30, OA=0.5, OH=0.4),
                row("bolt-2", "high", I=40, B=600, BL=580.4, BU=619.6, O=20)]
        rated = quality.rated(rows, "orchestrate")
        # right 0.5, wrong 0.4 of the 0.5 not right: 0.5 + 0.2 - 0.3² over 3000 questions
        omniscience = 100 * math.sqrt(0.61 / 3000)
        # at the best, a rating point is worth ln 10 / 16
        self.assertEqual(errors(rated, "acme-5", "high"),
                         rounded({NAMES["B"]: 10 * math.log(10) / 16, NAMES["A"]: 1,
                                  NAMES["O"]: omniscience, NAMES["AB"]: share(0.5, 657)}))
        # 400 behind the best, t = 10: a rating point is worth 100 ln 10 / 400 · 10 / 121
        self.assertEqual(errors(rated, "bolt-2", "high"),
                         rounded({NAMES["B"]: 25 * math.log(10) / 121, NAMES["O"]: omniscience}))

    def test_a_carried_score_adds_the_shift_s_error(self):
        self.assertEqual(errors(self.rated, "acme-5", "low"),
                         rounded({F: share(0.95, 132), T: math.hypot(share(0.5, 66), 1),
                                  A: math.hypot(SE_A, 1)}))
        self.assertAlmostEqual(found(self.rated, "acme-5", "medium")["measures"][T]["own"], 2)
        self.assertEqual(found(self.rated, "acme-5", "low")["measures"][T]["from"], "high")
        # an evaluation counts though no row with the index has it
        self.assertAlmostEqual(found(self.rated, "echo-1", "max")["measures"][T]["own"], 10)
        # under two evaluations, the shift's error is the measure's spread
        self.assertEqual(errors(self.rated, "bolt-2", "low"),
                         rounded({F: share(0.9, 132), T: math.hypot(share(0.4, 66), SPREAD_T),
                                  A: math.hypot(SE_A, SPREAD_A)}))

    def test_an_estimate_carries_the_error_it_adds(self):
        # own level's error √(2 · 50/9) / 2 = 5/3, and √(200/9 + 25/9) = 5
        self.assertAlmostEqual(found(self.rated, "dune-3", "high")["measures"][A]["se"], 5)
        self.assertAlmostEqual(found(self.rated, "dune-3", "high")["measures"][A]["own"], 5 / 3)

    def test_two_releases_count_both_errors(self):
        acme, bolt = found(self.rated, "acme-5", "high"), found(self.rated, "bolt-2", "high")
        self.assertTrue(apart(acme, bolt, math.hypot(acme["se"], bolt["se"])))

    def test_two_efforts_of_one_release_count_only_what_they_do_not_share(self):
        high, medium, low = (found(self.rated, "acme-5", effort)
                             for effort in ("high", "medium", "low"))
        # carried from the other: the shift alone; carried from one source: both shifts
        self.assertTrue(apart(low, high, math.hypot(0.4 * share(0.95, 132), 0.2 * 1, 0.4 * 1)))
        self.assertTrue(apart(high, low, math.hypot(0.4 * share(0.95, 132), 0.2 * 1, 0.4 * 1)))
        self.assertTrue(apart(low, medium, math.sqrt(0.4 ** 2 * (share(0.95, 132) ** 2
                                                                 + share(0.96, 132) ** 2)
                                                     + (0.2 ** 2 + 0.4 ** 2) * (1 + 4))))
        # two estimates: each row's own level
        dune_high, dune_low = found(self.rated, "dune-3", "high"), found(self.rated, "dune-3", "low")
        self.assertTrue(apart(dune_high, dune_low,
                              math.sqrt(0.4 ** 2 * (share(0.8, 132) ** 2
                                                    + share(0.7, 132) ** 2)
                                        + 0.2 ** 2 * 2 * share(0.3, 66) ** 2
                                        + 0.4 ** 2 * 2 * 25 / 9)))

    def test_what_they_share_never_ties_two_efforts(self):
        high, low = found(self.rated, "acme-5", "high"), found(self.rated, "acme-5", "low")
        # 2 apart: 0.88 · 1.645 = 1.45 is no tie; counted twice, 3.34 would be
        self.assertFalse(quality.tie(high, low, "execute"))
        self.assertTrue(quality.tie(high, dict(low, release="gulp-1"), "execute"))

    def test_pick_never_reads_a_tie(self):
        high, low = found(self.rated, "acme-5", "high"), found(self.rated, "acme-5", "low")
        other = dict(low, release="gulp-1")
        self.assertTrue(quality.tie(high, other, "execute"))
        self.assertEqual(quality.pick([high, other], 1), high)


if __name__ == "__main__":
    unittest.main()
