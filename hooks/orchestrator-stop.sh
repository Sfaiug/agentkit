#!/bin/bash
# The end-of-turn rule, where prose cannot enforce it.
#
# An orchestrator turn records an unanswered question, a completion or a live wait.
# Information-only answers use `ak notify done --quiet`; parked work still holds completion
# and waits. Questions and background work stand past it. The shared decision in stop.py
# checks current completion against retired notices, failures and open plans on every harness.
# Anything else is sent back to work with the harness's own block decision, which Claude Code
# 2.1.263, Codex 0.153.4 and Grok Build 1.0.40 spell the same way: `{"decision": "block",
# "reason": "..."}` on stdout.  "Here is my recommendation, let me know if I should continue"
# then costs the user nothing but one turn.  A question mark in prose ends nothing: only the
# question prompt or `ak notify needs` alerts the owner, and reading prose is not this hook's
# to do.
#
# A worker is silent here as it is everywhere: no $AGENTKIT_SESSION, or AK_RUN_ROLE=worker,
# and this decides nothing and exits 0.
#
# It blocks at most twice in one turn.  The counter lives beside the turn's own start in
# ~/.agentkit/state/stop-<seat>.json, which hooks/seat-state.sh writes fresh on every
# UserPromptSubmit; the third stop stands, so a model that truly cannot proceed is left to the
# state function, which shows the seat as `needs you` rather than looping forever.
#
# On that same harness this is also what writes the Stop down, in the record hooks/seat-state.sh
# keeps for every other event: the two run side by side, and only this one knows whether the
# turn ended -- a stop sent back is `held`, one on background work is `background`, and both are
# the turn going on.  hooks/seat-state.sh leaves such a Stop to this, so no screen ever reads
# one before it has been judged.
#
# A failed hook exits quietly; a missing transcript supplies no question, so recorded
# completion or a live wait is still needed.

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
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[2]).resolve().parents[1]))
from agentkit import config, harness, notify
from agentkit.run import handback_reason
from agentkit.stop import recorded_ending, ways_out
from agentkit.watch import owner_question

LIMIT = 2           # blocks in one turn; the third stop stands
REASON = ("You stopped without asking the user through the question prompt or ak notify needs, "
          "declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")
HOME = Path(os.path.expanduser("~")) / ".agentkit"
STATE = HOME / "state"
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
    A chain that does not resolve leaves the name as it is: a stop hook decides from what it
    can read and never fails the stop.
    """
    try:
        return config.resolve_session(name)
    except config.Error:
        return name


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


def questioned(payload):
    """Only an unanswered question still needs the owner; its result ends that wait.

    Input in the owner's words, as their harness tells them from its bookkeeping
    (`harness.prompt`), ends the scan: what was asked before it is answered or set aside.
    """
    answered, accepted = set(), set()
    for entry in transcript(payload):
        item = entry.get("payload")
        item = item if isinstance(item, dict) else {}
        if harness.prompt(entry) is not None:
            return False
        message = entry.get("message")
        message = message if isinstance(message, dict) else item
        content = message.get("content") or []
        if isinstance(content, list):
            answered.update(part.get("tool_use_id") for part in content
                            if isinstance(part, dict) and part.get("type") == "tool_result"
                            and isinstance(part.get("tool_use_id"), str))
        if item.get("type") == "function_call_output" and isinstance(item.get("call_id"), str):
            answered.add(item["call_id"])
            try:
                if json.loads(item.get("output")) == {"accepted": True}:
                    accepted.add(item["call_id"])
            except (TypeError, ValueError):
                pass
        if entry.get("type") == "assistant" and isinstance(content, list) and any(
                isinstance(part, dict) and part.get("type") == "tool_use"
                and part.get("name") == "AskUserQuestion" and part.get("id") not in answered
                for part in content):
            return True
        name = item.get("name")
        tool = name.rsplit(".", 1)[-1] if isinstance(name, str) else ""
        # The async call's output only says whether the question went out; the owner answers
        # later, as input of their own, which ends this scan above.  A refused call asked nothing.
        if (item.get("type") == "function_call" and tool in ("request_user_input",
                                                             "request_user_input_async")
                and (item.get("call_id") in accepted if tool.endswith("_async")
                     else item.get("call_id") not in answered)):
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
    are none.  Each of them wakes the seat again when it settles, so a stop on them is a wait.
    A `monitor` is a watch, not work: the comment watch on an artifact the seat published stays
    in that list for the rest of the session, and counted, it held the seat working for days.
    """
    tasks = payload.get("background_tasks")
    return isinstance(tasks, list) and any(
        isinstance(task, dict) and task.get("type") != "monitor" for task in tasks)


def parked_reason(found):
    """The block where runs sit parked and undecided: each run, its reason and the commands its
    state takes -- `ways_out`, so none that refuses it -- and the ways out."""
    runs = "; ".join(f"run {directory.name} parked: {handback_reason(state)} "
                     f"({' / '.join(ways_out(state, directory))})"
                     for directory, state in found)
    return (f"{runs}. Continue: settle each with one of its commands -- ak run status marks an "
            f"ended run looked at, ak run resume carries it on, ak run stop ends it -- relaunch "
            f"it split or on another model, or ask the owner.")


def held(launched, payload):
    """The reason to send this stop back with, or "" where the stop stands.

    At most LIMIT blocks in one turn, which the latch counts: a question, `ak notify needs`,
    background work and the third stop stand past a parked run as they always did, while a
    done, a run going or an `ak wait` ends the turn only
    with none of this seat's runs parked and undecided.
    """
    # The latch is this seat's own file, under the name its harness was launched with, the way
    # hooks/seat-state.sh writes it.  What it reads is the toolkit's, and that moved when the
    # seat was renamed.
    latch = STATE / f"stop-{launched}.json"
    record = read(latch)
    turn = moment(record.get("turn"))
    if turn is None:
        return ""    # no turn was written down; nothing here can say what happened during it
    if background(payload):
        return ""
    seat = resolve(launched)
    # a question to the owner that nothing has answered yet ends a turn whenever it was asked:
    # a hand-back or a told line opens turns on a seat while it stands (`watch.stop_nudge`)
    ends, undecided = recorded_ending(
        seat, question=questioned(payload) or owner_question(notify.last(seat)), since=turn)
    if ends:
        return ""
    blocks = record.get("blocks")
    blocks = blocks + 1 if isinstance(blocks, int) and not isinstance(blocks, bool) else 1
    if blocks > LIMIT:
        return ""    # the third stop stands, and the state function shows it as `needs you`
    kept = {"session": launched, "turn": turn, "blocks": blocks}
    tmp = latch.with_name(f"{latch.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(kept) + "\n")
    tmp.replace(latch)
    return parked_reason(undecided) if undecided else REASON


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
        written(launched, "background" if background(payload) else "held" if back else "")
    if back:
        print(json.dumps({"decision": "block", "reason": back}))


main()
STOPPY
) || return 0
  /usr/bin/env python3 -c "$script" "$seat" "${BASH_SOURCE[0]}"
}

main 2>/dev/null || true
exit 0
