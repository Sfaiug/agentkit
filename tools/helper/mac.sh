#!/bin/bash
# The suite helper's Mac side (agentkit/helper.py), run over ssh as `bash -c <this> mac.sh VERB
# ...`; macOS bash is 3.2. Each failure of its own exits 255, ssh's own: a lost piece.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$HOME/.agentkit-helper"
on_power() { pmset -g batt 2>/dev/null | head -1 | grep -q "'AC Power'"; }
# One suite at a time holds the Mac, by a mark made once it is ready and touched while a piece
# runs: one whose caller is gone lets go in minutes. Is it held by a suite other than key $1?
held() { find "$ROOT" -mindepth 2 -maxdepth 2 -name held -mmin -3 ! -path "$ROOT/$1/held" \
  2>/dev/null | grep -q .; }
case "$1" in
probe)
  on_power && ! held && { container system status ||
    container system start --enable-kernel-install; } >/dev/null 2>&1 || exit 255
  echo "cpus $(sysctl -n hw.ncpu)"
  echo "load $(sysctl -n vm.loadavg | awk '{print $2}')"
  echo "memory_mb $(( $(sysctl -n hw.memsize) / 1048576 ))"
  echo "free_percent $(memory_pressure -Q | awk -F': *' '/free percentage/ {print $2 + 0}')" ;;
prepare)   # KEY IMAGE, the parcel on stdin
  mkdir -p "$ROOT/$2" && tar -x -C "$ROOT/$2" || exit 255
  find "$ROOT" -mindepth 1 -maxdepth 1 -mtime +1 -exec rm -rf {} + 2>/dev/null   # dead callers'
  container image inspect "$3" >/dev/null 2>&1 || {
    cd "$ROOT/$2/image" && container build --progress plain -t "$3" -f Containerfile . \
      </dev/null >build.log 2>&1 || exit 255
    container builder stop >/dev/null 2>&1
    # The helper's image it replaces goes; the owner's own images stay.
    container image ls | awk -v name="${3%:*}" -v keep="${3#*:}" \
      'NR > 1 && $1 == name && $2 != keep {print $1":"$2}' |
      while read -r old; do container image delete "$old" >/dev/null 2>&1; done
  }
  # Two suites marking at once each see the other's mark, and both run at home.
  touch "$ROOT/$2/held" && ! held "$2" || exit 255 ;;
run)       # KEY IMAGE NAME CPUS MEMORY_MB, then piece.sh's arguments
  D="$ROOT/$2" image=$3 name=$4 cpus=$5 memory=$6
  shift 6
  on_power && [ -d "$D" ] || exit 255
  session=$PPID
  until [ "$session" -le 1 ] || ps -o comm= -p "$session" | grep -q sshd; do
    session=$(ps -o ppid= -p "$session" | tr -d ' ')
  done
  # psi=1: the suite sizes its pool from pressure; an unmasked /proc lets its sandbox mount one.
  caffeinate -is container run --rm --init --progress none --kernel-arg psi=1 --masked-path NONE \
    --read-only-path NONE --no-dns --cpus "$cpus" --memory "${memory}m" --name "$name" \
    --volume "$D:/in:ro" "$image" /bin/bash /in/piece.sh "$@" &
  vm=$!
  # The VM stops once ak's ssh session ends or the Mac leaves its charger; the stop is repeated
  # until `container run` ends, so a VM that comes up after the first stop stops too.
  ( while ps -p "$session" && on_power; do touch "$D/held"; sleep 5; done
    touch "$D/$name.lost"
    while ps -p "$vm"; do container stop "$name"; sleep 1; done ) >/dev/null 2>&1 &
  wait "$vm"
  code=$?
  kill $! 2>/dev/null
  [ -e "$D/$name.lost" ] && exit 255 || exit "$code" ;;
finish) rm -rf "${ROOT:?}/$2" ;;
*) exit 255 ;;
esac
