#!/usr/bin/env bash
# The Go build's hook: the event its harness hands it goes to the Go program's own `ak hook`, by
# this file, with the harness's process that ran it.  ak runs beside this shell rather than in its
# place, as Python's hook runs its own: a harness that ends a hook still running, as OpenCode's
# plugin does after 5 seconds, ends the shell, and ak finishes the follow it began.
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
"$root/bin/ak" hook "${BASH_SOURCE[0]}" "$PPID"
