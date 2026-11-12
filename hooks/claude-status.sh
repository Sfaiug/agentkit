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
# Every render runs this one jq: its conversation, its model, and its login's limits where the
# API has reported them (2.1.322's `rate_limits`).
report=$(jq -er 'select(.session_id | strings | test("^[A-Za-z0-9_-]+$"))
    | select(.model.id | strings | length > 0)
    | .session_id, ({model: .model.id, effort: (.model.effort // .effort.level // null)} | tojson),
      (.rate_limits | objects | {five_hour, seven_day} | select(any(.[]; type == "object")) | tojson)' \
    <<<"$payload" 2>/dev/null) || exit 0
conversation=${report%%$'\n'*}
report=${report#*$'\n'}
limits=
[[ $report != *$'\n'* ]] || { limits=${report#*$'\n'}; report=${report%%$'\n'*}; }
dir="$HOME/.agentkit/state"
umask 077
trap 'rm -f -- "${tmp:-}"' EXIT
trap 'exit 0' HUP INT TERM
# keep KIND TEXT: TEXT is what state/KIND-<conversation>.json says from now on, written whole
# through a dot-file beside it; 1, with nothing started, where it said so already.  Read with a
# builtin: a render that changed nothing costs the jq alone.
keep() {
  local path="$dir/$1-$conversation.json" was=
  IFS= read -r -d '' was 2>/dev/null <"$path"
  [[ $was != "$2"$'\n' ]] && mkdir -p -- "$dir" && tmp=$(mktemp "$dir/.$1-$conversation.XXXXXX") &&
    printf '%s\n' "$2" >"$tmp" && mv -f -- "$tmp" "$path"
}
# start CODE ARG...: agentkit's CODE, its words in sys.argv[2:], in a session of its own
start() {
  ( /usr/bin/env python3 -c 'import os, sys
from pathlib import Path
try:
    os.setsid()
except OSError:
    pass
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
'"$1" "${BASH_SOURCE[0]}" "${@:2}" </dev/null >/dev/null 2>&1 & )
}
# Limits are kept per conversation, not per login: a seat that has not asked the API since
# renders its older numbers, and those would replace another seat's newer ones.
[[ -z $limits ]] || ! keep limits "${AGENTKIT_ACCOUNT:-} $limits" || start '
from agentkit import watch
watch.hook_meters(*sys.argv[2:])' "$AGENTKIT_SESSION" "${AGENTKIT_ACCOUNT:-}" "$limits"
keep model "$report" && [[ -n ${TMUX:-} && -n ${TMUX_PANE:-} ]] || exit 0
start '
from agentkit import watch
watch.hook_look(sys.argv[2])' "$AGENTKIT_SESSION"
