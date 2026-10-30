#!/bin/bash
# The suite helper's Linux side (agentkit/helper.py): mac.sh's verbs on a machine with docker that
# holds nothing but ak's work, so its whole size is ak's. Exits match helper.py: 252 no room, 253
# docker or preparation failure; 255 belongs to ssh. A piece keeps its own exit.
export ROOT="$HOME/.agentkit-helper"
export MIRRORS="$ROOT/mirrors"   # each repository's history, kept between its suites
locked() { flock "$1" bash -c "$(declare -f)"'
  "$@"' linux.sh "${@:2}"; }
held() { rm "$1"; until [ -e "$1" ] || ! kill -0 "$2"; do sleep 0.1; done; rm -f "$1"; }
# left: the MiB of memory no container of ak's has been given; the system keeps a tenth.
left() {
  total=$(free -m | awk 'NR == 2 {print $2}')
  given=$(docker ps -q --filter name=ak- | xargs -r docker inspect --format '{{.HostConfig.Memory}}' |
    awk '{sum += $1} END {print int(sum / 1048576)}') || return
  echo $(( total - total / 10 - given ))
}
running() { [ "$(docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
images() {
  docker image inspect "$2" >/dev/null 2>&1 || {
    cd "$ROOT/$1" && mkdir -p context || exit 253
    docker build -q -t "$2" -f "$PWD/image/Containerfile" context </dev/null >build.log 2>&1 || exit 253
  }
  docker image ls --format '{{.Repository}}:{{.Tag}}' "${2%:*}" | grep -vxF "$2" | xargs -r docker image rm >/dev/null 2>&1
  find "$MIRRORS" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null
  return 0
}
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
case "$1" in
probe)
  docker info >/dev/null 2>&1 || exit 253
  room=$(left) || exit 253
  echo "cpus $(nproc)"
  echo "load $(uptime | awk -F'load average: ' '{split($2, load, ","); print load[1] + 0}')"
  echo "room_mb $room" ;;
known)
  touch -c "$MIRRORS/$2"
  git -C "$MIRRORS/$2" rev-parse -q --verify refs/known/base 2>/dev/null; exit 0 ;;
prepare)
  mkdir -p "$ROOT/$2" && tar -x -p -C "$ROOT/$2" && echo "$3" >"$ROOT/$2/image/name" || exit 253
  find "$ROOT" -mindepth 1 -maxdepth 1 -type d ! -name mirrors -mtime +1 -exec rm -rf {} + 2>/dev/null
  M="$MIRRORS/$4"
  mkdir -p "$MIRRORS" && locked "$M.lock" git init -q --bare "$M" || exit 253
  locked "$ROOT/build.lock" images "$2" "$3" || exit
  locked "$M.lock" history "$2" "$M" ;;
run)
  D="$ROOT/$2" image=$3 name=$4 cpus=$5 memory=$6 M="$MIRRORS/$7"
  shift 7
  out="$D/$name.out"
  [ -d "$D" ] && [ -d "$M" ] && rm -rf "$out" && mkdir -m 777 "$out" || exit 253
  session=$PPID
  until [ "$session" -le 1 ] || ps -o comm= -p "$session" | grep -q sshd; do
    session=$(ps -o ppid= -p "$session" | tr -d ' ')
  done
  flag=$D/$name.admit
  : >"$flag" && { locked "$ROOT/vms.lock" held "$flag" $$ </dev/null >/dev/null 2>&1 & }
  while [ -e "$flag" ]; do kill -0 $! 2>/dev/null || exit 253; sleep 0.1; done
  room=$(left) || exit 253
  [ "$memory" -le "$room" ] || exit 252
  docker run --rm --init --name "$name" --network none --cpus "$cpus" --memory "${memory}m" \
    --memory-swap "${memory}m" --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --security-opt systempaths=unconfined --volume "$D:/in:ro" --volume "$M:/mirror:ro" \
    --volume "$out:/out" "$image" /bin/bash /in/piece.sh "$@" &
  vm=$!
  ( while ps -p "$session"; do sleep 5; done
    echo 253 >"$D/$name.lost"
    while ps -p "$vm"; do docker stop -t 1 "$name"; sleep 1; done ) >/dev/null 2>&1 &
  until running "$name" || ! kill -0 "$vm" 2>/dev/null; do sleep 0.2; done
  : >"$flag"
  wait "$vm"
  code=$?
  kill $! 2>/dev/null; wait $! 2>/dev/null
  [ ! -e "$D/$name.lost" ] || exit "$(cat "$D/$name.lost")"
  exit "$code" ;;
failed)
  f="$ROOT/$2/$3.out/${4:-failed}"
  [ ! -f "$f" ] || [ -L "$f" ] || cat "$f"; exit 0 ;;
finish) rm -rf "${ROOT:?}/$2" ;;
*) exit 253 ;;
esac
