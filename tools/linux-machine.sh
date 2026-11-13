# This Mac's Linux machine, where ak's server runs: its worker box, landing gate and limits
# exist only on Linux.  This file hides how: Lima (2.2 or newer, for `limactl autostart`) on
# Apple's virtualization, the machine's settings, its size, its start at boot and the Mac's power
# settings that keep it up.  install.sh sources it and uses only
#   LINUX_MACHINE           the ssh alias the Mac reaches the machine by, a local port that
#                           needs no network
#   linux_machine_up        make sure the machine exists, is up and stays up with the Mac;
#                           nothing already right changes
#   linux_machine_run CMD   run CMD in the machine, in its home, with a terminal when there is one
# While the Mac runs, ak's own LaunchDaemon runs this file every minute (linux_machine_check), so
# a machine stopped with `limactl stop ak` starts again within a minute.  To stop it for good, boot
# the check out first: `sudo launchctl bootout system/com.agentkit.linux-machine && limactl stop
# ak`; the Mac's next start, or the next install, brings both back.
LINUX_INSTANCE=ak
LINUX_MACHINE=lima-$LINUX_INSTANCE
LINUX_CHECK=com.agentkit.linux-machine

# The Mac account's own name and /home/<name>, Lima's default being /home/<name>.linux: a server
# moved in from a Linux VM with the same user keeps the absolute paths its run records hold.
linux_user() { printf '%s' "${USER:-$(id -un)}"; }
# Lima keeps its machines in the store LIMA_HOME names, else ~/.lima.
linux_store() { printf '%s' "${LIMA_HOME:-$HOME/.lima}"; }
linux_dir() { printf '%s' "$(linux_store)/$LINUX_INSTANCE"; }

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
  local dir name cpus mem had when disk power gib=$((1024 * 1024 * 1024))
  local daemons=${AK_LAUNCH_DAEMONS:-/Library/LaunchDaemons}
  dir=$(linux_dir) name=$(linux_user)
  if ! limactl autostart --help >/dev/null 2>&1; then
    if command -v limactl >/dev/null 2>&1; then brew upgrade lima || return 1
    else brew install lima || return 1; fi
  fi
  # Memory is a reservation: the Mac never gets back what the machine has once touched, so a
  # machine holding more than its share, as one made by hand may, is held to it.
  mem=$(linux_share $(($(sysctl -n hw.memsize) / gib)) 4) || return 1
  if [ ! -f "$dir/lima.yaml" ]; then
    # Cores are shared with macOS as it runs, so a quarter left to it is room to schedule, and
    # a machine made with more keeps them: they come back to macOS whenever it idles.
    # The disk grows as it fills and never shrinks, so it is a share of the space free now.
    cpus=$(linux_share "$(sysctl -n hw.ncpu)" 2) || return 1
    disk=$(linux_share $(($(df -Pk "$HOME" | awk 'NR == 2 { print $4 }') / 1024 / 1024)) 64) ||
      return 1
    # Debian stable, which boots systemd; --mount-none: the machine sees none of the Mac's folders
    limactl create --tty=false --name="$LINUX_INSTANCE" --cpus="$cpus" --memory="$mem" \
      --disk="$disk" --mount-none \
      --set ".user.name = \"$name\" | .user.home = \"/home/$name\"" template:debian || return 1
    echo "linux: this Mac's Linux machine has $cpus cores, ${mem} GiB of memory and ${disk} GiB of disk"
  elif had=$(limactl list --format '{{.Memory}}' "$LINUX_INSTANCE") &&
    [ "$had" -gt $((mem * gib)) ]; then
    when=now
    [ "$(linux_machine_status)" != Running ] || when="from its next start"
    linux_machine_start --memory="$mem" || return 1
    echo "linux: this Mac's Linux machine takes $mem GiB of memory $when, not $((had / gib)) GiB, leaving macOS its share"
  fi
  linux_machine_start || return 1   # one already up stays as it is
  # A system LaunchDaemon starts it with the Mac, before anyone logs in; enabling asks for sudo.
  if [ ! -e "$daemons/io.lima-vm.daemon.$LINUX_INSTANCE.plist" ]; then
    limactl autostart enable --condition=boot "$LINUX_INSTANCE" || return 1
    echo "linux: this Mac's Linux machine starts when the Mac does"
  fi
  # Lima's daemon runs only at boot.  ak's own runs the check every minute; launchd reads a
  # changed plist only as it loads it, so one already loaded is booted out first, and one not
  # loaded, booted out or never loaded, is loaded.
  local plist=$daemons/$LINUX_CHECK.plist daemon
  daemon=$(linux_check_daemon "$name")
  if [ "$(cat -- "$plist" 2>/dev/null)" != "$daemon" ]; then
    printf '%s\n' "$daemon" | sudo tee "$plist" >/dev/null || return 1
    sudo launchctl bootout "system/$LINUX_CHECK" 2>/dev/null || true
  fi
  if ! launchctl print "system/$LINUX_CHECK" >/dev/null 2>&1; then
    sudo launchctl bootstrap system "$plist" || return 1
    echo "linux: this Mac's Linux machine starts again by itself when it stops or stops answering"
  fi
  # On power the Mac never sleeps, though its display may, and it starts again by itself when
  # power comes back after a cut.  pmset keeps both across restarts; only what is not so yet is
  # set, which asks for sudo as the start at boot does.
  power=$(pmset -g custom | awk '/^[^ ]/ { ac = /^AC Power:/ }
    ac && $1 == "sleep" && $2 != 0 { print "sleep 0" }
    ac && $1 == "autorestart" && $2 != 1 { print "autorestart 1" }') || return 1
  if [ -n "$power" ]; then
    sudo pmset -c $power || return 1   # each setting and its value split into words of their own
    echo "power: this Mac never sleeps on power, though its display may, and starts again after a power cut"
  fi
  # FileVault holds a Mac that starts again at its password before anything of it runs.
  if fdesetup isactive >/dev/null 2>&1; then
    echo "power: FileVault is on, so after a restart this Mac waits for its password, and ak's machine stays down until someone enters it"
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

# ak's LaunchDaemon, run as the account <name>, which launchd gives neither its HOME, Homebrew's
# PATH nor the Lima store the install used.  The host agent a check's `limactl start` leaves
# outlives the check.
linux_check_daemon() {   # linux_check_daemon <name>
  local path
  path=$(dirname "$(command -v limactl)"):/usr/bin:/bin:/usr/sbin:/sbin
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LINUX_CHECK</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$(linux_xml "${BASH_SOURCE[0]}")</string></array>
  <key>UserName</key><string>$(linux_xml "$1")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$(linux_xml "$HOME")</string>
    <key>PATH</key><string>$(linux_xml "$path")</string>
    <key>LIMA_HOME</key><string>$(linux_xml "$(linux_store)")</string>
  </dict>
  <key>StartInterval</key><integer>60</integer>
  <key>AbandonProcessGroup</key><true/>
</dict>
</plist>
EOF
}

# A string as XML text: a path may hold `&` or `<`.
linux_xml() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

# A Stopped machine starts.  Any other -- Running, or Broken while its host agent does not
# answer Lima, as while it starts up -- that has not answered for 10 minutes is stopped by force
# (Lima starts no Broken machine), then starts.  Silence counts from its last answer, start or
# check that found it Stopped, never from before the Mac started, when Lima's daemon starts it,
# and with none on record, as on a machine running before this check came, from now; a boot
# time that is no number restarts nothing.  One stopped by force is then left as it is,
# whatever the start after the stop did, until it answers, is found Stopped, linux_machine_start
# starts it or the Mac starts: a second stop mends nothing the first did not, such as this
# check's own way to the machine, and ends every session in it.  None of these may depend on
# what the clock reads, which is set back at times: the stop goes on record in the answer's
# place, where the next answer, start or Stopped writes over it, with the id of the Mac's boot,
# whose time moves with the clock; a boot id that is empty leaves none as it is.
linux_machine_check() {
  local status answered last forced session boot
  status=$(linux_machine_status) answered=$(linux_dir)/answered
  if [ "$status" != Stopped ]; then
    if linux_machine_answers; then date +%s >"$answered"; return; fi
    [ -e "$answered" ] || { date +%s >"$answered"; return; }
    read -r last forced <"$answered"
    session=$(sysctl -n kern.bootsessionuuid)
    [ -n "$forced" ] && [ "$forced" = "$session" ] && return 0
    # kern.boottime reads `{ sec = 1794268800, usec = 0 } Tue Nov 10 00:00:00 2026`
    boot=$(sysctl -n kern.boottime | awk -F '[ ,]+' '{ print $4 }')
    [ "${last:-0}" -gt "$boot" ] || last=$boot
    [ "$last" -le $(($(date +%s) - 600)) ] || return 0
    limactl stop --force "$LINUX_INSTANCE" || return
    echo "$(date +%s) $session" >"$answered"
    limactl start --tty=false "$LINUX_INSTANCE"
    return
  fi
  # Found stopped, it runs from now whoever starts it: another start may come before the look
  # at its status linux_machine_start takes, which then leaves the last answer as it is.
  date +%s >"$answered"
  linux_machine_start
}

linux_machine_status() { limactl list --format '{{.Status}}' "$LINUX_INSTANCE"; }

# `limactl start` returns once the machine answers, so starting one counts as its answer.  One
# already running stays as it is, and so does its last answer: it may hang.  Lima writes the flags
# it is given into the machine's file even while it runs, where they hold from its next start.
linux_machine_start() {   # linux_machine_start [<flag of limactl start>...]
  if [ "$(linux_machine_status)" != Running ]; then
    limactl start --tty=false "$@" "$LINUX_INSTANCE" && date +%s >"$(linux_dir)/answered"
  elif [ $# -gt 0 ]; then
    limactl start --tty=false "$@" "$LINUX_INSTANCE"
  fi
}

# Whether the machine runs `true` within 30 s, asked through Lima's own ssh file, which Lima
# writes at each start: nothing in the account's ssh setup, such as a lost Include, keeps the
# check from a machine that answers.  macOS has no timeout(1): a timer ends ssh at 30 s, and ends
# with its sleep once ssh is done.
linux_machine_answers() {
  local ssh timer code
  ssh -F "$(linux_dir)/ssh.config" "$LINUX_MACHINE" true </dev/null >/dev/null 2>&1 & ssh=$!
  { trap 'kill $!; exit' TERM; sleep 30 & wait $!; kill "$ssh"; } >/dev/null 2>&1 & timer=$!
  wait "$ssh"; code=$?
  kill "$timer" 2>/dev/null
  return "$code"
}

# launchd runs this file; install.sh sources it.
[ "${BASH_SOURCE[0]}" != "$0" ] || linux_machine_check
