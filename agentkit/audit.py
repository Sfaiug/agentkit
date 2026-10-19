"""The weekly audit: once a week the tick writes the scoreboard with the week's largest loss
against the vision and the one line the `audit` seat is told, for that seat to fix the loss
through the line.  The owner hears nothing of it but the seat's own done notice.

The first tick of each ISO week (UTC, so every host counts the same week) writes
`state/audit/<week>.md`: the board as `ak run status --history` prints it, and the largest
loss (`scoreboard.loss`): the first measure, in the vision's order -- quality (changes
rewritten within a week, runs ended without merging, runs merged in round 1), speed (hours to
merge, time waiting), cost (tokens per merged run, ak's share of all tokens, runs the park
stopped), size (ak's code lines and README words) -- that reads worse than the week before;
when none does, the first in that order the board reads at all, since nothing merges
perfectly.  The line names the week, the loss and the report; `state/audit.json` keeps the
week, the line and how far its delivery got, which `watch.tell_audit` reads each tick: it
opens or resumes the seat and types the line at its quiet prompt, at least once.  A line typed
and not yet delivered is finished before the next week's is written: its mark is what sends it.
`[audit].on = false` writes nothing; a setting the config cannot read is one WARN line a tick.
"""

from datetime import datetime, timezone
import json
import time

from . import config, scoreboard

NAME = "audit"           # the seat


def week_of(now):
    """The ISO week `now` falls in, in UTC: `2026-W42`."""
    year, week, _ = datetime.fromtimestamp(now, timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def path():
    return config.STATE / "audit.json"


def read():
    """The week last written, its line, and how far its delivery got; {} before the first."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(data):
    config.ensure_dirs()
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path())


def phrase(found):
    """The loss in words, `the largest loss is <measure>, 30% against 20% the week before`, or
    that there is none to name."""
    if found is None:
        return "no loss to name, since no run ended in two weeks"
    words, now, before, form = found
    return (f"the largest loss is {words}, {scoreboard.said(now, form)} against "
            f"{scoreboard.said(before, form)} the week before")


def report(week, board, found):
    """Write the week's report and return its path: the board as the history prints it, and
    the largest loss in one line."""
    directory = config.STATE / "audit"
    directory.mkdir(parents=True, exist_ok=True)
    sentence = phrase(found)
    lines = [f"# ak's week {week}", "", *scoreboard.render(board), "",
             sentence[0].upper() + sentence[1:] + "."]
    target = directory / f"{week}.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def line_for(week, target, found):
    """The one line the seat is told: the week, its loss and where the board is, and what to do
    with it, as a run's ending tells a seat what ended."""
    return (f"ak's week {week}: {phrase(found)}; the board is at {target}. Build the smallest "
            "change to ak that moves it, through the line. "
            "Quality, then speed, then cost: a gain in speed or cost while a quality measure gets "
            "worse is no win.")


def weekly(cfg, log, now=None):
    """The tick's pass: the first tick of a new week writes its report and its line, once no
    earlier line waits in the composer for its Enter.  Answers (the setting, the record) while
    that line is still to be delivered, for `watch.tell_audit`; None while the audit is off or
    unreadable, or the week's line is in."""
    now = time.time() if now is None else now
    try:
        setting = config.audit(cfg)
    except config.Error as exc:
        log(f"WARN the weekly audit is not run: {exc}")
        return None
    if not setting["on"]:
        return None
    state, week = read(), week_of(now)
    if state.get("week") != week and (state.get("delivered") or not state.get("typed")):
        board = scoreboard.compute(now)
        found = scoreboard.loss(board)
        target = report(week, board, found)
        state = {"week": week, "report": str(target), "line": line_for(week, target, found),
                 "typed": None, "delivered": None}
        write(state)
        log(f"audit: week {week}'s board is at {target}; {phrase(found)}")
    return None if state.get("delivered") else (setting, state)
