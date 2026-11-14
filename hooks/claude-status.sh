#!/bin/bash
# The report belongs to the status render's conversation,
# never its launch name; a detached look reads whatever report stands when it gets there.
set -u
# The moment this render began, by which its limits are judged: bash 5's clock, taken before
# anything the hook reads.  An older bash (macOS's 3.2) has none, and any other clock is either
# later than the render's start or a process on every render: no moment, no hand-in, so its
# seats' usage comes from the endpoint.
rendered=${EPOCHREALTIME:-}
payload=$(cat; printf .)
payload=${payload%.}
# A status command that ignores stdin must not end reporting by closing its pipe.
trap '' PIPE
printf '%s' "$payload" 2>/dev/null
[[ -n ${AGENTKIT_SESSION:-} && ${AK_RUN_ROLE:-} != worker ]] || exit 0
# Every render runs this one jq: its conversation, its model, and each window of its login's
# limits in the field its adapter names ($1), as `<window> <used%> <resets_at>` in arithmetic's
# one spelling of a number (jq 1.7 keeps a literal's own: 20.0 is no change from 20).
IFS=$'\n' read -r -d '' -a said < <(jq -r --arg limits "${1:-}" '
    select(.session_id | strings | test("^[A-Za-z0-9_-]+$")) | select(.model.id | strings | length > 0)
    | .session_id, ({model: .model.id, effort: (.model.effort // .effort.level // null)} | tojson),
      (.[$limits] | objects | {five_hour, seven_day} | to_entries[]
       | select(.value | objects | [.used_percentage, .resets_at] | all(type == "number"))
       | "\(.key) \(.value.used_percentage + 0) \(.value.resets_at + 0)")' <<<"$payload" 2>/dev/null)
# Its lines as "$@": macOS's bash 3.2 takes an empty array or slice for unset under `set -u`.
[[ -n ${said[1]:-} ]] && set -- "${said[@]}" || exit 0
conversation=$1 report=$2
shift 2
dir="$HOME/.agentkit/state"
# start CODE ARG...: agentkit's CODE, its words in sys.argv[2:], in a session of its own
start() {
  ( /usr/bin/env python3 -c 'import os, sys
from pathlib import Path
try:
    os.setsid()
except OSError:
    pass
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import watch
'"$1" "${BASH_SOURCE[0]}" "${@:2}" </dev/null >/dev/null 2>&1 & )
}
# With a moment, a window that reads otherwise than the note holds it, as watch.hook_meters
# writes it, hands every window of the render to that, the note's one writer, with the moment
# (a locale's decimal comma made a point).  This read takes no lock: a note read half-written
# or a moment old only costs one more hand-in, which the lock judges.
note=
IFS= read -r -d '' note 2>/dev/null <"$dir/limits-$conversation.json"
for window in ${rendered:+"$@"}; do
  [[ $note == *"\"${window%% *}\": [\"${AGENTKIT_ACCOUNT:-}\", \"${window#* }\","* ]] || {
    start 'watch.hook_meters(*sys.argv[2:])' "$AGENTKIT_SESSION" "$conversation" \
      "${AGENTKIT_ACCOUNT:-}" "${rendered/[!0-9]/.}" "$@"
    break
  }
done
path="$dir/model-$conversation.json"
kept=$(cat "$path" 2>/dev/null) || kept=
[[ $report != "$kept" ]] || exit 0
umask 077
mkdir -p -- "$dir" || exit 0
tmp=$(mktemp "$dir/.model-$conversation.XXXXXX") || exit 0
trap 'rm -f -- "$tmp"' EXIT
trap 'exit 0' HUP INT TERM
printf '%s\n' "$report" >"$tmp" && mv -f -- "$tmp" "$path" || exit 0
[[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] || exit 0
start 'watch.hook_look(sys.argv[2])' "$AGENTKIT_SESSION"
