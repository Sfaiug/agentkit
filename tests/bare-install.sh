#!/usr/bin/env bash
# Install this checkout's HEAD commit in a bare Debian container:
#   git archive HEAD | timeout -k 30 OUTER docker run --rm -i docker.io/library/debian:trixie-slim \
#     timeout -k 30 INNER sh -c "$inner"
# Inside the container, $inner adds sudo, git and ca-certificates and a user who may sudo, unpacks
# standard input to ~/agentkit as that user, makes it a git checkout of one commit, runs
# ~/agentkit/install.sh with no terminal, and then runs `ak --help` in that user's login shell.
# Exits 0 only if the install and `ak --help` both exit 0; otherwise prints the last lines of what
# failed and exits 1.
# Runs the user's git and docker as set up: what either does under an unusual setup, and a
# container docker made and never started, are theirs.
set -euo pipefail

INNER=900   # 6x the 150s bare install measured on 26 Nov 2026, for slow Debian mirrors
OUTER=1020  # INNER plus its 30s kill grace and 90s to pull debian:trixie-slim and start/remove it

inner='
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq </dev/null
apt-get install -y -qq --no-install-recommends sudo git ca-certificates </dev/null
useradd -m -s /bin/bash acme </dev/null
printf "acme ALL=(ALL) NOPASSWD:ALL\n" >/etc/sudoers.d/acme
chmod 0440 /etc/sudoers.d/acme
su - acme -c "mkdir -p ~/agentkit && tar -xf - -C ~/agentkit"
su - acme -c "
  set -eu
  git -C ~/agentkit init -q -b main
  git -C ~/agentkit add -f -A
  git -C ~/agentkit -c user.name=acme -c user.email=acme@example.com commit -q -m init
  ~/agentkit/install.sh
" </dev/null
su - acme -c "ak --help" </dev/null
'

if ! out=$({
  git archive HEAD | timeout -k 30 "$OUTER" docker run --rm -i docker.io/library/debian:trixie-slim \
    timeout -k 30 "$INNER" sh -c "$inner"
} 2>&1); then
  [ -z "$out" ] || printf '%s\n' "$out" | tail -n 40 >&2 || true
  exit 1
fi
