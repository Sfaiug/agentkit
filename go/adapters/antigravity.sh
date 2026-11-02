#!/usr/bin/env bash
# The Go build's adapter: for the harness this file is named after, the verb is the Go
# program's own, handed the checkout the stub sits in, but `hooks`, which are per launch.
case ${1:-} in
hooks) echo "agy: hooks are installed per launch by adapters/antigravity.sh interactive (PreInvocation, Stop); nothing to write here"; exit 0 ;;
esac
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$root/bin/ak" adapter "$root" "$(basename -- "${BASH_SOURCE[0]}" .sh)" "$@"
