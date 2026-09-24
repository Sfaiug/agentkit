#!/usr/bin/env bash
# Antigravity CLI adapter (Google's `agy`, successor of gemini-cli).
#                     run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                     -> `agy -p` headless: --model/--effort, --dangerously-skip-permissions,
#                        --print-timeout 0 and --output-format stream-json, --conversation to
#                        continue one; writes final.md, session_id, stderr.log and events.jsonl
#                     usage        -> the Gemini window of agy's `/usage` panel, read off the
#                        endpoint the panel reads; no login is a failed probe
#                     interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                  for `ak orch`; the id resumes that conversation.  `new` exits
#                                  3: `--conversation` opens one that exists and nothing names
#                                  one that does not, so an Antigravity seat is given no id
#                     install      -> Google's installer, unless agy is already here
#                     login        -> `agy` in the terminal (a URL, then the code pasted back),
#                                  unless already logged in
#                     auth [seat]  -> 0 when a turn can authenticate, 1 and one line why;
#                                  `seat` is the same login here, and is accepted and ignored
#                     hooks        -> says why this harness has none installed; writes nothing
#                     models       -> one `id<TAB>label<TAB>efforts` line per model it runs:
#                                  `agy models` folded, else the [catalog] table of
#                                  adapters/antigravity.toml
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
cmd=${1:-}; shift 2>/dev/null || true

# jq is the tool most likely to be missing, so build the error object with printf
err() { local m=${1//\\\\/}; m=${m//\"/\'}
        printf '{"provider":"google","meters":[],"error":"unknown: %s"}\n' "$m"; exit 0; }

# 0 when a turn can authenticate, 1 when it cannot, 2 when the question cannot be answered for
# want of jq.  GEMINI_API_KEY is agy's other sign-in; otherwise a refresh token is the login.
logged_in() {
  [ -n "${GEMINI_API_KEY:-}" ] && return 0
  [ -r "$TOKEN" ] || return 1
  command -v jq >/dev/null || return 2
  jq -e '.token.refresh_token | strings | test("[^[:space:]]")' "$TOKEN" >/dev/null 2>&1
}

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "antigravity.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  out=$(cd -- "$out" && pwd) || exit 2
  [ -d "$ws" ] || { echo "antigravity.sh: no such workspace: $ws" >&2; exit 2; }
  command -v agy >/dev/null || { echo "antigravity.sh: agy is not installed" >&2; exit 2; }
  msg=$(cat -- "$pf") || { echo "antigravity.sh: cannot read $pf" >&2; exit 2; }
  cd -- "$ws" || exit 2
  # stream-json and not json: json prints its one object when the turn is over, and a turn
  # whose events.jsonl stays silent that long is killed as dead by the loop's watchdog.  The
  # stream's last event is that same object under `result`.  --disable-slash-commands hands
  # agy the prompt as written, never a slash command or skill expansion of it.  stdin is
  # closed: logged out, agy waits a minute for a pasted code, and its stderr says why at once.
  set -- -p "$msg" --output-format stream-json --dangerously-skip-permissions --print-timeout 0 \
    --disable-slash-commands --model "$model"
  # `none` is a model agy runs at no effort (`claude-sonnet-4-6`), which is handed no --effort
  [ "$effort" = none ] || set -- "$@" --effort "$effort"
  [ -n "$sid" ] && set -- "$@" --conversation "$sid"
  agy "$@" </dev/null >"$out/events.jsonl" 2>"$out/stderr.log"
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
  # was asked for is worse than one that does not open.
  rb=$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}") || {
    echo "antigravity.sh interactive: no rulebook for this seat" >&2; exit 2; }
  agents="$(dirname -- "$rb")/antigravity"
  def="$agents/.agents/agents/agentkit"
  { mkdir -p -- "$def" &&
    { printf -- '---\nname: agentkit\ndescription: the agentkit orchestrator seat\nsubagent: false\n---\n'
      cat -- "$rb"; } >"$def/agent.md.$$" && mv -f -- "$def/agent.md.$$" "$def/agent.md"; } || {
    rm -f -- "$def/agent.md.$$"
    echo "antigravity.sh interactive: no rulebook for this seat" >&2; exit 2; }
  # The model by its full id, the one agy's own alias resolution makes of a model and an
  # effort: with --agent the TUI resolves `--model <m> --effort <e>` only seconds after it
  # draws, and a first prompt sent sooner fails with `plan model not specified`.  A model agy
  # runs at no effort (`claude-sonnet-4-6`, effort `none`) is its own full id.
  case $1 in *-"$2") model=$1 ;; *) model="$1-$2" ;; esac
  [ "$2" = none ] && model=$1
  printf 'env AGY_CLI_DISABLE_AUTO_UPDATE=1 agy %s--add-dir %q --agent agentkit --model %q --dangerously-skip-permissions\n' \
      "$resume" "$agents" "$model" ;;
usage)
  # agy's `/usage` panel draws what `retrieveUserQuotaSummary` answers for the project
  # `loadCodeAssist` names: groups of models, each with its windows, the share of one left and
  # when it refills.  Both are asked the way agy asks them; the endpoint serves only a client
  # that calls itself antigravity, so the User-Agent carries agy's own version.  Only the Gemini
  # group is a meter here: the Claude-and-GPT group is a quota of its own that no gemini turn
  # draws on, and a spent one must not park Gemini.  No login -- an API key included, which has
  # no windows -- is a failed probe, not a missing meter: an unauthenticated google read as
  # neutral would be picked ahead of logged-in ones, only for the turn to fail authentication.
  command -v agy >/dev/null || err "agy is not installed"
  command -v jq >/dev/null && command -v curl >/dev/null || err "jq and curl are required"
  GEMINI_API_KEY= logged_in || err "no login in $TOKEN; run agy once to sign in"
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
  ua="User-Agent: antigravity/$(within agy --version 2>/dev/null | head -1)"
  post() {   # post <method> <body>: sets $code and $body; the header goes down a pipe
    body=$(jq -r '"Authorization: Bearer " + (.token.access_token // "")' "$TOKEN" 2>/dev/null |
        within curl -s -w $'\n%{http_code}' "$API:$1" -H @- -H "$ua" \
        -H 'Content-Type: application/json' -d "$2" 2>/dev/null) || [ $? -ne 124 ] ||
      { code="timed out"; return; }
    code=${body##*$'\n'}; body=${body%$'\n'*}
  }
  quota() {
    post loadCodeAssist '{}'
    [ "$code" = 200 ] || return
    post retrieveUserQuotaSummary "$(jq -c '{project: .cloudaicompanionProject}' <<<"$body" 2>/dev/null)"
  }
  # The access token lives an hour and agy renews it only when it runs, so a refusal is first a
  # token nothing has renewed yet: `agy models` renews it at startup, writing the file itself,
  # and asks no model.  The endpoint is then asked once more with whatever agy left.
  quota
  [ "$code" = 401 ] && { within agy models </dev/null >/dev/null 2>&1; quota; }
  # `timed out` is the endpoint out of reach, never a logout: the menu keeps the reading
  # it could not replace, a spent window included, as it does for any probe refused
  [ "$code" = "timed out" ] && err "timed out asking ${API#https://}"
  [ "$code" = 200 ] || err "HTTP ${code:-000} from ${API#https://}; run agy once to sign in again"
  jq -c '{provider:"google", error:null, meters:[.groups[]? | select(.displayName // "" | test("gemini"; "i"))
      | .buckets[]? | select(.disabled != true and .remainingFraction != null and .resetTime != null)
      | {name:.bucketId, used:(100 - .remainingFraction * 100),
         resets_at:(.resetTime | sub("\\.[0-9]+"; "") | fromdateiso8601),
         window_secs:(if .window == "weekly" then 604800 else null end)}]}' <<<"$body" \
    2>/dev/null || err "unparsable response from ${API#https://}" ;;
install)
  if command -v agy >/dev/null; then echo "agy: already installed ($(agy --version 2>/dev/null | head -1))"; exit 0; fi
  command -v curl >/dev/null || { echo "antigravity.sh install: curl is required" >&2; exit 2; }
  curl -fsSL https://antigravity.google/cli/install.sh | bash ;;
login)
  command -v agy >/dev/null || { echo "antigravity.sh login: agy is not installed" >&2; exit 2; }
  logged_in && { echo "agy: already logged in"; exit 0; }
  [ -t 0 ] || { echo "agy: not logged in; run \`agy\` in a terminal, open the URL it prints and paste the code back" >&2; exit 1; }
  echo "agy: choose Google OAuth, open the URL, paste the code back, then leave with /exit"
  agy ;;
auth)
  # Can a headless turn authenticate right now?  Exit 0 and say so, or exit 1 with one line
  # saying why not; anything else is no answer, and the caller carries on as before.  A
  # refresh token is a login agy can use: it trades that for a fresh access token itself,
  # and a refresh token the sign-in server rejects is cleared from the file as agy signs out.
  # `seat` is the same login here, and is accepted and ignored.
  logged_in; rc=$?
  [ $rc -eq 0 ] && { echo "agy: a login is saved"; exit 0; }
  [ $rc -eq 2 ] && { echo "antigravity.sh auth: jq is required to read $TOKEN" >&2; exit 2; }
  if [ -e "$TOKEN" ]; then echo "agy: $TOKEN holds no refresh token; run \`agy\` and sign in" >&2
  else echo "agy: no $TOKEN; run \`agy\` and sign in" >&2; fi
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
    && timeout 10 agy models 2>/dev/null | awk -F'\t' '
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
  echo "usage: antigravity.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | antigravity.sh usage | antigravity.sh interactive <model> <effort> [session-id [new]] | antigravity.sh install | antigravity.sh login | antigravity.sh auth [seat] | antigravity.sh hooks | antigravity.sh models" >&2
  exit 2 ;;
esac
