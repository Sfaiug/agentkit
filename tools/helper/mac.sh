#!/bin/bash
# The suite helper's Mac side (agentkit/helper.py), run over ssh as `bash -c <this> mac.sh VERB
# ...`; macOS bash is 3.2. Exits match helper.py: 251 battery, 252 busy, 253 container or
# preparation failure; 255 belongs to ssh. A piece keeps its own exit.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
ROOT="$HOME/.agentkit-helper"
MIRRORS="$ROOT/mirrors"   # each repository's history, kept between its suites
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
  on_power || exit 251
  ! held || exit 252
  { container system status || container system start --enable-kernel-install; } \
    >/dev/null 2>&1 || exit 253
  echo "cpus $(sysctl -n hw.ncpu)"
  echo "load $(sysctl -n vm.loadavg | awk '{print $2}')"
  echo "memory_mb $(( $(sysctl -n hw.memsize) / 1048576 ))"
  echo "free_percent $(memory_pressure -Q | awk -F': *' '/free percentage/ {print $2 + 0}')" ;;
known)     # REPO: the commit its history here reaches, if any. A suite asks just before its
  # `prepare`, so this marks the history in use: no other suite's `prepare` deletes it for a week.
  touch -c "$MIRRORS/$2"
  git -C "$MIRRORS/$2" rev-parse -q --verify refs/known/base 2>/dev/null; exit 0 ;;
prepare)   # KEY IMAGE REPO, the parcel on stdin
  # -p: the recipe's files keep HEAD's modes, whatever umask the Mac's shell has.
  mkdir -p "$ROOT/$2" && tar -x -p -C "$ROOT/$2" || exit 253
  # Dead callers' trees go after a day.
  find "$ROOT" -mindepth 1 -maxdepth 1 ! -name mirrors -mtime +1 -exec rm -rf {} + 2>/dev/null
  # The repository's copy, empty at first, comes before its image, so the collection below finds
  # an image whose suite then lost the claim.
  M="$MIRRORS/$4"
  [ -d "$M" ] || git init -q --bare "$M" || exit 253
  container image inspect "$3" >/dev/null 2>&1 || {
    # The recipe stays outside its build's context, which holds only the files it copies.
    cd "$ROOT/$2" && mkdir -p context || exit 253
    base=$(awk '$1 == "FROM" {print $2; exit}' image/Containerfile)
    container image inspect "$base" >/dev/null 2>&1 && base=
    container build --progress plain -t "$3" -f "$PWD/image/Containerfile" context </dev/null \
      >build.log 2>&1
    built=$?
    container builder stop >/dev/null 2>&1
    # Once built, the helper's image it replaces goes; the base the build fetched goes even when
    # the build failed, so the Mac holds the one image. The owner's own images stay, the base too
    # where they had it before.
    { [ "$built" != 0 ] || container image ls | awk -v name="${3%:*}" -v keep="${3#*:}" \
        'NR > 1 && $1 == name && $2 != keep {print $1":"$2}'; echo "$base"; } |
      while read -r old; do [ -z "$old" ] || container image delete "$old" >/dev/null 2>&1; done
    [ "$built" = 0 ] || exit 253
  }
  claim "$2" held || exit 252
  # The history arrives once the suite holds the Mac, so one suite writes the copies at a time;
  # one unused (`known`) for a week goes, its image with it. Refs keep each suite's own commits
  # while its directory lives and the last suite's origin branch, for `known`; git's gc drops the
  # rest two weeks on. A copy gone since `known` answered lacks what the parcel left out: exit 3,
  # and helper.py sends the whole history.
  find "$MIRRORS" -mindepth 1 -maxdepth 1 -mtime +7 2>/dev/null | while read -r old; do
    rm -rf "$old"
    container image ls | awk -v name="ak-helper-${old##*/}" 'NR > 1 && $1 == name {print $1":"$2}' |
      while read -r image; do container image delete "$image" >/dev/null 2>&1; done
  done
  read -r tree base <"$ROOT/$2/heads" &&
    { [ ! -e "$ROOT/$2/repo.bundle" ] ||
      git -C "$M" bundle unbundle "$ROOT/$2/repo.bundle" >/dev/null; } &&
    rm -f "$ROOT/$2/repo.bundle" && git -C "$M" cat-file -e "$tree^{commit}" &&
    git -C "$M" update-ref "refs/suites/$2/tree" "$tree" &&
    { [ -z "$base" ] || { git -C "$M" update-ref "refs/suites/$2/base" "$base" &&
      git -C "$M" update-ref refs/known/base "$base"; }; } || exit 3
  git -C "$M" for-each-ref --format='%(refname:lstrip=2)' refs/suites | while read -r ref; do
    [ -d "$ROOT/${ref%/*}" ] || git -C "$M" update-ref -d "refs/suites/$ref"; done
  git -C "$M" -c gc.autoDetach=false gc --auto --quiet >/dev/null 2>&1 ;;
run)       # KEY IMAGE NAME CPUS MEMORY_MB REPO, then piece.sh's arguments
  key=$2 D="$ROOT/$2" image=$3 name=$4 cpus=$5 memory=$6 M="$MIRRORS/$7"
  shift 7
  on_power || exit 251
  [ -d "$D" ] && [ -d "$M" ] || exit 253
  session=$PPID
  until [ "$session" -le 1 ] || ps -o comm= -p "$session" | grep -q sshd; do
    session=$(ps -o ppid= -p "$session" | tr -d ' ')
  done
  # The suite's claim may have aged while ak ran its other checks, so each piece claims the Mac
  # again; held by another suite, it waits as long as a dead holder takes to let go.
  until claim "$key" "$name.held"; do
    on_power || exit 251
    ps -p "$session" >/dev/null || exit 253
    [ "$SECONDS" -lt 180 ] || exit 252
    sleep 5
  done
  rm -f "$D/held"
  # psi=1: the suite sizes its pool from pressure; an unmasked /proc lets its sandbox mount one.
  caffeinate -is container run --rm --init --progress none --kernel-arg psi=1 --masked-path NONE \
    --read-only-path NONE --no-dns --cpus "$cpus" --memory "${memory}m" --name "$name" \
    --volume "$D:/in:ro" --volume "$M:/mirror:ro" "$image" /bin/bash /in/piece.sh "$@" &
  vm=$!
  # The VM stops once ak's ssh session ends or the Mac leaves its charger; the stop is repeated
  # until `container run` ends, so a VM that comes up after the first stop stops too.
  ( lost=253
    while ps -p "$session"; do
      on_power || { lost=251; break; }
      touch "$D/$name.held"; sleep 5
    done
    echo "$lost" >"$D/$name.lost"
    while ps -p "$vm"; do container stop "$name"; sleep 1; done ) >/dev/null 2>&1 &
  wait "$vm"
  code=$?
  kill $! 2>/dev/null; wait $! 2>/dev/null
  rm -f "$D/$name.held"
  [ ! -e "$D/$name.lost" ] || exit "$(cat "$D/$name.lost")"
  exit "$code" ;;
finish) rm -rf "${ROOT:?}/$2" ;;
*) exit 253 ;;
esac
