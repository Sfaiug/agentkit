"""How good a model at one effort is for each role, from board numbers that cover some efforts
and models and not others.

Every row is rated, none left out for a missing score, and a missing score never helps it: a
measure another effort of its release has is carried from there, never credited upward, and
one no effort has counts as far behind as the row's furthest-behind measure, with that one's
error.  Every score carries its standard error, each error counted once however many scores
take it, and two rows whose qualities the errors cannot tell apart are a tie (`tie`), which
never picks: a model with noisier scores would tie more often, and so win more often.  Reads
no board, config or clock: rows come in, ratings go out.
"""

import math
import statistics

from .boards import effort_rank
from .catalog import INTERVAL

INTEL = "aa.intelligenceIndex"
# How a value is behind its board's best, in points out of 100, per kind of number: (which
# value is the best, the points behind it, the points one unit of value is worth there).  A
# percent in percentage points, a share from 0 to 1 in hundredths, and a rating as how far under
# half its wins against the best would be (35 behind is 45% of wins, 5 points).
SCALES = {
    "percent": (max, lambda best, value: best - value, lambda best, value: 1),
    "share": (max, lambda best, value: 100 * (best - value), lambda best, value: 100),
    "rating": (max, lambda best, value: 100 * (0.5 - 1 / (1 + 10 ** ((best - value) / 400))),
               lambda best, value: 100 * math.log(10) / 400 * (t := 10 ** ((best - value) / 400))
               / (1 + t) ** 2),
}
# What each role is rated on: a column (board.field), its kind (`SCALES`), its weight and, in
# plain words, what it tests.  A weight gives its measure its share of the role's say, weight ×
# the spread of its points among the strongest models: orchestrate's four a quarter each
# (Briefcase's rating spreads twice its own pass rate), execute's and review's own tasks 40%
# each, and Terminal-Bench 4.0 (spread under its error) and review's Omniscience (least direct) 20%.
# Gone: GDPval-AA ranked as Briefcase does, AA-LCR's, GDP.pdf's and FrontierCode 1.1's spread
# was under their error, and Arena WebDev scores new apps, not changes to a repository.  Pinned
# by tests/test_matrix_measures.py, so a change to it is a visible test change.
ROLES = {
    "orchestrate": (("aa.automationBenchPartialScore", "share", 0.35,
                     "work across apps under a policy, a task that breaks a rule scoring nothing"),
                    ("arena.agent", "share", 0.3, "agent sessions people judged done well"),
                    # the index, not its hallucination rate: the rate's best was a model that
                    # answers nothing, so it rewarded ignorance
                    ("aa.omniscience", "percent", 0.2,
                     "right answers less wrong guesses, an admitted unknown counting neither"),
                    ("aa.briefcaseBreakdown.overall.elo", "rating", 0.15,
                     "long business projects of hundreds of turns, delivering files")),
    "execute": (("aa.frontierCode20", "share", 0.4,
                 "the hardest coding problems, each solved or not"),
                ("arena.agent", "share", 0.4, "agent sessions people judged done well"),
                ("aa.terminalBench40", "share", 0.2,
                 "hard terminal tasks that pass only when all their tests do")),
    "review": (("aa.deepsecBench", "share", 0.4,
                "reviewing files for bugs, each report judged a true or a false finding"),
               ("aa.frontierCode20", "share", 0.4,
                "the hardest coding problems, each solved or not"),
               ("aa.omniscience", "percent", 0.2,
                "right answers less wrong guesses, an admitted unknown counting neither")),
}
# What a task of each role costs a row, in dollars: the Artificial Analysis evaluation nearest
# the role's work, review's the one whose cost per effort tracks DeepSec Bench's best (0.95).
# Pinned beside `ROLES`.
COSTS = {
    "orchestrate": "aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask",
    "execute": "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask",
    "review": "aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask",
}
# A measure's 95% interval, (lower, upper), where it is not `<column>` + `INTERVAL` (Arena's)
INTERVALS = {"aa.briefcaseBreakdown.overall.elo": ("aa.briefcaseBreakdown.overall.lower95ci",
                                                   "aa.briefcaseBreakdown.overall.upper95ci")}
# How many tasks a share without an interval is of: as Artificial Analysis's methodology pages
# say, DeepSec Bench's as its authors' write-up does
TASKS = {"aa.automationBenchPartialScore": 657, "aa.frontierCode20": 132, "aa.terminalBench40": 66,
         "aa.deepsecBench": 231}
# Omniscience's questions, each +1 right, -1 wrong and 0 declined
OMNISCIENCE = ("aa.omniscience", "aa.omniscienceAccuracy", "aa.omniscienceHallucinationRate", 3000)
# The evaluations of the Intelligence Index, each `<slug>`'s score at `EVALUATION` + `.score`,
# and the kind of those that are not shares: what an effort's change in them says of its error
EVALUATION = "aa.intelligenceIndexEvaluations."
EVALUATION_KINDS = {"aa-briefcase": "rating", "omniscience": "percent"}
Z = 1.645       # qualities closer than Z errors of their difference are inside its 90% interval


def interval(column):
    """The columns of a measure's 95% interval, (lower, upper)."""
    return INTERVALS.get(column, tuple(column + end for end in INTERVAL))


def reads(column):
    """The columns beside its own a measure's error cannot be had without (`_error`): its
    interval, but none for a share of `TASKS` and Omniscience's accuracy and hallucination rate
    for it, as Artificial Analysis publishes no interval for these: naming one would read the
    board again at every new build."""
    if column in TASKS:
        return ()
    return OMNISCIENCE[1:3] if column == OMNISCIENCE[0] else interval(column)


def _error(values, column, kind, best):
    """A measured value's standard error in points, None when its row lacks what it needs."""
    lower, upper = (values.get(name) for name in interval(column))
    if lower is not None and upper is not None:
        return (upper - lower) / 3.92 * SCALES[kind][2](best, values[column])
    if column in TASKS:
        share = values[column]
        return 100 * math.sqrt(share * (1 - share) / TASKS[column])
    index, accuracy, rate, questions = OMNISCIENCE
    if column == index and accuracy in values and rate in values:
        right = values[accuracy]
        wrong = values[rate] * (1 - right)
        return 100 * math.sqrt((right + wrong - (right - wrong) ** 2) / questions)
    return None


def rated(rows, role):
    """Each of `rows` ({"release", "effort", "values": {column: number}}) that has at least two
    of `role`'s measures measured or carried, as itself with its "quality" (100 less its
    weighted mean points behind the best over the role's measures a row of the index has), its
    error's "parts" by the score each comes from ({(release, effort, column): points of
    quality}) and "se", their root of squares, its "cost" (`COSTS` at its own effort, else
    None) and per measure {"points", "how", "parts"}: measured, carried (with the effort it is
    "from", its own part the shift's error) or missing (as its furthest-behind measure)."""
    measures = ROLES[role]
    kinds = {column: kind for column, kind, _, _ in measures}
    weights = {column: weight for column, _, weight, _ in measures}
    # each evaluation's kind and best, of every row scored on it: only its changes count
    evaluations = {column: (kind, SCALES[kind][0](row["values"][column] for row in rows
                                                  if column in row["values"]))
                   for column in {column for row in rows for column in row["values"]
                                  if column.startswith(EVALUATION) and column.endswith(".score")}
                   for kind in [EVALUATION_KINDS.get(column[len(EVALUATION):-len(".score")],
                                                     "share")]}
    indexed = [row for row in rows if INTEL in row["values"]]
    best = {column: SCALES[kind][0](found) for column, kind in kinds.items()
            for found in [[row["values"][column] for row in indexed if column in row["values"]]]
            if found}
    points_of = {id(row): {column: SCALES[kind][1](best[column], row["values"][column])
                           for column, kind in kinds.items()
                           if column in row["values"] and column in best} for row in rows}
    errors_of = {id(row): {column: _error(row["values"], column, kinds[column], best[column])
                           for column in points} for row in rows for points in [points_of[id(row)]]}
    typical = {column: statistics.median(found) for column in kinds
               for found in [[errors[column] for errors in errors_of.values()
                              if errors.get(column) is not None]] if found}

    def measured(row):
        return points_of[id(row)]

    def error(row, column):
        found = errors_of[id(row)][column]
        return typical.get(column, 0.0) if found is None else found

    def score(row, column):
        return row["release"], row["effort"], column

    def shift(row, source, column):
        # how far the measure's change between two efforts can be off, from how unevenly the
        # index's evaluations changed between them
        changes = [SCALES[kind][1](top, row["values"][name])
                   - SCALES[kind][1](top, source["values"][name])
                   for name, (kind, top) in evaluations.items()
                   if name in row["values"] and name in source["values"]]
        if len(changes) < 2:
            return typical.get(column, 0.0)
        return statistics.stdev(changes) / math.sqrt(len(changes))

    def carried(row, column):
        # a higher effort's points plus what the index loses down to this one; else a lower
        # effort's as they are, as a lower effort is never better
        others = [other for other in rows if other["release"] == row["release"]
                  and other is not row and column in measured(other)]
        above = [other for other in others if effort_rank(other["effort"]) > effort_rank(row["effort"])]
        nearest = min(above, key=lambda other: effort_rank(other["effort"]), default=None)
        if nearest and INTEL in nearest["values"] and INTEL in row["values"]:
            drop = nearest["values"][INTEL] - row["values"][INTEL]
            value = measured(nearest)[column] + max(0.0, drop)
        else:
            below = [other for other in others if effort_rank(other["effort"]) < effort_rank(row["effort"])]
            nearest = max(below, key=lambda other: effort_rank(other["effort"]), default=None)
            if not nearest:
                return None
            value = measured(nearest)[column]
        return {"points": value, "how": "carried", "from": nearest["effort"],
                "parts": {score(nearest, column): error(nearest, column),
                          score(row, column): shift(row, nearest, column)}}

    out = []
    for row in rows:
        points = {column: {"points": value, "how": "measured",
                           "parts": {score(row, column): error(row, column)}}
                  for column, value in measured(row).items()}
        for column in kinds:
            found = None if column in points else carried(row, column)
            if found:
                points[column] = found
        if len(points) < 2:
            continue
        worst = max(points.values(), key=lambda one: one["points"])
        for column in best:
            points.setdefault(column, {"points": worst["points"], "how": "missing",
                                       "parts": worst["parts"]})
        total = sum(weights[column] for column in points)
        parts = {}
        for column, one in points.items():
            for source, part in one["parts"].items():
                parts[source] = parts.get(source, 0.0) + weights[column] * part / total
        out.append(dict(row, measures=points, cost=row["values"].get(COSTS[role]),
                        quality=100 - sum(weights[column] * one["points"]
                                          for column, one in points.items()) / total,
                        parts=parts, se=math.hypot(*parts.values())))
    return out


def tie(a, b):
    """Whether two rows `rated` gave for one role are ones the boards cannot tell apart: their
    qualities differ by less than `Z` errors of their difference, a part of their errors both
    hold (what one carried from the other, or both from a third) counting by how much more of
    it one holds."""
    apart = math.hypot(*(a["parts"].get(source, 0.0) - b["parts"].get(source, 0.0)
                         for source in a["parts"].keys() | b["parts"].keys()))
    return abs(a["quality"] - b["quality"]) < Z * apart


def pick(rated, within):
    """The cheapest of `rated` with a cost whose quality is within `within` of the best, the
    higher quality on an equal cost; None when no row has a cost."""
    top = max((row["quality"] for row in rated), default=None)
    near = [row for row in rated if row["cost"] is not None and row["quality"] >= top - within]
    return min(near, key=lambda row: (row["cost"], -row["quality"]), default=None)
