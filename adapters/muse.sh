#!/usr/bin/env bash
# Muse Code adapter.  run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                     usage        -> cached meta subscription meters or a recorded quota window
#                     interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                  for `ak orch`; the id resumes that session.  `new` -- open the
#                                  next session under an id of the caller's -- exits 3: the TUI
#                                  rejects `--session-id`, so a Muse seat is given no id at all
#                     install      -> Meta's installer, unless muse is already here
#                     login        -> `muse login`, unless already logged in
#                     auth [seat]  -> 0 when a turn can authenticate, 1 and one line why;
#                                  `seat` is the same login here, and is accepted and ignored
#                     hooks        -> a no-op: Muse has none, so its seats are read off the screen
#                     models       -> one `id<TAB>label<TAB>efforts` line per model it runs,
#                                  from the [catalog] table of adapters/muse.toml
# AGENTKIT_MUSE_PROVIDER=echo selects the offline stub (tests); --model/--reasoning-effort
# are only legal with --provider meta.
set -uo pipefail
command -v muse >/dev/null || PATH="$HOME/.local/bin${PATH:+:$PATH}"   # its installer puts it here: the fallback when PATH has no answer
# Shell rc files need not run in a worker or a detached seat. Also neutralize an inherited
# installer request: the launcher handles it before it checks MUSE_NO_AUTO_UPDATE.
export MUSE_NO_AUTO_UPDATE=1 MUSE_LAUNCHER_INSTALL=0
# A seat's rulebook is named in this variable (see `interactive`), and every process that seat
# starts inherits it.  `[launch] seat_env` in adapters/muse.toml is what keeps it out of the
# environments agentkit builds for a run -- its workers, its done-when commands, whatever
# harness they start.  This line covers the rest: a call made straight into this adapter with
# the seat's own environment, `ak usage` from a seat's shell among them.  Either way only a
# launch that asks for a rulebook gets one, and no worker is ever told it is the orchestrator.
unset TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE
STATE="$HOME/.agentkit/state"
AUTH="${XDG_CONFIG_HOME:-$HOME/.config}/muse/auth.json"
cmd=${1:-}; shift 2>/dev/null || true

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "muse.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  [ -d "$ws" ] || { echo "muse.sh: no such workspace: $ws" >&2; exit 2; }
  prov=${AGENTKIT_MUSE_PROVIDER:-meta}
  set -- exec --provider "$prov" --yolo --approval-judge off --workspace "$ws" --prompt-file "$pf" --json
  [ "$prov" = meta ] && set -- "$@" --model "$model" --reasoning-effort "$effort"
  [ -n "$sid" ] && set -- "$@" --session-id "$sid"
  MUSE_NO_AUTO_UPDATE=1 muse "$@" >"$out/events.jsonl" 2>"$out/stderr.log"
  rc=$?
  # slurp: run_terminal text is multi-line, so take the last event's whole text, not the last line
  jq -rs '[.[] | select(.payload.kind=="run_terminal") | .payload.text // ""] | last // ""' \
    "$out/events.jsonl" >"$out/final.md" 2>/dev/null || : >"$out/final.md"
  # via a variable: `jq | head -1 >file || : >file` truncates the id it just wrote
  # whenever pipefail sees jq die of SIGPIPE, which it does once muse emits two session frames
  sid=$(jq -r 'select(.stream.kind=="session")|.stream.id' "$out/events.jsonl" 2>/dev/null | head -1)
  printf '%s' "$sid" >"$out/session_id"
  # A quota is recorded only from the harness's own failure signal: a `task_lifecycle`
  # failed event naming the quota error, a `run_terminal` reason (never its text, which
  # is the model's own prose), or the harness's own stderr.  Tool output and quoted
  # fixtures live in other event fields, so raw grep over events.jsonl would mistake a
  # quote for a spent quota: read the parsed fields with jq instead.  Record it as a
  # spent meter so `ak usage` sees meta exhausted until that time.
  ev429=$(jq -r '(select(.payload.kind=="task_lifecycle") | .payload.event // empty
      | select(.kind=="failed") | .reason // empty
      | select(type=="string" and contains("429"))),
    (select(.payload.kind=="run_terminal") | .payload.reason // empty
      | select(type=="string" and contains("429")))' \
    "$out/events.jsonl" 2>/dev/null || true)
  when=$( { printf '%s\n' "$ev429"; grep -hE '429' "$out/stderr.log" 2>/dev/null || true; } \
         | grep -oE 'resets (at )?[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z' | tail -1)
  if [ -n "$when" ]; then
    when=${when#resets }; when=${when#at }
    if date --version >/dev/null 2>&1; then epoch=$(date -u -d "$when" +%s 2>/dev/null)
    else epoch=$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$when" +%s 2>/dev/null); fi
    if [ -n "${epoch:-}" ] && mkdir -p -- "$STATE"; then
      secs=18000; [ $((epoch - $(date -u +%s))) -gt 18000 ] && secs=604800
      printf '{"meters":[{"name":"quota","used":100,"resets_at":%s,"window_secs":%s}]}\n' "$epoch" "$secs" \
        >"$STATE/usage-meta.json"
      # Neither cache is deleted: state/usage.json holds every other provider's reading, and
      # usage-meta-probe.json when a paid request was last spent.  Every read of the snapshot
      # applies this file at once (`usage_recorded` in agentkit/harness/muse.py).
    fi
  fi
  exit $rc ;;
interactive)
  [ $# -ge 2 ] || { echo "muse.sh interactive needs <model> <effort> [session-id [new]]" >&2; exit 2; }
  # `--session-id` is the `exec` spelling: `muse --help` (1.0.3) lists no such root option and
  # the TUI answers `invalid TUI options: unexpected argument '--session-id'`, so a session id
  # of the launcher's making is refused here rather than swallowed.  A seat whose id the
  # launcher could not set is a seat with no id: nothing goes looking for the one it opened.
  [ "${4:-}" = new ] && {
    echo "muse.sh interactive: the TUI cannot be given a session id" >&2; exit 3; }
  # a seat being resumed: the TUI takes `resume <session-uuid>`, with the root options on
  # either side of it
  resume=""; [ -n "${3:-}" ] && resume=$(printf 'resume %q ' "$3")
  # idle-compact.py wraps the TUI so a seat left open all day compacts itself instead of filling
  # its context, on the `[compact]` table of adapters/muse.toml.  `env` and the muse launcher
  # both exec in place, so the process it forked is the one Muse records as having opened the
  # session -- which is how it finds this seat's own context size and no neighbour's.  Headless
  # `ak worker` runs are not wrapped: they are not seats.
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  # The orchestrator rulebook this launch is handed.  `muse --help` (1.3.0) lists no instructions
  # or system-prompt option, so the rules would have had to be typed in as the TUI's opening
  # prompt -- but Muse does read an instructions file, from the environment:
  # TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE is appended to the session's system prompt, verified by a
  # headless run that answered out of a rulebook given it no other way.  That is the path taken
  # here: the rules hold for the whole session rather than being one message in it, and they
  # ride beside the two pins already here instead of in the command Muse itself parses.  It is
  # named for this launch only: adapters/muse.toml declares it under `[launch] seat_env` and the
  # top of this file drops an inherited one, so nothing a seat starts is told it is the
  # orchestrator.  No rulebook, no command line: a seat opened without the rules it was asked
  # for is worse than one that does not open.
  rb=$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}") || {
    echo "muse.sh interactive: no rulebook for this seat" >&2; exit 2; }
  rules=$(printf 'TBH_EVAL_APPEND_SYSTEM_PROMPT_FILE=%q ' "$rb")
  # --model/--reasoning-effort are only legal with --provider meta, so it is named here too
  printf 'python3 %q --harness muse -- env MUSE_NO_AUTO_UPDATE=1 MUSE_LAUNCHER_INSTALL=0 %smuse %s--yolo --provider meta --model %q --reasoning-effort %q\n' \
      "$REPO/tools/idle-compact.py" "$rules" "$resume" "$1" "$2" ;;
usage)
  # Recorded run quotas take precedence, even in a copied adapter without the probe helper.
  # One limit: each meter is trusted for at most its own window, so a weekly file is never
  # read more than seven days after it was written, whatever its reset timestamp says.
  now=$(date -u +%s)
  if [ -s "$STATE/usage-meta.json" ] &&
     jq -e --argjson now "$now" '[.meters[]? | select((.resets_at // 0) > $now)] | length > 0' \
        "$STATE/usage-meta.json" >/dev/null 2>&1; then
    mtime=$(stat -c %Y "$STATE/usage-meta.json" 2>/dev/null \
      || stat -f %m "$STATE/usage-meta.json" 2>/dev/null || true)
    case "$mtime" in ''|*[!0-9]*) mtime="";; esac
    if [ -n "$mtime" ] && jq -e --argjson now "$now" --argjson age "$((now - mtime))" \
        '[.meters[]? | select((.resets_at // 0) > $now and (.window_secs // 0) > $age)] | length > 0' \
        "$STATE/usage-meta.json" >/dev/null 2>&1; then
      jq -c --argjson now "$now" --argjson age "$((now - mtime))" \
        '.meters |= map(select((.resets_at // 0) > $now and (.window_secs // 0) > $age))' \
        "$STATE/usage-meta.json"
      exit 0
    fi
    # Past its window the record would be read straight back by the probe helper below,
    # which trusts it on its reset timestamp alone: drop it so the probe answers as when
    # no record exists.
    rm -f -- "$STATE/usage-meta.json"
  fi
  # One supervised, cached model request; the same deadline applies through ak usage.
  here=$(cd "$(dirname "$0")" && pwd)
  [ -x "$here/muse-usage.sh" ] || {
    printf '%s\n' '{"provider":"meta","meters":[],"error":"unknown: Muse usage probe is unavailable"}'
    exit 0
  }
  exec "$here/muse-usage.sh" ;;
install)
  if command -v muse >/dev/null; then echo "muse: already installed ($(muse --version 2>/dev/null))"; exit 0; fi
  command -v curl >/dev/null || { echo "muse.sh install: curl is required" >&2; exit 2; }
  # bash, not sh: the installer uses [[ ]] throughout and dies under dash
  curl -fsSL https://dev.meta.ai/install.sh | bash ;;
login)
  command -v muse >/dev/null || { echo "muse.sh login: muse is not installed" >&2; exit 2; }
  if [ -s "$AUTH" ]; then echo "muse: already logged in"; exit 0; fi
  [ -t 0 ] || { echo "muse: not logged in; run \`muse login\` in a terminal" >&2; exit 1; }
  MUSE_NO_AUTO_UPDATE=1 muse login ;;
auth)
  # Can a headless turn authenticate right now?  Exit 0 and say so, or exit 1 with one line
  # saying why not; anything else is no answer, and the caller carries on as before.
  # Muse's auth file records a key and no expiry, so its contents are the whole answer -- a
  # file holding nothing but a newline is not a login -- and the offline stub the tests drive
  # needs none of it.  `seat` is the same login here, and is accepted and ignored.
  [ "${AGENTKIT_MUSE_PROVIDER:-meta}" = meta ] || { echo "muse: the $AGENTKIT_MUSE_PROVIDER provider needs no login"; exit 0; }
  [ -n "${META_API_KEY:-}" ] && { echo "muse: META_API_KEY is set"; exit 0; }
  grep -q '[^[:space:]]' "$AUTH" 2>/dev/null || {
    echo "muse: no $AUTH; run \`muse login\`" >&2; exit 1; }
  echo "muse: the login in $AUTH is saved" ;;
hooks)
  # Muse Code 1.2.1 offers no lifecycle hooks, so every state one of its seats can be caught in
  # is read off its screen by the rules in adapters/muse.toml.  Nothing to install.
  echo "muse: no lifecycle hooks; its seats are read from the screen rules in adapters/muse.toml" ;;
models)
  # muse has no command that lists its models: the [catalog] table is the answer
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  python3 "$REPO/tools/catalog.py" muse ;;
*)
  echo "usage: muse.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | muse.sh usage | muse.sh interactive <model> <effort> [session-id [new]] | muse.sh install | muse.sh login | muse.sh auth [seat] | muse.sh hooks | muse.sh models" >&2
  exit 2 ;;
esac
