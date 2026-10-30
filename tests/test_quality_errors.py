"""Every score `quality.rated` gives carries its standard error in points, and its quality the
root of their squares, each by its weight, over the scores they come from: an interval's width
/ 3.92, a share of a known number of tasks, Omniscience's right and wrong answers, else the
median error of the rows measured; a carried score adds the shift's error, from how unevenly
the index's evaluations changed between the two efforts, else that median; `quality.pick` never
reads any of it."""

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
        row("dune-3", "high", I=30, F=0.8, T=0.3),                       # A as T
        row("dune-3", "low", I=30, F=0.7, T=0.3),                        # A as F
        row("echo-1", "high", F=0.5, T=0.5, beta=0.4, omni=20),          # no index, A as F
        row("echo-1", "max", F=0.35, beta=0.2, omni=20)]                 # changes 20, 0: 10

SE_A = 1                                  # an interval 3.92 hundredths wide


def share(p, n):
    return 100 * math.sqrt(p * (1 - p) / n)


def found(rated, release, effort):
    return next(r for r in rated if (r["release"], r["effort"]) == (release, effort))


def errors(rated, release, effort):
    return {column: round(math.hypot(*m["parts"].values()), 6)
            for column, m in found(rated, release, effort)["measures"].items()}


def rounded(numbers):
    return {column: round(number, 6) for column, number in numbers.items()}


class QualityErrors(unittest.TestCase):
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
        # 400 behind the best, t = 10: a rating point is worth 100 ln 10 / 400 · 10 / 121;
        # AutomationBench and Arena Agent missing, as far behind
        briefcase = 25 * math.log(10) / 121
        self.assertEqual(errors(rated, "bolt-2", "high"),
                         rounded({NAMES["B"]: briefcase, NAMES["O"]: omniscience,
                                  NAMES["AB"]: briefcase, NAMES["A"]: briefcase}))

    def test_a_carried_score_adds_the_shift_s_error(self):
        self.assertEqual(errors(self.rated, "acme-5", "low"),
                         rounded({F: share(0.95, 132), T: math.hypot(share(0.5, 66), 1),
                                  A: math.hypot(SE_A, 1)}))
        self.assertAlmostEqual(found(self.rated, "acme-5", "medium")["measures"][T]["parts"][
            ("acme-5", "medium", T)], 2)
        self.assertEqual(found(self.rated, "acme-5", "low")["measures"][T]["from"], "high")
        # an evaluation counts though no row with the index has it
        self.assertAlmostEqual(found(self.rated, "echo-1", "max")["measures"][T]["parts"][
            ("echo-1", "max", T)], 10)
        # under two evaluations, the shift's error is the median of the measure's: bolt-2
        # high's of Terminal-Bench's five, acme-5 high's alone of Arena Agent's
        self.assertEqual(errors(self.rated, "bolt-2", "low"),
                         rounded({F: share(0.9, 132), T: math.hypot(share(0.4, 66), share(0.4, 66)),
                                  A: math.hypot(SE_A, SE_A)}))

    def test_a_missing_score_adds_to_the_part_of_the_score_it_counts_as(self):
        # Arena Agent as echo-1 high's FrontierCode: 0.4 + 0.4 of that one error, counted once
        self.assertAlmostEqual(found(self.rated, "echo-1", "high")["se"],
                               math.hypot(0.8 * share(0.5, 132), 0.2 * share(0.5, 66)))

    def test_pick_never_reads_an_error(self):
        high, low = found(self.rated, "acme-5", "high"), found(self.rated, "acme-5", "low")
        for error in (0.0, 9.0):
            self.assertEqual(quality.pick([high, dict(low, se=error)], 10)["effort"], "low")


if __name__ == "__main__":
    unittest.main()
