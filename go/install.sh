#!/bin/sh
# What a person types to install Go's ak, as ./install.sh is for Python's: every step is the
# program's own (`ak install`, go/internal/install), so it is the same on every system.  A step
# changing the host has a section here too, headed as install.sh's, that its answer keys run
# alone with SANDBOX set, so each finds the program itself.
"$(dirname -- "$0")/bin/ak" install "$@" || exit
"$(dirname -- "$0")/bin/ak" install --sandboxed
# only a plain no lets a step change the host: a probe that failed says nothing of HOME
case $? in 0) SANDBOX=1 ;; 1) SANDBOX=0 ;; *) exit ;; esac

# --- a crashed program leaves no core dump file -------------------------------
[ "$SANDBOX" = 1 ] || "$(dirname -- "$0")/bin/ak" install --core-dumps

# --- (g2a) swapped memory stays compressed in RAM: not Go's yet ---------------
