#!/bin/bash
# The end-of-turn rule, where prose cannot enforce it.
#
# An orchestrator turn ends in exactly one of three ways -- a question the user must answer,
# `ak notify done` because the job is finished, or a run it is waiting on, which includes the
# background work it started in its own harness while the harness still lists it in flight, and
# another session's work it said it waits on with `ak wait`, for as long as `watch.waiting_on`
# says that session is working.  A run of its own that sits parked and undecided -- `unfinished`,
# the runs `ak notify done` refuses on -- holds the turn past a done or a run going: the block
# names each such run and its parked reason, and the seat resumes it, relaunches it split or on
# another model, stops it, or asks the owner.  A question, `ak notify needs`, background work
# and the third stop stand past it, as they always did.  A turn another session's message
# opened keeps a done declared before it: the seat only acknowledged the message, so that
# standing done ends the turn -- unless `ak notify` dropped it, or a run sits parked.
# Anything else is sent back to work with the harness's own block decision, which Claude Code
# 2.1.263, Codex 0.153.4 and Grok Build 1.0.40 spell the same way: `{"decision": "block",
# "reason": "..."}` on stdout.  "Here is my recommendation, let me know if I should continue"
# then costs the user nothing but one turn.  On a harness that tells its hook what background
# work it has in flight -- Claude Code -- so does "Shall I continue?": a last sentence that is
# only a bare request for leave to go on is not a question the user must answer.
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
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[2]).resolve().parents[1]))
from agentkit.run import going, handback_reason, unfinished
from agentkit.watch import waiting_on

HOPS = 8            # how many renames a seat name is followed through, as agentkit/config does
LIMIT = 2           # blocks in one turn; the third stop stands
REASON = ("You stopped without asking the user a question, declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")
HOME = Path(os.path.expanduser("~")) / ".agentkit"
STATE, RUNS = HOME / "state", HOME / "runs"
# Every last sentence that asks only leave to go on, word for word once case and the marks
# around it are set aside: "Shall I continue?", "Let me know if I should continue."  Going on
# is the rule, so the user never has to answer one.  A fixed list, because a sentence that
# says anything more -- asks for something, offers a choice -- is one the user must answer.
LEAVE = {f"{ask} {onward}"
         for ask in ("shall i", "should i", "shall we", "should we", "can i", "may i", "ok to",
                     "okay to", "want me to", "do you want me to", "would you like me to",
                     "let me know if i should", "let me know if you want me to")
         for onward in ("continue", "proceed", "go ahead", "go on", "carry on", "keep going")}


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


def spoken(line):
    """The assistant text one transcript line holds, in whichever shape its harness writes.

    Claude Code writes `{"type": "assistant", "message": {"content": [...]}}`, Codex
    `{"payload": {"type": "message", "role": "assistant", "content": [...]}}`.  A sidechain is
    a sub agent talking to itself and never what this seat said to the user.
    """
    entry = loads(line)
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


def last_message(payload):
    """What this seat said last, or None where nothing here can tell.

    Codex hands its Stop hook the message itself; Claude names the transcript instead, and the
    last assistant entry with text in it is the answer.  One harness spells the handover
    camelCase, so both keys are read.  Read from the end in widening windows,
    so a turn that moved a lot of tool output is still found without reading the conversation.
    """
    said = payload.get("last_assistant_message")
    if not (isinstance(said, str) and said.strip()):
        said = payload.get("lastAssistantMessage")
    if isinstance(said, str) and said.strip():
        return said
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None
    for window in (1 << 18, 1 << 22, 1 << 26):
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - window))
                lines = handle.read().splitlines()
        except OSError:
            return None
        # the first line of a window that starts mid-file is half a line, and half a line is
        # not JSON; dropping it costs nothing the next window does not read whole
        for line in reversed(lines if size <= window else lines[1:]):
            said = spoken(line)
            if said:
                return said
        if size <= window:
            break
    return None


def asks(said, leave=False):
    """A question the user must answer ends the message: its last paragraph carries the mark.

    With `leave`, a last sentence that is one of LEAVE asks nothing, and the paragraph asks only
    what the rest of it does.  A sentence ends at a mark with space after it, so
    `docs/guide.md?` is not two of them, and is taken whole, line breaks and all.
    """
    blocks = [block for block in re.split(r"\n\s*\n", said.strip()) if block.strip()]
    if not blocks:
        return False
    last = blocks[-1]
    if leave:
        *before, final = re.split(r"(?<=[.!?])\s+", last.strip())
        if " ".join(re.sub(r"^\W+|\W+$", "", final).lower().split()) in LEAVE:
            last = " ".join(before)
    return "?" in last


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
    """
    tasks = payload.get("background_tasks")
    return isinstance(tasks, list) and any(isinstance(task, dict) for task in tasks)


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
    """A run this turn launched from this seat, or one of this seat's runs still going."""
    try:
        directories = sorted(path for path in RUNS.iterdir() if path.is_dir())
    except OSError:
        return False
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
    return False


def parked(seat):
    """(run, parked reason) for this seat's runs that sit parked and undecided.

    Undecided is `unfinished` whole -- the runs `ak notify done` refuses on -- read through
    agentkit's own function, never a copy of its rule.  A run going somewhere is not parked:
    it resumes itself, and a stop that waits on it stands as it always did.  `stalled` is the
    exception: `going` counts it, but nothing resumes one -- the tick only told the seat --
    so it sits parked for `ak run resume` and holds the turn like any undecided run.
    """
    try:
        directories = sorted(path for path in RUNS.iterdir() if path.is_dir())
    except OSError:
        return []
    found = []
    for directory in directories:
        state = read(directory / "run.json")
        owner = state.get("launched_session") or state.get("session")
        # the rename chain is only walked for a run whose recorded name is not already this one
        if not isinstance(owner, str) or not owner or (owner != seat and resolve(owner) != seat):
            continue
        if going(state) and state.get("state") != "stalled":
            continue
        if not unfinished(state):
            continue
        found.append((directory.name, handback_reason(state)))
    return found


def parked_reason(found):
    """The block where runs sit parked and undecided: each run and its reason, and the four ways out."""
    runs = "; ".join(f"run {name} parked: {why}" for name, why in found)
    resume = " / ".join(f"ak run resume {name}" for name, _ in found)
    stop = " / ".join(f"ak run stop {name}" for name, _ in found)
    return (f"{runs}. Continue: resume it ({resume}), relaunch it split or on another model, "
            f"stop it ({stop}), or ask the owner.")


def held(launched, payload):
    """The reason to send this stop back with, or "" where the stop stands.

    At most LIMIT blocks in one turn, which the latch counts: a question, `ak notify needs`,
    background work and the third stop stand past a parked run as they always did, while a
    done, a run going or an `ak wait` ends the turn only with none of this seat's runs parked
    and undecided.
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
    peer = record.get("peer") is True    # another session's message opened the turn
    seat = resolve(launched)
    said = last_message(payload)
    if said is None or asks(said, leave=tells(payload)) or told(seat, turn, "needs"):
        return ""
    undecided = parked(seat)
    if not undecided and (told(seat, turn, "done", peer) or waiting(seat, turn)
                          or waiting_on(seat)):
        return ""
    blocks = record.get("blocks")
    blocks = blocks + 1 if isinstance(blocks, int) and not isinstance(blocks, bool) else 1
    if blocks > LIMIT:
        return ""    # the third stop stands, and the state function shows it as `needs you`
    kept = {"session": launched, "turn": turn, "blocks": blocks}
    if peer:
        kept["peer"] = True    # the turn it counts is still the peer's one
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
