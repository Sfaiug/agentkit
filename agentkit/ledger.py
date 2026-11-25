"""The tasks of the last 30 days, counted by the team that did them (the orchestrator that wrote a
task, the executor that built it and the reviewer that reviewed it, each a model at an effort) and
by their size, in one pass over one reading of the history: a task with a size is counted both
ways.  It hides which runs are a task, and how one launched again counts once: a task is a run of
kind `task` that ended with a verdict of the work (`record.JUDGED`), together with every later run
of its change, however it ended or while it runs (a relaunch from its kept branch carries the
change on, `runs.change`), one task of the team of its first run, counted where that run ended.
A run of another kind (a follow-up, a repair, a seat's own pull request) is no task, and a task
rewritten under a new title is a new one: ak keeps no link between the two.
"""

import math
import time

from . import history, record

# A release is judged on its recent work, done under the limits in force now; an older run stays
# in the history, outside every count here.
WINDOW = 30 * 86400
ROLES = ("orchestrator", "executor", "reviewer")
# What a team's tasks spent, in hours: each the sum of these columns over every run of them
HOURS = {"build": ("executor_seconds",), "review": ("reviewer_seconds",),
         "checks": ("done_when_seconds",),
         "waiting": tuple(f"{wait}_wait_seconds" for wait in history.WAITS)}
# The lines a row of the tasks by size spans: the owner sets a task's most lines by the hundred
SIZE = 100


def _whole(value, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _round_order(row):
    """SQLite `ORDER BY round` order: NULL before numbers before text before blobs."""
    round = row.get("round")
    if round is None:
        return (0, 0)
    if isinstance(round, (int, float)) and not isinstance(round, bool):
        return (1, round)
    return (2 if isinstance(round, str) else 3, round)


def counted():
    """{"since", "until", "teams", "sizes"}: the window; per team, most tasks first, each role's
    {"name", "effort"} as its first run's row names them (the reviewer's effort its first
    review's), its tasks, those whose first run merged (`history.merged`), those any of whose
    runs merged (`live`), those whose first run's first review (first written of its lowest round)
    was round 1 with verdict `PASS` (`first_pass`), the `reviews` rows with a round above zero
    over every run of them (`reviews`), their non-negative `blocking` summed (`issues`), and the
    hours every run of them spent (`HOURS`), however it ended or while it runs; and per `SIZE`
    lines, smallest first, the same of the tasks whose size is at most `upto` and over `upto`
    less SIZE, `lines_live` the sizes of those live summed."""
    until = time.time()
    since = until - WINDOW
    changes = {}
    for row in history.changes_since(since):
        changes.setdefault(row.get("change") or row["run_id"], []).append(row)
    reviewed = history.reviews()
    teams, sizes = {}, {}
    for change, runs in changes.items():
        # the run a change is named for began it, whatever start a relaunch ties with; a change
        # comes whole, so a task whose first run ended outside the window, or recorded no end,
        # takes its relaunches out with it
        runs.sort(key=lambda row: (row["run_id"] != change, row.get("started_at") or 0,
                                   row["run_id"]))
        start = next((at for at, row in enumerate(runs) if row.get("kind") == "task"
                      and row["final_state"] in record.JUDGED), None)
        if start is None or not since <= (runs[start]["finished_at"] or 0) <= until:
            continue
        task = runs[start:]
        first_reviews = reviewed.get(task[0]["run_id"], ())
        by_run = [[row for row in reviewed.get(run["run_id"], ()) if _whole(row.get("round"), 1)]
                  for run in task]
        first_effort = min(first_reviews, key=_round_order, default=None)
        first_round = min(by_run[0], key=_round_order, default=None)
        first = {**task[0], "reviewer_effort": first_effort and first_effort.get("effort")}
        roles = {role: {"name": first.get(role), "effort": first.get(f"{role}_effort")}
                 for role in ROLES}
        team = teams.setdefault(repr(roles), {
            **roles, "tasks": 0, "first_run": 0, "live": 0, "first_pass": 0, "reviews": 0,
            "issues": 0, "hours": dict.fromkeys(HOURS, 0)})
        team["first_run"] += history.merged(task[0])
        team["first_pass"] += bool(first_round and first_round["round"] == 1
                                   and first_round.get("verdict") == "PASS")
        team["reviews"] += sum(map(len, by_run))
        team["issues"] += sum(row["blocking"] for rows in by_run for row in rows
                              if _whole(row.get("blocking")))
        live = any(map(history.merged, task))
        counts = [team]
        # its size: the most lines a first review of one of its runs read; none kept, no size
        size = max((row["first_review_lines"] for row in task
                    if row.get("first_review_lines") is not None), default=None)
        if size is not None:
            counts.append(sizes.setdefault(max(1, math.ceil(size / SIZE)) * SIZE, {
                "tasks": 0, "live": 0, "lines_live": 0, "hours": dict.fromkeys(HOURS, 0)}))
            counts[-1]["lines_live"] += size * live
        for count in counts:
            count["tasks"] += 1
            count["live"] += live
            for part, columns in HOURS.items():
                count["hours"][part] += sum(row.get(column) or 0
                                            for row in task for column in columns) / 3600
    return {"since": since, "until": until,
            "teams": sorted(teams.values(), key=lambda team: -team["tasks"]),
            "sizes": [{"upto": upto, **count} for upto, count in sorted(sizes.items())]}
