#!/usr/bin/env bash
# tests/fixtures/adapters/echo.sh -- a fourth harness, with no harness behind it.
#
# The proof that adding one is an adapter pair and a config.toml line: every verb the contract
# in docs/guide.md names, answered in a dozen lines, with agentkit planning a seat on it,
# running a loop through it, showing its meter and listing it in an update plan -- and not one
# line of Python anywhere for it.  Paired with echo.toml; used by tests/test_v5al.py and by
# smoke check 46.  Nothing here reaches a network, a harness or the owner's files.
set -uo pipefail

case "${1:-}" in
  run)   # run <model> <effort> <workspace> <prompt-file> <out-dir> [<session-id>]
    out=$6
    mkdir -p -- "$out"
    # the last line the prompt asked for, echoed back: this harness does exactly that
    grep -v '^[[:space:]]*$' -- "$5" | tail -1 >"$out/final.md" || : >"$out/final.md"
    printf 'echo fixture: %s on %s\n' "$2" "$3" >"$out/stderr.log"
    : >"$out/session_id"           # nothing to resume: it keeps no conversation
    exit 0
    ;;
  interactive)   # interactive <model> <effort> [<session-id> [new]]
    [ "$#" -le 3 ] || exit 3       # ... so its TUI cannot be told one either
    printf '%s\n' "${SHELL:-/bin/sh}"
    ;;
  usage)   # one meter, always the same, with a window that is always still open
    printf '{"provider":"test","meters":[{"name":"weekly","used":42,"resets_at":%s,"window_secs":604800}],"error":null}\n' \
      "$(( $(date +%s) + 86400 ))"
    ;;
  hooks)
    echo "echo has no lifecycle hooks; nothing was installed"
    ;;
  auth)   # nothing to log in to, so a turn on it can always authenticate
    echo "the echo fixture needs no login"
    ;;
  install|login)
    echo "the echo fixture needs no $1"
    ;;
  *)
    echo "usage: echo.sh run|interactive|usage|hooks|auth|install|login" >&2
    exit 2
    ;;
esac
