#!/bin/bash
# The end-of-turn rule, where prose cannot enforce it: on every Stop of an orchestrator seat,
# and before its harness draws a question prompt, this hands the harness the answer
# `turn_end.judge` gives (agentkit/turn_end.py, where the rule is told and kept), judged by the
# warm looker, which has its imports done and the runs parsed, else here, cold (`looker.take`).
#
# A worker is silent here as it is everywhere: no $AGENTKIT_SESSION, or AK_RUN_ROLE=worker,
# and this decides nothing and exits 0.
#
# Every failure is exit 0 with nothing printed: a hook that fails loudly is a harness that
# stops, and an unreadable transcript is no evidence that anything was left undone.

set -u

main() {
  umask 077
  local seat payload
  seat=${AGENTKIT_SESSION:-}
  [[ -n $seat ]] || return 0
  [[ ${AK_RUN_ROLE:-} != worker ]] || return 0
  # the seat's name is one component of a path here as it is everywhere else
  case "$seat" in */*|.|..|"") return 0 ;; esac
  payload=$(/bin/cat) || return 0
  # a sub-agent's Stop is never this seat's end, by the rule hooks/seat-state.sh reads it with
  if /usr/bin/env jq -e -f "${BASH_SOURCE[0]%/*}/sub-agent.jq" <<<"$payload" >/dev/null 2>&1
  then
    return 0
  fi
  # The hook's own JSON goes on stdin, where the harness put it.  A turn that moved a lot of
  # tool output ends in a payload no argument list and no environment would carry -- Linux
  # refuses a single one past 128 KB -- and a hook that cannot be handed the turn it is judging
  # would decide nothing at all, quietly.
  printf '\0%s' "$payload" |
    /usr/bin/env python3 "${BASH_SOURCE[0]%/*}/../agentkit/looker.py" "$seat" "" judge
}

main 2>/dev/null || true
exit 0
