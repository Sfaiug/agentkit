#!/bin/bash
# Makes a Debian or Ubuntu machine ready for ak, as root, and prints the address the home reaches
# it by:
#   curl -fsSL https://raw.githubusercontent.com/Sfaiug/agentkit/main/tools/join.sh |
#     sudo bash -s -- '<the home's public ssh key>' [tailscale]
# A machine ak rents runs these same lines after its own mounts (agentkit/google_cloud.py's
# STARTUP).  Run again, it changes nothing that is already right.  The work is one function that
# the last line calls in braces, so a download cut short anywhere runs nothing.

join() {
  set -e
  if ! type -P apt-get >/dev/null; then
    echo "This sets up Debian and Ubuntu machines only: nothing here changed." >&2
    return 2
  fi
  id ak >/dev/null 2>&1 || useradd -m -s /bin/bash ak
  mkdir -p ~ak/.ssh
  grep -qxF -- "$1" ~ak/.ssh/authorized_keys 2>/dev/null || echo "$1" >>~ak/.ssh/authorized_keys
  chown -R ak: ~ak
  # Before Debian 13, docker.io holds docker's client, which has no package of its own.
  if ! type -P docker git jq >/dev/null; then
    apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -qy docker.io \
      $(apt-cache show docker-cli >/dev/null 2>&1 && echo docker-cli) git jq
  fi
  usermod -aG docker ak
  # sshd keeps a suite piece's connection, and its penalties off, as 40 connections that never
  # logged in made each ssh from the home exit 255 at once (tried on 2 Nov 2026, the day 247
  # pieces went so in 3 minutes): only ak's key gets in.  A setting this sshd does not know
  # (OpenSSH 9.8 brought PerSourcePenalties) is left out: it would keep sshd from starting.
  local setting known=
  for setting in 'MaxStartups 500:30:1000' 'PerSourcePenalties no'; do
    ! sshd -t -o "$setting" 2>/dev/null || known+=$setting$'\n'
  done
  printf %s "$known" >/etc/ssh/sshd_config.d/ak.conf
  sshd -t
  systemctl reload ssh
  if [ "$2" = tailscale ] && ! tailscale status >/dev/null 2>&1; then
    type -P tailscale >/dev/null ||
      curl -fsSL https://tailscale.com/install.sh | DEBIAN_FRONTEND=noninteractive sh
    tailscale up
  fi
  local address=$HOSTNAME
  ! tailscale status >/dev/null 2>&1 || address=$(tailscale status --json | jq -r .Self.DNSName)
  echo "ak@${address%.}"
}

{ join "$@"; }
