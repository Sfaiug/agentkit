#!/bin/bash
# turn.sh WORK AK BRANCH DEFAULT ARGV..., a model turn on a machine (agentkit/machine_turn.py),
# in its container: WORK, the checkout at its path here, cloned as piece.sh clones it, with what
# the checkout left uncommitted; then the adapter's ARGV, ak's bin and the harness program on
# PATH. At its end /in/back.bundle holds refs/ak/left, a commit of what the turn left uncommitted
# on its HEAD, and /in/code the turn's exit: its own is 0, so the helper's exits keep their meaning.
work=$1 ak=$2 branch=$3 default=$4
shift 4
fail() { echo "ak machine: $*" >&2; exit 253; }
read -r tree base </in/heads
git init -q --bare ${default:+-b "$default"} /in/origin.git &&
  echo /mirror/objects >/in/origin.git/objects/info/alternates &&
  { [ -z "$default" ] || git -C /in/origin.git update-ref "refs/heads/$default" "$base"; } &&
  git clone -q --no-checkout /in/origin.git "$work" && cd "$work" &&
  git checkout -q ${branch:+-B "$branch"} "$tree" || fail "the tree did not check out"
[ ! -f /in/exclude ] || cp /in/exclude .git/info/exclude || fail "info/exclude did not copy"
# Each uncommitted path goes, a directory in its way too, then comes back as the checkout has it.
while IFS= read -r -d '' path; do rm -rf -- "$path"; done </in/paths
[ ! -d /in/dirty ] || cp -a /in/dirty/. . || fail "the uncommitted paths did not apply"
while IFS= read -r -d '' pair; do export "$pair"; done </in/env
export PATH="/harness:$ak/bin:$PATH"
# A harness's login shell (`bash -lc`) starts over from /etc/profile's PATH, and reads this after
# it: it would find neither ak nor what the image adds (seen on a real machine, 30 Oct 2026).
printf 'PATH=%q\n' "$PATH" >>"$HOME/.profile"
"$@"
code=$?
export GIT_INDEX_FILE=/in/left.index
git read-tree HEAD && git add -A && git update-ref refs/ak/left "$(git -c user.name=ak \
  -c user.email=ak@localhost commit-tree "$(git write-tree)" -p HEAD -m left)" &&
  git bundle create -q /in/back.bundle refs/ak/left "^$tree" && echo "$code" >/in/code ||
  fail "what the turn did could not be bundled"
