#!/usr/bin/env bash
# The Go build's adapter: for the harness this file is named after, the verb is the Go
# program's own, handed the checkout the stub sits in, but `hooks`: `interactive` hands this
# harness its hooks as a plugin on each launch, so nothing is written a stale copy of could
# linger in.  One database keeps its logins and its conversations, so a named account is
# refused: a login of its own could resume none.
case ${1:-} in
hooks)
  [ -z "${AGENTKIT_ACCOUNT:-}" ] || {
    echo "account $AGENTKIT_ACCOUNT refused; one database keeps logins and conversations, so a login of its own cannot resume one" >&2
    exit 1; }
  echo "hooks are installed per launch by \`interactive\`, as a plugin; nothing to write here"; exit 0 ;;
esac
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$root/bin/ak" adapter "$root" "$(basename -- "${BASH_SOURCE[0]}" .sh)" "$@"
