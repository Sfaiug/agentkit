#!/bin/sh
# A harness with no model behind it, for every harness this directory names: each turn adds
# retry.txt unless it is there and hands in `done`, so the executor writes it and the reviewer
# passes it.  It sits in the checkout because a worker's box sees that, never a test's temporary
# directory; the program it hands in through is $AK_BIN.
case "$1" in
  usage) echo '{"meters":[],"error":"unknown: no meter for a fake"}' ;;
  auth) echo 'a fake needs no login' ;;
  interactive) echo 'sleep 600' ;;
  run)   # run <model> <effort> <workspace> <prompt-file> <out-dir> [<session-id>]
    mkdir -p "$6" && echo fake >"$6/session_id" && cd "$4" || exit 1
    [ -e retry.txt ] || echo hello >retry.txt
    "$AK_BIN" hand-in done && echo 'Handed in.' >"$6/final.md" ;;
  *) exit 2 ;;
esac
