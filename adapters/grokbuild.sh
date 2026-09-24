#!/usr/bin/env bash
# Grok Build adapter.  run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                     -> `grok -p` headless: --model/--reasoning-effort/--always-approve and
#                        --output-format streaming-messages-json, --resume to continue a
#                        conversation and --session-id with a fresh uuid to start one; writes
#                        final.md, session_id, stderr.log and events.jsonl, and exits the
#                        harness's own code
#                     usage        -> the weekly window on the billing endpoint's credits
#                        form (the response the TUI's Usage limit tab reads) when it carries
#                        a usage percent, else the subscription_usage entries of the CLI's own
#                        settings cache when it carries any, else [usage] none with the reason.
#                        Plain /v1/billing omits that percent on a SuperGrok seat; `grok usage`
#                        reports per-session tokens only.  A refused key, or none beside a
#                        refresh token, is first renewed by grok itself (`grok models`) and
#                        the endpoint asked once more; a renewed key refused is a logout
#                     interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                  for `ak orch`; the id resumes that conversation, `new` opens
#                                  the next one under it.  The rulebook rides `--rules`, grok's
#                                  own system-prompt option ("Extra rules to append to the
#                                  system prompt", `grok --help` 1.0.40), so the first prompt
#                                  stays the owner's; --trust marks the session's directory
#                                  trusted the
#                                  way trust.py does for the harnesses that need a wrapper
#                     install      -> the x.ai installer, unless grok is already here
#                     login        -> `grok login`, unless already logged in
#                     auth [seat]  -> 0 when a turn can authenticate, 1 and one line why: a
#                                  refresh token or an unexpired key is a login grok can use,
#                                  unless `usage` saw the endpoint refuse the key grok renewed;
#                                  `seat` is the same login here, and is accepted and ignored
#                     hooks        -> the seat-state hooks in $GROK_HOME/hooks/agentkit.json: a
#                        per-launch plugin is not possible (`grok --plugin-dir` is rejected by
#                        the TUI; the flag belongs to `grok agent`), so the hooks live where the
#                        TUI always trusts them, in agentkit's own file beside the user's
#                     models       -> one `id<TAB>label<TAB>efforts` line per model it runs:
#                                  `grok models`, with the efforts of the [catalog] table of
#                                  adapters/grokbuild.toml
# Seat state rides the hooks, not the screen: UserPromptSubmit/Stop/Notification carry
# Claude's own hook_event_name values on stdin (verified against 1.0.40 with a logging hook
# that was removed again), and Stop honours the {"decision":"block"} gate.  The turn's tokens
# for agentkit/history.py live in the event stream's `usage` objects -- input_tokens and
# output_tokens beside cache_read_input_tokens and cache_creation_input_tokens, on the
# assistant message's `usage` and on the terminal `result` event's `usage` (which repeats
# per-model in the camelCase `modelUsage` object) -- and event_tokens reads them untaught.
set -uo pipefail
command -v grok >/dev/null || PATH="${GROK_BIN_DIR:-$HOME/.grok/bin}${PATH:+:$PATH}"   # its installer puts it here: the fallback when PATH has no answer
GROK_HOME="${GROK_HOME:-$HOME/.grok}"
AUTH="$GROK_HOME/auth.json"
# The key grok renewed that the billing endpoint still refused, written down by `usage` as
# its SHA-256 digest -- never the key itself -- and read by `auth`: that key is a logout
# until auth.json holds another or the endpoint answers it.  The digest is of the very key
# that was sent, so a login saved while the request was out is never taken for it.
REFUSED="$HOME/.agentkit/state/grok-refused"
keyof() { jq -r '[.[] | select(type == "object") | .key // empty
  | select(type == "string" and test("[^[:space:]]"))] | first // empty' \
  "$AUTH" 2>/dev/null || true; }
digest() { if command -v sha256sum >/dev/null; then sha256sum; else shasum -a 256; fi \
  | cut -d' ' -f1; }
cmd=${1:-}; shift 2>/dev/null || true

# jq is the tool most likely to be missing, so build the error object with printf
err() { local m=${1//\\\\/}; m=${m//\"/\'}
        printf '{"provider":"xai","meters":[],"error":"unknown: %s"}\n' "$m"; exit 0; }

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "grokbuild.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  [ -d "$ws" ] || { echo "grokbuild.sh: no such workspace: $ws" >&2; exit 2; }
  [ -r "$pf" ] || { echo "grokbuild.sh: no such prompt file: $pf" >&2; exit 2; }
  # The id continues that conversation; a turn without one starts its own under a fresh
  # uuid, which is what --session-id demands: a valid UUID that does not already exist.
  if [ -n "$sid" ]; then set -- --resume "$sid"
  else set -- --session-id "$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null \
    || python3 -c 'import uuid; print(uuid.uuid4())')"; fi
  cd -- "$ws" || exit 2
  grok -p "$(cat -- "$pf")" --model "$model" --reasoning-effort "$effort" --always-approve \
    --output-format streaming-messages-json "$@" >"$out/events.jsonl" 2>"$out/stderr.log"
  rc=$?
  # slurp: the terminal `result` event is one JSON object per line, so take the last one's
  # whole `.result`, the way the claude adapter takes its own
  jq -rs '[.[] | select(.type == "result") | .result // ""] | last // ""' \
    "$out/events.jsonl" >"$out/final.md" 2>/dev/null || : >"$out/final.md"
  sid=$(jq -rs '[.[] | select(.session_id != null) | .session_id] | last // ""' \
    "$out/events.jsonl" 2>/dev/null || true)
  printf '%s' "$sid" >"$out/session_id"
  # No quota is recorded here: a quota refusal parks the provider in the core already
  # (run.py reads the [stall] words off the terminal record), and Grok's own reset-time
  # shape -- what a recorded meter would need -- was never observed, so there is nothing
  # honest to write down.  A turn that names one in stderr is still a refusal by its words.
  exit $rc ;;
interactive)
  [ $# -ge 2 ] || { echo "grokbuild.sh interactive needs <model> <effort> [session-id [new]]" >&2; exit 2; }
  # idle-compact.py wraps the TUI so a seat left open all day compacts itself instead of
  # filling its context, on the `[compact]` table of adapters/grokbuild.toml.  Headless
  # `ak worker` runs are not wrapped: they are not seats.
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  # Resume that conversation, or open the next one under the caller's id: both are the
  # TUI's own flags (`grok --help` 1.0.40), so a grok seat owns its id the way a claude
  # seat does and nothing goes looking for the one it opened.
  resume=""
  if [ -n "${3:-}" ]; then
    if [ "${4:-}" = new ]; then resume=$(printf -- '--session-id %q ' "$3")
    else resume=$(printf -- '--resume %q ' "$3"); fi
  fi
  # The orchestrator rulebook this launch is handed: rulebook.py writes it for this seat
  # under ~/.agentkit/state -- byte for byte what the claude adapter names -- and --rules
  # passes the text itself, appended to the session's system prompt inside a <human_rules>
  # block.  `--rules` is grok's own system-prompt option (1.0.40 documents it as
  # "Extra rules to append to the system prompt"), so no GROK.md and no agent profile
  # carries rules of their own.
  # No rulebook, no command line: a seat opened without the rules it was asked for is worse
  # than one that does not open, and `ak orch` prints what was said here.
  rb=$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}") || {
    echo "grokbuild.sh interactive: no rulebook for this seat" >&2; exit 2; }
  # The text is wrapped in single quotes with '\'' for every quote, not %q: %q renders
  # quotes and newlines as $'...', which the shlex.split `ak orch` parses this line with
  # does not understand, while single quotes survive it byte for byte.  The trailing `x`
  # keeps command substitution from eating the rulebook's own trailing newline.
  text=$(cat -- "$rb"; printf x); text=${text%x}
  sq="'"; rules="--rules '${text//$sq/$sq\\$sq$sq}' "
  # --trust marks the session's directory trusted first, so the TUI opens on the prompt
  # instead of the "do you trust the contents of this directory?" dialog (whose default is
  # "No, quit"); --always-approve is the seat's standing permission mode
  printf 'python3 %q --harness grokbuild -- grok %s%s--trust --always-approve --model %q --reasoning-effort %q\n' \
      "$REPO/tools/idle-compact.py" "$resume" "$rules" "$1" "$2" ;;
usage)
  # No login is a failed probe, not a missing meter: without one an unauthenticated xai
  # would read as a neutral 1.0 provider and be picked ahead of logged-in ones, only for
  # the turn to raise LoginExpired and park the run waiting_login without asking any other
  # provider.  So the probe answers the error first -- usage.py prefers it over none --
  # as JSON on exit 0, the way claude.sh and codex.sh do: usage.py only asks the
  # harness's `auth` verb (which is what puts `no login` on the menu row) when the probe
  # ran and said something, while an adapter that crashed or printed nothing usable was
  # never reached at all.  The check stays light, asking only for the token's presence;
  # expiry is still the auth verb's answer at turn time.
  command -v grok >/dev/null || err "grok is not installed"
  { [ -n "${XAI_API_KEY:-}" ] || grep -q '[^[:space:]]' "$AUTH" 2>/dev/null; } || \
    err "no $AUTH; run 'grok login' once"
  # The meter the Usage limit tab draws.  billing.rs requests `/billing?format=credits`
  # on the CLI chat proxy, and that query is what puts creditUsagePercent and currentPeriod
  # on the body: without it the same route answers spend and a monthlyLimit of 0, which is
  # the capture that used to read as no meter.  The percent is the panel's "N%"; the period
  # end is its "Resets:" (the panel prints that instant in local time).  The headline meter
  # takes its name from the period -- weekly for the SuperGrok window -- and each product
  # usagePercent is the same window broken out.  A currentPeriod may arrive as protobuf
  # seconds or as an ISO instant; either is the window, and the billing period is only the
  # fallback when the period itself did not parse.  Spend without a percent is not a meter
  # and falls through, as does any answer but 200: only 401/403 is terminal, an expired
  # login, which must fail the probe like a missing one instead of reading neutral.  An
  # XAI_API_KEY alone never probes: it is not the session this endpoint authenticates.
  if command -v curl >/dev/null && command -v jq >/dev/null; then
    key=$(keyof)
    if grep -q '[^[:space:]]' "$AUTH" 2>/dev/null; then
      tmpd=$(mktemp -d 2>/dev/null || true)
      if [ -n "$tmpd" ]; then
        trap 'rm -rf -- "$tmpd"' EXIT HUP INT TERM   # an interrupt must not leave the token on disk
        bill() {
          printf 'Authorization: Bearer %s\n' "$key" >"$tmpd/hdr"
          body=$(curl -s -m 10 -w $'\n%{http_code}' \
            "https://cli-chat-proxy.grok.com/v1/billing?format=credits" -H @"$tmpd/hdr" 2>/dev/null)
          rm -f -- "$tmpd/hdr"
          code=${body##*$'\n'}; body=${body%$'\n'*}
        }
        code=""
        [ -z "$key" ] || bill
        # The key lives six hours and grok trades its refresh token for a fresh one whenever
        # it runs, so a refusal -- or a refresh token with no key beside it -- is first a key
        # nothing has renewed yet.  `grok models` is the cheapest run that renews: it
        # refreshes a lapsed key at startup, under grok's own flock on auth.json.lock and
        # writing auth.json itself, and asks no model.  This never writes that file, and
        # never kills grok part way through a renewal.  The endpoint is asked once more with
        # whatever key grok left.  Only a key grok did renew that is refused all the same is
        # a logout nothing else writes down: its digest goes to $REFUSED for the `auth`
        # verb.  A renewal that failed -- the same key again, or none -- is not one by
        # itself, since grok may just not have reached its IdP; the `auth` verb reads the
        # file grok left, which no longer holds a login grok gave up on.
        first=$key
        case "$code" in ""|401|403)
          GROK_DISABLE_AUTOUPDATER=1 grok models </dev/null >/dev/null 2>&1
          key=$(keyof); code=""
          [ -z "$key" ] || bill ;;
        esac
        rm -rf -- "$tmpd"
        case "$code" in
          401|403)
            [ "$key" = "$first" ] || { mkdir -p -- "${REFUSED%/*}" &&
              printf '%s' "$key" | digest >"$REFUSED"; }
            err "HTTP $code from cli-chat-proxy.grok.com/v1/billing after grok's own renewal; run 'grok login'" ;;
          "") err "no session key in $AUTH after grok's own renewal; run 'grok login'" ;;
          200)
            rm -f -- "$REFUSED"
            meters=$(jq -c 'def epoch: sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | fromdateiso8601;
              def instant:
                if type == "number" then .
                elif type == "string" then (try epoch catch null)
                elif type == "object" then
                  ((.seconds | tonumber)? // null) as $s
                  | if $s == null then null
                    else $s + ((try ((.nanos // 0) | tonumber) catch 0) / 1000000000)
                    end
                else null end;
              def windowname:
                ascii_upcase
                | if test("WEEKLY") then "weekly"
                  elif test("MONTHLY") then "monthly"
                  else "credits" end;
              .config as $c
              | ($c.currentPeriod // null) as $p
              | (if $p == null then null
                 else
                   ($p.start | instant) as $s
                   | ($p.end | instant) as $e
                   | if ($s | type) == "number" and ($e | type) == "number" and $e > $s and $e > 0
                     then {resets: ($e | floor), window: (($e - $s) | floor),
                           name: (($p.type // "") | if type == "string" then windowname else "credits" end)}
                     else null end
                 end) as $fromp
              | (if $fromp != null then $fromp
                 else
                   (($c.billingPeriodEnd // "") as $be | ($c.billingPeriodStart // "") as $bs
                    | if ($be | type) == "string" and $be != "" and ($bs | type) == "string" and $bs != ""
                      then
                        (try ($be | epoch) catch null) as $re
                        | (try ($bs | epoch) catch null) as $rs
                        | if $re != null and $rs != null and $re > $rs and $re > 0
                          then {resets: $re, window: ($re - $rs), name: "credits"}
                          else null end
                      else null end)
                 end) as $w
              | select($w != null)
              | ([{name: $w.name, used: $c.creditUsagePercent}]
                 + [$c.productUsage[]? | {name: .product, used: .usagePercent}])
              | map(select(((.name // "") | type) == "string" and (.name | test("[^[:space:]]"))
                          and ((.used | type) == "number") and .used >= 0)
                    | {name, used, resets_at: $w.resets, window_secs: $w.window})
              | select(length > 0)' <<<"$body" 2>/dev/null || true)
            if [ -n "$meters" ]; then
              printf '{"provider":"xai","meters":%s,"error":null}\n' "$meters"
              exit 0
            fi ;;
        esac
      fi
    fi
  fi
  # The one subscription channel the CLI itself reads: tier and watch interval live in the
  # settings cache it fetches from its own endpoint, so meter entries would land here if the
  # CLI carried any.  Only a fully meter-shaped entry is answered -- name, used 0-100, an
  # epoch reset and a window in seconds -- and anything less falls through to none.
  cache="$GROK_HOME/settings_cache.json"
  if [ -s "$cache" ] && command -v jq >/dev/null; then
    meters=$(jq -c '.payload | fromjson? | .settings.subscription_usage // empty
      | map(select(((.name // "") | type) == "string"
        and ((.used | type) == "number") and .used >= 0 and .used <= 100
        and ((.resets_at | type) == "number") and ((.window_secs | type) == "number")))
      | select(length > 0)' "$cache" 2>/dev/null || true)
    if [ -n "$meters" ]; then
      printf '{"provider":"xai","meters":%s,"error":null}\n' "$meters"
      exit 0
    fi
  fi
  # No source answered a meter.  The credits billing response had no usage percent, and
  # the settings cache carries no subscription_usage entries.  [usage] none keeps the
  # provider neutral in the picker instead of ranking it last like a failed probe.
  printf '%s\n' '{"provider":"xai","meters":[],"error":null,"none":"no meter: cli-chat-proxy.grok.com/v1/billing?format=credits reports no usage percent, and the settings cache carries no subscription_usage entries"}' ;;
install)
  if command -v grok >/dev/null; then echo "grok: already installed ($(grok --version 2>/dev/null))"; exit 0; fi
  command -v curl >/dev/null || { echo "grokbuild.sh install: curl is required" >&2; exit 2; }
  curl -fsSL https://x.ai/cli/install.sh | bash ;;
login)
  command -v grok >/dev/null || { echo "grokbuild.sh login: grok is not installed" >&2; exit 2; }
  if grep -q '[^[:space:]]' "$AUTH" 2>/dev/null; then echo "grok: already logged in"; exit 0; fi
  [ -t 0 ] || { echo "grok: not logged in; run \`grok login\` in a terminal" >&2; exit 1; }
  grok login ;;
auth)
  # Can a headless turn authenticate right now?  Exit 0 and say so, or exit 1 with one line
  # saying why not; anything else is no answer, and the caller carries on as before.  The
  # answer is a login grok can use: an entry with a session key and a future ISO-8601
  # instant, which sorts as a string, so expiry is a string comparison and no date parsing;
  # or one with a refresh token, which grok trades for a fresh six-hour key itself whenever
  # it runs, so a key that lapsed while grok sat idle is still a login.  A lapsed key with
  # no refresh token is expired.  Grok saying the session expired (the `[auth]` signatures
  # in grokbuild.toml) is grok failing to trade that token, and it drops the login from
  # this file as it says so, so that answer is read here off the file it leaves.  A key
  # grok renewed that the billing endpoint still refused is the one logout grok does not
  # write down, so `usage` does, as its digest in $REFUSED, and it holds while auth.json
  # carries that key.
  # `seat` is the same login here, and is accepted and ignored.
  [ -n "${XAI_API_KEY:-}" ] && { echo "grok: XAI_API_KEY is set"; exit 0; }
  grep -q '[^[:space:]]' "$AUTH" 2>/dev/null || {
    echo "grok: no $AUTH; run \`grok login\`" >&2; exit 1; }
  command -v jq >/dev/null || { echo "grokbuild.sh auth: jq is required to read $AUTH" >&2; exit 2; }
  jq -e . "$AUTH" >/dev/null 2>&1 || {
    echo "grok: $AUTH is not JSON; run \`grok login\`" >&2; exit 1; }
  refused=$(cat -- "$REFUSED" 2>/dev/null || true); key=$(keyof)
  [ -z "$refused" ] || [ -z "$key" ] || [ "$refused" != "$(printf '%s' "$key" | digest)" ] || {
    echo "grok: the billing endpoint refused the login in $AUTH after grok's own renewal; run \`grok login\`" >&2
    exit 1; }
  now=$(date -u +%FT%TZ)
  keyed='((.key // "") | type == "string" and test("[^[:space:]]"))'
  dated="((.expires_at // \"\") | type == \"string\" and test(\"^[0-9]{4}-[0-9]{2}-[0-9]{2}T\") and . > \$now)"
  renewable='((.refresh_token // "") | type == "string" and test("[^[:space:]]"))'
  if jq -e --arg now "$now" "[.[] | select($keyed and $dated)] | length > 0" \
      "$AUTH" >/dev/null 2>&1; then
    echo "grok: the login in $AUTH is saved"
  elif jq -e "[.[] | select($renewable)] | length > 0" "$AUTH" >/dev/null 2>&1; then
    echo "grok: the login in $AUTH is saved; grok renews its lapsed key itself"
  elif jq -e "[.[] | select($keyed)] | length > 0" "$AUTH" >/dev/null 2>&1; then
    if jq -e '[.[] | select((.expires_at // "") != "")] | length > 0' \
        "$AUTH" >/dev/null 2>&1; then
      echo "grok: the login in $AUTH is expired; run \`grok login\`" >&2; exit 1
    else
      echo "grok: $AUTH records no usable expiry; run \`grok login\`" >&2; exit 1
    fi
  else
    echo "grok: $AUTH carries no session token; run \`grok login\`" >&2; exit 1
  fi ;;
hooks)
  # The seat-state hooks, in agentkit's own file under the global hooks directory the TUI
  # always trusts: UserPromptSubmit and Stop feed hooks/seat-state.sh, Stop also feeds the
  # end-of-turn gate in hooks/orchestrator-stop.sh, and Notification feeds idle/permission
  # facts to the same state script.  The file is agentkit's own, so installing it touches
  # no file of the user's; an older agentkit file is backed up once before it is replaced.
  # Grok also loads these commands from ~/.claude/settings.json through its claude-compat
  # layer, and only deduplicates identical (event, command) pairs across the two sources --
  # so both must keep naming this same checkout path, or the hooks fire twice.
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  GROK_HOME="$GROK_HOME" REPO="$REPO" python3 - <<'PY'
import json, os, sys, time
home = os.environ["GROK_HOME"]
repo = os.environ["REPO"]
d = os.path.join(home, "hooks")
os.makedirs(d, exist_ok=True)
seat = f"bash {repo}/hooks/seat-state.sh"
stop = f"bash {repo}/hooks/orchestrator-stop.sh"
wanted = {"hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": seat}]}],
    "Stop": [{"hooks": [{"type": "command", "command": seat},
                        {"type": "command", "command": stop}]}],
    "Notification": [{"hooks": [{"type": "command", "command": seat}]}]}}
target = os.path.join(d, "agentkit.json")
try:
    with open(target) as fh:
        have = json.load(fh)
except (OSError, ValueError):
    have = None
if have == wanted:
    print(f"grok: hooks already installed in {target}")
    sys.exit(0)
if os.path.exists(target):
    bak = target + ".bak-" + time.strftime("%Y%m%d")
    os.replace(target, bak)
    print(f"grok: backed up {target} to {bak}")
with open(target, "w") as fh:
    json.dump(wanted, fh, indent=2)
    fh.write("\n")
print(f"grok: wrote seat-state hooks to {target}; restart open seats to pick them up")
PY
  ;;
models)
  # `grok models` names the models this login runs (`  * grok-4.7 (default)`, `  - grok-4.6`)
  # and no effort: each takes the efforts the [catalog] table gives it, and one the table
  # does not know goes unsaid.  A listing that fails, outlasts ten seconds or names nothing
  # leaves the table as it is, and so does a host with no `timeout` to bound it (stock
  # macOS): nothing waits on a listing it cannot stop.
  ids=$(command -v timeout >/dev/null && command -v grok >/dev/null && timeout 10 grok models \
    2>/dev/null | awk '($1 == "*" || $1 == "-") && $2 ~ /^[A-Za-z0-9._\/-]+$/ { print $2 }') || ids=""
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  python3 "$REPO/tools/catalog.py" grokbuild $ids ;;
*)
  echo "usage: grokbuild.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | grokbuild.sh usage | grokbuild.sh interactive <model> <effort> [session-id [new]] | grokbuild.sh install | grokbuild.sh login | grokbuild.sh auth [seat] | grokbuild.sh hooks | grokbuild.sh models" >&2
  exit 2 ;;
esac
