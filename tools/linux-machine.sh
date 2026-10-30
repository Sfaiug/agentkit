# This Mac's Linux machine, where ak's server runs: its worker box, landing gate and limits
# exist only on Linux.  This file hides how: Lima (2.2 or newer, for `limactl autostart`) on
# Apple's virtualization, the machine's settings, its size and its start at boot.  install.sh
# sources it and uses only
#   LINUX_MACHINE           the ssh alias the Mac reaches the machine by, a local port that
#                           needs no network
#   linux_machine_up        make sure the machine exists and is up; nothing already right changes
#   linux_machine_run CMD   run CMD in the machine, in its home, with a terminal when there is one
LINUX_INSTANCE=ak
LINUX_MACHINE=lima-$LINUX_INSTANCE

# The Mac account's own name and /home/<name>, Lima's default being /home/<name>.linux: a server
# moved in from a Linux VM with the same user keeps the absolute paths its run records hold.
linux_user() { printf '%s' "${USER:-$(id -un)}"; }
linux_dir() { printf '%s' "${LIMA_HOME:-$HOME/.lima}/$LINUX_INSTANCE"; }

# What the machine takes of the Mac's `total`: macOS keeps a quarter for the desktop and its
# renders, and never less than `floor` until that would be more than half, so a small Mac still
# lends the machine half of what it has.
linux_share() {   # linux_share <total> <floor>
  local keep=$(($1 / 4)) floor=$2
  [ "$floor" -le $(($1 / 2)) ] || floor=$(($1 / 2))
  [ "$keep" -ge "$floor" ] || keep=$floor
  echo $(($1 - keep))
}

linux_machine_up() {
  local dir name cpus mem disk gib=$((1024 * 1024 * 1024))
  dir=$(linux_dir) name=$(linux_user)
  if ! limactl autostart --help >/dev/null 2>&1; then
    if command -v limactl >/dev/null 2>&1; then brew upgrade lima || return 1
    else brew install lima || return 1; fi
  fi
  if [ ! -f "$dir/lima.yaml" ]; then
    # Cores are shared with macOS as it runs, so a quarter left to it is room to schedule.
    # Memory is a reservation: the Mac never gets back what the machine has once touched.
    # The disk grows as it fills and never shrinks, so it is a share of the space free now.
    cpus=$(linux_share "$(sysctl -n hw.ncpu)" 2) || return 1
    mem=$(linux_share $(($(sysctl -n hw.memsize) / gib)) 4) || return 1
    disk=$(linux_share $(($(df -Pk "$HOME" | awk 'NR == 2 { print $4 }') / 1024 / 1024)) 64) ||
      return 1
    # Debian stable, which boots systemd; --mount-none: the machine sees none of the Mac's folders
    limactl create --tty=false --name="$LINUX_INSTANCE" --cpus="$cpus" --memory="$mem" \
      --disk="$disk" --mount-none \
      --set ".user.name = \"$name\" | .user.home = \"/home/$name\"" template:debian || return 1
    echo "linux: this Mac's Linux machine has $cpus cores, ${mem} GiB of memory and ${disk} GiB of disk"
  fi
  limactl start --tty=false "$LINUX_INSTANCE" || return 1   # one already up stays as it is
  # A system LaunchDaemon starts it with the Mac, before anyone logs in; enabling asks for sudo.
  if [ ! -e "${AK_LAUNCH_DAEMONS:-/Library/LaunchDaemons}/io.lima-vm.daemon.$LINUX_INSTANCE.plist" ]; then
    limactl autostart enable --condition=boot "$LINUX_INSTANCE" || return 1
    echo "linux: this Mac's Linux machine starts when the Mac does"
  fi
  # Lima keeps the alias's port and key in its own ssh.config; ssh reads it through this line,
  # first in the file, where an Include holds for every host.
  local config=$HOME/.ssh/config include="Include $dir/ssh.config" tmp
  if ! grep -qxF -- "$include" "$config" 2>/dev/null; then
    mkdir -p -- "$HOME/.ssh" && chmod 700 "$HOME/.ssh" && tmp=$(mktemp) &&
      { printf '%s\n' "$include"; cat -- "$config" 2>/dev/null || true; } >"$tmp" &&
      cat -- "$tmp" >"$config" && rm -f -- "$tmp" && chmod 600 "$config" || return 1
    echo "ssh: \`ssh $LINUX_MACHINE\` reaches this Mac's Linux machine"
  fi
}

# `limactl shell` puts a terminal on the command when its stdin is one.
linux_machine_run() { limactl shell --workdir "/home/$(linux_user)" "$LINUX_INSTANCE" "$@"; }
