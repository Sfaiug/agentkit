#!/bin/sh
# What a person types to install Go's ak, as ./install.sh is for Python's: every step is the
# program's own (`ak install`, go/internal/install), so it is the same on every system.
exec "$(dirname -- "$0")/bin/ak" install "$@"
