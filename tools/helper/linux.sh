#!/bin/bash
# The suite helper on a Linux machine with docker that holds nothing but ak's work (mac.sh):
# each piece in a container.
linux() {
  export LC_ALL=C    # `free` and `uptime` say what they read in English
  on_power() { :; }    # a rented machine has no battery
  lock() { flock "$@"; }
  # probe: docker answers; the machine's CPUs and load.
  probe() {
    docker info >/dev/null 2>&1 || return
    echo "cpus $(nproc)"
    echo "load $(uptime | awk -F'load average: ' '{print $2 + 0}')"
  }
  # left: the MiB ak's containers here may still be given: all the machine's memory but a tenth
  # its system keeps, less what the running ones were given.
  left() {
    ids=$(docker ps -q --filter name=ak-) || return
    total=$(free -m | awk '$1 == "Mem:" {print $2}')
    docker inspect --format '{{.HostConfig.Memory}}' $ids 2>/dev/null |
      awk -v total="$total" '{given += $1} END {print int(total - total / 10 - given / 1048576)}'
  }
  running() { [ "$(docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
  tags() { docker image ls --format '{{.Repository}}:{{.Tag}}' "$1"; }
  # drop: deletes the images named on stdin, but those a suite here prepared and has not finished
  # with; docker keeps those a container uses.
  drop() {
    grep -vxF -f <(cat "$ROOT"/*/image/name 2>/dev/null) | xargs -r docker image rm >/dev/null 2>&1
    return 0
  }
  # images KEY IMAGE, under the build lock: the suite's image, built unless the machine has it;
  # the repository's other images go once no suite here names them.
  images() {
    docker image inspect "$2" >/dev/null 2>&1 || {
      cd "$ROOT/$1" && mkdir -p context &&
        docker build -q -t "$2" -f "$PWD/image/Containerfile" context </dev/null >build.log 2>&1 ||
        exit 253
    }
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
  stop() { docker stop -t 1 "$1"; }
}
