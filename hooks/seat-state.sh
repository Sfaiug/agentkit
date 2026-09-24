#!/bin/bash
# The one hook agentkit asks a harness to run, for every lifecycle event it offers.
#
# It writes down what happened and decides nothing.  What the seat is doing -- the event, its
# payload discriminator and the moment it arrived -- goes to ~/.agentkit/state/hook-<seat>.json,
# and the classifier reads adapters/<harness>.toml to say what that event means.  A prompt also
# starts a turn, and ~/.agentkit/state/stop-<seat>.json is where that moment is kept, for
# hooks/orchestrator-stop.sh to judge the turn's end against.  On a turn's end it also stamps
# the time, the context size and the processes it ran under into the file
# tools/idle-compact.py polls, which is the half of the idle auto-compact that lives outside the
# wrapper; that last part is what lets the wrapper tell the seat's own harness from any other one
# the owner started inside it, which would otherwise inherit $IDLE_COMPACT_STATE and overwrite it.
#
# Every event it writes down also has the seat looked at again at once (`watch.hook_look`), so
# the seat's record and its status bar say what the event means now rather than at the next
# menu draw or tick.  The look runs in the background, in a session of its own, holding
# nothing of the harness's: the harness never waits on it.
#
# A worker is silent here as it is everywhere: a headless `ak worker` runs the same harness with
# the same hooks, and a seat's row must never be moved by one.  No $AGENTKIT_SESSION, or
# AK_RUN_ROLE=worker, and this writes nothing and exits 0.
#
# Every failure is exit 0 with nothing written: a hook that fails loudly is a harness that stops.

set -u

# Look at the seat again, off the harness's path: see the header.  Only from inside a tmux
# pane, which is where every seat's harness runs; watch.hook_look checks the pane is the seat's,
# on the seat's own server.  `heard`, on Claude's Stop only, is when this hook heard it.
look() {
  local seat=$1 heard=${2:-}
  [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] || return 0
  ( /usr/bin/env python3 -c '
import os, sys
from pathlib import Path
try:
    os.setsid()     # a session of its own: a harness ending the hook group ends none of this
except OSError:
    pass
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import watch
watch.hook_look(sys.argv[2], float(sys.argv[3]) if sys.argv[3] else None)
' "${BASH_SOURCE[0]}" "$seat" "$heard" </dev/null >/dev/null 2>&1 & )
}

seat_state() {
  local payload=$1 jq=$2 seat event kind text ts dir tmp row next hop
  seat=${AGENTKIT_SESSION:-}
  [[ -n $seat ]] || return 0
  [[ ${AK_RUN_ROLE:-} != worker ]] || return 0
  # the seat's name is one component of a path here as it is everywhere else
  case "$seat" in */*|.|..|"") return 0 ;; esac

  event=$("$jq" -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null) || return 0
  [[ -n $event ]] || return 0
  ts=$(/usr/bin/env python3 -c 'import time; print(time.time())' 2>/dev/null) || ts=$(/bin/date +%s)
  # A Stop that hands over the background work in flight -- Claude Code's -- is written down by
  # hooks/orchestrator-stop.sh, which runs beside this and is the one that knows whether the
  # turn ended there.  Written here too, it would read as the turn over until that one decided;
  # the look is made again once that one's word lands.
  if [[ $event = Stop ]] &&
    "$jq" -e '.background_tasks | type == "array"' <<<"$payload" >/dev/null 2>&1; then
    look "$seat" "$ts"
    return 0
  fi
  # the payload field that tells one kind of that event from another: Claude's Notification
  # carries notification_type, Codex's PermissionRequest carries the tool it wants -- and one
  # harness spells both camelCase, so the twins are read beside them
  kind=$("$jq" -r '.notification_type // .notificationType // .tool_name // .toolName // empty' \
    <<<"$payload" 2>/dev/null) || kind=''
  text=$("$jq" -r '(.message // .title // "") | .[0:160]' <<<"$payload" 2>/dev/null) || text=''

  dir="$HOME/.agentkit/state"
  # The record the seat's row reads is under the name the seat goes by now: `ak orch rename`
  # leaves a pointer at the old one, and the harness carries its launch name for its whole life.
  row=$seat
  for hop in 1 2 3 4 5 6 7 8; do
    next=$("$jq" -r '.renamed | strings' "$dir/session-$row.json" 2>/dev/null) || break
    case "$next" in */*|.|..|"") break ;; esac
    row=$next
  done
  # Claude says its prompt is idle a minute after a turn ends whether or not background work is
  # in flight.  A seat waiting on work it started is not idle, and the Stop that said so stands
  # until that work's notification begins a turn; a question going up still replaces it.
  if [[ $event = Notification && $kind = idle_prompt ]] &&
    [[ $("$jq" -r '"\(.event)/\(.kind)"' "$dir/hook-$row.json" 2>/dev/null) = Stop/background ]]
  then
    return 0
  fi
  /bin/mkdir -p -- "$dir" || return 0
  tmp="$dir/hook-$row.json.tmp.$$"
  "$jq" -n --arg session "$seat" --arg event "$event" --arg kind "$kind" --arg text "$text" \
    --argjson at "$ts" \
    '{session: $session, event: $event, kind: $kind, text: $text, at: $at}' \
    >"$tmp" || { /bin/rm -f -- "$tmp"; return 0; }
  /bin/mv -f -- "$tmp" "$dir/hook-$row.json" || /bin/rm -f -- "$tmp"
  look "$seat"

  # A new prompt is a new turn: hooks/orchestrator-stop.sh judges that turn against this
  # moment, and the two blocks it is allowed start again from zero here.
  [[ $event = UserPromptSubmit ]] || return 0
  tmp="$dir/stop-$seat.json.tmp.$$"
  "$jq" -n --arg session "$seat" --argjson turn "$ts" \
    '{session: $session, turn: $turn, blocks: 0}' \
    >"$tmp" || { /bin/rm -f -- "$tmp"; return 0; }
  /bin/mv -f -- "$tmp" "$dir/stop-$seat.json" || /bin/rm -f -- "$tmp"
}

# The process that ran this hook, and the ones above it, newest first.  The wrapper looks for
# its own forkpty child in this list rather than trusting $PPID alone, because the harness is
# never the hook's own parent: Claude Code 2.1.263 runs a hook as `sh -c bash <script>`, and the
# `codex` on PATH is a node shim that spawns the native binary underneath it.
ancestry() {
  local p=$1 n=0
  while [[ -n $p && $p -gt 1 && $n -lt 8 ]]; do
    printf '%s\n' "$p"
    if [[ -r /proc/$p/status ]]; then
      p=$(/bin/sed -n 's/^PPid:[[:space:]]*//p' "/proc/$p/status" 2>/dev/null)
    else
      p=$(/bin/ps -o ppid= -p "$p" 2>/dev/null | /usr/bin/tr -d ' ')
    fi
    n=$((n + 1))
  done
}

# The context the next turn would start on, from whichever of the three shapes a harness
# writes: Claude Code's assistant `usage`, Codex's `token_count` event in the rollout its Stop
# hook names, and Grok's `_meta.totalTokens` in the update stream its Stop hook names -- the
# turn's own total, input with output, a conservative stand-in for the context the next turn
# starts on.  Per line, so one truncated line costs that line and not the answer; widening
# windows, so a tool-heavy turn with no usage near the end is still found without reading the
# whole file.
context_tokens() {
  local transcript=$1 jq=$2 window tokens
  for window in 400 4000 20000; do
    tokens=$(
      /usr/bin/tail -n "$window" -- "$transcript" 2>/dev/null |
        "$jq" -Rrn '
          [ inputs
            | fromjson?
            | if (.type == "assistant" and (.message.usage? != null))
              then ((.message.usage.input_tokens // 0)
                    + (.message.usage.cache_read_input_tokens // 0)
                    + (.message.usage.cache_creation_input_tokens // 0))
              elif ((.payload? | objects | .type) == "token_count"
                    and (.payload.info.last_token_usage? != null))
              then (.payload.info.last_token_usage.total_tokens // 0)
              elif ((.params? | objects | ._meta?.totalTokens?) != null)
              then (.params._meta.totalTokens // 0)
              else empty end
            | select(. > 0)
          ] | last // empty
        ' 2>/dev/null
    ) || tokens=''
    if [[ $tokens =~ ^[0-9]+$ ]]; then printf '%s\n' "$tokens"; return 0; fi
  done
  return 1
}

idle_compact() {
  local payload=$1 jq=$2 transcript session_id tokens ts tmp pids
  [[ -n ${IDLE_COMPACT_STATE:-} ]] || return 0
  transcript=$("$jq" -r '.transcript_path // empty' <<<"$payload" 2>/dev/null) || transcript=''
  session_id=$("$jq" -r '.session_id // empty' <<<"$payload" 2>/dev/null) || session_id=''

  # a harness whose session lives behind its own API rather than in a transcript file hands
  # the size over outright; anything else shaped is read from the transcript below
  tokens=$("$jq" -r '.context_tokens // empty' <<<"$payload" 2>/dev/null) || tokens=''
  # a size nobody could read is not a size of zero, and zero would switch compaction off: with
  # nothing to say, this says nothing and the last good stamp stands
  if [[ ! $tokens =~ ^[1-9][0-9]*$ ]]; then
    [[ -n $transcript && -r $transcript ]] || return 0
    tokens=$(context_tokens "$transcript" "$jq") || return 0
  fi

  pids=$(ancestry "$PPID" | "$jq" -Rn '[inputs | tonumber?]' 2>/dev/null) || pids=''
  [[ -n $pids ]] || pids="[$PPID]"   # --argjson refuses an empty one, and the record with it
  ts=$(/usr/bin/env python3 -c 'import time; print(time.time())' 2>/dev/null) || ts=$(/bin/date +%s)
  tmp="${IDLE_COMPACT_STATE}.tmp.$$"
  /bin/mkdir -p -- "$(/usr/bin/dirname -- "$IDLE_COMPACT_STATE")" || return 0
  "$jq" -n \
    --argjson ts "$ts" \
    --argjson context_tokens "$tokens" \
    --arg session_id "$session_id" \
    --argjson pid "$PPID" \
    --argjson pids "$pids" \
    '{ts: $ts, context_tokens: $context_tokens, session_id: $session_id, pid: $pid, pids: $pids}' \
    >"$tmp" || { /bin/rm -f -- "$tmp"; return 0; }
  /bin/mv -f -- "$tmp" "$IDLE_COMPACT_STATE" || /bin/rm -f -- "$tmp"
}

main() {
  umask 077
  local jq payload event
  jq=$(command -v jq) || return 0
  payload=$(/bin/cat) || payload=''
  seat_state "$payload" "$jq"
  # the compaction stamp belongs to the end of a turn; an event that is not one leaves it alone
  event=$("$jq" -r '.hook_event_name // "Stop"' <<<"$payload" 2>/dev/null) || event=Stop
  [[ $event = Stop ]] || return 0
  idle_compact "$payload" "$jq"
}

main >/dev/null 2>&1 || true
exit 0
