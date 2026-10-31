#!/usr/bin/env bash
# The Go build's hook: the event its harness hands it goes to the Go program's own `ak hook`,
# under this file's name.
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$root/bin/ak" hook "$(basename -- "${BASH_SOURCE[0]}" .sh)"
