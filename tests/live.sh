#!/usr/bin/env bash
# agentkit's checks that need the outside world: real model calls on every harness, one real
# `ak run` merged on GitHub, the Discord webhook, live meters and seats, the shared browser,
# user systemd and, where docker answers, this commit installed on a bare machine.
# They are smoke.sh's live mode, so the sandbox HOME, the borrowed logins and the accounting
# are smoke.sh's own, and it runs only them (LIVE_CHECKS in tests/suite_shares.py): every
# other check ran at landing on the same commit.  The landing suite never runs them; ak runs
# this file before a host takes new agentkit code and when a harness upgrades, with
# AGENTKIT_ACCEPTANCE_REQUIRED=1, so a skipped check fails it too.
# AK_LIVE_NO_MODEL_CALLS=1 leaves out every check that makes a model call (MODEL_CALLS beside
# LIVE_CHECKS), so the host's logins pay no turn for it; a check left out is no skip.
# A live check of a commit (LIVE_RUN in agentkit/update.py: this checkout is the `tree` beside
# its `failed`) runs with this home's real records, so first it shadows Go on them and keeps what
# Go did differently in that folder's shadow.json.  The tick removes that folder once the install
# moves past the commit, so each difference confirmed keeps its runs' evidence in a case under
# ~/.agentkit/tmp/shadow/cases too, where later checks seeing it again count it, and the streak
# beside them keeps the UTC days Go agreed on in a row, which Go must hold for days before it
# takes over.  Whatever the shadow finds, or however it ends, the check exits as its suite does,
# an inherited errexit or not: Go is not yet what goes live.
here=$(dirname -- "${BASH_SOURCE[0]}")
if [[ ${AK_LIVE_FAILED:-} == */failed ]] && [ "${AK_LIVE_FAILED%/failed}/tree" -ef "$here/.." ]; then
  python3 "$here/shadow.py" --record "${AK_LIVE_FAILED%/failed}/shadow.json" \
    --cases "$HOME/.agentkit/tmp/shadow/cases" --streak "$HOME/.agentkit/tmp/shadow/streak" \
    || true
fi
export AGENTKIT_SMOKE_LIVE=1
if [ -n "${AK_LIVE_FAILED:-}" ]; then
  export AK_LIVE_FAILED_FINAL="$AK_LIVE_FAILED"
  export AK_LIVE_FAILED="$AK_LIVE_FAILED.tmp"
  : >"$AK_LIVE_FAILED"
  : >"$AK_LIVE_FAILED.spent"
fi
unset AK_SHARD AK_ONLY   # host certification always exercises the whole live suite
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/smoke.sh"
