"""The tasks of the last 30 days, counted by the team that did them (the orchestrator that wrote a
task, the executor that built it and the reviewer that reviewed it, each a model at an effort), by
their size, by the issues their first review found and by the review rounds they went through, in
one pass over one reading of the history: a task is counted in each view it has a value for.  It
hides which runs are a task, and how one launched again counts once: a task is a run of kind
`task` that ended with a verdict of the work (`record.JUDGED`), together with every later run of
its change, however it ended or while it runs (a relaunch from its kept branch carries the change
on, `runs.change`), one task of the team of its first run, counted where that run ended.
A run of another kind (a follow-up, a repair, a seat's own pull request) is no task, and a task
rewritten under a new title is a new one: ak keeps no link between the two.
"""

from fractions import Fraction
import time

from . import history, record

# A release is judged on its recent work, done under the limits in force now; an older run stays
# in the history, outside every count here.
WINDOW = 30 * 86400
ROLES = ("orchestrator", "executor", "reviewer")
USAGE_ROLES = ("executor", "reviewer")
# What a team's tasks spent, in hours: each the sum of these columns over every run of them
HOURS = {"build": ("executor_seconds",), "review": ("reviewer_seconds",),
         "checks": ("done_when_seconds",),
         "waiting": tuple(f"{wait}_wait_seconds" for wait in history.WAITS)}
# The lines a row of the tasks by size spans: the owner sets a task's most lines by the hundred
SIZE = 100


def _whole(value, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _add_usage(to, used):
    """Add `used`, `week_meters.run_usage`'s `(points, unrated)`, into one role's
    `{"points": {provider: {plan: Fraction}}, "unrated": tokens}`."""
    points, unrated = used
    to["unrated"] += unrated
    for (provider, plan), value in points.items():
        if value:
            plans = to["points"].setdefault(provider, {})
            plans[plan] = plans.get(plan, Fraction(0)) + value


def _unused():
    """A row's `usage`, before its tasks add theirs."""
    return {role: {"points": {}, "unrated": 0} for role in (*USAGE_ROLES, "orchestrator")}


def _split(used, weights):
    """`used`, `(points, unrated)` as `_add_usage` takes it, in parts by `weights`: points exact;
    unrated tokens each part's exact share rounded down, then one more to each part losing most
    by that, the earlier of those losing as much, until they sum to `unrated` (largest remainder):
    whole, every part is under a token from its exact share, and a whole share kept."""
    points, unrated = used
    whole = sum(weights)
    tokens = [unrated * weight // whole for weight in weights]
    for at in sorted(range(len(weights)),
                     key=lambda at: -(unrated * weights[at] % whole))[:unrated - sum(tokens)]:
        tokens[at] += 1
    return [({plan: value * Fraction(weight, whole) for plan, value in points.items()}, part)
            for weight, part in zip(weights, tokens)]


def sum_usage(by_run):
    """{role: {"points": {provider: {plan: Fraction}}, "unrated": tokens}} for `executor` and
    `reviewer`, summed exactly from `by_run`, `week_meters.run_usage`'s; a plan with none not
    named."""
    out = {role: {"points": {}, "unrated": 0} for role in USAGE_ROLES}
    for (_, role), used in by_run.items():
        if role in out:
            _add_usage(out[role], used)
    return out


def sum_seats(by_seat):
    """([{"name", "effort", "points", "unrated"}], {"points", "unrated"}) from `by_seat`,
    `week_meters.seat_usage`'s: one entry per `(orchestrator, effort)`, most points first (all
    plans summed), then name and effort, null last, and their exact sum."""
    total = {"points": {}, "unrated": 0}
    rows = []
    for (name, effort), used in sorted(
            by_seat.items(),
            key=lambda item: (-sum(item[1][0].values(), Fraction(0)),
                              item[0][0] is None, item[0][0] or "",
                              item[0][1] is None, item[0][1] or "")):
        row = {"name": name, "effort": effort, "points": {}, "unrated": 0}
        _add_usage(row, used)
        _add_usage(total, used)
        rows.append(row)
    return rows, total


def recorded(effort):
    """A team's effort, None where it names none or a blank one."""
    return effort if isinstance(effort, str) and effort.strip() else None


def _seat(team):
    """The key of `week_meters.seat_usage` that `team`'s orchestrator's own turns are kept under:
    neither its name nor its effort where it has none recorded (`seat_tokens.orchestrating`)."""
    orchestrator = team["orchestrator"]
    effort = recorded(orchestrator["effort"])
    return (None, None) if effort is None else (orchestrator["name"], effort)


def counted(usage=None, seats=None, *, until=None):
    """{"since", "until", "teams", "sizes", "first_issues", "rounds", "usage", "seats"}: the
    window; per team, most tasks first, each role's {"name", "effort"} as its first run's row
    names them (the reviewer's effort its first review's), its tasks, those whose first run
    merged (`history.merged`), those any of whose runs merged (`live`), those whose first run's
    first review (first written of its lowest round) was round 1 with verdict `PASS`
    (`first_pass`), the `reviews` rows with a round above zero over every run of them
    (`reviews`), their non-negative `blocking` summed (`issues`), the `findings` rows of those
    runs whose `outcome` is a text (`disputed`) and of them those `conceded` or `dropped`
    (`taken_back`), the hours every run of them spent (`HOURS`), and the `usage`
    (`week_meters.run_usage`'s) every run of them took by role, summed exactly, however it ended
    or while it runs, and of its orchestrator's entry of `seats` (`_seat`) its tasks over those
    of every team of that entry (`orchestrator`, `unrated` rounded half to even); per `SIZE`
    lines, smallest first, the same of the tasks whose size is at most `upto` and over `upto`
    less SIZE, `lines_live` the sizes of those live summed, `orchestrator` of each team's its
    tasks there over the team's (`_split`, its sizes smallest first, then those of none); per
    number of `blocking` issues its first run's first review found, fewest first, the same of the
    tasks whose first review holds a non-negative whole `blocking`, with `first_run` and no
    `lines_live`, `orchestrator` split the same way; per highest round among the reviews
    `reviews` counts of a task, fewest first, the same of the tasks with one; `usage` over every
    run (`executor`, `reviewer`) and seat (`orchestrator`); and `seats`, per orchestrator and
    effort (`sum_seats`)."""
    until = time.time() if until is None else until
    since = until - WINDOW
    usage = usage or {}
    changes = {}
    for row in history.changes_since(since):
        changes.setdefault(row.get("change") or row["run_id"], []).append(row)
    reviewed, first_efforts, disputes = history._reviews_read()
    # sized, by_issues, by_rounds: {team: {bucket: that team's tasks in that bucket}}
    teams, sizes, sized, first_issues, by_issues, rounds, by_rounds = {}, {}, {}, {}, {}, {}, {}
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
        by_run = [[row for row in reviewed.get(run["run_id"], ()) if _whole(row.get("round"), 1)]
                  for run in task]
        first_review = min(by_run[0], key=lambda row: row["round"], default=None)
        first = {**task[0], "reviewer_effort": first_efforts.get(task[0]["run_id"])}
        roles = {role: {"name": first.get(role), "effort": first.get(f"{role}_effort")}
                 for role in ROLES}
        key = repr(roles)
        team = teams.setdefault(key, {
            **roles, "tasks": 0, "first_run": 0, "live": 0, "first_pass": 0, "reviews": 0,
            "issues": 0, "disputed": 0, "taken_back": 0, "hours": dict.fromkeys(HOURS, 0),
            "usage": _unused()})
        first_merged = history.merged(task[0])
        team["first_run"] += first_merged
        team["first_pass"] += bool(first_review and first_review["round"] == 1
                                   and first_review.get("verdict") == "PASS")
        team["reviews"] += sum(map(len, by_run))
        team["issues"] += sum(row["blocking"] for rows in by_run for row in rows
                              if _whole(row.get("blocking")))
        for row in task:
            disputed, taken_back = disputes.get(row["run_id"], (0, 0))
            team["disputed"] += disputed
            team["taken_back"] += taken_back
        live = first_merged or any(map(history.merged, task[1:]))
        counts = [team]
        # its size: the most lines a first review of one of its runs read; none kept, no size
        size = max((row["first_review_lines"] for row in task
                    if row.get("first_review_lines") is not None), default=None)
        if size is not None:
            upto = max(1, (size + SIZE - 1) // SIZE) * SIZE
            counts.append(sizes.setdefault(upto, {
                "tasks": 0, "live": 0, "lines_live": 0, "hours": dict.fromkeys(HOURS, 0),
                "usage": _unused()}))
            counts[-1]["lines_live"] += size * live
            of_team = sized.setdefault(key, {})
            of_team[upto] = of_team.get(upto, 0) + 1
        issues = first_review and first_review.get("blocking")
        # over every run of it, not its first alone: a row holds what going that far took
        went = max((row["round"] for rows in by_run for row in rows), default=None)
        for rows, grouped, bucket in ((first_issues, by_issues, issues), (rounds, by_rounds, went)):
            if _whole(bucket):
                counts.append(rows.setdefault(bucket, {
                    "tasks": 0, "first_run": 0, "live": 0, "hours": dict.fromkeys(HOURS, 0),
                    "usage": _unused()}))
                counts[-1]["first_run"] += first_merged
                of_team = grouped.setdefault(key, {})
                of_team[bucket] = of_team.get(bucket, 0) + 1
        for count in counts:
            count["tasks"] += 1
            count["live"] += live
            for part, columns in HOURS.items():
                count["hours"][part] += sum(row.get(column) or 0
                                            for row in task for column in columns) / 3600
            for row in task:
                for role in USAGE_ROLES:
                    if (used := usage.get((row["run_id"], role))) is not None:
                        _add_usage(count["usage"][role], used)
    seats = seats or {}
    # a seat's turn belongs to no task, so an orchestrator's divides evenly over the tasks it
    # wrote, and a team's over its sizes, first-review issue counts and rounds
    wrote = {}
    for team in teams.values():
        wrote[_seat(team)] = wrote.get(_seat(team), 0) + team["tasks"]
    for key, team in teams.items():
        points, unrated = seats.get(_seat(team), ({}, 0))
        share = Fraction(team["tasks"], wrote[_seat(team)])
        used = ({plan: value * share for plan, value in points.items()}, round(unrated * share))
        _add_usage(team["usage"]["orchestrator"], used)
        # its tasks in no row a part last, which no row takes
        for rows, grouped in ((sizes, sized), (first_issues, by_issues), (rounds, by_rounds)):
            of_team = sorted(grouped.get(key, {}).items())
            for (bucket, _), part in zip(of_team, _split(used, [
                    *(tasks for _, tasks in of_team),
                    team["tasks"] - sum(tasks for _, tasks in of_team)])):
                _add_usage(rows[bucket]["usage"]["orchestrator"], part)
    seat_rows, orch_usage = sum_seats(seats)
    return {"since": since, "until": until,
            "teams": sorted(teams.values(), key=lambda team: -team["tasks"]),
            "sizes": [{"upto": upto, **count} for upto, count in sorted(sizes.items())],
            "first_issues": [{"issues": issues, **count}
                             for issues, count in sorted(first_issues.items())],
            "rounds": [{"rounds": number, **count} for number, count in sorted(rounds.items())],
            "usage": {**sum_usage(usage), "orchestrator": orch_usage},
            "seats": seat_rows}
