#!/usr/bin/env bash
# Antigravity CLI adapter (Google's `agy`, successor of gemini-cli).
#                     run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                     -> `agy` headless on the prompt down stdin: --model/--effort,
#                        --dangerously-skip-permissions, --print-timeout 0 and --output-format
#                        stream-json, --conversation to continue one; writes final.md,
#                        session_id, stderr.log and events.jsonl
#                     usage        -> the Gemini window of agy's `/usage` panel, read off the
#                        endpoint the panel reads; no login is a failed probe
#                     interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                  for `ak orch`; the id resumes that conversation.  `new` exits
#                                  3: `--conversation` opens one that exists and nothing names
#                                  one that does not, so an Antigravity seat is given no id
#                     install      -> Google's installer, unless agy is already here
#                     login [again] -> `agy` in the terminal (a URL, then the code pasted back),
#                                  ended once signed in, unless already logged in; `again`
#                                  signs a named account in afresh over a login that still stands
#                     logout       -> this login's token file removed, with the plan read for
#                                  it: agy 1.4.7 has no sign-out of its own, and its TUI's
#                                  /logout alone clears the desktop keyring's copy, so the usual
#                                  login fails with that remedy where a keyring can be reached
#                     forget       -> a named account's own files removed, its app data
#                                  directory with its token and plan: a link in it goes, never
#                                  what it leads to; the usual login is refused
#                     login-end    -> {"email","ends","plan"}: whose the login is, and the plan
#                                  `usage` last read for it; `ends` is null, since a Google
#                                  refresh token ends only when revoked
#                     lend <home>  -> a copy of the login, a refresh token renewing leaves valid,
#                                  where a turn with HOME=<home> reads it; prints nothing, as
#                                  it never lapses
#                     auth [seat]  -> 0 when a turn can authenticate, 1 and one line why;
#                                  `seat` is the same login here, and is accepted and ignored
#                     hooks        -> says why this harness has none installed; writes nothing
#                     models       -> one `id<TAB>label<TAB>efforts` line per model it runs:
#                                  `agy models` folded, else the [catalog] table of
#                                  adapters/antigravity.toml
#                     $AGENTKIT_ACCOUNT names one of the provider's `accounts`: every verb then
#                     uses that subscription's own login, and no other
# Verified against agy 1.2.9; see tests/fixtures/README.md for the captures.
set -uo pipefail
command -v agy >/dev/null || PATH="$HOME/.local/bin${PATH:+:$PATH}"   # its installer puts it here: the fallback when PATH has no answer
export AGY_CLI_DISABLE_AUTO_UPDATE=1   # `ak update` owns that; nothing mid-run moves
# The login `agy` keeps: an hour-long access token beside the refresh token it renews that
# one with, itself, whenever it runs.  Asked whether a refresh token is there, and `usage`
# pipes the access token from agy's file to the endpoint agy sends it to, never copying it into
# another file, a variable or a command line; no value in it is printed anywhere from here.
TOKEN="$HOME/.gemini/antigravity-cli/antigravity-oauth-token"
API=https://daily-cloudcode-pa.googleapis.com/v1internal   # the host agy's own log names
# An account other than the usual login keeps agy's application data, its login among it, in
# a directory of its own beside the usual one: `--app_data_dir`, a flag of agy's that `agy
# --help` does not list, puts it in ~/.gemini/antigravity-cli-<name> (agy 1.2.13).  Every agy
# call made for it carries that flag.  Its conversations/ and brain/ are the usual ones,
# linked before agy can make its own, so a conversation begun on one account is resumed on
# the next -- verified by a `--conversation` turn that answered out of the other's first.
# Nothing of the usual login answers for it: agy's API-key sign-ins are dropped, and agy asks
# the desktop keyring ahead of the file, so the session bus is closed and it reads and writes
# the file alone.  How a person signs it in by hand is $SIGNIN.
ACCOUNT=${AGENTKIT_ACCOUNT:-}
DATA="" SIGNIN=agy
if [ -n "$ACCOUNT" ]; then
  DATA="--app_data_dir=antigravity-cli-$ACCOUNT"
  TOKEN="$HOME/.gemini/antigravity-cli-$ACCOUNT/antigravity-oauth-token"
  SIGNIN="DBUS_SESSION_BUS_ADDRESS=disabled: agy $DATA"
  unset GEMINI_API_KEY GOOGLE_API_KEY AGY_ADC_AUTH
  export DBUS_SESSION_BUS_ADDRESS=disabled:
  for store in conversations brain; do
    mkdir -p -- "$HOME/.gemini/antigravity-cli/$store" "${TOKEN%/*}" 2>/dev/null
    [ -e "${TOKEN%/*}/$store" ] || ln -s -- "../antigravity-cli/$store" "${TOKEN%/*}/$store" 2>/dev/null
  done
fi
# The plan `usage` last read off `loadCodeAssist`, kept beside the login with whose login it
# was, so `login-end` answers it without asking the endpoint and never for another login.
PLAN="${TOKEN%/*}/ak-plan.json"
cmd=${1:-}; shift 2>/dev/null || true

# jq is the tool most likely to be missing, so build the error object with printf
err() { local m=${1//\\\\/}; m=${m//\"/\'}
        printf '{"provider":"google","meters":[],"error":"unknown: %s"}\n' "$m"; exit 0; }

# Whose the login is: agy 1.4 writes the email beside the token as `id_token_email`, and no id
# token; before it, the id token's own claim, decoded here and never printed with the token.
email() {
  jq -r '.id_token_email // (.id_token // empty | split(".")[1] // empty | gsub("-"; "+")
         | gsub("_"; "/") | @base64d | fromjson | .email) // empty' "$TOKEN" 2>/dev/null
}

# 0 when a turn can authenticate, 1 when it cannot, 2 when the question cannot be answered for
# want of jq.  GEMINI_API_KEY is agy's other sign-in; otherwise a refresh token is the login.
logged_in() {
  [ -n "${GEMINI_API_KEY:-}" ] && return 0
  [ -r "$TOKEN" ] || return 1
  command -v jq >/dev/null || return 2
  jq -e '.token.refresh_token | strings | test("[^[:space:]]")' "$TOKEN" >/dev/null 2>&1
}

# 0 when agy may keep the usual login in a desktop keyring too: a Mac's always; elsewhere a
# Secret Service answering on the session bus, started as agy would start it.  A bus with none,
# as on a server, keeps no copy; with no busctl to ask, any bus may.  An empty address is none
# to agy, which then takes the runtime socket, but one busctl fails to reach.
keyring() (
  [ "$(uname)" = Darwin ] && return 0
  [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || unset DBUS_SESSION_BUS_ADDRESS
  [ "${DBUS_SESSION_BUS_ADDRESS:-}" = disabled: ] && return 1
  command -v busctl >/dev/null || { [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] ||
    [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bus" ]; return; }
  busctl --user call org.freedesktop.secrets /org/freedesktop/secrets \
    org.freedesktop.DBus.Peer Ping >/dev/null 2>&1
)

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "antigravity.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  out=$(cd -- "$out" && pwd) || exit 2
  [ -d "$ws" ] || { echo "antigravity.sh: no such workspace: $ws" >&2; exit 2; }
  command -v agy >/dev/null || { echo "antigravity.sh: agy is not installed" >&2; exit 2; }
  # The prompt goes down stdin, opened before the cd so a relative path still names it: with no
  # -p, agy 1.2.13 takes a non-empty stdin as its print-mode prompt, and an argument over
  # 128 KiB -- a reviewer's prompt is three times that -- is one Linux refuses.  An empty one
  # would open the TUI instead.  The loop's own stdin never reaches agy: logged out, it asks
  # the terminal for a pasted code, and a turn with none fails at once saying why.
  [ -s "$pf" ] || { echo "antigravity.sh: no prompt in $pf" >&2; exit 2; }
  exec <"$pf" || { echo "antigravity.sh: cannot read $pf" >&2; exit 2; }
  cd -- "$ws" || exit 2
  # stream-json and not json: json prints its one object when the turn is over, and a turn
  # whose events.jsonl stays silent that long is killed as dead by the loop's watchdog.  The
  # stream's last event is that same object under `result`.  --disable-slash-commands hands
  # agy the prompt as written, never a slash command or skill expansion of it.  agy has no
  # switch for the GEMINI.md and AGENTS.md it loads, as adapters/antigravity.toml says.
  set -- ${DATA:+"$DATA"} --output-format stream-json --dangerously-skip-permissions \
    --print-timeout 0 --disable-slash-commands --model "$model"
  # `none` is a model agy runs at no effort (`claude-sonnet-4-6`), which is handed no --effort
  [ "$effort" = none ] || set -- "$@" --effort "$effort"
  [ -n "$sid" ] && set -- "$@" --conversation "$sid"
  agy "$@" >"$out/events.jsonl" 2>"$out/stderr.log"
  rc=$?
  events() { jq -R "fromjson? | objects | $1" "$out/events.jsonl" 2>/dev/null; }
  events 'select(.event == "result") | .result.response // empty' | jq -j . >"$out/final.md" 2>/dev/null || true
  # the id the stream named -- `init` carries it, `result` repeats it -- or the one this turn
  # continued, when agy stopped before saying any
  found=$(events '(.conversation_id // .result.conversation_id) | strings | select(length > 0)' \
    | jq -r . 2>/dev/null | tail -1)
  printf '%s' "${found:-$sid}" >"$out/session_id"
  # A turn agy ended as ERROR, CANCELED, INTERRUPTED or INVALID failed, whatever its exit code.
  # Nothing is appended for its tokens: agentkit/history.py reads each step's own usage off the
  # stream, never the result's, which totals every turn the conversation has had -- so a turn
  # killed before this line still counts the model calls it finished.
  status=$(events 'select(.event == "result") | .result.status // empty' | jq -r . 2>/dev/null | tail -1)
  [ "$rc" -eq 0 ] && [ -n "$status" ] && [ "$status" != SUCCESS ] && rc=1
  exit $rc ;;
interactive)
  [ $# -ge 2 ] || { echo "antigravity.sh interactive needs <model> <effort> [session-id [new]]" >&2; exit 2; }
  [ "${4:-}" = new ] && {
    echo "antigravity.sh interactive: the TUI cannot be given a conversation id" >&2; exit 3; }
  resume=""; [ -n "${3:-}" ] && resume=$(printf -- '--conversation %q ' "$3")
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  # The orchestrator rulebook this launch is handed.  agy 1.2.9 takes no system-prompt or
  # instructions flag; it takes `--agent <name>`, a custom agent whose agent.md is front
  # matter and then the system prompt, found under `.agents/agents/<name>/` of any directory
  # `--add-dir` gives the session.  So the rulebook goes verbatim under that front matter, in
  # a directory of agentkit's own beside rulebook.py's file -- verified by a seat that answered
  # out of an agent given it no other way.  Nothing is written into the user's ~/.gemini, and
  # only a launch naming this directory can see the agent; `subagent: false` keeps its own
  # model from calling it.  No rulebook, no command line: a seat opened without the rules it
  # was asked for is worse than one that does not open.  The directory is this launch's own,
  # made fresh under its rulebook's name: one every seat shared had each launch rewrite the
  # rules the seats before it were opened with.  A directory goes at a later launch once its
  # rulebook is gone, as nothing else removes it; a relaunch never reuses it, so the removal
  # takes nothing a launch made after its check.  `tools` names the shell: agy 1.3.1 offers it
  # to a custom agent either way, but one whose front matter names no tools never ran a command
  # in six tries ("I do not have access to a bash/shell execution tool"), and an orchestrator
  # that cannot run `ak` orchestrates nothing; naming it, every try did.
  rb=${AGENTKIT_RULEBOOK:-$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}")} || {
    echo "antigravity.sh interactive: no rulebook for this seat" >&2; exit 2; }
  state=$(dirname -- "$rb")
  for old in "$state"/antigravity/rulebook-*/; do
    name=$(basename -- "$old")
    [ -e "$state/${name%.*}.md" ] || rm -rf -- "$old"
  done
  agents=$(mkdir -p -- "$state/antigravity" &&
    mktemp -d "$state/antigravity/$(basename -- "$rb" .md).XXXXXX") &&
    def="$agents/.agents/agents/agentkit" && mkdir -p -- "$def" &&
    { printf -- '---\nname: agentkit\ndescription: the agentkit orchestrator seat\nsubagent: false\ntools:\n  - run_command\n---\n'
      cat -- "$rb"; } >"$def/agent.md" || {
    rm -rf -- ${agents:+"$agents"}
    echo "antigravity.sh interactive: no rulebook for this seat" >&2; exit 2; }
  # The model by its full id, the one agy's own alias resolution makes of a model and an
  # effort: with --agent the TUI resolves `--model <m> --effort <e>` only seconds after it
  # draws, and a first prompt sent sooner fails with `plan model not specified`.  A model agy
  # runs at no effort (`claude-sonnet-4-6`, effort `none`) is its own full id.
  case $1 in *-"$2") model=$1 ;; *) model="$1-$2" ;; esac
  [ "$2" = none ] && model=$1
  # A named account's seat carries what this file set above for it: the command runs later,
  # outside this adapter's environment.
  acct=""
  [ -n "$ACCOUNT" ] && acct="-u GEMINI_API_KEY -u GOOGLE_API_KEY -u AGY_ADC_AUTH DBUS_SESSION_BUS_ADDRESS=disabled: "
  # idle-compact.py wraps the TUI, as every seat's, so the seat is looked at again when its
  # screen comes to rest, starts moving or agy exits.
  # The seat's first message, when its launch carries one, goes in as agy's `--prompt-interactive`:
  # sent once the conversation has loaded, never typed into a TUI still loading it.
  # Joined by `=`, so a message starting with `-` is still its value; in single quotes, not
  # %q: shlex.split, which `ak orch` parses this line with, reads no $'...'.
  first=""; [ -z "${AGENTKIT_FIRST_PROMPT:-}" ] ||
    { sq="'"; first=" --prompt-interactive='${AGENTKIT_FIRST_PROMPT//$sq/$sq\\$sq$sq}'"; }
  printf 'python3 %q --harness antigravity -- env %sAGY_CLI_DISABLE_AUTO_UPDATE=1 agy %s%s--add-dir %q --agent agentkit --model %q --dangerously-skip-permissions%s\n' \
      "$REPO/tools/idle-compact.py" "$acct" "${DATA:+$DATA }" "$resume" "$agents" "$model" \
      "$first" ;;
usage)
  # agy's `/usage` panel draws what `retrieveUserQuotaSummary` answers for the project
  # `loadCodeAssist` names: groups of models, each with its windows, the share of one left and
  # when it refills.  Both are asked the way agy asks them; the endpoint serves only a client
  # that calls itself antigravity, so the User-Agent carries agy's own version -- and since agy
  # 1.4 the Gemini groups only to `antigravity/cli/<version>`: `antigravity/<version>` is
  # answered with the Claude-and-GPT group alone (both captured 26 Oct, agy 1.4.7).  Only the
  # Gemini Models group is a meter here: on a Pro plan Gemini 4 Argon has a week of its own, and
  # a spent one must not park Flash; the Claude-and-GPT group is a quota of its own that no
  # gemini turn draws on, and a spent one must not park Gemini.  No login -- an API key
  # included, which has no windows -- is a failed probe, not a missing meter: an
  # unauthenticated google read as neutral would be picked ahead of logged-in ones, only for
  # the turn to fail authentication.
  command -v agy >/dev/null || err "agy is not installed"
  command -v jq >/dev/null && command -v curl >/dev/null || err "jq and curl are required"
  GEMINI_API_KEY= logged_in || err "no login in $TOKEN; run $SIGNIN once to sign in"
  # One deadline over everything below -- agy's version, both requests, a renewal and both
  # again -- so the probe answers inside its ten seconds whatever hangs.  A call still running
  # at it is sent TERM, then KILL a second later, and answers 124.  The shell watches the call
  # itself, a tenth of a second at a time: a Mac ships no timeout(1), and a watchdog of its own
  # would outlive every call that finished first.  SECONDS counts whole seconds, so the
  # deadline falls 7 to 8 seconds from here.
  end=$((SECONDS + 8))
  within() {   # within <command...>: it, on this stdin, until the deadline
    [ "$SECONDS" -lt "$end" ] || return 124
    "$@" <&0 & local pid=$! n=0 rc
    while kill -0 "$pid" 2>/dev/null; do
      if [ "$SECONDS" -ge "$end" ]; then
        if [ "$n" -lt 10 ]; then kill "$pid"; else kill -KILL "$pid"; fi
        n=$((n + 1))
      fi
      sleep 0.1
    done 2>/dev/null
    wait "$pid"; rc=$?
    [ "$n" -eq 0 ] || rc=124
    return "$rc"
  }
  ua="User-Agent: antigravity/cli/$(within agy --version 2>/dev/null | head -1)"
  post() {   # post <method> <body>: sets $code and $body; the header goes down a pipe
    body=$(jq -r '"Authorization: Bearer " + (.token.access_token // "")' "$TOKEN" 2>/dev/null |
        within curl -s -w $'\n%{http_code}' "$API:$1" -H @- -H "$ua" \
        -H 'Content-Type: application/json' -d "$2" 2>/dev/null) || [ $? -ne 124 ] ||
      { code="timed out"; return; }
    code=${body##*$'\n'}; body=${body%$'\n'*}
  }
  # A plan is kept only as this read found it: none where the endpoint did not answer, and
  # none where the login changed while it was asked, as the answer may be either login's.
  quota() {
    local whose; whose=$(email)
    rm -f -- "$PLAN"
    post loadCodeAssist '{}'
    [ "$code" = 200 ] || return
    [ "$(email)" = "$whose" ] &&
      jq -c --arg email "$whose" '{email: $email, plan: (.paidTier.name // .currentTier.name)}' \
        <<<"$body" >"$PLAN.$$" 2>/dev/null && mv -f -- "$PLAN.$$" "$PLAN" || rm -f -- "$PLAN.$$"
    post retrieveUserQuotaSummary "$(jq -c '{project: .cloudaicompanionProject}' <<<"$body" 2>/dev/null)"
  }
  # The access token lives an hour and agy renews it only when it runs, so a refusal is first a
  # token nothing has renewed yet: `agy models` renews it at startup, writing the file itself,
  # and asks no model.  The endpoint is then asked once more with whatever agy left.
  quota
  [ "$code" = 401 ] && { within agy ${DATA:+"$DATA"} models </dev/null >/dev/null 2>&1; quota; }
  # `timed out` is the endpoint out of reach, never a logout: the menu keeps the reading
  # it could not replace, a spent window included, as it does for any probe refused
  [ "$code" = "timed out" ] && err "timed out asking ${API#https://}"
  [ "$code" = 200 ] || err "HTTP ${code:-000} from ${API#https://}; run $SIGNIN once to sign in again"
  jq -c '{provider:"google", error:null, meters:[.groups[]? | select(.displayName // "" | test("^gemini models$"; "i"))
      | .buckets[]? | select(.disabled != true and .remainingFraction != null and .resetTime != null)
      | {name:.bucketId, used:(100 - .remainingFraction * 100),
         resets_at:(.resetTime | sub("\\.[0-9]+"; "") | fromdateiso8601),
         window_secs:({weekly: 604800, "5h": 18000}[.window // ""])}]}' <<<"$body" \
    2>/dev/null || err "unparsable response from ${API#https://}" ;;
install)
  if command -v agy >/dev/null; then echo "agy: already installed ($(agy --version 2>/dev/null | head -1))"; exit 0; fi
  command -v curl >/dev/null || { echo "antigravity.sh install: curl is required" >&2; exit 2; }
  curl -fsSL https://antigravity.google/cli/install.sh | bash ;;
login)
  command -v agy >/dev/null || { echo "antigravity.sh login: agy is not installed" >&2; exit 2; }
  # `again` sets a named account's token aside, so agy opens on its sign-in, and puts it back
  # however this ends without a new one.  The usual login has no `again`: agy would restore it
  # from the desktop keyring, which only its own /logout clears.
  aside=""; [ "${1:-}" = again ] && [ -n "$ACCOUNT" ] && [ -e "$TOKEN" ] && aside="$TOKEN.aside"
  [ -z "$aside" ] && logged_in && { echo "agy: already logged in"; exit 0; }
  [ -t 0 ] || { echo "agy: not logged in; run \`$SIGNIN\` in a terminal, open the URL it prints and paste the code back" >&2; exit 1; }
  [ -z "$aside" ] || { mv -f -- "$TOKEN" "$aside" || exit 1
    trap 'if logged_in; then rm -f -- "$aside"; else mv -f -- "$aside" "$TOKEN"; fi' EXIT; }
  echo "agy: choose Google OAuth, open the URL and paste the code back"
  # agy 1.4.7 has no login of its own, only the TUI, so the sign-in ends here: once the token
  # file holds a refresh token, which it held none of above, agy is sent TERM -- it then
  # leaves the screen and the terminal as it found them.  Behind `&` and still in this
  # script's process group, agy keeps the terminal, and `<&0` hands it this stdin, not the
  # /dev/null a background command gets.  An owner who quits first is signed in or not.
  agy ${DATA:+"$DATA"} <&0 & pid=$!
  while kill -0 "$pid" 2>/dev/null && ! logged_in; do sleep 0.5; done
  kill "$pid" 2>/dev/null; wait "$pid"
  logged_in || exit 1 ;;
logout)
  rm -f -- "$TOKEN" "$PLAN" || exit 1
  [ -z "$ACCOUNT" ] && keyring || exit 0
  echo "agy: run \`agy\` and type /logout to clear the desktop keyring's copy" >&2; exit 1 ;;
forget)
  [ -n "$ACCOUNT" ] || { echo "antigravity.sh forget: the usual login is never forgotten" >&2; exit 2; }
  rm -rf -- "${TOKEN%/*}" ;;
login-end)
  # A Google refresh token ends only when revoked, which shows only once `auth` says so
  command -v jq >/dev/null || { echo "antigravity.sh login-end: jq is required" >&2; exit 2; }
  email=$(email)
  plan=$(jq -r --arg email "$email" 'select(.email == $email) | .plan | strings' "$PLAN" 2>/dev/null)
  jq -nc --arg email "$email" --arg plan "$plan" \
    '{email: $email, ends: null, plan: $plan} | map_values(if . == "" then null else . end)' ;;
lend)
  # Lent as it is: a Google refresh token stays valid after use, until revoked (see `login-end`)
  [ $# -ge 1 ] || { echo "antigravity.sh lend needs <home>" >&2; exit 2; }
  command -v jq >/dev/null || { echo "antigravity.sh lend: jq is required" >&2; exit 2; }
  lent=$(jq -c 'select(.token.refresh_token | strings | test("[^[:space:]]"))
      | {ends: null, login: .}' "$TOKEN" 2>/dev/null) && [ -n "$lent" ] || {
    echo "agy: no refresh token in $TOKEN to lend; run \`$SIGNIN\` and sign in" >&2; exit 1; }
  printf '%s' "$lent" | python3 "$(dirname -- "${BASH_SOURCE[0]}")/../tools/lend.py" \
    "$1" .gemini/antigravity-cli/antigravity-oauth-token ;;
auth)
  # Can a headless turn authenticate right now?  Exit 0 and say so, or exit 1 with one line
  # saying why not; anything else is no answer, and the caller carries on as before.  A
  # refresh token is a login agy can use: it trades that for a fresh access token itself,
  # and a refresh token the sign-in server rejects is cleared from the file as agy signs out.
  # `seat` is the same login here, and is accepted and ignored.
  logged_in; rc=$?
  [ $rc -eq 0 ] && { echo "agy: a login is saved"; exit 0; }
  [ $rc -eq 2 ] && { echo "antigravity.sh auth: jq is required to read $TOKEN" >&2; exit 2; }
  if [ -e "$TOKEN" ]; then echo "agy: $TOKEN holds no refresh token; run \`$SIGNIN\` and sign in" >&2
  else echo "agy: no $TOKEN; run \`$SIGNIN\` and sign in" >&2; fi
  exit 1 ;;
hooks)
  # agy 1.2.9 runs hooks from ~/.gemini/config/hooks.json or a workspace's .agents/hooks.json
  # (PreInvocation, PostInvocation, PreToolUse, PostToolUse, Stop), and a PreToolUse hook that
  # does not answer {"decision":"allow"} denies every tool.  None is installed: the screen
  # rules in adapters/antigravity.toml read a seat's state, and nothing of the user's is
  # written to.
  echo "agy: no hooks installed; its seats are read off the screen" ;;
models)
  # `agy models` prints one id per model and effort beside its label, strongest first
  # (`gemini-3.8-flash-high<TAB>Gemini 3.8 Flash (High)`).  They fold into the model `run`
  # hands to --model, with the words it hands to --effort strongest last; an id with no
  # effort word is a model agy runs at no effort, `none`.  A listing that fails,
  # outlasts ten seconds or says nothing leaves the [catalog] table, and so does a host with
  # no `timeout` to bound it (stock macOS): nothing waits on a listing it cannot stop.
  listed=$(command -v timeout >/dev/null && command -v agy >/dev/null \
    && timeout -k 1 10 agy ${DATA:+"$DATA"} models 2>/dev/null | awk -F'\t' '
    NF >= 2 {
      id = $1; label = $2; effort = ""
      if (match(id, /-(low|medium|high)$/)) {
        effort = substr(id, RSTART + 1); id = substr(id, 1, RSTART - 1)
        sub(/ \([^)]*\)$/, "", label)
      }
      if (!(id in labels)) { order[++n] = id; labels[id] = label }
      if (effort != "") took[id, effort] = 1
    }
    END {
      split("low medium high", ladder, " ")
      for (i = 1; i <= n; i++) {
        id = order[i]; words = ""
        for (j = 1; j <= 3; j++) if ((id, ladder[j]) in took) words = words (words == "" ? "" : " ") ladder[j]
        printf "%s\t%s\t%s\n", id, labels[id], (words == "" ? "none" : words)
      }
    }') || listed=""
  [ -n "$listed" ] && { printf '%s\n' "$listed"; exit 0; }
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  python3 "$REPO/tools/catalog.py" antigravity ;;
*)
  echo "usage: antigravity.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | antigravity.sh usage | antigravity.sh interactive <model> <effort> [session-id [new]] | antigravity.sh install | antigravity.sh login [again] | antigravity.sh logout | antigravity.sh forget | antigravity.sh login-end | antigravity.sh lend <home> | antigravity.sh auth [seat] | antigravity.sh hooks | antigravity.sh models" >&2
  exit 2 ;;
esac
