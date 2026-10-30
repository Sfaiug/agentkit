#!/usr/bin/env bash
# The Go build's adapter: for the harness this file is named after, the verb is the Go
# program's own, handed the checkout the stub sits in, but `hooks`: this harness runs none of
# ak's, a hook that does not answer its tool calls denying every one, and its seats are read
# off the screen.
case ${1:-} in
hooks) echo "no hooks installed; its seats are read off the screen"; exit 0 ;;
esac
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$root/bin/ak" adapter "$root" "$(basename -- "${BASH_SOURCE[0]}" .sh)" "$@"
