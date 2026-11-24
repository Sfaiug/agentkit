"""The tasks of the last 30 days, counted by the team that did them: the orchestrator that wrote a
task, the executor that built it and the reviewer that reviewed it, each a model at an effort.
It hides which runs are a task, and how one launched again counts once: a task is a run of kind
`task` that ended with a verdict of the work (`record.JUDGED`), together with every later run of
its change (a relaunch from its kept branch carries the change on, `runs.change`), one task of
the team of its first run, counted where that run ended.  A run of another kind (a follow-up, a
repair, a seat's own pull request) is no task, and a task rewritten under a new title is a new
one: ak keeps no link between the two.
"""

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


def by_team(now=None):
    """{"since", "until", "teams"}: the window, and per team, most tasks first, each role's
    {"name", "effort"} as its first run's row names them (the reviewer's effort its first
    review's), its tasks, those whose first run merged (`history.merged`), those any of whose
    runs merged, and the hours every run of them spent (`HOURS`), merged or not."""
    until = time.time() if now is None else now
    since = until - WINDOW
    changes = {}
    for row in sorted(history.ended_runs(0, until),
                      key=lambda row: (row.get("started_at") or 0, row["run_id"])):
        changes.setdefault(row.get("change") or row["run_id"], []).append(row)
    reviewed = history.first_review_efforts()
    teams = {}
    for runs in changes.values():
        # the whole history is read, so a task whose first run ended before the window takes
        # its relaunches out with it
        start = next((at for at, row in enumerate(runs) if row.get("kind") == "task"
                      and row["final_state"] in record.JUDGED), None)
        if start is None or runs[start]["finished_at"] < since:
            continue
        task = runs[start:]
        first = {**task[0], "reviewer_effort": reviewed.get(task[0]["run_id"])}
        roles = {role: {"name": first.get(role), "effort": first.get(f"{role}_effort")}
                 for role in ROLES}
        team = teams.setdefault(repr(roles), {**roles, "tasks": 0, "first_run": 0, "live": 0,
                                              "hours": dict.fromkeys(HOURS, 0)})
        team["tasks"] += 1
        team["first_run"] += history.merged(task[0])
        team["live"] += any(map(history.merged, task))
        for part, columns in HOURS.items():
            team["hours"][part] += sum(row.get(column) or 0
                                       for row in task for column in columns) / 3600
    return {"since": since, "until": until,
            "teams": sorted(teams.values(), key=lambda team: -team["tasks"])}
