#!/bin/bash
# The suite helper on a Linux machine with docker that holds nothing but ak's work (mac.sh):
# each piece in a container, and at most half the machine to one suite.
linux() {
  export LC_ALL=C    # `free` says what it reads in English
  on_power() { :; }    # a rented machine has no battery
  lock() { flock "$@"; }
  # given FIELD: the sum of HostConfig's FIELD over ak's running containers.
  given() {
    ids=$(docker ps -q --filter name=ak-) || return
    docker inspect --format "{{.HostConfig.$1}}" $ids 2>/dev/null |
      awk '{sum += $1} END {printf "%.0f\n", sum}'
  }
  # cpus: what ak's containers may be given together: twice the machine's CPUs, as a piece holds
  # half what it is given for its bursts (36 given two each kept 72 cores 48% busy, on a machine
  # that keeps their files in memory, with nothing waiting on a disk).
  cpus() { echo $(( $(nproc) * 2 )); }
  # spare: the CPUs nothing holds: `cpus`, less those its running containers were given and those
  # each `reserved` says it holds, of what was admitted in the last two minutes and has not started.
  spare() {
    given=$(given NanoCpus) || return
    find "$ROOT" -mindepth 2 -maxdepth 2 -name reserved -mmin -2 -exec cat {} + 2>/dev/null |
      awk -v cpus="$(cpus)" -v given="$given" '{held += $1} END {
        spare = cpus - given / 1e9 - held; print (spare > 0 ? spare : 0) }'
  }
  # probe: docker answers; half of `cpus`, what one suite takes at most, and a load that leaves
  # what is spare of them.
  probe() {
    docker info >/dev/null 2>&1 && spare=$(spare) || return
    awk -v half="$(cpus)" -v spare="$spare" 'BEGIN {
      half /= 2; print "cpus " half; print "load " (spare < half ? half - spare : 0) }'
    echo "turns 1"    # it takes a model's turn (agentkit/machine_turn.py)
  }
  # admit KEY [CPUS], from `prepare` under the suites lock: the suite comes in while a quarter of
  # the machine is spare and holds half of it until its first piece runs or two minutes pass, so
  # suites whose `probe`s all saw the machine empty do not all start. A turn asks and holds only the
  # CPUS it takes: turns start seconds apart, each holding half would turn suites and the next turn
  # away, and asking a quarter kept 13 turns on a host out of CPU beside a machine with 72 (30 Oct 2026).
  admit() {
    rm -f "$ROOT/$1/reserved"    # a suite preparing again (exit 3) is weighed without its own
    spare=$(spare) || exit 253
    awk -v cpus="$(cpus)" -v spare="$spare" -v turn="${2:-}" \
      'BEGIN {exit spare < (turn == "" ? cpus / 4 : turn)}' || exit 252
    mkdir -p "$ROOT/$1" && echo "${2:-$(( $(cpus) / 2 ))}" >"$ROOT/$1/reserved" || exit 253
  }
  # started, from `run` once its piece runs or has ended: the suite's reservation ends, under the
  # lock `admit` reads by, so no suite comes in while neither it nor the container holds the
  # machine.
  started() { [ ! -e "$D/reserved" ] || locked "$ROOT/suites.lock" rm -f "$D/reserved"; }
  # left: the MiB ak's containers here may still be given: all the machine's memory but a tenth
  # its system keeps, less what the running ones were given. A limit counts whole, though a piece
  # holds less at first: it may grow to it once running, and together they must fit the machine.
  left() {
    given=$(given Memory) || return
    free -m | awk -v given="$given" '$1 == "Mem:" {print int($2 - $2 / 10 - given / 1048576)}'
  }
  running() { [ "$(docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
  tags() { docker image ls --format '{{.Repository}}:{{.Tag}}' "$1"; }
  # drop: deletes the images named on stdin, but those a suite here prepared and has not finished
  # with; docker keeps those a container uses.
  drop() {
    grep -vxF -f <(cat "$ROOT"/*/image/name 2>/dev/null) | xargs -r docker image rm >/dev/null 2>&1
    return 0
  }
  # build KEY IMAGE: the suite's image, built unless the machine has it.
  build() {
    docker image inspect "$2" >/dev/null 2>&1 || {
      cd "$ROOT/$1" && mkdir -p context &&
        docker build -q -t "$2" -f "$PWD/image/Containerfile" context </dev/null >build.log 2>&1 ||
        exit 253
    }
  }
  # building KEY IMAGE, from `prepare` after `images`: the build, under its image's own lock, so
  # the minutes a new machine's first build of one image take hold up no other's. No `drop` takes
  # the image after: each runs under the build lock, reading the name this suite wrote before its
  # `images` took that lock.
  building() { locked "$ROOT/build-${2//[:\/]/-}.lock" build "$1" "$2"; }
  # images KEY IMAGE, under the build lock: the repository's other images go once no suite here
  # names them.
  images() {
    tags "${2%:*}" | grep -vxF "$2" | drop
    expire
  }
  # start, from `run`, with piece.sh's arguments: the piece's container, with no network beyond
  # loopback and no swap. Its sandboxes need user namespaces and an unmasked /proc.
  start() {
    docker run --rm --init --name "$name" --network none --cpus "$cpus" --memory "${memory}m" \
      --memory-swap "${memory}m" --security-opt seccomp=unconfined \
      --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
      --volume "$D:/in:ro" --volume "$M:/mirror:ro" --volume "$out:/out" "$image" \
      /bin/bash /in/piece.sh "$@"
  }
  # start_turn, from `turn`, with turn.sh's arguments: `start`'s container, but as the user who owns
  # its volumes, with a network for the harness's API and no CPU bound: a turn mostly waits.
  start_turn() {
    docker run --rm --init --name "$name" --user "$(id -u):$(id -g)" --memory "${memory}m" \
      --memory-swap "${memory}m" --security-opt seccomp=unconfined \
      --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
      --volume "$D:/in" --volume "$M:/mirror:ro" --volume "$H:/harness:ro" "${volumes[@]}" \
      "$image" /bin/bash /in/turn.sh "$@"
  }
  stop() { docker stop -t 1 "$1"; }
  # processes KEY, for `processes`: each process of the turn's container, its seconds since it
  # started, then its argv, one line each, its words split at spaces.
  processes() { docker top "ak-$1-turn" -eo pid,etimes,args | awk 'NR > 1 {$1 = ""; print}'; }
  # preparing KEY: `prepare`'s lock until it ends, as parcel, harness and image hold no container
  preparing() { exec 9>>"$ROOT/$1/preparing" && flock 9; }
  # quiet, for `idle`: nothing while a container of ak's runs, a suite prepares or docker cannot
  # say; else the seconds since the machine came up or $ROOT last changed, as a suite's folder
  # comes at `admit` and goes at `finish`: one killed part way changes it no more.
  quiet() {
    ids=$(docker ps -q --filter name=ak-) && [ -z "$ids" ] || return 0
    for held in "$ROOT"/*/preparing "$ROOT"/build-*.lock; do    # build-*: an older prepare's
      [ ! -e "$held" ] || flock -n "$held" true || return 0; done
    up=$(cut -d. -f1 /proc/uptime)
    changed=$(( $(date +%s) - $(stat -c %Y "$ROOT" 2>/dev/null || echo 0) ))
    echo $(( up < changed ? up : changed ))
  }
}
