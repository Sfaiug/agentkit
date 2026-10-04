#!/bin/bash
# The end-of-turn rule, where prose cannot enforce it.
#
# An orchestrator turn ends in exactly one of three ways -- an unanswered question through the
# harness's question prompt or `ak notify needs`,
# `ak notify done` because the job is finished, or a run or live job it is waiting on, including
# finite background work it started in its own harness while it is still in flight, and
# another session's work it said it waits on with `ak wait`, for as long as `watch.waiting_on`
# says that session is working.  A turn the owner opened with a question ends on its answer too:
# its prompt ends on a question mark, so a plain reply stands; any other prompt of the owner's
# gets one nudge and then its reply stands, since a request phrased as an instruction may ask
# for an answer.  A run of its own that sits parked and undecided --
# `unfinished`, the runs `ak notify done` refuses on, so not one a later merged run replaced --
# holds the turn past a done, an answer or a run going: the block names each such run, its
# parked reason and the commands its state takes, and the seat looks at it, resumes it,
# relaunches it split or on another model, stops it, or asks the owner.  A question, `ak notify
# needs`, background work and the third stop stand past it, as they always did.  A turn another
# session's message opened keeps a done declared before it: the seat only acknowledged the
# message, so that standing done ends the turn -- unless `ak notify` dropped it, or a run sits
# parked.  A peer's message is not the owner asking, so it answers nothing, and like a task
# notification or a line ak typed it leaves a question the seat put to the owner open.
# Anything else is sent back to work with the harness's own block decision, which Claude Code
# 2.1.263, Codex 0.153.4 and Grok Build 1.0.40 spell the same way: `{"decision": "block",
# "reason": "..."}` on stdout.  "Here is my recommendation, let me know if I should continue"
# then costs the user nothing but one turn.  A question mark in prose ends nothing: only the
# question prompt or `ak notify needs` alerts the owner, and reading prose is not this hook's
# to do.  A background command that starts with a loop or a sleep gets one corrective block:
# harness background tasks do not survive memory pressure, so a watcher belongs in ak run or
# tmux.  It counts against the same two-block limit; other stop rules still hold.
#
# A worker is silent here as it is everywhere: no $AGENTKIT_SESSION, or AK_RUN_ROLE=worker,
# and this decides nothing and exits 0.
#
# It blocks at most twice in one turn.  The counter lives beside the turn's own start in
# ~/.agentkit/state/stop-<seat>.json, under the name the seat goes by now, which
# hooks/seat-state.sh writes fresh on every
# UserPromptSubmit; the third stop stands, so a model that truly cannot proceed is left to the
# state function, which shows the seat as `needs you` rather than looping forever.
#
# On that same harness this is also what writes the Stop down, in the record hooks/seat-state.sh
# keeps for every other event: the two run side by side, and only this one knows whether the
# turn ended -- a stop sent back is `held`, one on background work is `background`, and both are
# the turn going on.  hooks/seat-state.sh leaves such a Stop to this, so no screen ever reads
# one before it has been judged.
#
# Every failure is exit 0 with nothing printed: a hook that fails loudly is a harness that
# stops, and an unreadable transcript is no evidence that anything was left undone.

set -u

main() {
  umask 077
  local seat script
  seat=${AGENTKIT_SESSION:-}
  [[ -n $seat ]] || return 0
  [[ ${AK_RUN_ROLE:-} != worker ]] || return 0
  # the seat's name is one component of a path here as it is everywhere else
  case "$seat" in */*|.|..|"") return 0 ;; esac
  # The script goes in on the command line and the hook's own JSON stays on stdin, where the
  # harness put it.  A turn that moved a lot of tool output ends in a payload no argument list
  # and no environment would carry -- Linux refuses a single one past 128 KB -- and a hook that
  # cannot be handed the turn it is judging would decide nothing at all, quietly.
  script=$(/bin/cat <<'STOPPY'
from collections import Counter
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[2]).resolve().parents[1]))
from agentkit import harness
from agentkit.run import going, handback_reason, unfinished, ways_out
from agentkit.job import job_waiting
from agentkit.watch import waiting_on

HOPS = 8            # how many renames a seat name is followed through, as agentkit/config does
LIMIT = 2           # blocks in one turn; the third stop stands
REASON = ("You stopped without asking the user through the question prompt or ak notify needs, "
          "declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")
WATCHER = ("A looping or sleeping harness background task is not a durable wait. "
           "Move it to ak run or a tmux session.")
NUDGE = ("The user's prompt did not end on a question. If it asked for work, continue: decide "
          "the next step and do it. If it asked you to find something out and your reply "
          "answers it, stop again; an answer is never ak notify done.")
HOME = Path(os.path.expanduser("~")) / ".agentkit"
STATE, RUNS = HOME / "state", HOME / "runs"
def loads(text):
    try:
        data = json.loads(text or "")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def read(path):
    try:
        return loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def moment(value):
    """A timestamp, or None: a bool is an int and `true` is not a moment."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def resolve(name):
    """The name that seat goes by now: `ak orch rename` leaves a pointer at the old one.

    The launch name stays in $AGENTKIT_SESSION for the life of the seat, so the records this
    reads -- which moved with the rename -- are only found under the name at the end of it.
    """
    seen = {name}
    for _ in range(HOPS):
        renamed = read(STATE / f"session-{name}.json").get("renamed")
        if not isinstance(renamed, str) or not renamed or renamed in seen or "/" in renamed:
            return name
        name = renamed
        seen.add(name)
    return name


def spoken(entry):
    """The assistant text one transcript line holds, in whichever shape its harness writes.

    Claude Code writes `{"type": "assistant", "message": {"content": [...]}}`, Codex
    `{"payload": {"type": "message", "role": "assistant", "content": [...]}}`.  A sidechain is
    a sub agent talking to itself and never what this seat said to the user.
    """
    if entry.get("isSidechain"):
        return None
    message = entry.get("message") if entry.get("type") == "assistant" else None
    payload = entry.get("payload")
    if (message is None and isinstance(payload, dict) and payload.get("type") == "message"
            and payload.get("role") == "assistant"):
        message = payload
    if not isinstance(message, dict):
        return None
    said = "\n".join(part["text"] for part in message.get("content") or []
                     if isinstance(part, dict) and isinstance(part.get("text"), str))
    return said or None


def transcript(payload):
    """Newest entries first, read back in growing chunks as far as the caller goes: a question
    still open stays found however much output followed it, in at most one chunk of memory."""
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return
    try:
        handle = open(path, "rb")
    except OSError:
        return
    with handle:
        end, chunk, rest = handle.seek(0, os.SEEK_END), 1 << 18, b""
        while end > 0:
            start = max(0, end - chunk)
            handle.seek(start)
            lines = (handle.read(end - start) + rest).split(b"\n")
            # the first line of a chunk that starts mid-file is half a line, read whole next time
            rest = lines.pop(0) if start else b""
            for line in reversed(lines):
                entry = loads(line)
                if not entry.get("isSidechain"):
                    yield entry
            end, chunk = start, min(chunk * 4, 1 << 26)


def last_message(payload):
    """Codex hands over the message; Claude names its transcript. Both key spellings occur."""
    said = payload.get("last_assistant_message")
    if not (isinstance(said, str) and said.strip()):
        said = payload.get("lastAssistantMessage")
    if isinstance(said, str) and said.strip():
        return said
    for entry in transcript(payload):
        said = spoken(entry)
        if said:
            return said
    return None


def questioned(payload, others=()):
    """Only an unanswered question still needs the owner; its result ends that wait.

    Only the owner's words answer it, as their harness tells them from its bookkeeping
    (`harness.prompt`).  `others` holds the keys hooks/seat-state.sh gave the prompts since
    the owner's last one that were not the owner's -- another session's message, a task
    notification, a line ak typed -- and the scan looks past each of those once, newest first,
    so an earlier answer of the owner's in the same words still answers.
    """
    answered, unanswering = set(), Counter(others)
    for entry in transcript(payload):
        item = entry.get("payload")
        item = item if isinstance(item, dict) else {}
        said = harness.prompt(entry)
        if said is not None:
            key = hashlib.sha256(said.strip().encode()).hexdigest()
            if not unanswering[key]:
                return False
            unanswering[key] -= 1
            continue
        message = entry.get("message")
        message = message if isinstance(message, dict) else item
        content = message.get("content") or []
        if isinstance(content, list):
            answered.update(part.get("tool_use_id") for part in content
                            if isinstance(part, dict) and part.get("type") == "tool_result"
                            and isinstance(part.get("tool_use_id"), str))
        if item.get("type") == "function_call_output" and isinstance(item.get("call_id"), str):
            answered.add(item["call_id"])
        if entry.get("type") == "assistant" and isinstance(content, list) and any(
                isinstance(part, dict) and part.get("type") == "tool_use"
                and part.get("name") == "AskUserQuestion" and part.get("id") not in answered
                for part in content):
            return True
        name = item.get("name")
        tool = name.rsplit(".", 1)[-1] if isinstance(name, str) else ""
        # The async call's output only says the question went out; the owner answers later,
        # as input of their own, which ends this scan above.
        if (item.get("type") == "function_call" and tool in ("request_user_input",
                                                             "request_user_input_async")
                and (tool.endswith("_async") or item.get("call_id") not in answered)):
            return True
    return False


def tells(payload):
    """Does this harness hand its Stop hook the background work it has in flight?

    Claude Code does, as `background_tasks`, an empty list when there is none.  A harness that
    does not -- Codex, Grok Build -- has its stops judged, and written down, as they always were.
    """
    return isinstance(payload.get("background_tasks"), list)


def background(payload):
    """Work this seat started in its own harness that has not reported back yet.

    Claude Code hands its Stop hook `background_tasks`, the agents and commands it still has in
    flight -- the ones whose task notification has not arrived -- and an empty list when there
    are none. Finite work wakes the seat when it settles, even beside a watcher.
    A `monitor` is a watch, not work: the comment watch on an artifact the seat published stays
    in that list for the rest of the session, and counted, it held the seat working for days.
    """
    tasks = payload.get("background_tasks")
    return isinstance(tasks, list) and any(
        isinstance(task, dict) and task.get("type") != "monitor" and not watcher(task)
        for task in tasks)


def watcher(task):
    """A background command that starts with a loop or a sleep, which keeps the seat waiting
    while its harness may kill it; any other command is finite work.  Its first word is read
    as bash reads it: line continuations gone, the word ended by a metacharacter."""
    if not (isinstance(task, dict) and isinstance(task.get("command"), str)):
        return False
    command = task["command"].replace("\\\n", "")
    return re.match(r"\s*(?:while|until|for|(?:[^\s|&;()<>]*/)?sleep)(?=[\s|&;()<>]|$)",
                    command) is not None


def told(seat, turn, kind, peer=False):
    """`ak notify <kind>` recorded for this seat during the turn.

    On a turn another session's message opened, a done standing from before it
    tells too: the seat only acknowledged the message, so it has nothing new to
    declare.  That done is still its last notice, and one `ak notify` did not
    drop -- a dropped done tells nothing on any such turn.
    """
    note = read(STATE / f"notify-{seat}.json")
    if note.get("kind") != kind:
        return False
    if peer and kind == "done":
        return not note.get("seen") and moment(note.get("time")) is not None
    when = moment(note.get("time"))
    return when is not None and when >= turn


def waiting(seat, turn):
    """A run this turn launched from this seat, or one of its runs or live jobs still going."""
    try:
        directories = sorted(path for path in RUNS.iterdir() if path.is_dir())
    except OSError:
        directories = []
    for directory in directories:
        state = read(directory / "run.json")
        owner = state.get("launched_session") or state.get("session")
        # the rename chain is only walked for a run whose recorded name is not already this one
        if not isinstance(owner, str) or not owner or (owner != seat and resolve(owner) != seat):
            continue
        if going(state):
            return True
        if state.get("state") in ("error", "waiting"):
            continue    # a rejected retry is no reason to wait, even if launched this turn
        for key in ("started_at", "queued_at"):
            when = moment(state.get(key))
            if when is not None and when >= turn:
                return True
    return job_waiting(seat)


def parked(seat):
    """(run, parked reason) for this seat's runs that sit parked and undecided.

    Undecided is `unfinished` whole over every run's record -- the runs `ak notify done`
    refuses on, so not one a later merged relaunch or continuation replaced -- read through
    agentkit's own function, never a copy of its rule.  A run going somewhere is not parked:
    it resumes itself, and a stop that waits on it stands as it always did.  `stalled` is the
    exception: `going` counts it, but nothing resumes one -- the tick only told the seat --
    so it sits parked for `ak run resume` and holds the turn like any undecided run.
    """
    try:
        directories = sorted(path for path in RUNS.iterdir() if path.is_dir())
    except OSError:
        return []
    records = [(directory, read(directory / "run.json")) for directory in directories]
    found = []
    for directory, state in records:
        owner = state.get("launched_session") or state.get("session")
        # the rename chain is only walked for a run whose recorded name is not already this one
        if not isinstance(owner, str) or not owner or (owner != seat and resolve(owner) != seat):
            continue
        if going(state) and state.get("state") != "stalled":
            continue
        if not unfinished(state, records):
            continue
        found.append((directory.name, handback_reason(state), ways_out(state, directory)))
    return found


def parked_reason(found):
    """The block where runs sit parked and undecided: each run, its reason and the commands its
    state takes -- `ways_out`, so none that refuses it -- and the ways out."""
    runs = "; ".join(f"run {name} parked: {why} ({' / '.join(ways)})" for name, why, ways in found)
    return (f"{runs}. Continue: settle each with one of its commands -- ak run status marks an "
            f"ended run looked at, ak run resume carries it on, ak run stop ends it -- relaunch "
            f"it split or on another model, or ask the owner.")


def held(launched, payload):
    """The reason to send this stop back with, or "" where the stop stands.

    At most LIMIT blocks in one turn, which the latch counts: a question, `ak notify needs`,
    background work and the third stop stand past a parked run as they always did, while a
    done, an answer to the owner's question, a run going or an `ak wait` ends the turn only
    with none of this seat's runs parked and undecided.
    """
    # The latch is this seat's own file, under the name it goes by now, as hooks/seat-state.sh
    # writes it and a rename moves it, like everything else this reads.
    seat = resolve(launched)
    latch = STATE / f"stop-{seat}.json"
    record = read(latch)
    turn = moment(record.get("turn"))
    if turn is None:
        return ""    # no turn was written down; nothing here can say what happened during it
    peer = record.get("peer") is True    # another session's message opened the turn
    asked = record.get("asked") is True    # the prompt that opened the turn asked something
    owner = record.get("owner") is True    # the owner, not a message or a report, opened it
    others = record.get("others")
    others = [key for key in others if isinstance(key, str)] if isinstance(others, list) else []
    said = last_message(payload)
    if questioned(payload, others) or told(seat, turn, "needs"):
        return ""
    warning = "watcher" if tells(payload) and any(
        watcher(task) for task in payload["background_tasks"]) else ""
    if warning and warning == record.get("warned"):
        return ""    # one correction for this violation; the state function owns the fallback
    reason = WATCHER
    if not warning:
        if said is None or background(payload):
            return ""
        undecided = parked(seat)
        if not undecided and (told(seat, turn, "done", peer) or waiting(seat, turn)
                              or waiting_on(seat) or (asked and not peer)):
            return ""
        if not undecided and owner:
            # A request phrased as an instruction may be answered: one nudge, then it stands.
            if record.get("warned") == "answer":
                return ""
            warning = "answer"
        reason = parked_reason(undecided) if undecided else NUDGE if warning else REASON
    blocks = record.get("blocks")
    blocks = blocks + 1 if isinstance(blocks, int) and not isinstance(blocks, bool) else 1
    if blocks > LIMIT:
        return ""    # the third stop stands, and the state function shows it as `needs you`
    # Every fact the prompt hook wrote about this turn stays with it, its typing receipt too.
    kept = {**record, "session": launched, "turn": turn, "blocks": blocks}
    if warning or record.get("warned"):
        kept["warned"] = warning or record["warned"]
    tmp = latch.with_name(f"{latch.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(kept) + "\n")
    tmp.replace(latch)
    return reason


def written(launched, kind):
    """This Stop, as hooks/seat-state.sh writes every other event down for the seat's row:
    under the name the seat goes by now, which is the name its row reads."""
    path = STATE / f"hook-{resolve(launched)}.json"
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"session": launched, "event": "Stop", "kind": kind,
                                   "text": "", "at": time.time()}) + "\n")
        tmp.replace(path)
    except OSError:
        pass        # a Stop nobody could write down is no reason to let the turn end


def main():
    launched = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = loads(sys.stdin.read())
    back = held(launched, payload)
    if tells(payload):
        written(launched, "held" if back else "background" if background(payload) else "")
    if back:
        print(json.dumps({"decision": "block", "reason": back}))


main()
STOPPY
) || return 0
  /usr/bin/env python3 -c "$script" "$seat" "${BASH_SOURCE[0]}"
}

main 2>/dev/null || true
exit 0
