#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$SOURCE/bootstrap.py" "$@"
