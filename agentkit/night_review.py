"""After-merge breaks arm a daily task; its ordinary run record is its only claim."""

from pathlib import Path
import time

from . import config, gitcall, handback, history, orch, record, run, watch

DAY = 86400
WEEK = 7 * DAY
MAIN = "refs/remotes/origin/main"
TASK = """---
repo: {repo}
base: {main}
target: main
---
# Review {repo.name}'s merged changes for {day}

Read the day's merged diff on origin/main, from {first} through {last}, including the first commit's change.
Look for defects the changes together introduced or the per-change review missed.
If a test can show a defect, add it, show it failing on the current origin/main tip,
then fix the defect. Otherwise hand in `ak hand-in not-needed "<why>"` without edits.

## Done when
```bash
{tests}
```
"""


def reading():
    """The last two seven-day windows, newest first, and yesterday's merged runs, in UTC."""
    now = time.time()
    midnight = now // DAY * DAY
    rows = [row for row in history.ended_runs(now - 2 * WEEK, now) if history.merged(row)]
    weeks = []
    for start, end in ((now - WEEK, now), (now - 2 * WEEK, now - WEEK)):
        known = [row for row in rows if start <= row["finished_at"]
                 and (row["finished_at"] < end or end == now)
                 and row.get("broke_after_merge") is not None]
        weeks.append((sum(bool(row["broke_after_merge"]) for row in known), len(known)))
    armed = all(broken * 200 > merged for broken, merged in weeks)
    day = time.strftime("%Y-%m-%d", time.gmtime(midnight - DAY))
    return armed, weeks, day, [row for row in rows if midnight - DAY <= row["finished_at"] < midnight]


def targets(rows):
    stands = orch.listed()
    seats = {name: data for name, data in config.session_records().items()
             if not watch.seat_stopped_at(name)}
    projects = {name: orch.checkout_of(data.get("repo"), stands) for name, data in seats.items()}
    for checkout in orch.checkouts(stands):
        merged = sorted((row for row in rows if row.get("repo") == checkout.name),
                        key=lambda row: row["finished_at"])
        if not merged:
            continue
        name = merged[-1].get("session")
        try:
            name = config.resolve_session(name) if name else None
        except config.Error:
            name = None
        if name not in seats:
            name = max((seat for seat in seats if projects[seat] == checkout),
                       key=lambda seat: (seats[seat].get("created") or 0, seat), default=None)
        yield checkout, merged, name


def doctor_line():
    armed, weeks, _, rows = reading()
    shares = " · ".join(f"{broken}/{merged} ({broken / merged:.1%})" if merged else "no merges"
                        for broken, merged in weeks)
    missing = [f"{checkout.name}: no seat" for checkout, _, seat in targets(rows) if seat is None]
    return f"night review  {'armed' if armed else 'disarmed'} · last two weeks {shares}" + (
        " · " + ", ".join(missing) if missing else "")


def tick(log):
    armed, _, day, rows = reading()
    if not armed:
        return
    claimed = {Path(state["task_file"]).expanduser().resolve() for _, state in record.runs()
               if state.get("task_file")}
    for checkout, merged, seat in targets(rows):
        task = config.HOME / "tasks" / checkout.name / f"night-review-{day}.md"
        if seat is None or task.resolve() in claimed:
            continue
        try:
            _start(checkout, merged, seat, day, task)
        except (config.Error, OSError) as exc:
            log(f"WARN {checkout.name}: no night review for {day}: {exc}")


def _start(checkout, merged, seat, day, task):
    env = gitcall.project_env(checkout)
    gitcall.fetch(checkout, "origin", f"+refs/heads/main:{MAIN}", check=True, env=env)
    wanted = {row.get("merge_sha") for row in merged}
    commits = [sha for sha in gitcall.git(checkout, "rev-list", "--first-parent", "--reverse",
                                        MAIN, env=env).splitlines() if sha in wanted]
    if not commits or set(commits) != wanted:
        raise config.Error("the day's merged commits are not all on origin/main")
    tests = gitcall.declared_at(checkout, MAIN, "tests", env=env)
    if not tests:
        raise config.Error("no tests: on origin/main")
    body = TASK.format(repo=checkout, main=MAIN, day=day, first=commits[0], last=commits[-1], tests=tests)
    task.parent.mkdir(parents=True, exist_ok=True)
    orch.replace_file(task, body.encode())
    directory = handback.free_run_dir(f"night-review-{checkout.name}-{day}")
    directory.mkdir(parents=True)
    (directory / "task.md").write_text(body)
    (directory / "log.txt").touch()
    # The existing follow-up launch lets the first executor end not-needed without a review.
    run.launch_for_seat(directory, {"launched_session": seat}, {
        "followup": {"run": merged[-1]["run_id"], "text": f"Review {day}'s merged changes",
                     "place": str(task)}, "repo": str(checkout)}, task_file=task)
