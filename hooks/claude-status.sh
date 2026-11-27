#!/bin/bash
# The report belongs to the status render's conversation,
# never its launch name; a detached look reads whatever report stands when it gets there.
set -u
# The moment this render began, by which its limits are judged, taken before
# anything the hook reads: bash 5's clock.  An older bash (macOS's 3.2) has none, and no moment
# would leave a Mac's seats never reporting their login's usage, so there it is perl's
# Time::HiRes, which macOS ships, to the microsecond: one more process a render, only there,
# beside the cat and jq every render runs.  `date`'s whole second would let an older render pass
# as newer, and jq's `now` comes after the payload is read.  A perl that gives no such number
# leaves no moment, and no moment hands in no limits.
rendered=${EPOCHREALTIME:-}
if [[ -z $rendered ]]; then
  rendered=$(perl -MTime::HiRes=gettimeofday -e 'printf "%d.%06d", gettimeofday' 2>/dev/null) &&
    [[ $rendered =~ ^[0-9]+[.][0-9]+$ ]] || rendered=
fi
payload=$(cat; printf .)
payload=${payload%.}
# A status command that ignores stdin must not end reporting by closing its pipe.
trap '' PIPE
printf '%s' "$payload" 2>/dev/null
# Close stdout at once so a piped owner command receives EOF without waiting on jq.
exec >/dev/null
[[ -n ${AGENTKIT_SESSION:-} && ${AK_RUN_ROLE:-} != worker ]] || exit 0
# Every render runs this one streaming jq with tagged lines: `c:`, `r:` and `l:` are the first
# valid conversation, model report and login limit windows in $1 (`<window> <used%> <resets_at>`, arithmetic spelling).  Streaming
# keeps a valid object before malformed trailing text; tagging stops empty objects shifting fields.
conversation= report=
found=0
windows=()
while IFS= read -r line; do
  case $line in
    c:*) (( found += 1 )); (( found == 1 )) && conversation=${line#c:} ;;
    r:*) (( found == 1 )) && report=${line#r:} ;;
    l:*) (( found == 1 )) && windows+=("${line#l:}") ;;
  esac
done < <(jq -r --arg limits "${1:-}" '
    objects
    | (select(.session_id | strings | test("^[A-Za-z0-9_-]+$"))
       | select(.model | objects | .id | strings | length > 0)
       | "c:\(.session_id)", "r:\({model: .model.id, effort: (.model.effort // .effort.level // null)} | tojson)",
         (.[$limits] | objects | {five_hour, seven_day} | to_entries[]
          | select(.value | objects | [.used_percentage, .resets_at] | all(type == "number"))
          | "l:\(.key) \(.value.used_percentage + 0) \(.value.resets_at + 0)"))' <<<"$payload" 2>/dev/null)
[[ -n $conversation && -n $report ]] || exit 0
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
# Guard empty array expansion: macOS's bash 3.2 treats empty `"${windows[@]}"` as unset under `set -u`.
if [[ -n $rendered && ${#windows[@]} -gt 0 ]]; then
  for window in "${windows[@]}"; do
    [[ $note == *"\"${window%% *}\": [\"${AGENTKIT_ACCOUNT:-}\", \"${window#* }\","* ]] || {
      start 'watch.hook_meters(*sys.argv[2:])' "$AGENTKIT_SESSION" "$conversation" \
        "${AGENTKIT_ACCOUNT:-}" "${rendered/[!0-9]/.}" "${windows[@]}"
      break
    }
  done
fi
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
