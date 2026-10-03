#!/usr/bin/env bash
# Claude Code adapter.  run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]
#                       usage        -> Anthropic subscription meters as JSON
#                       interactive <model> <effort> [session-id [new]] -> the TUI command line,
#                                    for `ak orch`; the id resumes that conversation, or with
#                                    `new` opens the seat's next one under an id it was given
#                       install      -> the native installer, unless claude is already here
#                       login        -> the device-code login, unless already logged in
#                       auth [seat]  -> 0 when a turn can authenticate, 1 and one line why;
#                                    `seat` asks about the interactive login alone, never the
#                                    worker token, because the two expire apart; a yes ends
#                                    `; logged in as <email>` where Claude Code wrote it down
#                       hooks        -> wire this harness's lifecycle hooks, idempotently
#                       models       -> one `id<TAB>label<TAB>efforts` line per model it runs:
#                                    Anthropic's models API, else the [catalog] table of
#                                    adapters/claude.toml
#                       $AGENTKIT_ACCOUNT names one of the provider's `accounts`: every verb then
#                       uses that subscription's own login, and no other
set -uo pipefail
command -v claude >/dev/null || PATH="$HOME/.local/bin${PATH:+:$PATH}"   # its installer puts it here: the fallback when PATH has no answer
TMPD="$HOME/.agentkit/tmp"
CREDS="$HOME/.claude/.credentials.json"
# `claude setup-token` mints a long-lived token; install.sh writes it here, 0600.  A worker given
# one never reads or refreshes the seat's own OAuth pair, so a refresh race between the seat and
# a dozen workers cannot log everybody out at one in the morning.
TOKEN="$HOME/.agentkit/secrets/claude_oauth_token"
# An account other than the usual login keeps its worker token beside that one, under its own
# name, and its interactive login in a config directory of its own, where `CLAUDE_CONFIG_DIR=
# ~/.claude-<name> claude` puts it.  Nothing of the usual login -- its files, its Keychain entry,
# a token exported for it -- ever answers for an account: that would spend the wrong
# subscription, or read its meters as this one's.  A seat on an account hands its directory
# to everything it starts, so a call that names no account drops one for the same reason.
case ${CLAUDE_CONFIG_DIR:-} in "$HOME"/.claude-*) unset CLAUDE_CONFIG_DIR ;; esac
ACCOUNT=${AGENTKIT_ACCOUNT:-}
if [ -n "$ACCOUNT" ]; then
  TOKEN="$TOKEN.$ACCOUNT"
  export CLAUDE_CONFIG_DIR="$HOME/.claude-$ACCOUNT"
  CREDS="$CLAUDE_CONFIG_DIR/.credentials.json"
  unset CLAUDE_CODE_OAUTH_TOKEN
  security() { return 1; }   # the Keychain's `Claude Code-credentials` is the usual login's
fi
cmd=${1:-}; shift 2>/dev/null || true

# Who this login is, as Claude Code keeps it beside the login: what `+ add` shows a login
# `− remove` left on disk by.  Silent where it says nobody.
who() {
  local email
  email=$(jq -r '.oauthAccount.emailAddress // empty' "${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json" \
          2>/dev/null) && [ -n "$email" ] && printf '; logged in as %s' "$email"
}

# jq is the tool most likely to be missing, so build the error object with printf
err() { local m=${1//\\/}; m=${m//\"/\'}
        printf '{"provider":"anthropic","meters":[],"error":"unknown: %s"}\n' "$m"; exit 0; }

# The seat login lapses some eight hours after Claude Code last ran on it, and nothing but
# Claude Code renews it.  A login no seat is open on stays lapsed: `auth seat` sent no seat
# onto it and `usage` fell back to the worker token, which the usage page refuses.  So before
# either reads it, a lapsed login that still holds a refresh token gets the smallest turn
# Claude Code runs on it -- its smallest model, one word, no tools, no conversation kept --
# one per login at a time: whoever waited finds it renewed and asks nothing.  A login that
# has not lapsed is never touched, and one the turn could not renew is read as it was.
lapsed() {
  local blob exp
  blob=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) \
    || blob=$(cat "$CREDS" 2>/dev/null) || return 1
  exp=$(printf '%s' "$blob" | jq -r '.claudeAiOauth | select((.refreshToken // "") != "")
      | .expiresAt // empty' 2>/dev/null)
  case "$exp" in ''|*[!0-9]*) return 1 ;; esac
  [ "${#exp}" -gt 11 ] || exp="${exp}000"
  [ "$exp" -le "$(( $(date +%s) * 1000 ))" ]
}
renew() {
  lapsed && mkdir -p -- "$TMPD" 2>/dev/null || return 0
  # flock(2) on fd 9 holds until this subshell closes it, after the turn; python3 because
  # macOS has no flock(1).  Silent throughout: `auth` answers in one line.
  ( python3 -c 'import fcntl, signal; signal.alarm(30); fcntl.flock(0, fcntl.LOCK_EX)' <&9 &&
      lapsed && cd -- "$TMPD" || exit 0
    # the seat login's own directory, never a token that would stand in for it; a worker's
    # role keeps the seat hooks quiet when the caller is a seat
    unset CLAUDE_CODE_OAUTH_TOKEN
    [ -n "$ACCOUNT" ] || unset CLAUDE_CONFIG_DIR
    echo hi | AK_RUN_ROLE=worker claude -p --model haiku --tools "" --no-session-persistence 9>&-
  ) >/dev/null 2>&1 9>>"$TMPD/claude-login${ACCOUNT:+.$ACCOUNT}.lock"
}

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "claude.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  cd -- "$ws" || { echo "claude.sh: no such workspace: $ws" >&2; exit 2; }
  if [ -n "$ACCOUNT" ]; then
    # Claude Code keeps conversations under its config directory's projects/: an account's is
    # the usual one, so a conversation begun on one account is resumed on the next
    mkdir -p -- "$HOME/.claude/projects" "$CLAUDE_CONFIG_DIR" || exit 2
    [ -e "$CLAUDE_CONFIG_DIR/projects" ] ||
      ln -s -- "$HOME/.claude/projects" "$CLAUDE_CONFIG_DIR/projects" || exit 2
  fi
  # The long-lived worker token, where there is one: a headless turn authenticates with it and
  # never reads or refreshes the seat's ~/.claude/.credentials.json.  No file, and the turn
  # falls back to whatever the seat's own login leaves there, exactly as it always did.
  tok=$(cat "$TOKEN" 2>/dev/null) && [ -n "$tok" ] && export CLAUDE_CODE_OAUTH_TOKEN="$tok"
  if [ -n "$sid" ]; then set -- -p --resume "$sid"; else set -- -p; fi
  # The prompt goes down stdin.  No CLAUDE.md or .claude/rules, the user's or the repository's,
  # and no auto-memory MEMORY.md reach the turn (2.1.280's own switches): a worker's rules are
  # the ones ak's prompt carries, whatever harness runs it.
  CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
  claude "$@" --model "$model" --effort "$effort" --dangerously-skip-permissions \
      --output-format stream-json --verbose <"$pf" >"$out/events.jsonl" 2>"$out/stderr.log"
  rc=$?
  jq -sr '[.[] | select(.type == "result")] | last | .result // ""' \
      "$out/events.jsonl" >"$out/final.md" 2>/dev/null || : >"$out/final.md"
  jq -sr '[.[] | select(.session_id != null)] | last | .session_id // ""' \
      "$out/events.jsonl" >"$out/session_id" 2>/dev/null || : >"$out/session_id"
  exit $rc ;;
interactive)
  [ $# -ge 2 ] || { echo "claude.sh interactive needs <model> <effort> [session-id [new]]" >&2; exit 2; }
  # The printed command runs later, outside this adapter's environment. Carry the login
  # into it, sharing the same transcripts as worker turns on these accounts do.
  if [ -n "$ACCOUNT" ]; then
    mkdir -p -- "$HOME/.claude/projects" "$CLAUDE_CONFIG_DIR" || exit 2
    [ -e "$CLAUDE_CONFIG_DIR/projects" ] ||
      ln -s -- "$HOME/.claude/projects" "$CLAUDE_CONFIG_DIR/projects" || exit 2
  fi
  # idle-compact.py wraps the TUI so a seat left open all day compacts itself instead of
  # filling its context; %q so a checkout path with a space still parses as one word
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  python3 "$REPO/agentkit/harness/claude.py" --check || exit 2
  # the conversation this seat owns: --resume <id> opens the one it was given where it stopped,
  # and --session-id <uuid> opens a new one under an id the launcher made before the seat did,
  # which is what lets `ak orch` write down whose conversation it is before it exists
  resume=""
  if [ -n "${3:-}" ]; then
    if [ "${4:-}" = new ]; then resume=$(printf -- '--session-id %q ' "$3")
    else resume=$(printf -- '--resume %q ' "$3"); fi
  fi
  # The orchestrator rulebook this launch is handed: rulebook.py writes it for this seat under
  # ~/.agentkit/state and `--append-system-prompt-file` names it, so agentkit's rules reach the
  # sessions agentkit opens and no other, and nothing of ours is written into the user's own
  # ~/.claude.  The flag is claude 2.1.263's own (named under `--bare` in `claude --help`).
  # No rulebook, no command line: a seat opened without the rules it was asked for is worse
  # than one that does not open, and `ak orch` prints what was said here.
  rb=$(python3 "$REPO/tools/rulebook.py" "${AGENTKIT_SESSION:-}") || {
    echo "claude.sh interactive: no rulebook for this seat" >&2; exit 2; }
  rules=$(printf -- '--append-system-prompt-file %q ' "$rb")
  # trust.py marks the session's directory trusted first, so the TUI opens on the prompt
  # instead of the "do you trust this folder?" dialog (whose default is "No, exit").
  # CLAUDE_CODE_DISABLE_AGENT_VIEW keeps the conversation in this seat: with Claude's
  # background daemon on, `/background` moved a seat's conversation into a daemon process that
  # carried whichever seat had started the daemon, so its hooks and `ak` commands spoke for
  # that other seat and its resume reopened the conversation from before the move.
  printf 'env -u CLAUDE_CODE_OAUTH_TOKEN -u CLAUDE_CONFIG_DIR CLAUDE_CODE_DISABLE_AGENT_VIEW=1 python3 %q claude -- ' "$REPO/tools/trust.py"
  # Seat preparation runs in the seat's actual cwd, after trust.py, and before the TUI:
  # bypass permissions and the answered auto-mode offer, on either login.
  printf 'python3 %q -- ' "$REPO/agentkit/harness/claude.py"
  # Remote Control on, named after the seat: the owner follows his seats from the Claude
  # app, and a seat reopened without it -- a resume, an account move -- would be lost there.
  printf 'python3 %q -- claude %s%s--model %q --effort %q --dangerously-skip-permissions --remote-control %q\n' \
      "$REPO/tools/idle-compact.py" "$resume" "$rules" "$1" "$2" "${AGENTKIT_SESSION:-}" ;;
usage)
  command -v jq >/dev/null && command -v curl >/dev/null || err "jq and curl are required"
  # One request per ask: the seat login's token while its own expiry is still in the future,
  # else the worker token -- never both.  A second request per ask kept both tokens inside a
  # 429 penalty nothing read, and a fallback answer replaced a good reading with an empty one.
  # The Keychain holds the usual login's pair, the credentials file every login's.
  renew
  tok=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) \
    || tok=$(cat "$CREDS" 2>/dev/null) || tok=
  # pipe, not a here-string: a here-string would put the credentials in a temp file
  seat_at=$(printf '%s' "${tok:-{\}}" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
  seat_exp=$(printf '%s' "${tok:-{\}}" | jq -r '.claudeAiOauth.expiresAt // empty' 2>/dev/null)
  at=
  case "$seat_exp" in ''|*[!0-9]*) ;; *)
    # `expiresAt` is epoch milliseconds in every file seen; a ten-digit value is seconds
    [ "${#seat_exp}" -gt 11 ] || seat_exp="${seat_exp}000"
    [ "$seat_exp" -gt "$(( $(date +%s) * 1000 ))" ] && [ -n "$seat_at" ] && at=$seat_at ;;
  esac
  if [ -z "$at" ]; then
    # No live seat login: the worker's own token, which never reads or refreshes the pair
    # the seat is refreshing -- this probe runs beside a dozen turns.
    at=${CLAUDE_CODE_OAUTH_TOKEN:-}
    [ -n "$at" ] || at=$(cat "$TOKEN" 2>/dev/null) || at=
  fi
  [ -n "$at" ] || err "no Claude Code OAuth token ($TOKEN / macOS Keychain 'Claude Code-credentials' / $CREDS); run 'claude' once to log in"
  mkdir -p -- "$TMPD" && chmod 700 "$TMPD" 2>/dev/null   # BSD chmod has no -- option
  hf=$(mktemp "$TMPD/.hdr.XXXXXX") || err "cannot create header file in $TMPD"
  df=$(mktemp "$TMPD/.resp.XXXXXX") || err "cannot create header file in $TMPD"
  trap 'rm -f -- "$hf" "$df"' EXIT HUP INT TERM   # an interrupt must not leave the token on disk
  chmod 600 "$hf"; printf 'Authorization: Bearer %s\n' "$at" >"$hf"
  body=$(curl -s -m 10 -D "$df" -w $'\n%{http_code}' https://api.anthropic.com/api/oauth/usage -H @"$hf" \
      -H 'anthropic-beta: oauth-2025-04-20' -H 'anthropic-version: 2023-06-01' 2>/dev/null)
  code=${body##*$'\n'}; body=${body%$'\n'*}
  # The endpoint's own not-before, when it named one: delay seconds, or the HTTP date to
  # wait for, answered in seconds from now.  Either arrives with any amount of header
  # whitespace around it, and leading zeros are decimal, never octal.  Anything else waits
  # out the harness's own fifteen minutes instead.
  raw=$(sed -n 's/^[Rr][Ee][Tt][Rr][Yy]-[Aa][Ff][Tt][Ee][Rr]:[[:space:]]*//p' "$df" 2>/dev/null | tail -n 1 | tr -d '\r' | sed 's/[[:space:]]*$//')
  retry=
  case "$raw" in
    ''|*[!0-9]*)
      exp=$(date -d "$raw" +%s 2>/dev/null || date -j -f '%a, %d %b %Y %T %Z' "$raw" +%s 2>/dev/null) || exp=
      case "$exp" in ''|*[!0-9]*) ;; *)
        retry=$(( exp - $(date +%s) ))
        [ "$retry" -gt 0 ] 2>/dev/null || retry= ;;
      esac ;;
    *) retry=$((10#$raw)) ;;
  esac
  rm -f -- "$hf" "$df"
  if [ "$code" != 200 ]; then
    msg="HTTP ${code:-000} from api.anthropic.com/api/oauth/usage"
    # Only a refused login is the token's fault; a 429 or a 5xx says nothing about it.
    case "$code" in 401|403) msg="$msg; token may be expired, run 'claude' once to refresh" ;; esac
    case "$retry" in ''|0|*[!0-9]*) err "$msg" ;; esac
    m=${msg//\\/}; m=${m//\"/\'}
    printf '{"provider":"anthropic","meters":[],"error":"unknown: %s","retry_after":%d}\n' "$m" "$retry"
    exit 0
  fi
  # Extra usage answers turns once the windows are spent, so what its monthly limit has left
  # is credits; off or uncapped, there is no balance to count.  Its amounts are minor units of
  # its `currency`, USD where it names none, as Claude Code reads them: cents, or whole yen,
  # won and dong.  The one-time credit (`cinder_cove`) adds nothing: the reply says only what
  # share of it is used, never what it is worth.
  jq -c '{provider:"anthropic", error:null, meters:[ .limits[]
      | select(.resets_at != null and .percent != null)
      | {name:.kind, used:.percent,
         resets_at:(.resets_at|sub("\\.[0-9]+";"")|sub("\\+00:00$";"Z")|fromdateiso8601),
         window_secs:(if .group=="session" then 18000 else 604800 end)} ]}
    + ([.extra_usage | objects | select(.is_enabled == true)
        | (.currency // "USD" | ascii_upcase) as $c
        | {credits:((.monthly_limit - .used_credits)?
                    / (if $c | IN("JPY", "KRW", "VND") then 1 else 100 end)), currency:$c}]
       | first // {})' <<<"$body" \
    2>/dev/null || err "unparsable response from api.anthropic.com" ;;
install)
  if command -v claude >/dev/null; then echo "claude: already installed ($(claude --version 2>/dev/null | head -1))"; exit 0; fi
  command -v curl >/dev/null || { echo "claude.sh install: curl is required" >&2; exit 2; }
  curl -fsSL https://claude.ai/install.sh | bash ;;
login)
  command -v claude >/dev/null || { echo "claude.sh login: claude is not installed" >&2; exit 2; }
  # the token lives in the macOS Keychain or in ~/.claude/.credentials.json; either means logged in
  if security find-generic-password -s "Claude Code-credentials" -w >/dev/null 2>&1 ||
     { [ -r "$CREDS" ] && grep -q '"accessToken"' "$CREDS" 2>/dev/null; }; then
    echo "claude: already logged in"; exit 0
  fi
  [ -t 0 ] || { echo "claude: not logged in; run \`claude auth login\` in a terminal" >&2; exit 1; }
  claude auth login ;;
auth)
  # Can a turn authenticate right now?  Exit 0 and name the token, or exit 1 with one line
  # saying why not.  The loop asks before every turn and again after a turn that produced
  # nothing, and parks the run on a `no` rather than waiting out twenty minutes of silence and
  # spending three retries on a wall.  Anything but 0 or 1 is no answer at all, and the caller
  # carries on as it did before this verb existed.
  #
  # `auth seat` asks the other question: whether the seat's own interactive login is good.
  # There are two logins here once a worker token exists, and they expire apart -- a box whose
  # workers are fine can still have a seat showing `Please run /login`, and answering that
  # seat with the worker's token would hide exactly the thing this is here to catch.
  [ "${1:-}" = seat ] || {
    [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && { echo "claude: CLAUDE_CODE_OAUTH_TOKEN is set"; exit 0; }
    tok=$(cat "$TOKEN" 2>/dev/null) && case "$tok" in *[![:space:]]*)
      # A `claude setup-token` token lives exactly one year from the day its file was
      # written -- the installer's write or a hand's -- so the file's own date is the token's.
      mtime=$(stat -c %Y "$TOKEN" 2>/dev/null || stat -f %m "$TOKEN" 2>/dev/null || echo "")
      case "$mtime" in ''|*[!0-9]*)
        echo "claude: long-lived worker token in $TOKEN$(who)"; exit 0 ;;
      esac
      now=$(date +%s); exp=$((mtime + 365 * 24 * 3600))
      if [ "$now" -ge "$exp" ]; then
        echo "claude: worker token expired; run \`claude setup-token\` and replace $TOKEN" >&2
        exit 1
      fi
      echo "claude: long-lived worker token in $TOKEN (expires in $(((exp - now) / 86400)) days)$(who)"
      exit 0 ;;
    esac
  }
  renew
  tok=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) \
    || tok=$(cat "$CREDS" 2>/dev/null) || tok=
  case "$tok" in *accessToken*) ;; *)
    echo "claude: no OAuth credentials in $CREDS and no CLAUDE_CODE_OAUTH_TOKEN; run /login" >&2
    exit 1 ;;
  esac
  # Present is not enough: these credentials are a pair the seat refreshes, and the whole
  # point of asking is whether this one is still good.  Without jq the question cannot be
  # answered at all, so it is not answered -- exit 2 is no answer, and the loop carries on
  # as it did before this verb existed rather than parking every run on a missing tool.
  command -v jq >/dev/null || {
    echo "claude: credentials present ($CREDS) but jq is missing, so no expiry could be read" >&2
    exit 2; }
  # The key itself, not the word: a file that is not JSON at all, or that spells the name
  # with nothing behind it, is a `no` and never a token nobody looked inside.
  key=$(printf '%s' "$tok" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
  [ -n "$key" ] || {
    echo "claude: the credentials in $CREDS carry no access token; run /login" >&2; exit 1; }
  exp=$(printf '%s' "$tok" | jq -r '.claudeAiOauth.expiresAt // empty' 2>/dev/null)
  case "$exp" in ''|*[!0-9]*)
    echo "claude: the credentials in $CREDS record no usable expiry; run /login" >&2; exit 1 ;;
  esac
  # `expiresAt` is epoch milliseconds in every file seen; a ten-digit value is seconds
  [ "${#exp}" -gt 11 ] || exp="${exp}000"
  [ "$exp" -gt "$(( $(date +%s) * 1000 ))" ] || {
    echo "claude: the OAuth token in $CREDS expired; run /login" >&2; exit 1; }
  echo "claude: the OAuth token in $CREDS is still valid$(who)" ;;
hooks)
  # SessionStart follows /clear's new conversation. The other events say a turn began, a
  # turn ended, a prompt is waiting -- all to the one hook script, which writes the fact down and
  # decides nothing.  Stop also carries the idle auto-compact stamp, so a seat left open all day
  # compacts itself instead of filling its context, and the one hook that does decide something:
  # a turn that ended with neither a question, nor a done, nor a run to wait on is sent back to
  # work.  Merged into settings.json, never rewritten.
  command -v python3 >/dev/null || { echo "claude.sh hooks: python3 is required" >&2; exit 2; }
  mkdir -p -- "$HOME/.claude" || exit 2
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  python3 - "$HOME/.claude/settings.json" "$(date +%Y%m%d)" "$REPO" <<'HOOKPY'
import json, os, pathlib, shutil, sys

path, stamp, repo = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
# Which of our scripts runs on which event: the one that writes down what the seat is doing,
# and on the end of a turn the one that decides whether that turn was allowed to end.
EVENTS = {"SessionStart": ("seat-state.sh",),
          "UserPromptSubmit": ("seat-state.sh",),
          "Stop": ("seat-state.sh", "orchestrator-stop.sh"),
          "Notification": ("seat-state.sh",)}
# The names each was generalised from: a settings.json written by an older checkout keeps its
# entry, repointed, so nothing is left calling a file that is no longer there.
NAMES = {"seat-state.sh": ("seat-state.sh", "idle-compact-stop.sh"),
         "orchestrator-stop.sh": ("orchestrator-stop.sh",)}


def command(script):
    return f"bash {repo}/hooks/{script}"


try:
    raw = path.read_text()
except FileNotFoundError:
    raw, data = None, {}
except OSError as exc:
    sys.exit(f"cannot read {path}: {exc}")
else:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        # a malformed file is not a missing one: replacing it would drop the user's settings
        sys.exit(f"{path} is not valid JSON ({exc}); left alone")
    if not isinstance(data, dict):
        sys.exit(f"{path} is not a JSON object; left alone")
hooks = data.get("hooks")
hooks = dict(hooks) if isinstance(hooks, dict) else {}


def ours(entry, script):
    return isinstance(entry, dict) and any(n in str(entry.get("command", ""))
                                           for n in NAMES[script])


def entries(event, script):
    groups = hooks.get(event)
    return [entry for group in (groups if isinstance(groups, list) else [])
            if isinstance(group, dict) and isinstance(group.get("hooks"), list)
            for entry in group["hooks"] if ours(entry, script)]


def wired(event, script):
    found = entries(event, script)
    return (len(found) == 1 and found[0].get("type") == "command"
            and found[0].get("command") == command(script))


# read before anything is mutated: the early exit below must see the file as it is on disk
if all(wired(event, script) for event, scripts in EVENTS.items() for script in scripts):
    print(f"hooks: {path} already runs hooks/seat-state.sh on {', '.join(EVENTS)}, "
          "with hooks/orchestrator-stop.sh beside it on Stop")
    raise SystemExit(0)
if raw is not None:                     # back up only when something actually changes
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    print(f"backed up {path} -> {backup}")
for event, scripts in EVENTS.items():
    groups = hooks.get(event)
    groups = list(groups) if isinstance(groups, list) else []
    for script in scripts:
        found = entries(event, script)
        if found:                       # a checkout that moved keeps its entries, repointed
            for entry in found:
                entry["type"], entry["command"] = "command", command(script)
        else:
            groups.append({"hooks": [{"type": "command", "command": command(script)}]})
    hooks[event] = groups
data["hooks"] = hooks
tmp = path.with_name(f"{path.name}.ak-tmp")
tmp.write_text(json.dumps(data, indent=2) + "\n")
os.replace(tmp, path)
print(f"hooks: {path} hooks.{'/'.join(EVENTS)} -> {command('seat-state.sh')}, "
      f"and {command('orchestrator-stop.sh')} on Stop")
HOOKPY
  ;;
models)
  # claude has no command that lists its models, but Anthropic's models API names every model
  # this login runs, newest first, a page at a time: its id, its `display_name` without the
  # leading `Claude `, and the effort levels its `capabilities.effort` supports, weakest first,
  # or `none` where it takes no effort.  A dated id the [catalog] table knows undated
  # (`claude-haiku-4-5-20251001`) answers as the table's, so a model added from the table stays
  # marked as added.  The worker token asks, else the seat's own login, never renewed for this;
  # $ANTHROPIC_BASE_URL is claude's own, and where the tests' fake API lives.  A listing that
  # fails, outlasts ten seconds or names nothing leaves the table as it is.
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  table=$(python3 "$REPO/tools/catalog.py" claude)
  at=${CLAUDE_CODE_OAUTH_TOKEN:-}
  [ -n "$at" ] || at=$(cat "$TOKEN" 2>/dev/null) || at=
  [ -n "$at" ] || at=$( { security find-generic-password -s "Claude Code-credentials" -w ||
      cat "$CREDS"; } 2>/dev/null | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
  pages= after= deadline=$(( $(date +%s) + 10 ))
  while [ -n "$at" ]; do
    left=$(( deadline - $(date +%s) ))
    # the header on stdin, from a builtin: the token is in no argument list and no file
    page=$([ "$left" -gt 0 ] && printf 'Authorization: Bearer %s\n' "$at" | curl -sf -m "$left" \
        -H @- -H 'anthropic-beta: oauth-2025-04-20' -H 'anthropic-version: 2023-06-01' \
        "${ANTHROPIC_BASE_URL:-https://api.anthropic.com}/v1/models?limit=1000${after:+&after_id=$after}") &&
      after=$(jq -r 'select(.has_more == true) | .last_id // ""' <<<"$page") || { pages=; break; }
    pages+=$page$'\n'
    [ -n "$after" ] || break
  done
  listed=$(printf '%s' "$pages" | jq -rs --arg table "$table" '
      [$table | split("\n")[] | split("\t")[0]] as $known
      | .[].data[] | (.id | sub("-[0-9]{8}$"; "")) as $bare
      | [(if any($known[]; . == $bare) then $bare else .id end),
         ((.display_name // .id) | sub("^Claude "; "")),
         (.capabilities.effort // {} | if .supported == true
            then [to_entries[] | select(.value | type == "object" and .supported == true) | .key]
              | join(" ")
            else "none" end)]
      | @tsv' 2>/dev/null) || listed=
  printf '%s\n' "${listed:-$table}" ;;
*)
  echo "usage: claude.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | claude.sh usage | claude.sh interactive <model> <effort> [session-id [new]] | claude.sh install | claude.sh login | claude.sh auth [seat] | claude.sh hooks | claude.sh models" >&2
  exit 2 ;;
esac
