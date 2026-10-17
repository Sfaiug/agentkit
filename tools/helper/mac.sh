#!/bin/bash
# The suite helper's Mac side (agentkit/helper.py), run over ssh as `bash -c <this> mac.sh VERB
# ...`; macOS bash is 3.2. Each failure of its own exits 255, ssh's own: a lost piece.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$HOME/.agentkit-helper"
on_power() { pmset -g batt 2>/dev/null | head -1 | grep -q "'AC Power'"; }
# One suite at a time holds the Mac: by its claim from `prepare` until its pieces start, then by
# each piece's mark until that piece ends. A running piece keeps touching its mark, so one whose
# caller is gone lets go in minutes. held KEY: is it held by a suite other than KEY?
held() { find "$ROOT" -mindepth 2 -maxdepth 2 -name '*held' -mmin -3 ! -path "$ROOT/$1/*" \
  2>/dev/null | grep -q .; }
# claim KEY MARK: two suites marking at once each see the other's mark, and both let go.
claim() { touch "$ROOT/$1/$2" && ! held "$1" || { rm -f "$ROOT/$1/$2"; return 1; }; }
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
    cd "$ROOT/$2/image" || exit 255
    base=$(awk '$1 == "FROM" {print $2; exit}' Containerfile)
    container image inspect "$base" >/dev/null 2>&1 && base=
    container build --progress plain -t "$3" -f Containerfile . </dev/null >build.log 2>&1
    built=$?
    container builder stop >/dev/null 2>&1
    # Once built, the helper's image it replaces goes; the base the build fetched goes even when
    # the build failed, so the Mac holds the one image. The owner's own images stay, the base too
    # where they had it before.
    { [ "$built" != 0 ] || container image ls | awk -v name="${3%:*}" -v keep="${3#*:}" \
        'NR > 1 && $1 == name && $2 != keep {print $1":"$2}'; echo "$base"; } |
      while read -r old; do [ -z "$old" ] || container image delete "$old" >/dev/null 2>&1; done
    [ "$built" = 0 ] || exit 255
  }
  claim "$2" held || exit 255 ;;
run)       # KEY IMAGE NAME CPUS MEMORY_MB, then piece.sh's arguments
  key=$2 D="$ROOT/$2" image=$3 name=$4 cpus=$5 memory=$6
  shift 6
  on_power && [ -d "$D" ] || exit 255
  session=$PPID
  until [ "$session" -le 1 ] || ps -o comm= -p "$session" | grep -q sshd; do
    session=$(ps -o ppid= -p "$session" | tr -d ' ')
  done
  # The suite's claim may have aged while ak ran its other checks, so each piece claims the Mac
  # again; held by another suite, it waits as long as a dead holder takes to let go.
  until claim "$key" "$name.held"; do
    [ "$SECONDS" -lt 180 ] && ps -p "$session" >/dev/null && on_power || exit 255
    sleep 5
  done
  rm -f "$D/held"
  # psi=1: the suite sizes its pool from pressure; an unmasked /proc lets its sandbox mount one.
  caffeinate -is container run --rm --init --progress none --kernel-arg psi=1 --masked-path NONE \
    --read-only-path NONE --no-dns --cpus "$cpus" --memory "${memory}m" --name "$name" \
    --volume "$D:/in:ro" "$image" /bin/bash /in/piece.sh "$@" &
  vm=$!
  # The VM stops once ak's ssh session ends or the Mac leaves its charger; the stop is repeated
  # until `container run` ends, so a VM that comes up after the first stop stops too.
  ( while ps -p "$session" && on_power; do touch "$D/$name.held"; sleep 5; done
    touch "$D/$name.lost"
    while ps -p "$vm"; do container stop "$name"; sleep 1; done ) >/dev/null 2>&1 &
  wait "$vm"
  code=$?
  kill $! 2>/dev/null; wait $! 2>/dev/null
  rm -f "$D/$name.held"
  [ -e "$D/$name.lost" ] && exit 255 || exit "$code" ;;
finish) rm -rf "${ROOT:?}/$2" ;;
*) exit 255 ;;
esac
