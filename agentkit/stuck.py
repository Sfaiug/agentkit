"""Work that waits while nothing moves it: the tick finds it and has the `audit` seat told, once
per stall, for that seat to fix ak through the line as it fixes the week's loss (`audit`).

A stall is a landing line's check pass that has run more than three times the median of the
line's last passes (`land.passes`), and half an hour at least, while its lander lives: red
stacks narrowed with whole suites, a suite that hangs, or a cause nobody has met yet.  So is the
run first in line for a slot as long, against the waits there of the last firsts let in, while
the queue is polled (`gate.first_in_line`): a gate that never opens, or a dead run the waiters
behind it wait on.  So is ~/agentkit half an hour short of going live at a commit it owes
(`update.owed_live`): a move a killed git left half done kept it so for ten hours.  The seat is told one stall at a time, each once (`told`); `state/stuck.json`
keeps the line being told and how far its delivery got, as `state/audit.json` does the week's,
which goes first (`watch.tell_audit`).
"""

import json
from pathlib import Path
import statistics
import time

from . import config, land, record

SLOWER = 3            # a pass or wait this many times its usual is stuck,
FLOOR = 30 * 60       # and none shorter than half an hour, however quick its usual
SAMPLES = 3           # fewer finished passes or waits give no pace to compare with
ASKED = ("Find why and build the smallest change to ak that keeps it from happening again, "
         "through the line.")     # of the seat, each stall


def path():
    return config.STATE / "stuck.json"


def read():
    """The stall last written, its line, how far its delivery got, and the stalls told that
    still run."""
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


def _far_past(took):
    """How long a pass or wait runs before it is stuck: SLOWER times the median of the last
    (`took`), and FLOOR at least; FLOOR while fewer than SAMPLES give it a pace."""
    return max(FLOOR, SLOWER * statistics.median(took)) if len(took) >= SAMPLES else FLOOR


def stalls(now):
    """(key, what, line) for each landing pass and slot wait running at `now`, the line None
    while it is not stuck: its key names it while it runs (`scan`)."""
    from . import gate, orch
    for kept_at in sorted(config.RUNS.glob(".merge-*.passes")):
        turn = kept_at.with_suffix(".lock")     # the line's own name (`deliver.merge_lock_path`)
        kept = land.passes(turn)
        took, started = kept.get("took") or [], kept.get("started")
        if not started or len(took) < SAMPLES or not record.process_active(kept):
            continue
        usual = statistics.median(took)
        if now - started <= _far_past(took):
            yield f"{turn.name}:{started}", None, None
            continue
        members = land.line(turn)
        what = (f"the {Path(members[0][1]['repo']).name} landing line" if members
                else f"the landing line {turn.name}")
        yield (f"{turn.name}:{started}", f"the stall of {what}",
               f"ak stalled: {what} has run one check pass for {orch.span(now - started)}, more "
               f"than {SLOWER} times its usual {orch.span(usual)}, with {len(members)} in line; "
               f"its log is {turn.with_suffix('.log')}. {ASKED}")
    from . import update, watch
    owed = update.owed_live(now)
    if owed:
        commit, since = owed
        why = update.left_as_is()
        yield (f"live:{commit}", "the stall of ak going live",
               f"ak stalled: {update.agentkit_dir()} has not gone live at {commit[:12]} for "
               f"{orch.span(now - since)}{f', and it is {why}' if why else ''}; the tick's log "
               f"{watch.log_path()} says why. {ASKED}" if now - since > FLOOR else None)
    first = gate.first_in_line(now)
    if first:
        run_id, since, behind, took = first
        past = _far_past(took)
        yield (f"slot:{run_id}:{since}", "the stall of the slot queue",
               f"ak stalled: {run_id} has been first in line for a slot for "
               f"{orch.span(now - since)}, more than {orch.span(past)}, with {behind} behind "
               f"it; `ak run status` shows what it waits on. {ASKED}"
               if now - since > past else None)


def scan(cfg, log, now=None):
    """The tick's pass: answers (the setting, the record) while a stall's line is still to be
    told, for `watch.tell_audit`; a new stall is looked for only once the line before is in.
    None while the audit is off or unreadable (`audit.weekly` says so), or nothing is stuck."""
    now = time.time() if now is None else now
    try:
        setting = config.audit(cfg)
    except config.Error:
        return None
    if not setting["on"]:
        return None
    state = read()
    if state.get("line") and not state.get("delivered"):
        return setting, state
    found = {key: (what, line) for key, what, line in stalls(now)}
    # a stall stays one until it ends: its key is kept while it runs, back under its line or
    # not (a clock set back), and no longer
    told = [key for key in state.get("told") or [] if key in found]
    for key, (what, line) in found.items():
        if key in told or not line:
            continue
        state = {"about": what, "line": line, "typed": None, "delivered": None,
                 "told": [*told, key]}
        write(state)
        log(f"stuck: {line}")
        return setting, state
    return None
