#!/bin/bash
# The one hook agentkit asks a harness to run, for every lifecycle event it offers.
#
# It writes down events the manifest gives a state. What the seat is doing -- the event, its
# payload discriminator and the moment it arrived -- goes to ~/.agentkit/state/hook-<seat>.json,
# and the classifier reads adapters/<harness>.toml to say what that event means. A notice with
# no state leaves that fact alone, so it cannot erase a turn or restore one over a Stop. A prompt
# also starts a turn, and ~/.agentkit/state/stop-<seat>.json is where that moment is kept, for
# hooks/orchestrator-stop.sh to judge the turn's end against.
#
# Every event it hears also has the seat looked at again at once (`watch.hook_look`), so
# the seat's record and its status bar say what the event means now rather than at the next
# menu draw or tick.  The look also records the owner's answer to a question. It runs in the
# background, in a session of its own, holding nothing of the harness's: the harness never
# waits on it, even while a notice's lock is held for delivery.
#
# A worker is silent here as it is everywhere: a headless `ak worker` runs the same harness with
# the same hooks, and a seat's row must never be moved by one.  No $AGENTKIT_SESSION, or
# AK_RUN_ROLE=worker, and this writes nothing and exits 0.
#
# On a prompt it passes on where its current rulebook is, when the one it was handed is out
# of date or unknown (`orch.rulebook_news`), and the open questions an owner's prompt may
# answer (`notify.answer_context`), as the harness's prompt context.
#
# Every failure is exit 0 with nothing written: a hook that fails loudly is a harness that stops.

set -u

# Look at the seat again, off the harness's path: see the header.  Only from inside a tmux
# pane, which is where every seat's harness runs; watch.hook_look checks the pane is the seat's,
# on the seat's own server.
look() {
  local seat=$1 answered=${2:-} said=${3:-} event=${4:-}
  [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] || return 0
  # the owner's words go on its stdin: on its command line, a long one would never run it
  ( printf '%s' "$said" | /usr/bin/env python3 -c '
import os, sys
from pathlib import Path
try:
    os.setsid()     # a session of its own: a harness ending the hook group ends none of this
except OSError:
    pass
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import watch
watch.hook_look(sys.argv[2], float(sys.argv[3]) if sys.argv[3] else None, sys.stdin.read(),
                prompt=sys.argv[4] == "UserPromptSubmit")
' "${BASH_SOURCE[0]}" "$seat" "$answered" "$event" >/dev/null 2>&1 & )
}

seat_state() {
  local payload=$1 jq=$2 owner=$3 said=$4 seat event kind text ts dir tmp row next hop write
  seat=${AGENTKIT_SESSION:-}
  [[ -n $seat ]] || return 0
  [[ ${AK_RUN_ROLE:-} != worker ]] || return 0
  # the seat's name is one component of a path here as it is everywhere else
  case "$seat" in */*|.|..|"") return 0 ;; esac

  event=$("$jq" -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null) || return 0
  [[ -n $event ]] || return 0
  # Capture while the hook's caller still exists, before a background look can read the
  # old conversation. Claude verifies the process and transcript; other harnesses do nothing.
  if [[ $event = SessionStart && -n ${TMUX:-} && -n ${TMUX_PANE:-} ]]; then
    /usr/bin/env python3 "${BASH_SOURCE[0]%/*}/../agentkit/harness/claude.py" \
      --hook "$PPID" <<<"$payload" || true
  fi
  [[ $event != SessionStart ]] || return 0
  ts=$(/usr/bin/env python3 -c 'import time; print(time.time())' 2>/dev/null) || ts=$(/bin/date +%s)
  # A Stop that hands over the background work in flight -- Claude Code's, Grok Build's -- is
  # written down by hooks/orchestrator-stop.sh, which runs beside this and is the one that knows
  # whether the turn ended there.  Written here too, it would read as the turn over until that
  # one decided; that one looks at the seat once its word is down, however long it took.
  if [[ $event = Stop ]] &&
    "$jq" -e '(.background_tasks // .backgroundTasks) | type == "array"' <<<"$payload" \
      >/dev/null 2>&1; then
    return 0
  fi
  # the payload field that tells one kind of that event from another: Claude's Notification
  # carries notification_type, a PermissionRequest the tool it wants -- and one harness spells
  # both camelCase, so the twins are read beside them -- and a compaction its trigger
  kind=$("$jq" -r '.notification_type // .notificationType // .tool_name // .toolName // .trigger
                   // empty' <<<"$payload" 2>/dev/null) || kind=''
  # a question's own words, where the event carries one, before a notice's
  text=$("$jq" -r '((.tool_input.questions[0].question)? // .message // .title // "") | .[0:160]' \
    <<<"$payload" 2>/dev/null) || text=''

  dir="$HOME/.agentkit/state"
  # The record the seat's row reads is under the name the seat goes by now: `ak orch rename`
  # leaves a pointer at the old one, and the harness carries its launch name for its whole life.
  row=$seat
  for hop in 1 2 3 4 5 6 7 8; do
    next=$("$jq" -r '.renamed | strings' "$dir/session-$row.json" 2>/dev/null) || break
    case "$next" in */*|.|..|"") break ;; esac
    row=$next
  done
  # The fact standing is read, judged and replaced by one writer at a time, as
  # hooks/orchestrator-stop.sh replaces it with its Stop (`config.record_hook_fact`): an event its
  # harness does not wait on can finish after a newer one, and is never put back over it.
  # Claude says its prompt is idle a minute after a turn ends whether or not background work is
  # in flight: a seat waiting on work it started is not idle, and the Stop that said so stands
  # until that work's notification begins a turn; a question going up still replaces it.
  write='
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import config
row, seat, event, kind, text, at = sys.argv[2:]
fact = {"session": seat, "event": event, "kind": kind, "text": text, "at": float(at)}
def passive(standing):
    return False
def kept(standing):
    return ((event, kind, standing.get("event"), standing.get("kind"))
            == ("Notification", "idle_prompt", "Stop", "background") or passive(standing))
'
  # Only events that could be passive ask the classifier, before that writer's turn, which then
  # judges with it; prompt and Stop do not.  A notice the seat's own manifest gives no state
  # writes nothing, and nor does one meaning what the fact standing means -- a permission notice
  # six seconds after the PermissionRequest that wrote its question down.  An event it marks
  # `interrupt` always writes: the owner stopped a turn a harness with no prompt hook began
  # under an earlier Stop's at_prompt, which that Stop does not say.  Where nothing can
  # say -- no record names the harness, or the asking fails -- the event is written all the same.
  /usr/bin/env python3 -c "$write"'
if event not in ("UserPromptSubmit", "Stop"):
    from agentkit import watch
    harness = watch.seat_model(config.load(), row)[0]
    state, said = watch.hook_state(harness, fact)[:2]
    def passive(standing):
        return (bool(harness) and said not in watch.marked_events(harness, "interrupt")
                and state in (None, watch.hook_state(harness, standing)[0]))
config.record_hook_fact(row, fact, kept)
' "${BASH_SOURCE[0]}" "$row" "$seat" "$event" "$kind" "$text" "$ts" ||
    /usr/bin/env python3 -c "$write"'
config.record_hook_fact(row, fact, kept)
' "${BASH_SOURCE[0]}" "$row" "$seat" "$event" "$kind" "$text" "$ts"

  # A new prompt is a new turn: hooks/orchestrator-stop.sh judges that turn against this
  # moment, and the two blocks it is allowed start again from zero here.
  if [[ $event = UserPromptSubmit ]]; then
    tmp="$dir/stop-$seat.json.tmp.$$"
    "$jq" -n --arg session "$seat" --argjson turn "$ts" \
      '{session: $session, turn: $turn, blocks: 0}' \
      >"$tmp" || { /bin/rm -f -- "$tmp"; return 0; }
    /bin/mv -f -- "$tmp" "$dir/stop-$seat.json" || /bin/rm -f -- "$tmp"
  fi
  # The owner's word answers an older question, once the background look checks its pane --
  # and, for a prompt, the seat's conversation (`notify.answer_written`).  The launch name still
  # resolves after a rename; main leaves harness bookkeeping alone.
  if [[ $owner = true ]]; then
    look "$seat" "$ts" "$said" "$event"
  else
    look "$seat"
  fi
}

main() {
  umask 077
  local payload=$1 jq event owner=true said=''
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
                | any(contains("<task-notification") or test("^[[:space:]]*/")
                      or test("^[[:space:]]*<system-reminder>")))
               or ((.promptId // .prompt_id // "") | strings
                   | test("^(task|subagent)-completed-"))' \
      <<<"$payload" >/dev/null 2>&1; then
    owner=false
  fi
  # Capture the questions before seat_state starts the look that marks them answered.
  if [[ $event = UserPromptSubmit ]]; then
    said=$("$jq" -r '[(.prompt // empty), (.message // empty)] | map(strings)
                     | first // ""' <<<"$payload" 2>/dev/null) || said=''
    news "$payload" "$owner" "$said"
  # The owner's answer to the harness's own question tool is their word as a prompt is, its
  # answers what they said; any other event, and a sub-agent's tool, says nothing of theirs.
  elif [[ $event != PostToolUse ]] ||
    "$jq" -e -f "${BASH_SOURCE[0]%/*}/sub-agent.jq" <<<"$payload" >/dev/null 2>&1 ||
    ! said=$("$jq" -er '(.tool_input.answers // .tool_response.answers) | objects
                          | [.. | strings] | join("\n")' \
      <<<"$payload" 2>/dev/null); then
    owner=false
  fi
  seat_state "$payload" "$jq" "$owner" "$said" >/dev/null 2>&1
  # SessionStart first captures the conversation its harness vouches for.
  if [[ $event = SessionStart ]]; then
    news "$payload" "$owner" "$said"
  fi
}

# A seat's prompt carries its rulebook news and the questions it may answer; a harness that
# takes no context, a worker, a client that is not the seat's own conversation and every other
# event print nothing. A compaction (a `SessionStart` from `compact`) leaves the conversation
# holding its launch's rulebook again, which its next prompt is then told about.
news() {
  local payload=$1 owner=$2 said=$3 jq event
  [[ -n ${AGENTKIT_SESSION:-} && ${AK_RUN_ROLE:-} != worker ]] || return 0
  jq=$(command -v jq) || return 0
  event=$("$jq" -r '.hook_event_name // empty' <<<"$payload")
  [[ $event = UserPromptSubmit || $event = SessionStart ]] || return 0
  # JSON contains no literal NUL; both it and a long answer travel on stdin, never argv.
  printf '%s\0%s' "$payload" "$said" | /usr/bin/env python3 -c '
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import orch
payload, said = sys.stdin.read().split("\0", 1)
payload = json.loads(payload)
if payload.get("hook_event_name") == "SessionStart":
    if payload.get("source") == "compact":
        orch.rulebook_compacted(sys.argv[2], payload.get("session_id"))
    sys.exit(0)
news = orch.prompt_news(sys.argv[2], payload.get("session_id"),
                        said if sys.argv[3] == "true" else None)
if news:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": news}}))
' "${BASH_SOURCE[0]}" "$AGENTKIT_SESSION" "$owner"
}

payload=$(/bin/cat 2>/dev/null) || payload=''
main "$payload" 2>/dev/null || true
exit 0
