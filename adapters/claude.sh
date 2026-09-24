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
#                                    worker token, because the two expire apart
#                       hooks        -> wire this harness's lifecycle hooks, idempotently
#                       models       -> one `id<TAB>label<TAB>efforts` line per model it runs,
#                                    from the [catalog] table of adapters/claude.toml
set -uo pipefail
command -v claude >/dev/null || PATH="$HOME/.local/bin${PATH:+:$PATH}"   # its installer puts it here: the fallback when PATH has no answer
TMPD="$HOME/.agentkit/tmp"
CREDS="$HOME/.claude/.credentials.json"
# `claude setup-token` mints a long-lived token; install.sh writes it here, 0600.  A worker given
# one never reads or refreshes the seat's own OAuth pair, so a refresh race between the seat and
# a dozen workers cannot log everybody out at one in the morning.
TOKEN="$HOME/.agentkit/secrets/claude_oauth_token"
cmd=${1:-}; shift 2>/dev/null || true

# jq is the tool most likely to be missing, so build the error object with printf
err() { local m=${1//\\/}; m=${m//\"/\'}
        printf '{"provider":"anthropic","meters":[],"error":"unknown: %s"}\n' "$m"; exit 0; }

case "$cmd" in
run)
  [ $# -ge 5 ] || { echo "claude.sh run needs <model> <effort> <workspace> <prompt-file> <out-dir> [session-id]" >&2; exit 2; }
  model=$1 effort=$2 ws=$3 pf=$4 out=$5 sid=${6:-}
  mkdir -p -- "$out" || exit 2
  cd -- "$ws" || { echo "claude.sh: no such workspace: $ws" >&2; exit 2; }
  # The long-lived worker token, where there is one: a headless turn authenticates with it and
  # never reads or refreshes the seat's ~/.claude/.credentials.json.  No file, and the turn
  # falls back to whatever the seat's own login leaves there, exactly as it always did.
  tok=$(cat "$TOKEN" 2>/dev/null) && [ -n "$tok" ] && export CLAUDE_CODE_OAUTH_TOKEN="$tok"
  if [ -n "$sid" ]; then set -- -p --resume "$sid"; else set -- -p; fi
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
  # idle-compact.py wraps the TUI so a seat left open all day compacts itself instead of
  # filling its context; %q so a checkout path with a space still parses as one word
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
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
  # instead of the "do you trust this folder?" dialog (whose default is "No, exit")
  printf 'python3 %q claude -- python3 %q -- claude %s%s--model %q --effort %q --dangerously-skip-permissions\n' \
      "$REPO/tools/trust.py" "$REPO/tools/idle-compact.py" "$resume" "$rules" "$1" "$2" ;;
usage)
  command -v jq >/dev/null && command -v curl >/dev/null || err "jq and curl are required"
  # The worker token first, for the same reason `run` prefers it: this probe runs beside a
  # dozen turns and must not be one more reader of the pair the seat is refreshing.
  at=${CLAUDE_CODE_OAUTH_TOKEN:-}
  [ -n "$at" ] || at=$(cat "$TOKEN" 2>/dev/null) || at=
  worker_first=0; [ -n "$at" ] && worker_first=1
  if [ "$worker_first" = 0 ]; then
    tok=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) \
      || tok=$(cat "$CREDS" 2>/dev/null) || tok=
    # pipe, not a here-string: a here-string would put the credentials in a temp file
    at=$(printf '%s' "${tok:-{\}}" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
  fi
  [ -n "$at" ] || err "no Claude Code OAuth token ($TOKEN / macOS Keychain 'Claude Code-credentials' / ~/.claude/.credentials.json); run 'claude' once to log in"
  mkdir -p -- "$TMPD" && chmod 700 "$TMPD" 2>/dev/null   # BSD chmod has no -- option
  hf=$(mktemp "$TMPD/.hdr.XXXXXX") || err "cannot create header file in $TMPD"
  trap 'rm -f -- "$hf"' EXIT HUP INT TERM   # an interrupt must not leave the token on disk
  chmod 600 "$hf"; printf 'Authorization: Bearer %s\n' "$at" >"$hf"
  body=$(curl -s -m 10 -w $'\n%{http_code}' https://api.anthropic.com/api/oauth/usage -H @"$hf" \
      -H 'anthropic-beta: oauth-2025-04-20' -H 'anthropic-version: 2023-06-01' 2>/dev/null)
  code=${body##*$'\n'}; body=${body%$'\n'*}
  if [ "$code" != 200 ] && [ "$worker_first" = 1 ]; then
    # The usage endpoint refuses some setup-minted tokens while the seat's own login answers
    # 200 at the same second, so a refused worker token gets one try as the seat before the
    # probe gives up; the error below then names that last answer only.
    tok=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) \
      || tok=$(cat "$CREDS" 2>/dev/null) || tok=
    at=$(printf '%s' "${tok:-{\}}" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null)
    if [ -n "$at" ]; then
      printf 'Authorization: Bearer %s\n' "$at" >"$hf"
      body=$(curl -s -m 10 -w $'\n%{http_code}' https://api.anthropic.com/api/oauth/usage -H @"$hf" \
          -H 'anthropic-beta: oauth-2025-04-20' -H 'anthropic-version: 2023-06-01' 2>/dev/null)
      code=${body##*$'\n'}; body=${body%$'\n'*}
    fi
  fi
  rm -f -- "$hf"
  [ "$code" = 200 ] || err "HTTP ${code:-000} from api.anthropic.com/api/oauth/usage; token may be expired, run 'claude' once to refresh"
  jq -c '{provider:"anthropic", error:null, meters:[ .limits[]
      | select(.resets_at != null and .percent != null)
      | {name:.kind, used:.percent,
         resets_at:(.resets_at|sub("\\.[0-9]+";"")|sub("\\+00:00$";"Z")|fromdateiso8601),
         window_secs:(if .group=="session" then 18000 else 604800 end)} ]}' <<<"$body" \
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
        echo "claude: long-lived worker token in $TOKEN"; exit 0 ;;
      esac
      now=$(date +%s); exp=$((mtime + 365 * 24 * 3600))
      if [ "$now" -ge "$exp" ]; then
        echo "claude: worker token expired; run \`claude setup-token\` and replace $TOKEN" >&2
        exit 1
      fi
      echo "claude: long-lived worker token in $TOKEN (expires in $(((exp - now) / 86400)) days)"
      exit 0 ;;
    esac
  }
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
  echo "claude: the OAuth token in $CREDS is still valid" ;;
hooks)
  # The three events Claude Code 2.1.263 emits that say what a seat is doing -- a turn began, a
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
EVENTS = {"UserPromptSubmit": ("seat-state.sh",),
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
  # claude has no command that lists its models: the [catalog] table is the answer
  REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
  python3 "$REPO/tools/catalog.py" claude ;;
*)
  echo "usage: claude.sh run <model> <effort> <workspace> <prompt-file> <out-dir> [session-id] | claude.sh usage | claude.sh interactive <model> <effort> [session-id [new]] | claude.sh install | claude.sh login | claude.sh auth [seat] | claude.sh hooks | claude.sh models" >&2
  exit 2 ;;
esac
