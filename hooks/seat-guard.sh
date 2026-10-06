#!/usr/bin/env bash
# hooks/seat-guard.sh -- the PreToolUse hook: before a seat's shell command starts, refuse one
# that agentkit/guard.py's rules refuse.  Every harness whose adapter installs it hands it the
# same payload and reads the same refusal (`permissionDecision: deny`, with the reason the
# model sees).  Only a seat is guarded: no $AGENTKIT_SESSION, or AK_RUN_ROLE=worker, and it says
# nothing.  A command that names no tmux is let through before any Python starts.  Every
# failure lets the command run: a guard that fails loudly is a seat that cannot work.
set -u
seat=${AGENTKIT_SESSION:-}
[[ -n $seat && ${AK_RUN_ROLE:-} != worker ]] || exit 0
payload=$(cat) || exit 0
[[ $payload == *tmux* ]] || exit 0
/usr/bin/env python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve().parents[1]))
from agentkit import guard
guard.main()
' "${BASH_SOURCE[0]}" <<<"$payload" 2>/dev/null
exit 0
