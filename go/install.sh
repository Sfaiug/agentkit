#!/bin/sh
# What a person types to install Go's ak, as ./install.sh is for Python's: every step is the
# program's own (`ak install`, go/internal/install), so it is the same on every system.  A step
# changing the host has a section here too, headed as install.sh's, that its answer keys run
# alone with SANDBOX set, so each finds the program itself.
"$(dirname -- "$0")/bin/ak" install "$@" || exit
SANDBOX=0
if "$(dirname -- "$0")/bin/ak" install --sandboxed; then SANDBOX=1; fi

# --- a crashed program leaves no core dump file -------------------------------
[ "$SANDBOX" = 1 ] || "$(dirname -- "$0")/bin/ak" install --core-dumps

# --- (g2a) swapped memory stays compressed in RAM: not Go's yet ---------------
