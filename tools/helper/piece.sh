#!/bin/bash
# piece.sh SHARD BRANCH DEFAULT PROGRAMS COMMAND, one suite piece in the helper's VM (mac.sh):
# the host checkout's tree and origin branch (/in/heads), its harness programs as stand-ins,
# then offline the command. The repository's history is /mirror's, borrowed, not copied.
shard=$1 branch=$2 default=$3 programs=$4 command=$5
fail() { echo "ak helper: $*" >&2; exit 253; }
read -r tree base </in/heads
git init -q --bare ${default:+-b "$default"} /home/ak/origin.git &&
  echo /mirror/objects >/home/ak/origin.git/objects/info/alternates &&
  { [ -z "$default" ] || git -C /home/ak/origin.git update-ref "refs/heads/$default" "$base"; } &&
  git clone -q --no-checkout /home/ak/origin.git /home/ak/work && cd /home/ak/work &&
  git checkout -q ${branch:+-B "$branch"} "$tree" || fail "the tree did not check out"
git config --global user.name "ak helper"; git config --global user.email "helper@localhost"
mkdir -p /home/ak/stand-ins
for program in $programs; do   # the suite fakes every harness; it only looks for the program
  printf '#!/bin/sh\n[ "$1" = --version ] && { echo "%s 0.0.0"; exit 0; }\nexit 127\n' "$program" \
    >"/home/ak/stand-ins/$program" && chmod +x "/home/ak/stand-ins/$program"
done
export PATH="$PATH:/home/ak/stand-ins" SHELL=/bin/bash LANG=C.UTF-8 AK_SHARD="$shard"
offline() {
  unshare --user --map-current-user --net --keep-caps sh -c \
    'ip link set lo up && exec setpriv --inh-caps=-all --ambient-caps=-all "$@"' - "$@"
}
offline sh -c '[ -z "$(ip -o link show | grep -v ": lo:")" ]' || fail "could not go offline"
oom() { awk '$1 == "oom_kill" {print $2}' /proc/vmstat; }
before=$(oom)
offline bash -c "$command"
code=$?
# The kernel killed a process for memory: the VM was too small for the piece, which ak then
# runs here and gives a larger VM next time (helper.short).
[ "$(oom)" = "$before" ] || { echo "ak helper: the VM ran out of memory" >&2; exit 254; }
exit "$code"
