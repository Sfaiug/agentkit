#!/usr/bin/env bash
# The Go build's adapter: for the harness this file is named after, the verb is the Go
# program's own, handed the checkout the stub sits in, but `hooks`: `interactive` hands this
# harness its hooks on each launch's command line, so nothing is written a stale copy of could
# linger in.
case ${1:-} in
hooks) echo "hooks are given per launch by \`interactive\`; nothing to write here"; exit 0 ;;
esac
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$root/bin/ak" adapter "$root" "$(basename -- "${BASH_SOURCE[0]}" .sh)" "$@"
