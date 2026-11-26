#!/bin/bash
# piece.sh SHARD BRANCH DEFAULT PROGRAMS COMMAND, one suite piece on the helper (mac.sh):
# the host checkout's tree and origin branch (/in/heads), its harness programs as stand-ins,
# then offline the command. The repository's history is /mirror's, borrowed, not copied. It
# defines no function: bash would hand the command it in place of one the suite's image exports.
shard=$1 branch=$2 default=$3 programs=$4 command=$5
read -r tree base </in/heads
git init -q --bare ${default:+-b "$default"} /home/ak/origin.git &&
  echo /mirror/objects >/home/ak/origin.git/objects/info/alternates &&
  { [ -z "$default" ] || git -C /home/ak/origin.git update-ref "refs/heads/$default" "$base"; } &&
  git clone -q --no-checkout /home/ak/origin.git /home/ak/work && cd /home/ak/work &&
  git checkout -q ${branch:+-B "$branch"} "$tree" ||
  { echo "ak helper: the tree did not check out" >&2; exit 253; }
git config --global user.name "ak helper"; git config --global user.email "helper@localhost"
mkdir -p /home/ak/stand-ins
for program in $programs; do   # the suite fakes every harness; it only looks for the program
  printf '#!/bin/sh\n[ "$1" = --version ] && { echo "%s 0.0.0"; exit 0; }\nexit 127\n' "$program" \
    >"/home/ak/stand-ins/$program" && chmod +x "/home/ak/stand-ins/$program"
done
# The suite names its failed tests in /out, those failing, then passing, those it ran, and those
# its tree does not hold, which mac.sh's `failed` hands ak.
export PATH="$PATH:/home/ak/stand-ins" SHELL=/bin/bash LANG=C.UTF-8 AK_SHARD="$shard" \
  AK_FAILED=/out/failed AK_FLAKY=/out/flaky AK_RAN=/out/ran AK_NOT_THERE=/out/not-there
# Its test times and the tests to run alone, beside heads where ak sent them: a file holds any
# length, which one argument of the command does not.
for name in AK_TIMES AK_ONLY; do [ ! -f "/in/$name" ] || export "$name=/in/$name"; done
# A new network namespace holds 10 unread notes on a unix datagram socket whatever it starts in,
# and a container's own is such a one, while a host systemd started holds 512: a suite whose
# stand-in sent more than its test had read yet hung on 10 (17 Nov 2026). The sandbox holds what
# it starts in, and 512 at least, with no link but lo. One that does not, as under a read-only
# /proc/sys, runs nothing and ends 253: the helper could not run the piece, which ak then runs
# here, and its suite has not failed. The sandbox is the script's arguments, read by now: a name
# for it could clash with one the suite exported, and reach the command.
notes=$(cat /proc/sys/net/unix/max_dgram_qlen 2>/dev/null)
[ "${notes:-0}" -ge 512 ] || notes=512
set -- unshare --user --map-current-user --net --keep-caps sh -c \
  'echo "$0" >/proc/sys/net/unix/max_dgram_qlen
   ip link set lo up && grep -qx "$0" /proc/sys/net/unix/max_dgram_qlen &&
     [ -z "$(ip -o link show | grep -v ": lo:")" ] || exit 253
   echo built >&9
   exec setpriv --inh-caps=-all --ambient-caps=-all "$@" 9>&-' "$notes"
# It builds, asked before the command by sh, which the sandbox runs anyway: an image may hold no
# true program.
"$@" sh -c : 9>/dev/null || { echo "ak helper: the sandbox did not build" >&2; exit 253; }
# Kills for memory, before the command's launch and after it: of the piece's own cgroup where it
# has one, as a container on a kernel other pieces share does, else of its VM's kernel.
before=$({ cat /sys/fs/cgroup/memory.events || cat /proc/vmstat; } 2>/dev/null | awk '/^oom_kill /')
# Built, the sandbox says so on a descriptor of its own, closed to the command, whose output goes
# where the piece's does: one that said nothing ran nothing, as unshare ends 1 where it builds
# none, this once or since the preflight.
exec 8>&1
built=$("$@" bash -c "$command" 9>&1 >&8 8>&-)
code=$?
# The kernel killed a process for memory: the VM or container was too small for the piece, which
# ak then runs here and gives a larger one next time (helper.short).
[ "$({ cat /sys/fs/cgroup/memory.events || cat /proc/vmstat; } 2>/dev/null | awk '/^oom_kill /')" \
  = "$before" ] || { echo "ak helper: the VM ran out of memory" >&2; exit 254; }
# A launch that ran nothing ends the piece as one the helper could not run, which ak then runs here.
[ -n "$built" ] || { echo "ak helper: the sandbox ran nothing" >&2; exit 253; }
exit "$code"
