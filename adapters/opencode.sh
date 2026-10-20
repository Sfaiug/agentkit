#!/usr/bin/env bash
# OpenCode adapter.  run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                     usage        -> the named provider's meters: MiMo's plan meters off
#                        the console's own API through the shared browser's login (else
#                        the mimo CLI, else the provider key), [usage] none with the
#                        reason once a key is configured and no source answers; any
#                        other provider's, [usage] none once it has a login; a missing
#                        login is a failed probe, not a neutral meter
#                     interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                  for `ak orch`; the id resumes that session.  `new` -- open the
#                                  next session under an id of the caller's -- exits 3: the TUI
#                                  takes `--session` for one that exists and has no flag for one
#                                  that does not, so a seat's id is the one its plugin reports
#                     install      -> the owner's installer, unless opencode is already here
#                     login        -> `opencode auth login <provider>`, unless already logged in
#                     auth [seat]  -> 0 when a turn on each named provider can authenticate, 1
#                                  and one line why; `seat` is the same login here, and is
#                                  accepted and ignored
#                     hooks        -> says where this harness's hooks come from; writes nothing
#                     models       -> one `id<TAB>label<TAB>efforts` line per model it runs:
#                                  OpenCode's own list, with the label and efforts of the
#                                  [catalog] table of adapters/opencode.toml where it has
#                                  them, else that table
#                     providers    -> one `id<TAB>name<TAB>mode` line per provider OpenCode
#                                  can log in to: logged-in ones first, with their mode, then
#                                  the rest with none
#                     $AGENTKIT_PROVIDER names the providers a call is about, by OpenCode's own
#                     ids (config.provider_env); none named is any provider with a login
#                     $AGENTKIT_ACCOUNT naming one of the provider's `accounts` is refused by
#                     every verb, in one line
set -uo pipefail
PROVIDERS=${AGENTKIT_PROVIDER:-}
# OpenCode 2.0.14 keeps its saved logins (the `credential` and `account` tables) in opencode.db,
# the database its sessions live in, and the only ways to move that file -- OPENCODE_DB and
# XDG_DATA_HOME -- move both: a login of an account's own would strand every conversation
# begun on another.  OPENCODE_CONFIG_DIR moves the config's provider key and not that store,
# so the usual login's saved credentials would still answer, and `opencode auth login` would
# write into the usual one's.  A named account is refused rather than handed the usual login.
if [ -n "${AGENTKIT_ACCOUNT:-}" ]; then
  why="opencode: account $AGENTKIT_ACCOUNT refused; OpenCode keeps logins and sessions in one opencode.db, so a login of its own cannot resume a conversation"
  # a usage probe fails in its own shape, which only an exit 0 keeps
  [ "${1:-}" = usage ] && { printf '{"provider":"%s","meters":[],"error":"unknown: %s"}\n' "${PROVIDERS%% *}" "$why"; exit 0; }
  echo "$why" >&2; exit 1
fi
command -v opencode >/dev/null || PATH="$HOME/.opencode/bin${PATH:+:$PATH}"   # its installer puts it here: the fallback when PATH has no answer
export OPENCODE_DISABLE_AUTOUPDATE=1   # `ak update` owns that; nothing mid-run moves
# No project's opencode.json reaches a turn: the global one is the only config, which is where
# agentkit/harness/opencode.py reads how MiMo is paid, and a workspace can never move it.  The
# same switch keeps the repository's AGENTS.md from a turn, so a worker's rules are ak's.
# OpenCode reads OPENCODE_CONFIG_PROJECT_DISABLE ahead of the older name (2.0.14), so an
# inherited `=0` of it would win: both are pinned.  A seat gets the same: `interactive` prints them.
OWN_RULES_OFF="OPENCODE_DISABLE_PROJECT_CONFIG=1 OPENCODE_CONFIG_PROJECT_DISABLE=1"
# shellcheck disable=SC2086 # OWN_RULES_OFF is one NAME=value per word
export $OWN_RULES_OFF
# A seat's rulebook is named in this variable (see `interactive`), and every process that seat
# starts inherits it.  `[launch] seat_env` in adapters/opencode.toml is what keeps it out of the
# environments agentkit builds for a run -- its workers, its done-when commands, whatever
# harness they start.  This line covers the rest: a call made straight into this adapter with
# the seat's own environment, `ak usage` from a seat's shell among them.  Either way only a
# launch that asks for a rulebook gets one, and no worker is ever told it is the orchestrator.
unset OPENCODE_CONFIG_CONTENT
CFGDIR="${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"
CFG="$CFGDIR/opencode.json"
cmd=${1:-}; shift 2>/dev/null || true

# The first non-blank apiKey configured for provider $1, or for any provider where $1 is
# empty, failing when there is none.  The file is read whole first (`-s`), so one that is
# not JSON fails before any key in it is printed.
config_key() {
  jq -ers --arg p "${1:-}" 'first(.[]
      | (if $p == "" then . else [.provider[$p]?, .providers[$p]?] end)
      | .. | objects | select(has("apiKey")) | .apiKey | strings | select(length > 0))' \
      "$CFG" 2>/dev/null
}

# 0 when config_key finds one, non-zero when it does not, 2 when the question cannot be
# answered for want of jq: a blank file is not a login, and a guess is not an answer.
have_key() {
  [ -r "$CFG" ] || return 1
  command -v jq >/dev/null || return 2
  config_key "${1:-}" >/dev/null
}

# 0 when the auth store holds a login for provider $1, or for any provider where $1 is empty:
# what `opencode auth login` keeps beside the config.  OpenCode's provider list is no answer:
# its config alone enables a provider, key or not, and a saved login leaves one `auto`.  Slow
# -- it boots a private server -- so the config check runs first and this only on its `no`.
# `--standalone` is load-bearing: without it the call waits on the shared background service
# instead of answering.  The list names every provider with a saved login, one
# `"id": "<provider>"` each (2.0.24).  Matched as text, since a saved login is a yes even
# where jq is missing.
store_key() {
  listed=$(command -v opencode >/dev/null \
    && opencode auth list --standalone --format json 2>/dev/null) || listed=""
  [ -n "${1:-}" ] && want="\"id\":\"$1\"" || want='"id":'
  case "${listed//[[:space:]]/}" in *"$want"*) return 0 ;; esac
  return 1
}

# The providers OpenCode runs with no login at all -- its own free models, `opencode`'s
# (2.0.24) -- as one JSON array: those its provider list calls `enabled` that no config
# document it merged names, since an entry alone would enable one, key or not.  `config.get`
# lists every such document, opencode.jsonc and $OPENCODE_CONFIG among them, already parsed.
# The list is the background service's, whose documents are the ones it started with, while
# a turn's private server (`--standalone`) reads this environment's: a provider either names
# is excluded.  The service fills that list from the plugins it activates in the background,
# `opencode`'s among them, and answers it before they are active, so a fresh service lists
# none at first (2.0.24); of its lists integration.list alone waits for them, so it is asked
# first and its answer dropped.  All four answers come within one 10-second bound, which leaves
# `auth` inside its caller's cap, and a missing or stopped one is no provider.  Settings, keys
# among them, never leave jq.
own_providers() {
  command -v jq >/dev/null && command -v timeout >/dev/null && command -v opencode >/dev/null || return 1
  timeout 10 sh -c 'opencode api integration.list >/dev/null && opencode api provider.list &&
      opencode api config.get && opencode api --standalone config.get' 2>/dev/null | jq -cs '
      select(length == 3 and all(.[1:][]; type == "array"))
      | [.[1:][][].info? | (.provider, .providers) | objects | keys[]] as $named
      | [.[0].data[]? | select(.activation == "enabled") | .id | select(IN($named[]) | not)]' 2>/dev/null
}

own_login() { [ -n "${1:-}" ] && own_providers | jq -e --arg p "$1" 'index([$p])' >/dev/null 2>&1; }

# A login for provider $1, or none needed: a key in the config, a saved one, OpenCode's own --
# the service last, so a saved login answers even while the service does not.
logged_in() { have_key "${1:-}" || store_key "${1:-}" || own_login "${1:-}"; }

# The effort is OpenCode's model variant, `provider/model#variant` its `-m` spelling.  OpenCode
# fails a turn handed a variant the model does not define (`Variant unavailable`) and merges
# the variants of this layered config document -- which writes nothing -- into the model's own
# by name (2.0.24).  So `none`, a model that runs at no effort, is always a variant defined
# here empty: a model with a `none` of its own keeps its settings, any other runs bare.  MiMo's
# API has one reasoning control, `thinking`, on by default; a `thinking` option in the model's
# `options`, or in a variant's own keys, never reaches the request, while a variant's
# `extraBody` is sent as it is.  So a `mimo/` model's `none` turns it off and its `high` on.
turn_variants() {  # <model>: the document defining its variants for this turn
  p=${1%%/*} m=${1#*/} v='"none":{}'
  [ "$p" = mimo ] && v='"none":{"extraBody":{"thinking":{"type":"disabled"}}},"high":{"extraBody":{"thinking":{"type":"enabled"}}}'
  printf '{"provider":{"%s":{"models":{"%s":{"variants":{%s}}}}}}' "$p" "${m%%#*}" "$v"
}

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "opencode.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  out=$(cd -- "$out" && pwd) || exit 2
  [ -d "$ws" ] || { echo "opencode.sh: no such workspace: $ws" >&2; exit 2; }
  command -v opencode >/dev/null || { echo "opencode.sh: opencode is not installed" >&2; exit 2; }
  cd -- "$ws" || { echo "opencode.sh: no such workspace: $ws" >&2; exit 2; }
  # the effort as the model's variant (turn_variants); a model already carrying one keeps it
  tagged="$model#$effort"
  case $model in *#*) tagged=$model;; esac
  export OPENCODE_CONFIG_CONTENT="$(turn_variants "$model")"
  # The session is titled for the run it belongs to: <run>/round-N/<role> reads as
  # `<run-id>/<role>` in `opencode session list`, anything else as its own directory.
  title=$(basename -- "$out")
  [ -f "$out/../../run.json" ] && title="$(basename -- "$(dirname -- "$(dirname -- "$out")")")/$title"
  # The prompt is attached whole with --file, and the message only points to it: `opencode
  # run` reads neither stdin nor a prompt file, `--prompt` is not one of its flags, and Linux
  # refuses a single argument over 128 KiB -- the exec fails at once with `Argument list too
  # long`.  The message stays before --file, which swallows a trailing prompt as another
  # filename.  `--session` continues that session; `--standalone` keeps the turn on a private
  # server rather than the shared background service.
  [ -r "$pf" ] || { echo "opencode.sh: cannot read $pf" >&2; exit 2; }
  msg="The full prompt is attached. Read it whole and follow it as your task: $pf"
  set -- run --standalone --auto --format json -m "$tagged" --title "$title"
  [ -n "$sid" ] && set -- "$@" --session "$sid"
  opencode "$@" "$msg" --file "$pf" >"$out/events.jsonl" 2>"$out/stderr.log"
  rc=$?
  # The turn's last message, as every other harness hands back: the text parts of the message
  # the last one belongs to, where a tool turn's earlier messages are narration between its
  # calls.  Read a line at a time, so an unparsable line costs only itself.
  jq -nrR '[inputs | fromjson? | select(.type? == "text") | .part | objects] as $p
      | ($p | last | .messageID) as $m
      | if $m == null then $p[-1:] else $p | map(select(.messageID == $m)) end
      | .[] | .text // empty' "$out/events.jsonl" >"$out/final.md" 2>/dev/null || true
  # the last id seen wins -- an id does not change within a turn anyway -- and an empty
  # stream leaves an empty file, which is what a turn that never authenticated says
  sid=$(jq -r 'select(.sessionID != null) | .sessionID' "$out/events.jsonl" 2>/dev/null | tail -1 2>/dev/null)
  printf '%s' "$sid" >"$out/session_id"
  # OpenCode says a failure in its event log and nothing on stderr, while the loop's auth
  # watch reads stderr alone -- tool output quoting a logout must never trip it.  Only real
  # error records are mirrored, so the property holds: a turn that said `Invalid API Key`
  # parks waiting_login instead of burning three retries on a wall.
  jq -r 'select(.type == "error") | (.error.message // empty) | select(length > 0)' \
      "$out/events.jsonl" 2>/dev/null >>"$out/stderr.log" || true
  # A trivial turn streams no usage at all, so the session's own totals are read back and
  # appended as this run's `result` record, which is what agentkit/history.py counts.
  # `session export` reports input, output and reasoning apart -- output never includes
  # reasoning (19 beside 23 on the turn this was read from) -- with the cache each step
  # re-sent beside them, so output_tokens here is output plus reasoning, the whole of what
  # the turn generated.  An export that fails leaves no line: that turn reports no tokens,
  # the way an unparsable stream does on every harness.
  if [ -n "$sid" ]; then
    usage=$(opencode session export "$sid" --standalone 2>/dev/null | jq -c \
        '{type: "result", sessionID: .info.id,
          usage: {input_tokens: (.info.tokens.input // 0),
                  output_tokens: ((.info.tokens.output // 0) + (.info.tokens.reasoning // 0)),
                  cache_read_input_tokens: (.info.tokens.cache.read // 0),
                  cache_creation_input_tokens: (.info.tokens.cache.write // 0)}}' \
        2>/dev/null) || usage=""
    [ -n "$usage" ] && printf '%s\n' "$usage" >>"$out/events.jsonl"
  fi
  exit $rc ;;
interactive)
  [ $# -ge 2 ] || { echo "opencode.sh interactive needs <model> <effort> [session-id [new]]" >&2; exit 2; }
  # `--session` reopens a conversation that exists; nothing names one that does not, so an id
  # of the launcher's making is refused here rather than swallowed.  The id a seat comes back
  # on is the one OpenCode made for it, which hooks/opencode-seat wrote into that launch's
  # receipt -- agentkit/harness/opencode.py -- and never a directory's latest by guess.
  [ "${4:-}" = new ] && {
    echo "opencode.sh interactive: the TUI cannot be given a session id" >&2; exit 3; }
  resume=""; [ -n "${3:-}" ] && resume=$(printf -- '--session %q ' "$3")
  # idle-compact.py wraps the TUI, as every seat's, so the seat is looked at again when its
  # screen comes to rest, starts moving or opencode exits.  Headless `ak worker` runs are not
  # wrapped: they are not seats.
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  # The orchestrator rulebook this launch is handed.  OpenCode 2.0.13 takes no --model, --agent
  # or instructions flag on its TUI: new sessions open on the build agent and the last-used
  # model.  All three are pinned per launch instead, as one layered config document in
  # OPENCODE_CONFIG_CONTENT -- the rulebook verbatim as the build agent's system prompt, the
  # model with the effort as its variant, and the seat plugin beside them -- verified by a
  # headless probe that answered out of a rulebook given it no other way, and by a seat that
  # opened on the model it names.  The owner's own ~/.config/opencode is never written to.
  # It is named for this launch only: adapters/opencode.toml declares it under `[launch]
  # seat_env` and the top of this file drops an inherited one, so nothing a seat starts is
  # told it is the orchestrator.  No rulebook, no command line: a seat opened without the
  # rules it was asked for is worse than one that does not open.
  rb=${AGENTKIT_RULEBOOK:-$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}")} || {
    echo "opencode.sh interactive: no rulebook for this seat" >&2; exit 2; }
  tagged="$1#$2"   # as `run` hands it, and with its variants beside it
  case $1 in *#*) tagged=$1;; esac
  # jq writes the document, the rulebook read as one string: a Python started for it was more
  # than half of what a launch waited on this adapter.  ASCII out, as that Python wrote it, so
  # the command line stays plain whatever the rulebook says.
  content=$(jq -acRs --arg model "$tagged" --arg plugin "$REPO/hooks/opencode-seat" \
      --argjson more "$(turn_variants "$1")" \
      '{model: $model, agents: {build: {system: .}}, plugins: [$plugin]} + $more' <"$rb") || {
    echo "opencode.sh interactive: no rulebook for this seat" >&2; exit 2; }
  rules=$(printf 'OPENCODE_CONFIG_CONTENT=%q ' "$content")
  # The seat's first message, when its launch carries one, goes in as the TUI's `--prompt`:
  # sent once the conversation has loaded, never typed into a TUI still loading it.
  # Single quotes, not %q: shlex.split, which `ak orch` parses this line with, reads no $'...'.
  first=""; [ -z "${AGENTKIT_FIRST_PROMPT:-}" ] ||
    { sq="'"; first=" --prompt '${AGENTKIT_FIRST_PROMPT//$sq/$sq\\$sq$sq}'"; }
  printf 'python3 %q --harness opencode -- env OPENCODE_DISABLE_AUTOUPDATE=1 %s %sopencode %s--standalone --auto%s\n' \
      "$REPO/tools/idle-compact.py" "$OWN_RULES_OFF" "$rules" "$resume" "$first" ;;
usage)
  # No login is a failed probe, not a missing meter: without one an unauthenticated provider
  # would read as a neutral 1.0 provider and be picked ahead of logged-in ones, only for
  # the turn to fail authentication.  usage.py prefers an error over none, and asks the
  # harness's `auth` verb -- what puts `no login` on the menu row -- only when the probe
  # ran and said something.  MiMo's plan has a meter, read below; OpenCode reads no other
  # provider's, so a logged-in one is [usage] none and stays neutral.
  p=${PROVIDERS%% *}
  if [ "$p" != mimo ]; then
    if [ -z "$p" ]; then why="unknown: no provider named in AGENTKIT_PROVIDER"
    elif logged_in "$p"; then
      printf '{"provider":"%s","meters":[],"error":null,"none":"no meter: OpenCode reads none for %s"}\n' "$p" "$p"
      exit 0
    else why="unknown: no login for $p; run opencode auth login $p"; fi
    printf '{"provider":"%s","meters":[],"error":"%s"}\n' "$p" "$why"
    exit 0
  fi
  have_key mimo; rc=$?
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 2 ]; then why="could not be checked without jq"
    else why="is missing"; fi
    printf '{"provider":"mimo","meters":[],"error":"unknown: no provider key (%s); run opencode auth login"}\n' \
      "$why"
    exit 0
  fi
  # The key is configured: the plan meter is the figures the console's own
  # plan-manage page draws.  That page is a static bundle whose request helper
  # prefixes every call with /api/v1, and the two calls behind its plan figures
  # are GET tokenPlan/usage and GET tokenPlan/detail, answered only with the
  # Xiaomi web login -- the provider key gets 401.  usage carries the plan's
  # items as {name, used, limit, percent}, percent a 0-1 fraction, across
  # data.usage (plan_total_token, compensation_total_token) and data.monthUsage
  # (month_total_token); detail carries the plan's currentPeriodEnd as UTC
  # "YYYY-MM-DD HH:mm:ss".  (Envelope and field names verified 2026-09-22
  # against the live API's own answers and the bundle it serves.)
  # Three sources are tried in order -- the shared browser's login, the mimo
  # CLI, the provider key against the same two calls -- and the first
  # meter-shaped answer wins.  Only when every source was tried and none
  # answered does the verb fall to none with the reason, naming each source
  # and what it said, so [usage] none keeps the logged-in provider neutral
  # instead of ranking it last like a failed probe.  The caller's probe timeout
  # is 30s: past 20s the sources still untried are noted, not tried, so a slow
  # console still answers neutral instead of timing the probe out -- which would
  # rank the provider last, the outcome the none exists to prevent.
  API="https://platform.xiaomimimo.com/api/v1"
  CONSOLE="https://platform.xiaomimimo.com/console/plan-manage"
  HOST="platform.xiaomimimo.com"
  notes=""; login_missing=0
  note() { notes="${notes:+$notes; }$1"; }
  # tokenplan_meters <usage-body> <detail-body>: the console's two answers as one
  # meter list, or nothing when either is not a code-0 answer with items.  The
  # plan window is a calendar month whose start the API never names, so plan and
  # compensation reset at the period end on a nominal 30 days, while the month
  # counter resets at month end on the month's own length (UTC; the period end
  # when the month cannot be computed).
  tokenplan_meters() {
    TZ=UTC jq -c -n --argjson u "$1" --argjson t "$2" '
      ($u | select(.code == 0) | .data) as $d
      | ($t | select(.code == 0) | .data) as $p
      | select($d != null and $p != null)
      | ((($p.currentPeriodEnd // "") | sub(" "; "T") | . + "Z")
         | try fromdateiso8601 catch null) as $r
      | select(($r | type) == "number" and $r > 0)
      | (try (now | gmtime | .[0:2] as [$y,$m0] | ($m0 + 1) as $mo
             | (if $mo == 12 then [$y+1,1] else [$y,$mo+1] end) as [$ny,$nm]
             | {e: ("\($ny)-\($nm)-01" | strptime("%Y-%m-%d") | mktime),
                s: ("\($y)-\($mo)-01" | strptime("%Y-%m-%d") | mktime)})
           catch null
         | select(. != null and .e > .s and .e > 0)) as $m
      | [(($d.usage.items // []) + ($d.monthUsage.items // []))[]]
      | map(select((.name | type) == "string" and (.percent | type) == "number")
            | {name: (.name | sub("_total_token$"; "")),
               used: (((.percent * 1000 | round) / 10)
                      | if . < 0 then 0 elif . > 100 then 100 else . end)}
            | .resets_at = (if .name == "month" and $m != null then $m.e
                            else ($r | floor) end)
            | .window_secs = (if .name == "month" and $m != null then ($m.e - $m.s)
                              else 2592000 end))
      | select(length > 0)' 2>/dev/null || true
  }
  # plan_probe <header-file>: the console's two calls with those credentials.
  # Prints one line: `meters <json>` when both answers parse, else `expired`,
  # `unreachable`, `http <code> <call>` or `nometers`.  Nothing of the
  # credentials is ever printed, only the outcome.  The detail call runs only
  # when the usage call answered 200: one credential, one verdict.
  plan_probe() {
    uresp=$(curl -s -m 8 -w $'\n%{http_code}' "$API/tokenPlan/usage" -H @"$1" 2>/dev/null || true)
    ucode=${uresp##*$'\n'}; ubody=${uresp%$'\n'*}
    case "$ucode" in
      200) ;;
      000|"") printf 'unreachable\n'; return 0 ;;
      401|403) printf 'expired\n'; return 0 ;;
      *) printf 'http %s usage\n' "$ucode"; return 0 ;;
    esac
    dresp=$(curl -s -m 8 -w $'\n%{http_code}' "$API/tokenPlan/detail" -H @"$1" 2>/dev/null || true)
    dcode=${dresp##*$'\n'}; dbody=${dresp%$'\n'*}
    [ "$dcode" = 200 ] || { printf 'http %s detail\n' "${dcode:-000}"; return 0; }
    meters=$(tokenplan_meters "$ubody" "$dbody")
    if [ -n "$meters" ]; then printf 'meters %s\n' "$meters"; else printf 'nometers\n'; fi
  }
  # First the shared browser's login, replaying the plan page's own calls as its
  # own fetch in a tab on the console page.  Chromium keeps its cookie values
  # AES-encrypted in its store, which no adapter call can decrypt -- the page's
  # own fetch is the read that carries the login, and no cookie of it is ever
  # read out.  The remembered tab is reused across probes; one that went away is
  # recreated over CDP (bridge `open` would steal the owner's focus), and one a
  # login elsewhere left behind is moved to the console in place.  Whatever the
  # tab answers short of meters is a note, never an error: only a missing
  # provider key fails this probe.
  BRIDGE_DIR="$HOME/.local/share/browser-bridge"
  BRIDGE_PY="$BRIDGE_DIR/bridge.py"; BRIDGE_VENV="$BRIDGE_DIR/venv/bin/python"
  SESS="agentkit-mimo-usage"
  bexec=""; command -v timeout >/dev/null && bexec="timeout"
  # bridge_eval <js> [by]: one eval, cut off after 6s or at second <by> of the
  # probe, whichever comes first, and never started once <by> is past.
  bridge_eval() {
    left=$(( ${2:-99} - SECONDS )); [ "$left" -le 6 ] || left=6
    [ "$left" -gt 0 ] || return 1
    BRIDGE_SESSION="$SESS" ${bexec:+$bexec $left} "$BRIDGE_VENV" "$BRIDGE_PY" eval "$1" 2>/dev/null
  }
  JS="(async () => { const host = location.host; const get = async (p) => { const r = await fetch(p, {credentials: 'include'}); const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch (e) { return {http: r.status, json: false}; } return {http: r.status, json: true, code: j.code, data: j.data}; }; try { const u = await get('/api/v1/tokenPlan/usage'); if (!u.json || u.code !== 0) return JSON.stringify({ok: false, stage: 'usage', http: u.http, code: u.code, host: host}); const d = await get('/api/v1/tokenPlan/detail'); if (!d.json || d.code !== 0) return JSON.stringify({ok: false, stage: 'detail', http: d.http, code: d.code, host: host}); return JSON.stringify({ok: true, usage: u.data, detail: d.data, host: host}); } catch (e) { return JSON.stringify({ok: false, stage: 'fetch', host: host}); } })()"
  fetch_payload() {  # [by]: one fetch round in the remembered tab, as JSON or empty
    out=$(bridge_eval "$JS" "${1:-}" || true)
    payload=$(printf '%s' "$out" | jq -r . 2>/dev/null || true)
    case "$payload" in '{'*) ;; *) payload="";; esac
  }
  if [ ! -x "$BRIDGE_VENV" ] || [ ! -f "$BRIDGE_PY" ]; then
    note "browser bridge not installed"
  else
    fetch_payload
    if [ -z "$payload" ]; then
      # No answer: the remembered tab is gone, or there never was one.  Start
      # clean over CDP, then fetch twice: a fresh tab may still be navigating
      # when the first round lands, and its redirect destroys that round.
      rm -f "$BRIDGE_DIR/selections/$SESS.json" 2>/dev/null
      port=${BROWSER_BRIDGE_CDP_PORT:-$(jq -r '.cdp_port // empty' \
        "$BRIDGE_DIR/runtime.json" 2>/dev/null || true)}
      target=$(curl -s -m 5 -X PUT \
        "http://127.0.0.1:${port:-9222}/json/new?$CONSOLE" 2>/dev/null \
        | jq -r '.id // empty' 2>/dev/null || true)
      if [ -n "$target" ] && mkdir -p "$BRIDGE_DIR/selections" 2>/dev/null \
          && printf '{"target_id":"%s"}' "$target" \
            >"$BRIDGE_DIR/selections/$SESS.json" 2>/dev/null; then
        fetch_payload
        [ -n "$payload" ] || fetch_payload
      fi
    fi
    # A 401 on the console's own host is its session lapsed: the console keeps a
    # short-lived one and the remembered tab never reloads, while the Xiaomi
    # account login behind it outlasts both, so one page load of the console
    # signs in again by itself.  The tab is sent there once -- its old page
    # marked, so that page is never taken for the new one -- polled until it
    # settles back on the console, 8s at most, and fetched again: only that
    # round can say the login is missing.  The renewal counts toward the probe
    # budget, and one still settling past it is left to finish for the next probe.
    renewed=0
    if [ "$SECONDS" -lt 20 ] \
        && [ "$(printf '%s' "$payload" | jq -r '"\(.host) \(.http)"' 2>/dev/null)" = "$HOST 401" ]; then
      settle=$((SECONDS + 8)); [ "$settle" -le 20 ] || settle=20; page=""
      bridge_eval "window.akRenew = 1, location.href = '$CONSOLE'" "$settle" >/dev/null 2>&1 || true
      while [ "$page" != "$HOST complete" ] && [ "$SECONDS" -lt "$settle" ]; do
        sleep 0.5
        page=$(bridge_eval "window.akRenew ? '' : location.host + ' ' + document.readyState" \
          "$settle" | jq -r . 2>/dev/null || true)
      done
      [ "$SECONDS" -lt 20 ] && { fetch_payload 20; renewed=1; }
    fi
    if [ -n "$payload" ] && [ "$(printf '%s' "$payload" | jq -r '.ok // false' 2>/dev/null)" = true ]; then
      u=$(printf '%s' "$payload" | jq -c '{code:0,data:.usage}' 2>/dev/null || true)
      t=$(printf '%s' "$payload" | jq -c '{code:0,data:.detail}' 2>/dev/null || true)
      meters=$(tokenplan_meters "$u" "$t")
      if [ -n "$meters" ]; then
        printf '{"provider":"mimo","meters":%s,"error":null}\n' "$meters"
        exit 0
      fi
      note "browser session answered no usage items"
    elif [ -z "$payload" ]; then
      note "browser bridge unreachable"
    else
      host=$(printf '%s' "$payload" | jq -r '.host // empty' 2>/dev/null || true)
      http=$(printf '%s' "$payload" | jq -r '.http // empty' 2>/dev/null || true)
      stage=$(printf '%s' "$payload" | jq -r '.stage // empty' 2>/dev/null || true)
      if [ "$host" != "$HOST" ]; then
        bridge_eval "location.href='$CONSOLE'" 20 >/dev/null 2>&1 || true
        note "browser has no Xiaomi login"; login_missing=1
      elif [ "$http" = 401 ] && [ "$renewed" = 0 ]; then
        note "browser session expired, renewal unfinished (probe budget)"
      elif [ "$http" = 401 ]; then
        note "browser session refused (HTTP 401)"; login_missing=1
      elif [ "$stage" = fetch ]; then
        note "console API unreachable from the browser session"
      elif [ "$http" = 200 ]; then
        code=$(printf '%s' "$payload" | jq -r '.code // empty' 2>/dev/null || true)
        note "browser session: plan ${stage:-usage} answered code ${code:-?}"
      else
        note "browser session: plan ${stage:-usage} HTTP ${http:-000}"
      fi
    fi
  fi
  # Then the mimo CLI, where one is installed.  Upstream keeps no plan meter --
  # `account` is the login and `stats` counts the local sessions -- so only the
  # adapter's own meter shape is accepted here, and anything else the CLI says
  # is passed over, never trusted as the plan.
  if [ "${SECONDS:-0}" -ge 20 ]; then
    note "mimo CLI untested (probe budget)"
  elif command -v mimo >/dev/null; then
    mexec="mimo"; command -v timeout >/dev/null && mexec="timeout 5 mimo"
    mmeters=""
    for sub in usage status; do
      mout=$($mexec $sub 2>/dev/null || true)
      [ -n "$mout" ] || continue
      mmeters=$(printf '%s' "$mout" | jq -c '
        .meters
        | map(select(((.name // "") | type) == "string"
            and ((.used | type) == "number") and .used >= 0 and .used <= 100
            and ((.resets_at | type) == "number")
            and ((.window_secs | type) == "number")))
        | select(length > 0)' 2>/dev/null || true)
      [ -n "$mmeters" ] && break
    done
    if [ -n "$mmeters" ]; then
      printf '{"provider":"mimo","meters":%s,"error":null}\n' "$mmeters"
      exit 0
    fi
    note "mimo CLI answered no plan meter"
  else
    note "mimo CLI not installed"
  fi
  # Last the provider key against the same two console calls, in case the API
  # ever accepts it; today it answers 401, which only the browser login satisfies.
  # The key travels in a pipe, never a file: nothing of it can be left behind.
  if [ "${SECONDS:-0}" -ge 20 ]; then
    note "provider key untested (probe budget)"
  elif ! command -v curl >/dev/null; then note "provider key untested (curl missing)"
  else
    key=$(config_key mimo)
    if [ -z "$key" ]; then note "provider key unreadable"
    else
      out=$(plan_probe <(printf 'Authorization: Bearer %s\n' "$key"))
      case "$out" in
        meters\ *)
          printf '{"provider":"mimo","meters":%s,"error":null}\n' "${out#meters }"
          exit 0 ;;
        expired) note "provider key refused (HTTP 401)" ;;
        unreachable) note "console API unreachable from the provider key" ;;
        http*)
          code=${out#http }; code=${code%% *}; call=${out##* }
          note "provider key: plan $call HTTP $code" ;;
        *) note "provider key answered no usage items" ;;
      esac
    fi
  fi
  # Every source was tried and none answered a meter.  The reason names each
  # source and what it said; where the missing piece is the login it says
  # exactly where to go, because the meter appears on the next probe after it.
  why="no meter: $notes"
  if [ "$login_missing" = 1 ]; then
    why="$why; log into $CONSOLE in the shared browser (\`ak browser login\` prints its address)"
  fi
  jq -n --arg p mimo --arg n "$why" \
    '{"provider":$p,"meters":[],"error":null,"none":$n}' ;;
install)
  if command -v opencode >/dev/null; then echo "opencode: already installed ($(opencode --version 2>/dev/null | head -1))"; exit 0; fi
  command -v curl >/dev/null || { echo "opencode.sh install: curl is required" >&2; exit 2; }
  curl -fsSL https://opencode.ai/v2/install | bash ;;   # v2: the v1 channel's latest rejects --standalone
login)
  # The provider named, through OpenCode's own login for it; none named is OpenCode's own
  # list of every provider it can log in to.
  command -v opencode >/dev/null || { echo "opencode.sh login: opencode is not installed" >&2; exit 2; }
  p=${PROVIDERS%% *}
  logged_in "$p" && { echo "opencode: already logged in${p:+ to $p}"; exit 0; }
  [ -t 0 ] || { echo "opencode: not logged in${p:+ to $p}; run \`opencode auth login${p:+ $p}\` in a terminal" >&2; exit 1; }
  opencode auth login ${p:+"$p"} ;;
auth)
  # Can a headless turn authenticate right now?  Exit 0 and say so, or exit 1 with one line
  # saying why not; anything else is no answer, and the caller carries on as before.  The
  # key is the whole answer -- a file holding only a blank is not a login, and one that is
  # not JSON at all is a `no` and never a login nobody looked inside.  `seat` asks about
  # the interactive login, which on OpenCode is the same key a headless turn uses -- there
  # is no second credential here to tell apart -- so it is accepted and ignored.  Each
  # provider named must have its own: a DeepSeek key cannot run a `zai/` turn.
  set -f; set -- $PROVIDERS; set +f; [ $# -gt 0 ] || set -- ""
  said=""
  for p in "$@"; do
    have_key "$p"; rc=$?
    if [ $rc -eq 0 ]; then said="${said:+$said; }a key for ${p:-a provider} is configured in $CFG"
    elif store_key "$p"; then said="${said:+$said; }a login for ${p:-a provider} is saved in the auth store"
    elif own_login "$p"; then said="${said:+$said; }OpenCode runs $p with no login"
    elif [ $rc -eq 2 ]; then echo "opencode: $CFG cannot be read without jq" >&2; exit 2
    else echo "opencode: no login for ${p:-any provider}; run \`opencode auth login${p:+ $p}\`" >&2; exit 1
    fi
  done
  echo "opencode: $said"
  exit 0 ;;
hooks)
  # OpenCode 2.0.13 takes its hooks as a plugin, and this harness's plugin is installed per
  # launch: `interactive` names hooks/opencode-seat in OPENCODE_CONFIG_CONTENT, beside the
  # rulebook, so every seat carries that launch's hooks and nothing is written into the
  # user's own ~/.config/opencode.  There is nothing persistent to merge or back up here.
  echo "opencode: hooks are installed per launch by adapters/opencode.sh interactive (the hooks/opencode-seat plugin); nothing to write here" ;;
models)
  # OpenCode's own list of every logged-in provider's models: each `provider/model` under the
  # name OpenCode gives it, its variants its efforts (turn_variants), `none` for one with none.
  # An id the [catalog] table knows takes the table's label and efforts: MiMo's thinking
  # switch.  Not --standalone, whose private server lists no model at all (2.0.24).  A list
  # that fails, outlasts ten seconds or says nothing leaves the table as it is, and so does a
  # host with no `timeout` to bound it (stock macOS): nothing waits on a listing it cannot
  # stop.  Settings, keys among them, never leave jq.
  listed=$(command -v timeout >/dev/null && command -v opencode >/dev/null \
    && timeout 10 opencode api model.list 2>/dev/null | jq -r '.data[]? | select(.enabled != false)
        | ["\(.providerID)/\(.id)", .name // .id,
           ([.variants[]?.id] | if length == 0 then "none" else join(" ") end)] | join("\t")') \
    || listed=""
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  IFS=$'\n'; set -f   # one argument a line
  python3 "$REPO/tools/catalog.py" opencode $listed ;;
providers)
  # Every provider OpenCode can log in to, for `+ add a provider`: the ones with a login
  # first -- a key in its config, one saved in its auth store or none needed, as `auth` reads
  # them -- each
  # `subscription` where OpenCode prices every one of its models at nothing behind a login (a
  # plan's), `free` where it does with none (its own free ones), and `payg` where it prices one
  # or says nothing of one (MiMo's), which never spends money unasked; then the rest, with no
  # mode, in OpenCode's own order.  Its
  # background service is asked one list at a time, since lists asked at once while it starts
  # can fail, each cut to the fields read here: settings, keys among them, never leave jq.  A
  # list of providers that fails is a failed verb: nothing to offer.
  command -v jq >/dev/null || { echo "opencode: listing providers needs jq" >&2; exit 2; }
  bound=""; command -v timeout >/dev/null && bound="timeout 20"
  ask() { $bound opencode api "$1" 2>/dev/null | jq -ce "[.data[] | $2]" 2>/dev/null; }
  if all=$(ask integration.list '{id, name}'); then
    saved=$($bound opencode auth list --standalone --format json 2>/dev/null | jq -c '[.[]?.id]')
    keyed=$(jq -c '[(.provider, .providers) | objects | to_entries[]
        | select([.value | .. | objects | .apiKey? | strings | select(length > 0)] != []) | .key]' \
        "$CFG" 2>/dev/null)
    own=$(own_providers)
    costs=$(ask model.list '{id: .providerID, cost}') || costs='[]'
    jq -rn --argjson all "$all" --argjson in "[${keyed:-[]}, ${saved:-[]}, ${own:-[]}]" --argjson costs "$costs" '
      ($in[0] + $in[1]) as $login
      | (reduce ($in | add // [])[] as $p ([]; if index([$p]) then . else . + [$p] end)) as $in
      | ([$all[] | {(.id): .name}] | add // {}) as $names
      | ($in[] | . as $p | [$costs[] | select(.id == $p) | .cost] as $priced
        | [$p, $names[$p] // $p, if ($priced | length) > 0 and all($priced[]; length > 0
            and all(.[]; type == "object" and .input == 0 and .output == 0))
          then (if $login | index([$p]) then "subscription" else "free" end) else "payg" end]),
        ($all[] | select(.id | IN($in[]) | not) | [.id, .name // .id, ""])
      | join("\t")'
  else
    echo "opencode: OpenCode did not list its providers" >&2; exit 1
  fi ;;
*)
  echo "usage: opencode.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | opencode.sh usage | opencode.sh interactive <model> <effort> [session-id [new]] | opencode.sh install | opencode.sh login | opencode.sh auth [seat] | opencode.sh hooks | opencode.sh models | opencode.sh providers" >&2
  exit 2 ;;
esac
