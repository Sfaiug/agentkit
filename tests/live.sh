#!/usr/bin/env bash
# agentkit's checks that need the outside world: real model calls on every harness, one real
# `ak run` merged on GitHub, the Discord webhook, live meters and seats, the shared browser
# and user systemd.
# They are smoke.sh's live mode, so the sandbox HOME, the borrowed logins and the accounting
# are smoke.sh's own, and it runs only them (LIVE_CHECKS in tests/suite_shares.py): every
# other check ran at landing on the same commit.  The landing suite never runs them; ak runs
# this file before a host takes new agentkit code and when a harness upgrades, with
# AGENTKIT_ACCEPTANCE_REQUIRED=1, so a skipped check fails it too.
# A live check of a commit (LIVE_RUN in agentkit/update.py: this checkout is the `tree` beside
# its `failed`) runs with this home's real records, so first it shadows Go on them and keeps what
# Go did differently in that folder's shadow.json.  Whatever the shadow finds, or however it
# ends, the check exits as its suite does, an inherited errexit or not: Go is not yet what goes
# live.
here=$(dirname -- "${BASH_SOURCE[0]}")
if [ -n "${AK_LIVE_FAILED:-}" ] && [ "${AK_LIVE_FAILED%/failed}/tree" -ef "$here/.." ]; then
  python3 "$here/shadow.py" --record "${AK_LIVE_FAILED%/failed}/shadow.json" || true
fi
export AGENTKIT_SMOKE_LIVE=1
if [ -n "${AK_LIVE_FAILED:-}" ]; then
  export AK_LIVE_FAILED_FINAL="$AK_LIVE_FAILED"
  export AK_LIVE_FAILED="$AK_LIVE_FAILED.tmp"
  : >"$AK_LIVE_FAILED"
  : >"$AK_LIVE_FAILED.spent"
fi
unset AK_SHARD   # host certification always exercises the whole live suite
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/smoke.sh"
