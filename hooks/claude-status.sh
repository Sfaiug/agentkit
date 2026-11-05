#!/bin/bash
# The report belongs to the status render's conversation,
# never its launch name; a detached look reads whatever report stands when it gets there.
set -u
payload=$(cat; printf .)
payload=${payload%.}
# A status command that ignores stdin must not end reporting by closing its pipe.
trap '' PIPE
printf '%s' "$payload" 2>/dev/null
[[ -n ${AGENTKIT_SESSION:-} && ${AK_RUN_ROLE:-} != worker ]] || exit 0
report=$(jq -er 'select(.session_id | strings | test("^[A-Za-z0-9_-]+$"))
    | select(.model.id | strings | length > 0)
    | .session_id, ({model: .model.id, effort: (.model.effort // .effort.level // null)} | tojson)' \
    <<<"$payload" 2>/dev/null) || exit 0
conversation=${report%%$'\n'*}
report=${report#*$'\n'}
dir="$HOME/.agentkit/state"
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
( /usr/bin/env python3 -c '
import os, sys
from pathlib import Path
try:
    os.setsid()
except OSError:
    pass
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import watch
watch.hook_look(sys.argv[2])
' "${BASH_SOURCE[0]}" "$AGENTKIT_SESSION" </dev/null >/dev/null 2>&1 & )
