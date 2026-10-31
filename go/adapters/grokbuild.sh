#!/usr/bin/env bash
# The Go build's adapter: for the harness this file is named after, the verb is the Go
# program's own, handed the checkout the stub sits in.
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$root/bin/ak" adapter "$root" "$(basename -- "${BASH_SOURCE[0]}" .sh)" "$@"
