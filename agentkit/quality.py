"""How good a model at one effort is for each role, from board numbers that cover some efforts
and models and not others.

Every row is rated, none left out for a missing score, and a missing score never helps it: a
measure another effort of its release has is carried from there, never credited upward, and
one no effort has is estimated from the rows measured on all of the role's measures, plus one
standard error of that estimate.  Every score carries its standard error, and two rows whose
qualities the errors cannot tell apart are a tie (`tie`), which never picks: a model with
noisier scores would tie more often, and so win more often.  Reads no board, config or clock:
rows come in, ratings go out.
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
# What each role is rated on: a column (board.field), its kind (`SCALES`) and, in plain words,
# what it tests.  Pinned by tests/test_matrix_measures.py, so a change to it is a visible test change.
ROLES = {
    "orchestrate": (("aa.briefcaseBreakdown.overall.elo", "rating",
                     "long business projects of hundreds of turns, delivering files"),
                    ("aa.gdpval", "rating",
                     "work products of 44 occupations, judged against each other in pairs"),
                    ("arena.agent", "share", "agent sessions people judged done well"),
                    # the index, not its hallucination rate: the rate's best was a model that
                    # answers nothing, so it rewarded ignorance
                    ("aa.omniscience", "percent",
                     "right answers less wrong guesses, an admitted unknown counting neither"),
                    ("aa.lcr", "share", "reasoning across documents of 100,000 words and more")),
    "execute": (("aa.frontierCode", "share", "the hardest coding problems, each solved or not"),
                ("aa.terminalBench40", "share",
                 "hard terminal tasks that pass only when all their tests do"),
                ("arena.webdev", "rating", "apps people pick between two built alike")),
    "review": (("aa.deepsecBench", "share",
                "reviewing files for bugs, each report judged a true or a false finding"),
               ("aa.omniscience", "percent",
                "right answers less wrong guesses, an admitted unknown counting neither"),
               ("aa.gdpPdfAllPass", "share", "documents it writes that pass every check"),
               ("aa.frontierCode", "share", "the hardest coding problems, each solved or not"),
               ("aa.lcr", "share", "reasoning across documents of 100,000 words and more")),
}
# What a task of each role costs a row, in dollars: the Artificial Analysis evaluation nearest
# the role's work.  Pinned beside `ROLES`.
COSTS = {
    "orchestrate": "aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask",
    "execute": "aa.intelligenceIndexEvaluations.terminalbench-4-0.costPerTask",
    "review": "aa.intelligenceIndexEvaluations.gdp-pdf.costPerTask",
}
# A measure's 95% interval, (lower, upper), where it is not `<column>` + `INTERVAL` (Arena's)
INTERVALS = {"aa.briefcaseBreakdown.overall.elo": ("aa.briefcaseBreakdown.overall.lower95ci",
                                                   "aa.briefcaseBreakdown.overall.upper95ci"),
             "aa.gdpval": ("aa.gdpvalInterval.lower", "aa.gdpvalInterval.upper")}
# How many tasks a share without an interval is of: as Artificial Analysis's methodology pages
# say, DeepSec Bench's as its authors' write-up does
TASKS = {"aa.lcr": 100, "aa.frontierCode": 100, "aa.gdpPdfAllPass": 100, "aa.terminalBench40": 66,
         "aa.deepsecBench": 231}
# Omniscience's questions, each +1 right, -1 wrong and 0 declined
OMNISCIENCE = ("aa.omniscience", "aa.omniscienceAccuracy", "aa.omniscienceHallucinationRate", 6000)
# The evaluations of the Intelligence Index, each `<slug>`'s score at `EVALUATION` + `.score`,
# and the kind of those that are not shares: what an effort's change in them says of its error
EVALUATION = "aa.intelligenceIndexEvaluations."
EVALUATION_KINDS = {"aa-briefcase": "rating", "gdpval-aa": "rating", "omniscience": "percent"}
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
    of `role`'s measures measured or carried, as itself with its "quality" (100 less its mean
    points behind the best over the role's measures) and that quality's standard error "se",
    its "cost" (`COSTS` at its own effort, else None) and per measure {"points", "how", "se"}:
    measured, carried (with the effort it is "from" and the error of the shift, its "own") or
    estimated (with the error of the row's own level, its "own")."""
    measures = ROLES[role]
    kinds = {column: kind for column, kind, _ in measures}
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

    def shift(row, source, column):
        # how far the measure's change between two efforts can be off, from how unevenly the
        # index's evaluations changed between them
        changes = [SCALES[kind][1](top, row["values"][name])
                   - SCALES[kind][1](top, source["values"][name])
                   for name, (kind, top) in evaluations.items()
                   if name in row["values"] and name in source["values"]]
        if len(changes) < 2:
            return shape.get(column, (0.0, 0.0))[1]
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
        own = shift(row, nearest, column)
        return {"points": value, "how": "carried", "from": nearest["effort"], "own": own,
                "se": math.hypot(error(nearest, column), own)}

    # per measure, (offset, spread) of how its points stand from a row's mean, over the rows
    # measured on every measure
    complete = [points for row in indexed for points in [measured(row)]
                if len(points) == len(measures)]
    gaps = {column: [points[column] - statistics.mean(points.values()) for points in complete]
            for column, _, _ in measures}
    shape = ({column: (statistics.mean(found), statistics.stdev(found))
              for column, found in gaps.items()} if len(complete) >= 2 else {})

    out = []
    for row in rows:
        points = {column: {"points": value, "how": "measured", "se": error(row, column)}
                  for column, value in measured(row).items()}
        for column in kinds:
            found = None if column in points else carried(row, column)
            if found:
                points[column] = found
        if len(points) < 2:
            continue
        own = [column for column in points if column in shape]
        if own:
            level = statistics.mean(points[column]["points"] - shape[column][0] for column in own)
            own_error = math.sqrt(sum(shape[column][1] ** 2 for column in own)) / len(own)
            for column, _, _ in measures:
                if column not in points and column in shape:
                    offset, spread = shape[column]
                    se = math.hypot(spread, own_error)
                    points[column] = {"points": level + offset + se, "how": "estimated",
                                      "se": se, "own": own_error}
        found = points.values()
        out.append(dict(row, measures=points, cost=row["values"].get(COSTS[role]),
                        quality=100 - statistics.mean(one["points"] for one in found),
                        se=math.sqrt(sum(one["se"] ** 2 for one in found)) / len(found)))
    return out


def tie(a, b, role):
    """Whether two rows `rated` gave for `role` are ones the boards cannot tell apart: their
    qualities differ by less than `Z` errors of their difference."""
    if a["release"] != b["release"]:
        apart = math.hypot(a["se"], b["se"])
    else:
        columns = [column for column, _, _ in ROLES[role]
                   if column in a["measures"] or column in b["measures"]]
        apart = math.sqrt(sum(_unshared(a, b, column) for column in columns)) / len(columns)
    return abs(a["quality"] - b["quality"]) < Z * apart


def _unshared(a, b, column):
    """The squared error of `column`'s difference between two efforts of one release, counting
    only what one did not take from the other or from where the other did: what one carried
    from the other is off only by the shift, and two estimates only by each row's own level."""
    one, other = a["measures"].get(column, {}), b["measures"].get(column, {})
    if "from" in one and one["from"] == b["effort"]:
        return one["own"] ** 2
    if "from" in other and other["from"] == a["effort"]:
        return other["own"] ** 2
    if "own" in one and one["how"] == other.get("how") and one.get("from") == other.get("from"):
        return one["own"] ** 2 + other["own"] ** 2
    return one.get("se", 0.0) ** 2 + other.get("se", 0.0) ** 2


def pick(rated, within):
    """The cheapest of `rated` with a cost whose quality is within `within` of the best, the
    higher quality on an equal cost; None when no row has a cost."""
    top = max((row["quality"] for row in rated), default=None)
    near = [row for row in rated if row["cost"] is not None and row["quality"] >= top - within]
    return min(near, key=lambda row: (row["cost"], -row["quality"]), default=None)
