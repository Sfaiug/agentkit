#!/usr/bin/env bash
# Codex CLI adapter.  run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                     usage        -> ChatGPT subscription meters as JSON
#                     reset-status -> usage-limit resets available, with the weekly meter, as JSON
#                     reset        -> spend one usage-limit reset, and print the meter it left
#                     interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                  for `ak orch`; the id resumes that thread.  `new` -- open the
#                                  next thread under an id of the caller's -- exits 3: the TUI
#                                  has no flag for one, so a Codex seat is given no id at all
#                     install      -> npm i -g @openai/codex, unless codex is already here
#                     login        -> the device-code login, unless already logged in
#                     auth [seat]  -> 0 when a turn can authenticate, 1 and one line why;
#                                  `seat` is the same login here, and is accepted and ignored
#                     hooks        -> says where this harness's hooks come from; writes nothing
#                     models       -> one `id<TAB>label<TAB>efforts` line per model it runs:
#                                  `codex debug models`, else the [catalog] table of
#                                  adapters/codex.toml
# The model `default`, and an empty one, mean this account picks no model: `run` and
# `interactive` then pass no -m at all -- see the note above the `interactive` printf.
set -uo pipefail
command -v codex >/dev/null || PATH="$HOME/.npm-global/bin${PATH:+:$PATH}"   # install.sh's npm prefix puts it here: the fallback when PATH has no answer
AUTH="$HOME/.codex/auth.json"
TMPD="$HOME/.agentkit/tmp"
# The three read/write endpoints the Codex TUI itself uses: /usage carries the meters and the
# reset count, /rate-limit-reset-credits lists the credits, and .../consume spends one.
API=https://chatgpt.com/backend-api/wham
# How many resets are really in hand, read from the credits list rather than from the count
# /usage carries: minutes after one was spent /usage still said 3 where the list said 2, and
# the list is what `reset` picks from.  It is counted the way `reset` picks, so the number and
# the next spend can never disagree; the summary count is the fallback for a list that is gone.
AVAIL='if (.credits | type) == "array"
       then [.credits[] | select(.status == "available" and .is_supported_by_plan != false)] | length
       else (.available_count // 0) end'
# The weekly meter is whichever reported window is not the 5h session one, the one furthest
# along winning -- the same rule `ak usage` uses to fill its "used this week" column.
WEEKLY='[.rate_limit.primary_window, .rate_limit.secondary_window]
        | map(select(. != null and .used_percent != null
                     and (.limit_window_seconds // 604800) != 18000))
        | (max_by(.used_percent) // null)'
cmd=${1:-}; shift 2>/dev/null || true

# jq is the tool most likely to be missing, so build the error object with printf
err() { local m=${1//\\/}; m=${m//\"/\'}
        printf '{"provider":"openai","meters":[],"error":"unknown: %s"}\n' "$m"; exit 0; }
# reset-status and reset answer with an object carrying `error`, which the policy in
# agentkit/usage.py reads and then does nothing, rather than guessing at a half-answer
jerr() { local m=${1//\\/}; m=${m//\"/\'}
         printf '{"error":"%s"}\n' "$m"; exit 1; }
# The ChatGPT token stays out of the process table and out of everything printed here: it is
# written to a 0600 file curl reads with `-H @`.  Sets $HF; 1 = no file, 2 = no token in it.
mkhdr() {
  mkdir -p -- "$TMPD" && chmod 700 "$TMPD" 2>/dev/null   # BSD chmod has no -- option
  HF=$(mktemp "$TMPD/.hdr.XXXXXX") || return 1
  chmod 600 "$HF"
  jq -r '"Authorization: Bearer \(.tokens.access_token)","chatgpt-account-id: \(.tokens.account_id)"' \
      "$AUTH" >"$HF" 2>/dev/null || { rm -f -- "$HF"; return 2; }
}
# One GET, as "<body>\n<http code>"; the caller decides what a non-200 means for its own output
get() { curl -s -m 10 -w $'\n%{http_code}' "$1" -H @"$HF" 2>/dev/null; }

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "codex.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  cd -- "$ws" || { echo "codex.sh: no such workspace: $ws" >&2; exit 2; }
  # `codex exec resume` has no -C flag, hence the cd above; prompt comes from stdin.
  if [ -n "$sid" ]; then set -- exec resume "$sid" -; else set -- exec; fi
  # A `default` (or empty) model means this account cannot be told which model to run, so -m is
  # left off entirely and codex runs its own -- see the note above the `interactive` printf.
  case $model in ""|default) ;; *) set -- "$@" -m "$model" ;; esac
  codex "$@" -c model_reasoning_effort="$effort" \
      --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --json \
      -o "$out/final.md" <"$pf" >"$out/events.jsonl" 2>"$out/stderr.log"
  rc=$?
  [ -f "$out/final.md" ] || : >"$out/final.md"
  # via a variable: `jq | head -1 >file || : >file` truncates the id it just wrote
  # whenever pipefail sees jq die of SIGPIPE
  sid=$(jq -r 'select(.type=="thread.started")|.thread_id' "$out/events.jsonl" 2>/dev/null | head -1)
  printf '%s' "$sid" >"$out/session_id"
  exit $rc ;;
interactive)
  [ $# -ge 2 ] || { echo "codex.sh interactive needs <model> <effort> [session-id [new]]" >&2; exit 2; }
  # `codex exec --session-id` is the headless spelling; the TUI takes no thread id of anyone
  # else's making (codex 0.153: `codex --help` has no such flag), so the launcher is told so
  # rather than handed a command that would drop the id on the floor. The seat wrapper records
  # the actual TUI thread from SessionStart metadata; only that receipt permits a resume.
  [ "${4:-}" = new ] && {
    echo "codex.sh interactive: the TUI cannot be given a thread id" >&2; exit 3; }
  # the effort is quoted TOML on purpose: -c parses the value as TOML and only falls back to
  # the raw string when that fails.  Those quotes have to survive whoever splits this line
  # into words, so they are inside single quotes rather than backslash-escaped by %q -- which
  # only holds for an effort that is a plain word.
  case $2 in *[!A-Za-z0-9_.-]*)
    echo "codex.sh interactive: effort '$2' is not a plain word" >&2; exit 2 ;; esac
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  # a seat being resumed: `codex resume <thread-id>`, which takes the same options
  resume=""; [ -n "${3:-}" ] && resume=$(printf 'resume %q ' "$3")
  # Codex on a ChatGPT subscription runs its own model and no other: every -m comes back as
  # HTTP 400 "The '<model>' model is not supported when using Codex with a ChatGPT account".
  # So the model `default` -- and an empty one -- passes no -m at all, and the effort, which
  # that account does take, still goes through.  A real id (an API key's, which may choose)
  # is passed exactly as before.  The model value decides; the auth is never probed.
  mflag=""; case $1 in ""|default) ;; *) mflag=$(printf -- '-m %q ' "$1") ;; esac
  # The orchestrator rulebook this launch is handed.  Codex 0.153.4 has no instructions-file
  # option of its own (`codex --help`, `codex exec --help`); what it does take per launch is the
  # config key `developer_instructions`, whose text `codex debug prompt-input` shows arriving as
  # the developer message of the first turn.  So rulebook.py writes the file for this seat and
  # the seat wrapper is told where it is: the wrapper is already where every other -c this
  # launch carries is added, which keeps the rulebook's text off the command line, and nothing
  # is written into the user's own ~/.codex.  No rulebook, no command line: a seat opened
  # without the rules it was asked for is worse than one that does not open.
  rb=$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}") || {
    echo "codex.sh interactive: no rulebook for this seat" >&2; exit 2; }
  rules=$(printf -- '--rulebook %q ' "$rb")
  # idle-compact.py wraps the TUI so a seat left open all day compacts itself instead of filling
  # its context, on the `[compact]` table of adapters/codex.toml.  It sits outside the seat
  # wrapper, which still installs this launch's hooks and receipt and then execs codex in place,
  # so the process idle-compact.py forked is the harness itself.  Headless `ak worker` runs are
  # not wrapped: they are not seats.
  printf "python3 %q codex -- python3 %q --harness codex -- python3 %q %s-- codex %s--yolo %s-c 'model_reasoning_effort=\"%s\"'\n" \
      "$REPO/tools/trust.py" "$REPO/tools/idle-compact.py" "$REPO/tools/codex-seat.py" "$rules" \
      "$resume" "$mflag" "$2" ;;
usage)
  command -v jq >/dev/null && command -v curl >/dev/null || err "jq and curl are required"
  [ -r "$AUTH" ] || err "no $AUTH; run 'codex login' once"
  trap 'rm -f -- "${HF:-}"' EXIT HUP INT TERM   # an interrupt must not leave the token on disk
  mkhdr; rc=$?
  case $rc in 1) err "cannot create header file in $TMPD" ;;
              2) err "$AUTH has no tokens.access_token/account_id" ;; esac
  body=$(get "$API/usage")
  rm -f -- "$HF"
  code=${body##*$'\n'}; body=${body%$'\n'*}
  [ "$code" = 200 ] || err "HTTP ${code:-000} from chatgpt.com/backend-api/wham/usage; token may be expired, run 'codex login' to refresh"
  jq -c '{provider:"openai", error:null, meters:[
      {name:"primary_window",   w:.rate_limit.primary_window},
      {name:"secondary_window", w:.rate_limit.secondary_window} ]
    | map(select(.w != null and .w.used_percent != null and .w.reset_at != null)
          | {name, used:.w.used_percent, resets_at:.w.reset_at,
             window_secs:(.w.limit_window_seconds // 604800)}) }' <<<"$body" \
    2>/dev/null || err "unparsable response from chatgpt.com" ;;
reset-status)
  # A subscription earns "usage limit resets" that refill the weekly window.  Two reads: the
  # credits list for what is in hand, /usage for where the week stands.  `applicable` is passed
  # on but nothing acts on it -- it read 0 on a Pro account both before and after a reset that
  # plainly worked, so whatever it counts, gating on it would block every reset there is.
  command -v jq >/dev/null && command -v curl >/dev/null || jerr "jq and curl are required"
  [ -r "$AUTH" ] || jerr "no $AUTH; run 'codex login' once"
  trap 'rm -f -- "${HF:-}"' EXIT HUP INT TERM
  mkhdr; rc=$?
  case $rc in 1) jerr "cannot create header file in $TMPD" ;;
              2) jerr "$AUTH has no tokens.access_token/account_id" ;; esac
  list=$(get "$API/rate-limit-reset-credits")
  code=${list##*$'\n'}; list=${list%$'\n'*}
  [ "$code" = 200 ] || jerr "HTTP ${code:-000} from chatgpt.com/backend-api/wham/rate-limit-reset-credits"
  avail=$(jq -c "$AVAIL" <<<"$list" 2>/dev/null) || jerr "unparsable credits list from chatgpt.com"
  body=$(get "$API/usage")
  rm -f -- "$HF"
  code=${body##*$'\n'}; body=${body%$'\n'*}
  [ "$code" = 200 ] || jerr "HTTP ${code:-000} from chatgpt.com/backend-api/wham/usage; token may be expired, run 'codex login' to refresh"
  jq -c --argjson a "${avail:-0}" \
        "{available: \$a, applicable: (.rate_limit_reset_credits.applicable_available_count // null)}
         + ($WEEKLY | {weekly_used: .used_percent, resets_at: .reset_at})
         + {error: null}" <<<"$body" 2>/dev/null || jerr "unparsable response from chatgpt.com" ;;
reset)
  # Spend one, exactly the way the TUI's /usage screen does it: list the credits, POST the id
  # of one with an idempotency key, then read the meters back.  `code` comes back as one of
  # reset / nothing_to_reset / no_credit / already_redeemed, and only `reset` spent anything.
  command -v jq >/dev/null && command -v curl >/dev/null || jerr "jq and curl are required"
  [ -r "$AUTH" ] || jerr "no $AUTH; run 'codex login' once"
  trap 'rm -f -- "${HF:-}"' EXIT HUP INT TERM
  mkhdr; rc=$?
  case $rc in 1) jerr "cannot create header file in $TMPD" ;;
              2) jerr "$AUTH has no tokens.access_token/account_id" ;; esac
  list=$(get "$API/rate-limit-reset-credits")
  code=${list##*$'\n'}; list=${list%$'\n'*}
  [ "$code" = 200 ] || jerr "HTTP ${code:-000} from chatgpt.com/backend-api/wham/rate-limit-reset-credits"
  # the credit closest to expiring is the one to spend; one this plan cannot use is not one
  cid=$(jq -r '[.credits[]? | select(.status == "available" and .is_supported_by_plan != false)]
               | sort_by(.expires_at // "") | .[0].id // empty' <<<"$list" 2>/dev/null)
  [ -n "$cid" ] || jerr "no usage-limit reset is available to spend"
  rid=$( { uuidgen || cat /proc/sys/kernel/random/uuid \
           || od -An -tx1 -N16 /dev/urandom | tr -d ' \n'; } 2>/dev/null | head -1)
  [ -n "$rid" ] || jerr "cannot make an idempotency key"
  req=$(jq -nc --arg c "$cid" --arg r "consume-rate-limit-reset-$rid" \
        '{credit_id: $c, redeem_request_id: $r}') || jerr "cannot build the consume request"
  out=$(curl -s -m 20 -w $'\n%{http_code}' -X POST "$API/rate-limit-reset-credits/consume" \
        -H @"$HF" -H 'Content-Type: application/json' -d "$req" 2>/dev/null)
  code=${out##*$'\n'}; out=${out%$'\n'*}
  [ "$code" = 200 ] || jerr "HTTP ${code:-000} from chatgpt.com/backend-api/wham/rate-limit-reset-credits/consume"
  outcome=$(jq -r '.code // empty' <<<"$out" 2>/dev/null)
  [ "$outcome" = reset ] || jerr "no reset was applied: ${outcome:-the response carried no outcome}"
  # from here on a credit has been spent, so every answer says so -- whatever the re-read does,
  # the caller has to record the spend or it will spend a second one on the next read
  spent() { printf '{"code":"reset","available":null,"weekly_used":null,"resets_at":null,"error":"%s"}\n' "$1"; exit 0; }
  list=$(get "$API/rate-limit-reset-credits")
  code=${list##*$'\n'}; list=${list%$'\n'*}
  [ "$code" = 200 ] || spent "the reset was applied, but HTTP ${code:-000} came back from the credits list"
  avail=$(jq -c "$AVAIL" <<<"$list" 2>/dev/null) || spent "the reset was applied, but the credits list came back unparsable"
  body=$(get "$API/usage")
  rm -f -- "$HF"
  code=${body##*$'\n'}; body=${body%$'\n'*}
  [ "$code" = 200 ] || spent "the reset was applied, but HTTP ${code:-000} came back from the meters"
  jq -c --argjson a "${avail:-0}" \
        "{code: \"reset\", available: \$a}
         + ($WEEKLY | {weekly_used: .used_percent, resets_at: .reset_at})
         + {error: null}" <<<"$body" 2>/dev/null \
    || spent "the reset was applied, but the meters came back unparsable" ;;
install)
  if command -v codex >/dev/null; then echo "codex: already installed ($(codex --version 2>/dev/null | head -1))"; exit 0; fi
  command -v npm >/dev/null || { echo "codex.sh install: npm is required" >&2; exit 2; }
  npm i -g @openai/codex ;;
login)
  command -v codex >/dev/null || { echo "codex.sh login: codex is not installed" >&2; exit 2; }
  if [ -s "$AUTH" ]; then echo "codex: already logged in"; exit 0; fi
  [ -t 0 ] || { echo "codex: not logged in; run \`codex login --device-auth\` in a terminal" >&2; exit 1; }
  codex login --device-auth ;;
auth)
  # Can a turn authenticate right now?  Exit 0 and say so, or exit 1 with one line saying why
  # not.  Without jq the file cannot be read at all, so the question is not answered: exit 2 is
  # no answer, and the caller carries on as it did before this verb existed rather than passing
  # a token nothing has checked.  `seat` asks about the interactive login, which on Codex is
  # the same one a headless turn uses -- there is no second credential here to tell apart.
  grep -q '[^[:space:]]' "$AUTH" 2>/dev/null || {
    echo "codex: no $AUTH; run \`codex login\`" >&2; exit 1; }
  command -v jq >/dev/null || {
    echo "codex: $AUTH is present but jq is missing, so it could not be read" >&2; exit 2; }
  # The key itself, not the file's size: a file that is not JSON, or that carries no access
  # token, is a `no` and never a login nobody looked inside.
  jq -e '.tokens.access_token // .access_token | strings | select(length > 0)' "$AUTH" \
      >/dev/null 2>&1 || {
    echo "codex: $AUTH carries no access token; run \`codex login\`" >&2; exit 1; }
  # auth.json records an expiry only on some plans; where it records none at all, its presence
  # is the whole answer -- a refresh that fails says so on the seat's screen and in a turn's
  # stderr.  One it records but nobody can read is not the same thing, and is a `no`.
  exp=$(jq -r '(.tokens.expires_at // .expires_at // empty) | tostring' "$AUTH" 2>/dev/null)
  case "$exp" in '')
    echo "codex: $AUTH is present and records no expiry"; exit 0 ;;
  esac
  case "$exp" in null|*[!0-9]*)
    echo "codex: the expiry in $AUTH cannot be read; run \`codex login\`" >&2; exit 1 ;;
  esac
  [ "${#exp}" -gt 11 ] && exp=$(( exp / 1000 ))    # milliseconds where it records them
  [ "$exp" -gt "$(date +%s)" ] || {
    echo "codex: the token in $AUTH expired; run \`codex login\`" >&2; exit 1; }
  echo "codex: the token in $AUTH is still valid" ;;
hooks)
  # Codex takes its hooks on the command line, and the seat wrapper already builds that line:
  # tools/codex-seat.py installs them per launch, beside the SessionStart receipt that says
  # which thread the seat owns, so there is nothing persistent to merge or back up here.
  # A launch is the only place they can go: the receipt path differs for every one of them.
  echo "codex: hooks are installed per launch by tools/codex-seat.py (SessionStart," \
       "UserPromptSubmit, Stop, Interrupt, PermissionRequest); nothing to write here"
  if command -v codex >/dev/null && ! codex --help 2>/dev/null | grep -q -- '--dangerously-bypass-hook-trust'; then
    echo "codex: this build reports no hook support; its seats fall back to screen rules" >&2
  fi ;;
models)
  # `default` alone for a ChatGPT login: that account runs Codex's own model and no other, and
  # any -m comes back HTTP 400 there.  Any other login gets `default`, then the listed models
  # of `codex debug models`, refreshed for it (never --bundled, which skips that), each with
  # the reasoning levels it supports, strongest last.  A listing that fails, outlasts ten
  # seconds or lists nothing leaves the [catalog] table, and so does a host with no `timeout`
  # to bound it (stock macOS): nothing waits on a listing it cannot stop.
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  if jq -e '.auth_mode == "chatgpt"' "$AUTH" >/dev/null 2>&1; then
    python3 "$REPO/tools/catalog.py" codex | awk -F'\t' '$1 == "default"'
  elif listed=$(command -v timeout >/dev/null && command -v codex >/dev/null \
      && timeout 10 codex debug models 2>/dev/null | jq -r '.models[] | select(.visibility == "list")
        | [.slug, .display_name, ((.supported_reasoning_levels // []) | map(.effort) | join(" "))]
        | @tsv') && [ -n "$listed" ]; then
    python3 "$REPO/tools/catalog.py" codex default
    printf '%s\n' "$listed"
  else
    python3 "$REPO/tools/catalog.py" codex
  fi ;;
*)
  echo "usage: codex.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | codex.sh usage | codex.sh reset-status | codex.sh reset | codex.sh interactive <model> <effort> [session-id [new]] | codex.sh install | codex.sh login | codex.sh auth [seat] | codex.sh hooks | codex.sh models" >&2
  exit 2 ;;
esac
