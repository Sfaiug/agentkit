#!/bin/bash
# The suite helper (agentkit/helper.py), run over ssh as `bash -c <linux.sh this> mac.sh VERB
# ...`: the verbs every kind of machine shares, and what each does its own way in a function
# picked by `uname`: a Mac's here, so this file alone, as an ak updated under a running suite
# still sends it, runs a Mac as before; Linux's in linux.sh. macOS bash is 3.2. Exits match
# helper.py: 251 battery, 252 no room, 253 container or preparation failure; 255 belongs to ssh.
# A piece keeps its own exit.
export ROOT="$HOME/.agentkit-helper"
export MIRRORS="$ROOT/mirrors"   # each repository's history, kept between its suites
# darwin: a Mac's own, while it is on its charger: each piece in a Linux VM of Apple's
# `container`.
darwin() {
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
  on_power() { pmset -g batt 2>/dev/null | head -1 | grep -q "'AC Power'"; }
  lock() { lockf -k "$@"; }
  # probe: `container` is up, started where it was not; the Mac's CPUs and load.
  probe() {
    { container system status || container system start --enable-kernel-install; } \
      >/dev/null 2>&1 || return
    echo "cpus $(sysctl -n hw.ncpu)"
    echo "load $(sysctl -n vm.loadavg | awk '{print $2}')"
  }
  # admit and started: a Mac takes every suite; its VMs share it by `left`.
  admit() { :; }
  started() { :; }
  # left: the MiB ak's VMs here may still be given. Together they get at most half of what would
  # be free without them, so the Mac stays its owner's: half of what macOS calls free and what
  # they hold, less what they were given. The VMs running are the truth: one counts exactly while
  # it runs. Stats that fail count nothing held, which only gives less.
  left() {
    vms=$(container list --all --format json) || return
    stats=$(container stats --no-stream --format json 2>/dev/null) || stats=
    free=$(( $(sysctl -n hw.memsize) / 1048576 *
      $(memory_pressure -Q | awk -F': *' '/free percentage/ {print $2 + 0}') / 100 ))
    jq -n --argjson vms "$vms" --argjson stats "${stats:-[]}" --argjson free "$free" '
      [$vms[] | select(.status.state == "running" and (.configuration.id | startswith("ak-")))]
      | (map(.configuration.id)) as $ids
      | ([$stats[] | select(.id | IN($ids[])) | .memoryUsageBytes] | add // 0) as $held
      | ((($free * 1048576 + $held) / 2 - (map(.configuration.resources.memoryInBytes) | add // 0))
         / 1048576 | floor)'
  }
  # running NAME: is the VM NAME running?
  running() {
    container list --all --format json | jq -e --arg id "$1" \
      'any(.[]; .configuration.id == $id and .status.state == "running")' >/dev/null
  }
  # tags NAME: the images of the repository NAME, as NAME:TAG.
  tags() { container image ls | awk -v name="$1" 'NR > 1 && $1 == name {print $1":"$2}'; }
  # bare: image references without registry or namespace, tagged `latest` where untagged, as
  # `container ls`, `container image ls` and FROM each write one image differently; an image
  # matching another of its name elsewhere stays rather than going while a VM uses it.
  bare() { sed -e 's,.*/,,' -e '/:/!s/$/:latest/'; }
  # drop: deletes the images named on stdin, but those a suite here prepared and has not finished
  # with or a container uses; none while the containers are unknown. Under the build lock, so a
  # suite either is named here already or finds its image gone and builds it.
  drop() {
    vms=$(container ls --all 2>/dev/null) || return 0
    keep=$({ cat "$ROOT"/*/image/name 2>/dev/null
      printf '%s\n' "$vms" | awk 'NR > 1 {print $2}'; } | bare)
    while read -r old; do
      [ -z "$old" ] || printf '%s\n' "$keep" | grep -qxF -e "$(printf '%s\n' "$old" | bare)" ||
        container image delete "$old" >/dev/null 2>&1
    done
    return 0
  }
  building() { :; }    # `images` does it: any build's end stops the builder of all
  # images KEY IMAGE, under the build lock, as any build's end stops the builder of all: the
  # suite's image, built unless the Mac has it.
  images() {
    base= built=0
    container image inspect "$2" >/dev/null 2>&1 || {
      # The recipe stays outside its build's context, which holds only the files it copies.
      cd "$ROOT/$1" && mkdir -p context || exit 253
      base=$(awk '$1 == "FROM" {print $2; exit}' image/Containerfile)
      container image inspect "$base" >/dev/null 2>&1 && base=
      container build --progress plain -t "$2" -f "$PWD/image/Containerfile" context </dev/null \
        >build.log 2>&1
      built=$?
      container builder stop >/dev/null 2>&1
    }
    # With this one in place, the repository's other images go once no suite here names them, at
    # the first prepare after, built or not; the base a build fetched goes even when the build
    # failed, so the Mac holds the one image. The owner's own images stay, the base too where they
    # had it before. The stopped builder goes with its cache: only a changed recipe's build could
    # use it, and it kept every build's layers (27 GB in ten days).
    { [ "$built" != 0 ] || tags "${2%:*}" | grep -vxF "$2"; echo "$base"; } | drop
    container builder delete >/dev/null 2>&1
    [ "$built" = 0 ] || exit 253
    expire
  }
  # start, from `run`, with piece.sh's arguments: the piece's VM. psi=1: the suite sizes its pool
  # from pressure; an unmasked /proc lets its sandbox mount one.
  start() {
    caffeinate -is container run --rm --init --progress none --kernel-arg psi=1 --masked-path NONE \
      --read-only-path NONE --no-dns --cpus "$cpus" --memory "${memory}m" --name "$name" \
      --volume "$D:/in:ro" --volume "$M:/mirror:ro" --volume "$out:/out" "$image" \
      /bin/bash /in/piece.sh "$@"
  }
  stop() { container stop "$1"; }
}
# locked FILE COMMAND...: COMMAND, a program or a function here, runs holding FILE's lock, which
# the kernel drops when its holder dies; suites preparing at once share the machine by these locks.
locked() { lock "$1" bash -c "$(declare -f)"'
  "$@"' mac.sh "${@:2}"; }
# held FLAG PID, under a lock: says it holds the lock by deleting FLAG, then keeps it until FLAG
# is back or PID has ended.
held() { rm "$1"; until [ -e "$1" ] || ! kill -0 "$2"; do sleep 0.1; done; rm -f "$1"; }
# admitted START ARGS..., from `run` and `turn`: START ARGS, container $name, once $memory MiB fit.
admitted() {
  session=$PPID
  until [ "$session" -le 1 ] || ps -o comm= -p "$session" | grep -q sshd; do
    session=$(ps -o ppid= -p "$session" | tr -d ' ')
  done
  # Containers are admitted one at a time, each running before the next is weighed, so those placed
  # at once never get more together than `left` allows; one that does not fit runs on ak's host.
  flag=$D/$name.admit
  : >"$flag" && { locked "$ROOT/vms.lock" held "$flag" $$ </dev/null >/dev/null 2>&1 & }
  while [ -e "$flag" ]; do kill -0 $! 2>/dev/null || exit 253; sleep 0.1; done
  room=$(left) || exit 253
  [ "$memory" -le "$room" ] || exit 252
  "$@" &
  vm=$!
  # It stops once ak's ssh session ends or the machine leaves its charger; the stop is repeated
  # until START ends, so a container that comes up after the first stop stops too.
  ( lost=253
    while ps -p "$session"; do
      on_power || { lost=251; break; }
      sleep 5
    done
    echo "$lost" >"$D/$name.lost"
    while ps -p "$vm"; do stop "$name"; sleep 1; done ) >/dev/null 2>&1 &
  # The next is weighed once this one runs, or has ended: stopped while starting, it ends.
  until running "$name" || ! kill -0 "$vm" 2>/dev/null; do sleep 0.2; done
  started
  : >"$flag"
  wait "$vm"
  code=$?
  kill $! 2>/dev/null; wait $! 2>/dev/null
  [ ! -e "$D/$name.lost" ] || exit "$(cat "$D/$name.lost")"
  exit "$code"
}
# expire, from `images` under the build lock: a repository's history unused (`known`) for a week
# goes, under its own lock, and its images with it.
expire() {
  find "$MIRRORS" -mindepth 1 -maxdepth 1 -type d -mtime +7 2>/dev/null | while read -r old; do
    locked "$old.lock" find "$old" -maxdepth 0 -mtime +7 -exec rm -rf {} +
    [ -d "$old" ] || tags "ak-helper-${old##*/}" | drop
  done
}
# history KEY COPY, under the copy's lock: the parcel's history into the repository's copy. Refs
# keep each suite's own commits while its directory lives and the last suite's origin branch,
# for `known`; git's gc drops the rest two weeks on. A copy gone since `known` answered lacks
# what the parcel left out: exit 3, and helper.py sends the whole history.
history() {
  read -r tree base <"$ROOT/$1/heads" &&
    { [ ! -e "$ROOT/$1/repo.bundle" ] ||
      git -C "$2" bundle unbundle "$ROOT/$1/repo.bundle" >/dev/null; } &&
    rm -f "$ROOT/$1/repo.bundle" && git -C "$2" cat-file -e "$tree^{commit}" &&
    git -C "$2" update-ref "refs/suites/$1/tree" "$tree" &&
    { [ -z "$base" ] || { git -C "$2" update-ref "refs/suites/$1/base" "$base" &&
      git -C "$2" update-ref refs/known/base "$base"; }; } || exit 3
  git -C "$2" for-each-ref --format='%(refname:lstrip=2)' refs/suites | while read -r ref; do
    [ -d "$ROOT/${ref%/*}" ] || git -C "$2" update-ref -d "refs/suites/$ref"; done
  git -C "$2" -c gc.autoDetach=false gc --auto --quiet >/dev/null 2>&1
}
# fetch PROGRAM URLFILE, under its version's lock: a turn's harness program, unless a turn before
# this one fetched it, whole or not at all: it stays outside the directory `turn` mounts until it
# is all here. A `.tar.gz` holds only the program, under another name. Bounded, as a hung download
# would hold the lock against every later turn.
fetch() {
  [ ! -x "$1" ] || return 0
  url=$(cat "$2") || return
  part=${1%/*}.part
  case $url in *.tar.gz) unpack="tar -xzO" ;; *) unpack=cat ;; esac
  (set -o pipefail; curl -fsSL --max-time 600 "$url" | $unpack >"$part") && chmod +x "$part" &&
    mv "$part" "$1" || { rm -f "$part"; return 1; }
}
case $(uname) in Darwin) darwin ;; Linux) linux ;; *) false ;; esac || exit 253
case "$1" in
probe)     # what helper.room reads
  on_power || exit 251
  readings=$(probe) && room=$(left) || exit 253
  echo "$readings"
  echo "room_mb $room" ;;
known)     # REPO: the commit its history here reaches, if any. A suite asks just before its
  # `prepare`, so this marks the history in use: no other suite's `prepare` deletes it for a week.
  touch -c "$MIRRORS/$2"
  git -C "$MIRRORS/$2" rev-parse -q --verify refs/known/base 2>/dev/null; exit 0 ;;
prepare)   # KEY IMAGE REPO [CPUS a turn holds], the parcel on stdin
  # Suites are admitted one at a time, before anything of theirs is unpacked.
  mkdir -p "$ROOT" || exit 253
  locked "$ROOT/suites.lock" admit "$2" "$5" || exit
  # -p: the recipe's files keep HEAD's modes, whatever umask the machine's shell has.
  mkdir -p "$ROOT/$2" && tar -x -p -C "$ROOT/$2" && echo "$3" >"$ROOT/$2/image/name" || exit 253
  # A turn's harness program is $ROOT/harness/<harness>/<version>/<program>; a suite names none.
  [ ! -f "$ROOT/$2/harness" ] || {
    program=$ROOT/harness/$(cat "$ROOT/$2/harness")
    mkdir -p "${program%/*}" &&
      locked "${program%/*}.lock" fetch "$program" "$ROOT/$2/fetch/$(uname -m)"
  } || exit 253
  # Dead callers' trees go after a day; the locks and harness programs stay.
  find "$ROOT" -mindepth 1 -maxdepth 1 -type d ! -name mirrors ! -name harness -mtime +1 \
    -exec rm -rf {} + 2>/dev/null
  # The repository's copy, empty at first, comes before its image, so the collection finds an
  # image whose suite then failed.
  M="$MIRRORS/$4"
  mkdir -p "$MIRRORS" && locked "$M.lock" git init -q --bare "$M" || exit 253
  locked "$ROOT/build.lock" images "$2" "$3" || exit
  building "$2" "$3" || exit
  locked "$M.lock" history "$2" "$M" ;;
run)       # KEY IMAGE NAME CPUS MEMORY_MB REPO, then piece.sh's arguments
  D="$ROOT/$2" image=$3 name=$4 cpus=$5 memory=$6 M="$MIRRORS/$7"
  shift 7
  on_power || exit 251
  # The piece names its failed tests in /out (piece.sh), which `failed` reads once it ends.
  out="$D/$name.out"
  [ -d "$D" ] && [ -d "$M" ] && rm -rf "$out" && mkdir -m 777 "$out" || exit 253
  admitted start "$@" ;;
failed)    # KEY NAME [flaky]: the tests piece NAME named as failed (or flaky); never through a
           # link it left there
  f="$ROOT/$2/$3.out/${4:-failed}"
  [ ! -f "$f" ] || [ -L "$f" ] || cat "$f"; exit 0 ;;
turn)      # KEY IMAGE MEMORY_MB REPO, volumes PART:PATH[:ro] of its parcel, `home` first, `--`,
  # turn.sh's arguments: the turn's container, its events on stdout and harness's stderr on stderr,
  # ended with ak's ssh session. It exits as turn.sh did: 0 once the turn's exit is in `code`. By
  # then, however it ended, the paths `lent` names, read before the turn could change them, are
  # gone, so `collect` cannot send them.
  D="$ROOT/$2" image=$3 memory=$4 M="$MIRRORS/$5" name="ak-$2-turn" volumes=() lent=()
  H="$ROOT/harness/$(dirname "$(cat "$D/harness")")"
  shift 5
  while IFS= read -r -d '' path; do lent+=("$D/home/$path"); done <"$D/lent"
  trap 'rm -rf -- "${lent[@]}"' EXIT
  home=${1#home:}
  while [ "${1:---}" != -- ]; do
    mkdir -p "$D/${1%%:*}" && volumes+=(--volume "$D/$1") || exit 253
    # docker makes a mount point missing from HOME as root, which `finish` could not remove.
    place=${1#*:} place=${place%:ro}
    case $place in "$home"/*) mkdir -p "$D/home/${place#"$home"/}" || exit 253 ;; esac
    shift
  done
  shift
  streamed() {
    start_turn "$@" >&2 & turn=$!
    tail -c +1 -F --pid="$turn" "$D/out/events.jsonl" 2>/dev/null &
    tail -c +1 -F --pid="$turn" "$D/out/stderr.log" >&2 2>/dev/null &
    wait "$turn"; code=$?; wait; exit "$code"
  }
  admitted streamed "$@" ;;
collect)   # KEY: an ended turn's out dir, the bundle and exit turn.sh left, as a tar on stdout
  cd "$ROOT/$2" && [ -f code ] && tar -c out back.bundle code || exit 253 ;;
finish) rm -rf "${ROOT:?}/$2" ;;
*) exit 253 ;;
esac
