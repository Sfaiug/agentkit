#!/bin/bash
# The one hook agentkit asks a harness to run, for every lifecycle event it offers.
#
# It writes down events the manifest gives a state. What the seat is doing -- the event, its
# payload discriminator and the moment it arrived -- goes to ~/.agentkit/state/hook-<seat>.json,
# and the classifier reads adapters/<harness>.toml to say what that event means. A notice with
# no state leaves that fact alone, so it cannot erase a turn or restore one over a Stop. A prompt
# also starts a turn, and ~/.agentkit/state/stop-<seat>.json is where that moment is kept, for
# hooks/orchestrator-stop.sh to judge the turn's end against (`looker.prompted`).
#
# Every event it hears also has the seat looked at again at once (`watch.hook_look`), so
# the seat's record and its status bar say what the event means now rather than at the next
# menu draw or tick.  The look also records the owner's answer to a question. It runs in the
# background, in a session of its own, holding nothing of the harness's: the harness never
# waits on it, even while a notice's lock is held for delivery.  Every event but a Stop is heard
# where it is looked at (agentkit/looker.py): its moment, its fact and its look in one hand-over
# to the warm looker, which has its imports done, else in the client, cold.
#
# A worker is silent here as it is everywhere: a headless `ak worker` runs the same harness with
# the same hooks, and a seat's row must never be moved by one.  No $AGENTKIT_SESSION, or
# AK_RUN_ROLE=worker, and this writes nothing and exits 0.
#
# On a prompt it passes on what changed in its rulebook, or the whole of it where the one it
# holds is unknown (`orch.rulebook_news`), and the open questions an owner's prompt may
# answer (`notify.answer_context`), as the harness's prompt context.
#
# Every failure is exit 0 with nothing written: a hook that fails loudly is a harness that stops.

set -u

# Look at the seat again, off the harness's path: see the header.  Only from inside a tmux
# pane, which is where every seat's harness runs; watch.hook_look checks the pane is the seat's,
# on the seat's own server.
look() {
  [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] || return 0
  ( /usr/bin/env python3 "${BASH_SOURCE[0]%/*}/../agentkit/looker.py" "$1" \
      </dev/null >/dev/null 2>&1 & )
}

# The moment that seat heard its event, on its own clock (`config.heard_at`), which never runs
# back as the host's can: else the host's.
heard() {
  /usr/bin/env python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import config
print(config.heard_at(sys.argv[2]))
' "${BASH_SOURCE[0]}" "$1" 2>/dev/null || /bin/date +%s
}

seat_state() {
  local payload=$1 jq=$2 owner=$3 said=$4 seat event kind text ts dir row next hop pid=''
  seat=${AGENTKIT_SESSION:-}

  event=$("$jq" -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null) || return 0
  [[ -n $event ]] || return 0
  [[ $event != SessionStart ]] || return 0
  # the payload field that tells one kind of that event from another: Claude's Notification
  # carries notification_type, a PermissionRequest the tool it wants -- and one harness spells
  # both camelCase, so the twins are read beside them -- and a compaction its trigger
  kind=$("$jq" -r '.notification_type // .notificationType // .tool_name // .toolName // .trigger
                   // empty' <<<"$payload" 2>/dev/null) || kind=''
  # a question's own words, where the event carries one, before a notice's: whole, for each
  # reader fits them to its own room, and on stdin, for one argument holds 128 KiB
  text=$("$jq" -r '(.tool_input.questions[0].question)? // .message // .title // ""' \
    <<<"$payload" 2>/dev/null) || text=''
  # Any other event is the looker's to hear (`looker.record`), wherever the harness runs, and
  # the hook goes on once its fact is down: an event the harness waits on is never written after
  # the next.  The owner's word answers at the moment the event is heard.  A prompt
  # (`looker.prompted`) comes with its payload, and with the hook's caller, while it lives, for
  # the seat to follow on somebody's words in a pane; what it says, its news, is the hook's.
  if [[ $event = UserPromptSubmit ]]; then
    [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} && $owner = true ]] && pid=$PPID
    printf '%s\0%s\0%s' "$said" "$text" "$payload" | /usr/bin/env python3 \
      "${BASH_SOURCE[0]%/*}/../agentkit/looker.py" "$seat" "$owner" "$event" "$kind" "$pid"
    return 0
  elif [[ $event != Stop ]]; then
    printf '%s\0%s' "$said" "$text" | /usr/bin/env python3 \
      "${BASH_SOURCE[0]%/*}/../agentkit/looker.py" "$seat" "$owner" "$event" "$kind" >/dev/null
    return 0
  fi
  ts=$(heard "$seat")

  dir="$HOME/.agentkit/state"
  # The record the seat's row reads is under the name the seat goes by now: `ak orch rename`
  # leaves a pointer at the old one, and the harness carries its launch name for its whole life.
  row=$seat
  for hop in 1 2 3 4 5 6 7 8; do
    next=$("$jq" -r '.renamed | strings' "$dir/session-$row.json" 2>/dev/null) || break
    case "$next" in */*|.|..|"") break ;; esac
    row=$next
  done
  # A Stop that hands over the background work in flight -- Claude Code's, Grok Build's, a Codex
  # seat's -- is written down by hooks/orchestrator-stop.sh, which runs beside this and knows
  # whether the turn ended there.  Written here too, it would read as the turn over until that
  # one decided; that one looks at the seat once its word is down, however long it took.  A
  # harness that is nudged instead (`watch.stop_enforced`) runs no such hook: its Stop is here.
  if [[ $event = Stop ]] &&
    "$jq" -e '(.background_tasks // .backgroundTasks) | type == "array"' <<<"$payload" \
      >/dev/null 2>&1; then
    /usr/bin/env python3 -c '
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import config, lifecycle, watch
row, seat, at = sys.argv[2:]
if not watch.stop_enforced(watch.seat_model(config.load(), row)[0]):
    sys.exit(1)
config.record_hook_fact(row, lifecycle.stop_fact(seat, json.load(sys.stdin), float(at)))
' "${BASH_SOURCE[0]}" "$row" "$seat" "$ts" <<<"$payload" && look "$seat"
    return 0
  fi
  # The fact standing is replaced by one writer at a time, as hooks/orchestrator-stop.sh
  # replaces it with its Stop (`config.record_hook_fact`): an event its harness does not wait on
  # can finish after a newer one, and is never put back over it.
  /usr/bin/env python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import config
row, seat, event, kind, at = sys.argv[2:]
config.record_hook_fact(row, {"session": seat, "event": event, "kind": kind,
                              "text": sys.stdin.read()[:-1], "at": float(at)})
' "${BASH_SOURCE[0]}" "$row" "$seat" "$event" "$kind" "$ts" <<<"$text"
  look "$seat"
}

main() {
  umask 077
  local payload=$1 jq event owner=true said='' seat=${AGENTKIT_SESSION:-}
  [[ ${AK_RUN_ROLE:-} != worker ]] || return 0
  # The seat's name is one component of a path here as it is everywhere else.
  case "$seat" in */*|.|..|"") return 0 ;; esac
  jq=$(command -v jq) || return 0
  event=$("$jq" -r '.hook_event_name // "Stop"' <<<"$payload" 2>/dev/null) || event=Stop
  # A sub-agent's own turn is not the seat's: written down, it would be a turn that never ends,
  # its prompt the owner's answer, and its end the seat's idleness.
  if [[ $event = UserPromptSubmit || $event = Stop ]] &&
    "$jq" -e -f "${BASH_SOURCE[0]%/*}/sub-agent.jq" <<<"$payload" >/dev/null 2>&1; then
    return 0
  fi
  # Slash commands and turns the harness begins on completed work answer nothing.
  if "$jq" -e '([(.prompt // empty), (.message // empty)] | map(strings)
                | any(contains("<task-notification") or test("^[[:space:]]*/[^/[:space:]]+([[:space:]]|$)")
                      or test("^[[:space:]]*<system-reminder>")))
               or ((.promptId // .prompt_id // "") | strings
                   | test("^(task|subagent)-completed-"))' \
      <<<"$payload" >/dev/null 2>&1; then
    owner=false
  fi
  if [[ $event = UserPromptSubmit ]]; then
    said=$("$jq" -r '[(.prompt // empty), (.message // empty)] | map(strings)
                     | first // ""' <<<"$payload" 2>/dev/null) || said=''
  # The owner's answer to the harness's own question tool is their word as a prompt is, and
  # answers only the questions it names: by their words, or by an id its call gives the words
  # of, each beside the choices the card showed with it (`notify.replied`).  A card cancelled
  # or left empty, any other event, and a sub-agent's tool say nothing of theirs.
  elif [[ $event != PostToolUse ]] ||
    "$jq" -e -f "${BASH_SOURCE[0]%/*}/sub-agent.jq" <<<"$payload" >/dev/null 2>&1 ||
    ! said=$("$jq" -ec '. as $call | (.tool_input.answers // .tool_response.answers)
                        | objects | [to_entries[] | select([.value | .. | strings
                                                           | select(test("\\S"))] != [])
                          | .key as $id
                          | (first($call.tool_input.questions[]?, $call.tool_response.questions[]?
                                   | objects | select(.id == $id or .question == $id)) // {})
                          | [(.question | strings) // $id, (.options[]? | .label? // . | strings)]]
                        | select(. != [])' <<<"$payload" 2>/dev/null); then
    owner=false
  fi
  # A prompt's news is the hook's output; nothing else it hears says anything.
  if [[ $event = UserPromptSubmit ]]; then
    seat_state "$payload" "$jq" "$owner" "$said"
  else
    seat_state "$payload" "$jq" "$owner" "$said" >/dev/null 2>&1
  fi
  # SessionStart first captures the conversation its harness vouches for.
  if [[ $event = SessionStart ]]; then
    news "$payload"
  fi
}

# A seat's SessionStart: first, while the hook's caller lives and before a background look reads
# it, the seat goes on in the conversation the event names where its own process went
# (`Harness.follow`), only in a pane.  A compaction (`source` compact) leaves the conversation
# holding its launch's rulebook again, which its next prompt is then told about.
news() {
  local payload=$1 pid=''
  [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] && pid=$PPID
  # JSON travels on stdin, never argv.
  printf '%s' "$payload" | /usr/bin/env python3 -c '
import contextlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import config, orch
payload = json.load(sys.stdin)
if sys.argv[3]:
    with contextlib.suppress(Exception):    # the seat stays put, and a compaction is still heard
        orch.seat_plugin(config.session_records().get(config.resolve_session(sys.argv[2]), {})
                         ).follow(sys.argv[2], payload, int(sys.argv[3]))
if payload.get("source") == "compact":
    orch.rulebook_compacted(sys.argv[2], payload.get("session_id"))
' "${BASH_SOURCE[0]}" "$AGENTKIT_SESSION" "$pid"
}

payload=$(/bin/cat 2>/dev/null) || payload=''
main "$payload" 2>/dev/null || true
exit 0
