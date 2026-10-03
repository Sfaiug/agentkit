#!/usr/bin/env bash
# agentkit's checks that need the outside world: real model calls on every harness, one real
# `ak run` merged on GitHub, the Discord webhook, live meters and seats, the shared browser.
# They are smoke.sh's live mode, so the sandbox HOME, the borrowed logins and the accounting
# are smoke.sh's own and every other check of it runs beside them.  The landing suite never
# runs them; ak runs this file before a host takes new agentkit code and when a harness
# upgrades, with AGENTKIT_ACCEPTANCE_REQUIRED=1, so a skipped check fails it too.
export AGENTKIT_SMOKE_LIVE=1
unset AK_SHARD   # host certification always exercises the whole live suite
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/smoke.sh"
