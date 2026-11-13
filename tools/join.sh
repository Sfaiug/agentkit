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
  if ! grep -qsxE 'ID="?(debian|ubuntu)"?' /etc/os-release; then
    echo "This sets up Debian and Ubuntu machines only: nothing here changed." >&2
    return 2
  fi
  id ak >/dev/null 2>&1 || useradd -m -s /bin/bash ak
  local keys=~ak/.ssh/authorized_keys
  mkdir -p ~ak/.ssh
  if ! grep -qxF -- "$1" "$keys" 2>/dev/null; then
    [ -z "$(tail -c 1 "$keys" 2>/dev/null)" ] || echo >>"$keys"    # ends a last line unended
    echo "$1" >>"$keys"
  fi
  chmod go-w ~ak ~ak/.ssh "$keys"    # sshd refuses a key that others could have written
  chown -R ak: ~ak
  # sshd where the system came without it; docker's client has been a package of its own since
  # Debian 13, and Docker's daemon is what makes group docker.
  if ! type -P dockerd docker git jq sshd >/dev/null; then
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -qy docker.io \
      $(apt-cache show docker-cli >/dev/null 2>&1 && echo docker-cli) git jq \
      $(type -P sshd >/dev/null || echo openssh-server)
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
  # One not running starts now: Ubuntu's socket would start it only at the first connection.
  if systemctl is-active -q ssh; then systemctl reload ssh; else systemctl start ssh; fi
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
