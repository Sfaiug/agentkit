"""How good a model at one effort is for each role, from board numbers that cover some efforts
and models and not others.

Every row is rated, none left out for a missing score, and a missing score never helps it: a
measure another effort of its release has is carried from there, never credited upward, and
one no effort has is estimated from the rows measured on all of the role's measures, plus one
standard error of that estimate.  Reads no board, config or clock: rows come in, ratings go out.
"""

import math
import statistics

from .boards import effort_rank

INTEL = "aa.intelligenceIndex"
# How a value is behind its board's best, in points out of 100, per kind of number: (which
# value is the best, the points behind it).  A percent in percentage points, a share from 0 to 1
# in hundredths, and a rating as how far under half its wins against the best would be (35
# behind is 45% of wins, 5 points).
SCALES = {
    "percent": (max, lambda best, value: best - value),
    "share": (max, lambda best, value: 100 * (best - value)),
    "rating": (max, lambda best, value: 100 * (0.5 - 1 / (1 + 10 ** ((best - value) / 400)))),
}
# What each role is rated on: a column (board.field), its kind (`SCALES`) and, in plain words,
# what it tests.  Pinned by tests/test_matrix_measures.py: it changes only with the owner's yes.
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


def rated(rows, role):
    """Each of `rows` ({"release", "effort", "values": {column: number}}) that has at least two
    of `role`'s measures measured or carried, as itself with its "quality" (100 less its mean
    points behind the best over the role's measures), its "cost" (`COSTS` at its own effort,
    else None) and per measure {"points", "how"}: measured, carried or estimated."""
    measures = ROLES[role]
    indexed = [row for row in rows if INTEL in row["values"]]
    best = {column: SCALES[kind][0](found) for column, kind, _ in measures
            for found in [[row["values"][column] for row in indexed if column in row["values"]]]
            if found}
    points_of = {id(row): {column: SCALES[kind][1](best[column], row["values"][column])
                           for column, kind, _ in measures
                           if column in row["values"] and column in best} for row in rows}

    def measured(row):
        return points_of[id(row)]

    def carried(row, column):
        # a higher effort's points plus what the index loses down to this one; else a lower
        # effort's as they are, as a lower effort is never better
        others = [other for other in rows if other["release"] == row["release"]
                  and other is not row and column in measured(other)]
        above = [other for other in others if effort_rank(other["effort"]) > effort_rank(row["effort"])]
        nearest = min(above, key=lambda other: effort_rank(other["effort"]), default=None)
        if nearest and INTEL in nearest["values"] and INTEL in row["values"]:
            drop = nearest["values"][INTEL] - row["values"][INTEL]
            return measured(nearest)[column] + max(0.0, drop)
        below = [other for other in others if effort_rank(other["effort"]) < effort_rank(row["effort"])]
        nearest = max(below, key=lambda other: effort_rank(other["effort"]), default=None)
        return measured(nearest)[column] if nearest else None

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
        points = {column: {"points": value, "how": "measured"}
                  for column, value in measured(row).items()}
        for column, _, _ in measures:
            value = None if column in points else carried(row, column)
            if value is not None:
                points[column] = {"points": value, "how": "carried"}
        if len(points) < 2:
            continue
        own = [column for column in points if column in shape]
        if own:
            level = statistics.mean(points[column]["points"] - shape[column][0] for column in own)
            error = math.sqrt(sum(shape[column][1] ** 2 for column in own)) / len(own)
            for column, _, _ in measures:
                if column not in points and column in shape:
                    offset, spread = shape[column]
                    points[column] = {"points": level + offset + math.hypot(spread, error),
                                      "how": "estimated"}
        out.append(dict(row, measures=points, cost=row["values"].get(COSTS[role]),
                        quality=100 - statistics.mean(found["points"]
                                                      for found in points.values())))
    return out


def pick(rated, within):
    """The cheapest of `rated` with a cost whose quality is within `within` of the best, the
    higher quality on an equal cost; None when no row has a cost."""
    top = max((row["quality"] for row in rated), default=None)
    near = [row for row in rated if row["cost"] is not None and row["quality"] >= top - within]
    return min(near, key=lambda row: (row["cost"], -row["quality"]), default=None)
