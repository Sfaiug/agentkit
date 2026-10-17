#!/bin/bash
# piece.sh SHARD BRANCH DEFAULT PROGRAMS COMMAND, one suite piece in the helper's VM (mac.sh):
# the host checkout's tree and refs, its harness programs as stand-ins, then offline the command.
shard=$1 branch=$2 default=$3 programs=$4 command=$5
fail() { echo "ak helper: $*" >&2; exit 255; }
git init -q --bare ${default:+-b "$default"} /home/ak/origin.git &&
  git -C /home/ak/origin.git fetch -q /in/repo.bundle 'refs/remotes/origin/*:refs/heads/*' \
    'HEAD:refs/ak/tree' &&
  git clone -q --no-checkout /home/ak/origin.git /home/ak/work && cd /home/ak/work &&
  git fetch -q origin refs/ak/tree && git checkout -q ${branch:+-B "$branch"} FETCH_HEAD ||
  fail "the tree did not check out"
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
offline bash -c "$command"
