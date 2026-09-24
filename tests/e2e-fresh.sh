#!/usr/bin/env bash
# agentkit fresh-HOME gate: install this checkout's committed revision into a throwaway HOME;
# then `ak` (or tapping the phone host) is the whole interface. Exits 0 only if every selected step
# passes.  Linux only, no privilege needed, safe to run over and over: the HOME it makes lives
# under a workdir that is removed again on the way out.
#
# What it cannot test, and what a newcomer does instead, is printed in the summary: the three
# device-code logins are interactive by definition, so this test injects the caller's
# GH_TOKEN and links its harness credentials into the throwaway HOME instead; one harness
# with its login is all it needs, and the rest are skipped by name.
# Nothing here posts to Discord: every command's environment carries `AK_NOTIFY_SINK=dry-run`,
# which outranks any webhook the HOME was given, the webhook is `off` besides, and the two
# notify checks are --dry-run.
#
# Every tmux server it touches is the throwaway HOME's own -- a test socket in a socket
# directory under the workdir -- and it never runs a tmux command except to stop that server
# on the way out, so no session of yours is in reach.
#
#   tests/e2e-fresh.sh                 every step
#   tests/e2e-fresh.sh --steps d,e     only those steps (a and c always run: the HOME
#                                     and its logins are what every other step needs)
#   tests/e2e-fresh.sh --keep          leave the HOME behind for a look
set -uo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

STEPS=all KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --steps) [ $# -gt 1 ] || { echo "e2e-fresh.sh: --steps needs a list" >&2; exit 2; }
             STEPS=,$2, ; shift ;;
    --keep)  KEEP=1 ;;
    *) echo "usage: e2e-fresh.sh [--steps a,b,c] [--keep]  (got $1)" >&2; exit 2 ;;
  esac
  shift
done
doing() { [ "$STEPS" = all ] || [ "${STEPS#*,$1,}" != "$STEPS" ]; }

[ "$(uname -s)" = Linux ] || { echo "e2e-fresh.sh: Linux only (this is $(uname -s))" >&2; exit 2; }

# The logins this test borrows are the caller's own, linked into the throwaway HOME from
# wherever the caller's harnesses keep them.
INVOKER=$(id -un)
INVHOME=$HOME
[ -n "$INVHOME" ] || { echo "e2e-fresh.sh: no home directory for $INVOKER" >&2; exit 2; }
caller_config=${XDG_CONFIG_HOME:-$INVHOME/.config}
caller_data=${XDG_DATA_HOME:-$INVHOME/.local/share}
caller_claude=${CLAUDE_CONFIG_DIR:-$INVHOME/.claude}
caller_grok=${GROK_HOME:-$INVHOME/.grok}
caller_opencode=${OPENCODE_CONFIG:-${OPENCODE_CONFIG_DIR:-$caller_config/opencode}/opencode.json}

TS=$(date +%Y%m%d-%H%M%S)
MARKER="e2e-$TS.txt"                 # the file the real task adds to the private target
WORK=$(mktemp -d /tmp/ak-e2e-XXXXXX) || exit 2
UH="$WORK/home"
mkdir -p -- "$UH"
SMOKE_REPO=""
# Step f's run is nobody's worker and nobody's seat either: a session that executes tasks
# exports AK_RUN_ROLE=worker, and it may export AGENTKIT_SESSION, which would record this
# gate's throwaway run against the owner's live seat.
unset AK_RUN_ROLE AGENTKIT_SESSION
# The throwaway HOME borrows the host's harness binaries the way it borrows the logins:
# install.sh under a sandbox HOME installs none, so the shell below puts the caller's
# bins beside the throwaway's own -- and the directory of each harness the caller has, found
# on the caller's PATH or where its installer puts it, wherever that is.
EPATH="$UH/.local/bin:$UH/.npm-global/bin:$INVHOME/.local/bin:$INVHOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"
HOSTBIN=" "   # the harness binaries this host has
for h in claude codex muse grok opencode agy; do
  found=$(PATH="$PATH:$INVHOME/.local/bin:$INVHOME/.npm-global/bin:${GROK_BIN_DIR:-$INVHOME/.grok/bin}:$INVHOME/.opencode/bin" \
          command -v "$h") || continue
  EPATH="$EPATH:${found%/*}" HOSTBIN="$HOSTBIN$h "
done
# The throwaway HOME's own tmux server, like the smoke suite's: a test socket in a socket
# directory under the workdir, so no seat of yours is in reach.
E2E_TMUX_SOCKET=agentkit-test
E2E_TMUX_DIR="$WORK/tmux"
mkdir -p -- "$E2E_TMUX_DIR"

# --- the same one-suite-at-a-time lock tests/smoke.sh takes ------------------
# Step f's clone, run and delivery check are one turn on the host-wide lock: two gates running
# at once would collide on seat names and on the account's persistent target.  Same file,
# same hour-long wait, same wording, and the file is created world-readable and locked
# through a read-only descriptor so suites running as
# different accounts all reach it.  $AK_SMOKE_LOCK_WAIT overrides the wait, for tests.
SMOKE_LOCK=/tmp/agentkit-smoke-remote.lock
SMOKE_LOCK_WAIT=${AK_SMOKE_LOCK_WAIT:-3600}
SMOKE_LOCK_WAITING="check 4: waiting for another suite's turn"
SMOKE_LOCK_PID=""
SMOKE_LOCK_HELD=0
SMOKE_LOCK_PY='
import fcntl, os, signal, sys, threading, time
path, wait, parent = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
def open_lock():
    # Opening it and creating it are two different asks.  /tmp is sticky and world-writable, and
    # with fs.protected_regular=2 the kernel refuses any O_CREAT open of a file a third account
    # already owns there -- read-only or not.  Suites running as different accounts meet on
    # this file -- that is the ordinary case, not a corner -- so ask for the file that is
    # already there without O_CREAT, and create it exclusively only when genuinely missing.
    try:
        return os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        pass
    try:
        made = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return os.open(path, os.O_RDONLY)      # somebody created it between the two calls
    try:
        os.fchmod(made, 0o644)                 # world-readable whatever the umask was
    finally:
        os.close(made)
    return os.open(path, os.O_RDONLY)

try:
    fd = open_lock()
except OSError as exc:
    sys.stderr.write("smoke lock %s: %s\n" % (path, exc))
    print("busy", flush=True)
    sys.exit(75)
def expired(signum, frame):
    raise TimeoutError()

# Waiting for the shared turn is bounded work, not a hung suite. Report that wait
# without leaving the kernel queue, so the silence watchdog need not guess.
def report_wait(done):
    while not done.wait(60):
        print("waiting", flush=True)

try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    # Queue in the kernel rather than poll.  A waiter that sleeps between tries can miss a lock
    # that is only briefly free -- two suites handing the turn over do exactly that -- and then
    # reports busy while nobody holds it.  The alarm is what keeps the wait bounded.
    print("waiting", flush=True)
    if wait <= 0:
        print("busy", flush=True)
        sys.exit(75)
    done = threading.Event()
    reporter = threading.Thread(target=report_wait, args=(done,))
    signal.signal(signal.SIGALRM, expired)
    busy = False
    try:
        signal.setitimer(signal.ITIMER_REAL, wait)
        reporter.start()
        fcntl.flock(fd, fcntl.LOCK_EX)
    except (TimeoutError, OSError):
        busy = True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        done.set()
        if reporter.is_alive():
            reporter.join()
    if busy:
        print("busy", flush=True)
        sys.exit(75)
print("held", flush=True)
sys.stdout.close()
while os.getppid() == parent:
    time.sleep(2)
'
smoke_lock_hold() {   # smoke_lock_hold <wait seconds>: 0 and the remote is this gate's, or 75
  local dir line status=busy
  dir=$(mktemp -d "${TMPDIR:-/tmp}/ak-e2e-lock-XXXXXX") || return 75
  if ! mkfifo "$dir/status"; then rm -rf -- "$dir"; return 75; fi
  python3 -c "$SMOKE_LOCK_PY" "$SMOKE_LOCK" "$1" $$ >"$dir/status" &
  SMOKE_LOCK_PID=$!
  while IFS= read -r line; do
    case "$line" in
      waiting) printf '%s\n' "$SMOKE_LOCK_WAITING" ;;
      held|busy) status=$line; break ;;
    esac
  done <"$dir/status"
  rm -rf -- "$dir"
  if [ "$status" = held ]; then
    # The holder must not stay a job this shell can wait on.  A bare `wait` waits for *every*
    # child -- check 9 collects its two background runs that way, and so does the name-pair
    # block below -- and this child only exits when the suite does: the suite would sit there
    # for as long as anyone let it.  Disowned it is still the EXIT trap's to kill by pid, and
    # it still watches its parent, so a crashed suite gives the remote back too.  (The pid form
    # of `disown` is newer than bash 3.2, hence the jobspec fallback: right here the holder is
    # the current job.)
    disown "$SMOKE_LOCK_PID" 2>/dev/null || disown %% 2>/dev/null || :
    SMOKE_LOCK_HELD=1
    return 0
  fi
  wait "$SMOKE_LOCK_PID" 2>/dev/null   # it printed busy and exited; this only reaps it
  SMOKE_LOCK_PID=""
  return 75
}
smoke_lock_drop() {
  [ -z "$SMOKE_LOCK_PID" ] || kill "$SMOKE_LOCK_PID" 2>/dev/null
  SMOKE_LOCK_PID=""; SMOKE_LOCK_HELD=0
}

. "$REPO/tests/acceptance.sh"
# The log `finish` fails on: a diverted notification inside the throwaway HOME still turns
# this gate red through it.
: >"$AK_NOTIFY_SINK_LOG"
bad="" ASSERTION=0
must() {   # must "<what should hold>" <command...>
  local what=$1; shift
  ASSERTION=$((ASSERTION + 1))
  checked "$WORK/assert-$ASSERTION.log" "$@" || bad="$bad; $what"
}
verdict() {   # verdict "<step>" "<evidence when it passes>"
  if [ -z "$bad" ]; then ok "$1: $2"; else no "$1:${bad#;}"; fi
  bad=""
}
say() { printf '      %s\n' "$*"; }

# --- the throwaway HOME's shell -------------------------------------------
# env -i: a fresh login, nothing of the caller's leaking in except the harness bins on PATH.
# The GitHub token is sourced from a file inside the HOME rather than passed on the command
# line, where `ps` would show it.
AS_TERM=dumb
# `cd $HOME` first: a newcomer's shell never starts in somebody else's 0700 home -- where
# even `git config --global` fails, on the cwd it cannot stat.
as() { env -i "HOME=$UH" "USER=$INVOKER" "LOGNAME=$INVOKER" SHELL=/bin/bash \
         "TERM=$AS_TERM" "PATH=$EPATH" AGENTKIT_DISCORD_WEBHOOK=off AK_NOTIFY_SINK=dry-run \
         "AK_NOTIFY_SINK_LOG=$AK_NOTIFY_SINK_LOG" "AGENTKIT_TMUX_SOCKET=$E2E_TMUX_SOCKET" \
         "TMUX_TMPDIR=$E2E_TMUX_DIR" \
         bash -lc "cd \"\$HOME\" || exit 1; . \"\$HOME/.ak-e2e-env\" 2>/dev/null; $1"; }

# A subscription login is one token, and the harnesses rotate it: whichever HOME refreshes
# last holds the only one that still works.  The throwaway HOME links the caller's, so one
# renewed in place is the caller's already; one a harness renamed over its link goes back,
# when newer, before the workdir is deleted, or the caller is logged out.
sync_back() {
  python3 "$REPO/tests/merge_logins.py" "$UH" "$caller_claude/.credentials.json" \
    "$caller_grok/auth.json" && return 0
  say "WARN could not return a renewed login to $INVOKER; its HOME is kept"
  return 1
}

cleanup_logs() {   # cleanup_logs <gate exit>: one archive of the latest failure, no tmp growth
  local rc=$1 archive staging=""
  if [ "$rc" != 0 ]; then
    # Never retain the borrowed token or phone private key with the evidence.
    archive="$INVHOME/.agentkit/tmp/e2e-fresh-failure.tar.gz"
    if rm -f -- "$WORK/phone" "$WORK/phone.pub" "$WORK/ghenv" "$WORK/source.bundle" &&
       mkdir -p -- "$(dirname -- "$archive")" &&
       staging=$(mktemp "$archive.XXXXXX") &&
       tar -czf "$staging" -C "$WORK" . &&
       mv -f -- "$staging" "$archive"; then
      say "failure logs: $archive (replaces the previous failed gate's archive)"
    else
      say "WARN could not archive $WORK; diagnostics are in this gate's output"
    fi
    [ -z "$staging" ] || rm -f -- "$staging"
  fi
  rm -rf -- "$WORK"
}

cleanup() {
  local rc=$?
  sync_back || { KEEP=1 rc=1; }
  [ "$KEEP" = 1 ] && { echo "kept: HOME $UH, workdir $WORK${SMOKE_REPO:+ (repo $SMOKE_REPO)}"; exit "$rc"; }
  TMUX_TMPDIR="$E2E_TMUX_DIR" tmux -L agentkit-test kill-server >/dev/null 2>&1 || true
  smoke_lock_drop
  cleanup_logs "$rc"
}
trap cleanup EXIT

echo "e2e: HOME $UH, workdir $WORK, borrowing the logins of $INVOKER"

# ==== a) a fresh HOME, this revision of the documented installer ============
TOKEN=$(gh auth token 2>/dev/null)
if [ -z "$TOKEN" ]; then
  no "a fresh install: $INVOKER has no \`gh auth token\` to lend the throwaway HOME"
  finish; exit 1
fi

# the token the newcomer would have gotten from `gh auth login`, out of sight of `ps`
printf 'export GH_TOKEN=%s\n' "$TOKEN" >"$WORK/ghenv"
install -m 0600 "$WORK/ghenv" "$UH/.ak-e2e-env"
rm -f -- "$WORK/ghenv"
install -d -m 0755 "$UH/e2e"

# Install this checkout's committed revision, not the origin's default branch. Refuse a
# dirty tree so the printed revision identifies every byte under test. A bundle also works
# before the worker branch has been pushed, and needs no network access to prepare.
SOURCE_SHA=$(git -C "$REPO" rev-parse HEAD) || exit 1
SOURCE_DIRTY=$(git -C "$REPO" status --porcelain) || exit 1
if [ -n "$SOURCE_DIRTY" ]; then
  no "a fresh install: commit the worktree before testing revision $SOURCE_SHA"
  finish; exit 1
fi
checked "$WORK/source.log" git -C "$REPO" bundle create "$WORK/source.bundle" HEAD || {
  no "a fresh install: could not bundle revision $SOURCE_SHA"; finish; exit 1;
}
echo "source revision: $SOURCE_SHA (from $REPO)"
as "git clone -q '$WORK/source.bundle' ~/agentkit &&
    cd ~/agentkit && git checkout -q --detach '$SOURCE_SHA' &&
    test \"\$(git rev-parse HEAD)\" = '$SOURCE_SHA' && bash install.sh </dev/null" \
   >"$WORK/install1.log" 2>&1
IRC=$?
must "install.sh exited $IRC, not 0" test "$IRC" = 0
must "no ak on PATH for a login shell" as 'command -v ak >/dev/null && [ "$(command -v ak)" = "$HOME/.local/bin/ak" ]'
must "~/.local/bin/ak is not a link to the checkout" \
  test "$(readlink -- "$UH/.local/bin/ak")" = "$UH/agentkit/bin/ak"
must "the PATH line is not above bashrc's non-interactive return" \
  bash -c "head -3 '$UH/.bashrc' | grep -q '^# agentkit PATH'"
must "no PATH line in .profile" grep -q '^# agentkit PATH' "$UH/.profile"
must "~/.claude/CLAUDE.md is a link of ours; the rulebook belongs to the session, not to the user's harness" \
  test ! -L "$UH/.claude/CLAUDE.md"
must "~/.codex/AGENTS.md is a link of ours; the rulebook belongs to the session, not to the user's harness" \
  test ! -L "$UH/.codex/AGENTS.md"
must "claude settings.json has no yolo defaults" as \
  'jq -e ".permissions.defaultMode == \"bypassPermissions\"
          and .skipDangerousModePermissionPrompt == true
          and .env.DISABLE_AUTOUPDATER == \"1\"" ~/.claude/settings.json'
must "the seat-state hooks are not wired exactly once on each event" as \
  'jq -e --arg c "bash $HOME/agentkit/hooks/seat-state.sh" ".hooks as \$h
      | [\"UserPromptSubmit\", \"Stop\", \"Notification\"]
      | map([\$h[.][]?.hooks[]? | select(.type == \"command\" and .command == \$c)] | length)
      | . == [1, 1, 1]" ~/.claude/settings.json'
must "codex config.toml has no yolo defaults" as \
  'python3 -c "import pathlib,sys,tomllib
c=tomllib.loads(pathlib.Path.home().joinpath(\".codex/config.toml\").read_text())
sys.exit(0 if c.get(\"approval_policy\")==\"never\" and c.get(\"sandbox_mode\")==\"danger-full-access\" else 1)"'
must "the alias block is missing" grep -qxF "alias orch='ak orch'" "$UH/.bashrc"
must "MUSE_NO_AUTO_UPDATE is not pinned" grep -qF 'export MUSE_NO_AUTO_UPDATE=1' "$UH/.bashrc"
must "~/.agentkit is not 0700" test "$(stat -c %a "$UH/.agentkit")" = 700
must "~/code was not created" test -d "$UH/code"
# A harness this host has must reach the new HOME's PATH; one it never installed is skipped.
for h in claude codex muse grok opencode agy; do
  case "$HOSTBIN" in
    *" $h "*) must "$h is not on PATH from the host" as "command -v $h" ;;
    *) skip "a: $h is not on this host" ;;
  esac
done
awk '/^summary: /,0' "$WORK/install1.log" >"$WORK/summary.txt"
must "the install did not summarise what it skipped" test -s "$WORK/summary.txt"
must "the summary does not name the skipped discord" grep -qi "discord" "$WORK/summary.txt"
must "the install did not say it was a sandbox HOME" grep -q "sandbox HOME" "$WORK/install1.log"
# A sandbox HOME installs no cron: prove it said so, and touch the caller's real crontab never.
must "no sandbox cron skip for the server role" grep -q 'ak watch cron is not installed' "$WORK/install1.log"
verdict "a  fresh HOME: revision $SOURCE_SHA + install.sh with no tty" \
  "ak on PATH, yolo defaults, idle-compact hook, harnesses on PATH, cron skipped for sandbox, summary printed"
[ "$IRC" = 0 ] || diagnose "$IRC" "$WORK/install1.log" as "clone revision $SOURCE_SHA and bash install.sh"

# ==== b) the second run changes nothing =====================================
if doing b; then
  before=$(bash -c "md5sum '$UH/.claude/settings.json' '$UH/.codex/config.toml' '$UH/.bashrc' '$UH/.profile' 2>&1 | md5sum")
  baks=$(bash -c "ls -1 '$UH/.claude/' '$UH/.codex/' 2>/dev/null | grep -c '\.bak-'")
  as 'bash ~/agentkit/install.sh </dev/null' >"$WORK/install2.log" 2>&1
  IRC2=$?
  after=$(bash -c "md5sum '$UH/.claude/settings.json' '$UH/.codex/config.toml' '$UH/.bashrc' '$UH/.profile' 2>&1 | md5sum")
  baks2=$(bash -c "ls -1 '$UH/.claude/' '$UH/.codex/' 2>/dev/null | grep -c '\.bak-'")
  must "the second install exited $IRC2" test "$IRC2" = 0
  must "it rewrote a config file" test "$before" = "$after"
  must "it took another backup" test "$baks" = "$baks2"
  must "it did not say the settings were already current" \
    grep -q 'already bypassPermissions' "$WORK/install2.log"
  must "it did not say the codex config was already current" \
    grep -q 'already approval_policy=never' "$WORK/install2.log"
  must "it did not say the aliases were already current" \
    grep -q 'aliases already current' "$WORK/install2.log"
  verdict "b  idempotent: install.sh a second time" "no file rewritten, no new backup, three 'already' lines"
fi

# ==== c) logged in: the credentials a newcomer's three logins would leave ====
if true; then       # always: every step below needs the HOME to be logged in
  # Each login is linked, file by file, as tests/smoke.sh links its own: a harness here renews
  # the caller's login as it would at home, and sync_back returns one it renamed over its link.
  # The worker token keeps Claude's headless turns off the seat's own pair.  OpenCode's
  # settings, which may hold its key, and the Discord secrets are copies, and lend no login.
  LENT=" "      # the harnesses whose login, or part of it, this host lent the new HOME
  SEATPAIR=""   # Claude's own pair, which the menu's seat needs: the worker token is not one
  there() {   # there <caller's file>: 0 to borrow it, 1 when nothing is there, 2 when unreadable
    # A file this user cannot read, or cannot reach through a directory or a link, is there and
    # broken, not absent: it fails the step rather than letting another harness pass without it.
    local dir=$1
    [ -f "$1" ] && [ -r "$1" ] && return 0
    while [ ! -e "$dir" ] && [ ! -L "$dir" ] && [ "$dir" != "${dir%/*}" ]; do dir=${dir%/*}; dir=${dir:-/}; done
    [ "$dir" != "$1" ] && [ -e "$dir" ] && { [ ! -d "$dir" ] || [ -x "$dir" ]; } && return 1
    bad="$bad; $1 cannot be read"; return 2
  }
  lend() {   # lend <harness> <caller's file> <file under the new HOME>: 1 when absent
    there "$2" || return
    LENT="$LENT$1 "
    install -d -m 0700 "$(dirname -- "$UH/$3")" && ln -s -- "$2" "$UH/$3" ||
      bad="$bad; $2 could not be linked into the new HOME"
  }
  copyin() {   # copyin <caller's file> <file under the new HOME>: 1 when absent
    there "$1" || return
    install -d -m 0700 "$(dirname -- "$UH/$2")" && install -m 0600 -- "$1" "$UH/$2" ||
      bad="$bad; $1 could not be copied into the new HOME"
  }
  lend claude "$caller_claude/.credentials.json" .claude/.credentials.json && SEATPAIR=1
  lend claude "$INVHOME/.agentkit/secrets/claude_oauth_token" .agentkit/secrets/claude_oauth_token
  lend codex "${CODEX_HOME:-$INVHOME/.codex}/auth.json" .codex/auth.json
  lend muse "$caller_config/muse/auth.json" .config/muse/auth.json
  # Grok flocks auth.json.lock when it renews: the same inode guards both homes, even before
  # the caller's first renewal has made it.
  lend grokbuild "$caller_grok/auth.json" .grok/auth.json && { ln -s -- "$caller_grok/auth.json.lock" \
    "$UH/.grok/auth.json.lock" || bad="$bad; Grok's lock could not be linked into the new HOME"; }
  lend opencode "$caller_data/opencode/auth.json" .local/share/opencode/auth.json
  lend antigravity "$INVHOME/.gemini/antigravity-cli/antigravity-oauth-token" \
    .gemini/antigravity-cli/antigravity-oauth-token
  copyin "$caller_opencode" .config/opencode/opencode.json
  copyin "$INVHOME/.agentkit/secrets/discord_webhook" .agentkit/secrets/discord_webhook || [ $? = 2 ] ||
    skip "c: the Discord webhook is not on this host"
  copyin "$INVHOME/.agentkit/secrets/discord_user_id" .agentkit/secrets/discord_user_id || [ $? = 2 ] ||
    skip "c: the Discord user id is not on this host"
  # Whether each harness can log in is worker.auth_ok's answer in the new HOME, as before a
  # turn: 0 for a yes, 3 for a no, anything else no answer.  Claude's worker token is a login
  # as good as the seat's pair.  A login this host lent that is refused, or that gets no
  # answer at all, fails the step; a harness with none lent is skipped.
  HERE=""       # the harnesses installed here with their login, one of which the gate needs
  here() { case "$HERE " in *" $1:"*) ;; *) return 1 ;; esac; }   # here <harness>
  for pair in "claude claude anthropic" "codex codex openai" "muse muse meta" \
              "grokbuild grok -" "opencode opencode -" "antigravity agy -"; do
    set -- $pair
    case "$HOSTBIN" in *" $2 "*) ;; *) skip "c: $1 is not on this host"; continue ;; esac
    WHY=$(env -i HOME="$UH" PATH="$EPATH" PYTHONPATH="$UH/agentkit" \
            AGENTKIT_ADAPTER_DIR="$UH/agentkit/adapters" python3 -c 'import sys
from agentkit import worker
ok, why = worker.auth_ok(sys.argv[1])
print(why)
sys.exit({True: 0, False: 3}.get(ok, 2))' "$1" 2>&1 </dev/null)
    case "$?:$LENT" in
      0:*) HERE="$HERE $1:$3" ;;
      3:*" $1 "*) bad="$bad; $WHY" ;;
      3:*) skip "c: $1's login is not on this host: $WHY" ;;
      *) bad="$bad; $1: its auth gave no answer: $WHY" ;;
    esac
  done
  [ -n "$HERE" ] || bad="$bad; no harness here is installed with its login; the gate needs one"
  SEATLOGIN=""  # the menu's seat: Claude here, with its own pair lent
  here claude && [ -n "$SEATPAIR" ] && SEATLOGIN=1
  # `claude` also writes the account it belongs to into ~/.claude.json when you log in; without
  # it the TUI opens on the login screen however good the credentials are.  Only the account
  # keys are copied -- the caller's project list, history and caches stay where they are.
  python3 - "${CLAUDE_CONFIG_DIR:-$INVHOME}/.claude.json" "$UH/.claude.json" <<'PY'
import json, os, pathlib, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
have = json.loads(src.read_text()) if src.exists() else {}
data = json.loads(dst.read_text()) if dst.exists() else {}
for key in ("oauthAccount", "userID", "firstStartTime", "installMethod"):
    if key in have:
        data[key] = have[key]
data["hasCompletedOnboarding"] = True
data.setdefault("theme", "dark")
dst.write_text(json.dumps(data, indent=2))
PY
  chmod 600 "$UH/.claude.json"
  as 'ak usage --json' >"$WORK/usage.json" 2>"$WORK/usage.err"
  URC=$?
  must "ak usage exited $URC" test "$URC" = 0
  # A meter the provider throttles is its skip, as in tests/smoke.sh; one that answers wrong fails.
  for p in $HERE; do
    p=${p#*:}
    if [ "$p" = - ]; then
      :
    elif WHY=$(meter_unavailable "$WORK/usage.json" "$p"); then
      skip "c: provider meter unavailable ($WHY)"
    else
      must "no meters for $p" jq -e --arg p "$p" '.providers[$p].meters | length >= 1' "$WORK/usage.json"
    fi
  done
  must "an empty pick order" jq -e '.pick_order | type == "array" and length > 0' "$WORK/usage.json"
  verdict "c  logged in: harness credentials linked + Discord secrets copied in" \
    "ak usage --json meters $(jq -c '[.providers | to_entries[] | {(.key): (.value.meters|length)}] | add' "$WORK/usage.json" 2>/dev/null), pick_order $(jq -c .pick_order "$WORK/usage.json" 2>/dev/null)"
  [ -s "$WORK/usage.err" ] && sed 's/^/      /' "$WORK/usage.err" | head -5
fi

# ==== the pty driver the menu steps are driven through ======================
cat >"$WORK/ptydrive.py" <<'PY'
#!/usr/bin/env python3
"""Drive a command through a pty from a tiny script, and say which line did not happen.

    expect <secs> <regex>   wait for it after the previous match
    refute <regex>          fail if it has been printed at all
    send <text>             \n and \x02 escapes are honoured
    sleep <secs>

Usage: ptydrive.py <transcript> <script> -- <command...>
"""
import fcntl, os, pty, re, select, signal, struct, sys, termios, time

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z@]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][B0]|\x1b[=><]|\r")


def seen(pattern, text):
    """Is it on the screen?  Spaces in the pattern match no space at all as well.

    tmux moves the cursor rather than writing a run of spaces, and those moves are escape
    sequences like every other, so a footer that reads `bypass permissions on` arrives as
    `bypasspermissionson` once the escapes are stripped.
    """
    return bool(re.search(pattern, text) or re.search(pattern.replace(" ", r"\s*"), text))


def main():
    out, script = sys.argv[1], sys.argv[2]
    cmd = sys.argv[sys.argv.index("--") + 1:]
    steps = [l for l in open(script).read().splitlines() if l.strip() and not l.startswith("#")]
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["COLUMNS"], os.environ["LINES"] = "120", "40"
        os.execvp(cmd[0], cmd)
    # a real window size: tmux sizes its client from the pty, and pty.fork leaves it at 0x0
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    raw, clean, rc = bytearray(), "", 0
    cursor = 0

    def save():
        with open(out, "w") as fh:      # as it goes, so an expect that hangs can be read while it hangs
            fh.write(clean)

    def pump(seconds):
        nonlocal clean
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                return False
            if not data:
                return False
            raw.extend(data)
            clean = ANSI.sub("", raw.decode("utf-8", "replace"))
            save()
        return True

    try:
        for step in steps:
            verb, _, arg = step.partition(" ")
            if verb == "expect":
                secs, _, pattern = arg.partition(" ")
                end, found = time.time() + float(secs), False
                while time.time() < end:
                    pending = clean[cursor:]
                    if seen("Hooks need review", pending):
                        if seen(r"3\. Continue without trusting", pending):
                            # Codex's trust decision is real. Decline the new hooks, never
                            # approve them on behalf of the borrowed account.
                            os.write(fd, b"3\r")
                            cursor = len(clean)
                    elif seen(pattern, pending):
                        found = True
                        break
                    if not pump(0.4):
                        break
                found = found or (not seen("Hooks need review", clean[cursor:]) and seen(pattern, clean[cursor:]))
                if not found:
                    print(f"MISSING after {secs}s: {pattern}", file=sys.stderr)
                    rc = 1
                    break
                match = re.search(pattern, clean[cursor:]) or re.search(pattern.replace(" ", r"\s*"), clean[cursor:])
                cursor += match.end()
                print(f"saw: {pattern}", flush=True)
            elif verb == "refute":
                if seen(arg, clean):
                    print(f"PRESENT but must not be: {arg}", file=sys.stderr)
                    rc = 1
                    break
                print(f"absent: {arg}", flush=True)
            elif verb == "send":
                os.write(fd, arg.encode().decode("unicode_escape").encode("latin-1"))
                pump(0.3)
            elif verb == "sleep":
                pump(float(arg))
            else:
                print(f"ptydrive: unknown step {step!r}", file=sys.stderr)
                rc = 2
                break
    finally:
        pump(0.5)
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            pass
        save()
    return rc


sys.exit(main())
PY
chmod 755 "$WORK/ptydrive.py"
# the transcripts live under $WORK/pty, beside the logs that say which line did not happen
install -d -m 0755 "$WORK/pty"
drive() {   # drive <name> <TERM> <command...>; the script is $WORK/<name>.exp
  local name=$1 term=$2; shift 2
  env -i "HOME=$UH" "USER=$INVOKER" "LOGNAME=$INVOKER" SHELL=/bin/bash "TERM=$term" \
    "PATH=$EPATH" AGENTKIT_DISCORD_WEBHOOK=off AK_NOTIFY_SINK=dry-run "AGENTKIT_SESSION=${SEAT:-}" \
    "AK_NOTIFY_SINK_LOG=$AK_NOTIFY_SINK_LOG" "AGENTKIT_TMUX_SOCKET=$E2E_TMUX_SOCKET" \
    "TMUX_TMPDIR=$E2E_TMUX_DIR" \
    bash -lc "cd \"\$HOME\" || exit 1; . \"\$HOME/.ak-e2e-env\" 2>/dev/null
              exec python3 $WORK/ptydrive.py $WORK/pty/$name.txt $WORK/$name.exp -- $*" \
    >"$WORK/$name.log" 2>&1
}
# All supported harnesses: Claude's footer, Codex's composer, Muse's complete model footer.
# A selection cursor or the Codex banner's "permissions: YOLO mode" is not a ready composer.
# Match the text without line anchors: tmux can position a row without emitting a newline.
PROMPT='bypass permissions on|[▌›] Ask Codex to do (?:anything|something)|[\w.-]+ · \w+ · [^\n]+ · YOLO'
MENU='n (start a session|new) '
NODIALOG='Do you trust|trust the files|No, exit|Choose the text style|Select a theme|Yes, I accept|WARNING: Claude Code running|Update available|Sign in with|sign in again|Trust this directory|Trust directory'

# ==== d) the menu, through a pty, on both terminals ==========================
SEAT=""
if doing d && [ -z "$SEATLOGIN" ]; then
  skip_checks d/d2 "the menu's seat is fable, and claude or its own login is not on this host"
elif doing d; then
  cat >"$WORK/menu1.exp" <<EXP
expect 120 $MENU
send n\n
expect 60 Project \[
send \n
expect 60 Name:
send atoll\n
expect 240 Orchestrator \[fable\]:
send \n
expect 240 $PROMPT
refute $NODIALOG
send \x02d
expect 120 $MENU
send q\n
EXP
  drive menu1 xterm-256color ak
  D1=$?
  must "the menu did not run through to a supported harness prompt (xterm-256color)" test "$D1" = 0
  LIST=$(as 'ak orch list' 2>&1)
  must "ak orch list does not show the seat" grep -q '^atoll ' <<<"$LIST"
  must "ak orch list does not show its models" awk -F'  +' '/^atoll /{ok = ($5 == "fable" && $6 != "" && $6 != "—")} END{exit !ok}' <<<"$LIST"
  SEAT=atoll
  # the same menu from a terminal whose terminfo this box has never seen
  cat >"$WORK/menu2.exp" <<EXP
expect 120 $MENU
send 1\n
expect 240 $PROMPT
refute missing or unsuitable terminal
send \x02d
expect 120 $MENU
send q\n
EXP
  drive menu2 xterm-ghostty ak
  D2=$?
  must "the menu could not attach the seat under TERM=xterm-ghostty" test "$D2" = 0
  verdict "d  menu through a pty: n, the name, Enter, Enter, detach; attach again from xterm-ghostty" \
    "atoll created on $(printf '%s' "$LIST" | awk -F'  +' '/^atoll /{print $5; exit}'), prompt up with no trust/theme/permission dialog, listed, detached"
  for f in menu1 menu2; do
    [ -s "$WORK/$f.log" ] && grep -q 'MISSING\|PRESENT' "$WORK/$f.log" && {
      sed 's/^/      /' "$WORK/$f.log" | tail -4; tail -c 600 "$WORK/pty/$f.txt" | sed 's/^/      | /'; }
  done
fi

# ==== e) the phone: one key, one forced command, the same menu ==============
if doing e; then
  ssh-keygen -q -t ed25519 -N '' -C e2e-phone -f "$WORK/phone" || true
  chmod 600 "$WORK/phone"
  install -m 0644 "$WORK/phone.pub" "$UH/e2e/phone.pub"
  as 'bash ~/agentkit/install.sh --phone-key ~/e2e/phone.pub </dev/null' >"$WORK/install-key.log" 2>&1
  must "the phone key did not get the ak attach forced command" \
    grep -q 'command="[^"]*ak attach",no-agent-forwarding,no-port-forwarding.*phone-termius' \
      "$UH/.ssh/authorized_keys"
  FORCED=$(sed -n 's/^command="\([^"]*\)".*phone-termius$/\1/p' "$UH/.ssh/authorized_keys")
  # No sshd here: the forced command itself is driven through a pty, which is what proves it
  # lands in the menu rather than in a shell.
  cat >"$WORK/phone.exp" <<EXP
expect 120 $MENU
send q\n
EXP
  # shellcheck disable=SC2086
  drive phone xterm-256color $FORCED
  PRC=$?
  must "the forced command exited $PRC" test "$PRC" = 0
  must "the phone key did not land in the menu" grep -qE "$MENU" "$WORK/pty/phone.txt"
  must "the phone key reached a shell instead of the menu" \
    bash -c "! grep -qi 'command not found\|Permission denied' '$WORK/pty/phone.txt'"
  verdict "e  phone: the forced command" "command=\"$FORCED\" put the session straight in the menu"
  [ "$PRC" = 0 ] || { sed 's/^/      /' "$WORK/phone.log" | tail -4; tail -c 600 "$WORK/pty/phone.txt" | sed 's/^/      | /'; }
fi

# ==== f) a real task, start to merged ======================================
# Creating or resetting the private target, the run and the delivery check share the
# host-wide lock. The remote stays; its seed and leftover ak/* branches are reset each run.
if ! doing f; then
  :
elif GONE=$(for h in claude codex; do here "$h" || printf ' %s' "$h"; done) && [ -n "$GONE" ]; then
  skip "f: the run's workers are opus and astra;$GONE not on this host"
elif ! smoke_lock_hold "$SMOKE_LOCK_WAIT"; then
  no "f  a real task, orchestrated headlessly: another suite still holds the turn after\
 ${SMOKE_LOCK_WAIT}s; its seats and turn were never this gate's to take"
else
  E2E_LOGIN=$(gh api user --jq .login 2>"$WORK/e2e-login.err" || true)
  SMOKE_REPO="$E2E_LOGIN/agentkit-e2e"
  [ -n "$E2E_LOGIN" ] &&
    { gh repo view "$SMOKE_REPO" >/dev/null 2>&1 ||
      gh repo create "$SMOKE_REPO" --private >"$WORK/e2e-create.log" 2>&1; } &&
    as "gh repo clone $SMOKE_REPO ~/agentkit-smoke -- -q" >"$WORK/clone-smoke.log" 2>&1
  CRC=$?
  # No clone, no seed: one cause, one failure, and the seed's `cd` never runs somewhere else.
  SRC=1
  if [ "$CRC" = 0 ]; then
    as 'set -e
        cd ~/agentkit-smoke
        git config user.email e2e@localhost; git config user.name e2e
        if ! git rev-parse --verify -q HEAD >/dev/null 2>&1; then
          echo "# agentkit e2e target: reset on every run" >README.md
          git add -A && git commit -qm init
        fi
        git reset --hard "$(git rev-list --max-parents=0 HEAD)"
        git branch -M main
        git push -q --force -u origin main
        for branch in $(git for-each-ref --format="%(refname:strip=3)" refs/remotes/origin/ak/); do
          git push -q origin --delete "$branch"
        done' >"$WORK/seed.log" 2>&1
    SRC=$?
  fi
  cat >"$WORK/task.md" <<TASK
---
repo: $UH/agentkit-smoke
base: main
rounds: 2
---
# Add the e2e marker file

## Goal
The repository root holds a file named $MARKER whose only line is: agentkit e2e $TS

## Constraints
- Add that one file and change nothing else.
- No new dependencies.

## Done when
\`\`\`bash
grep -qxF 'agentkit e2e $TS' $MARKER
\`\`\`
TASK
  install -m 0644 "$WORK/task.md" "$UH/e2e/task.md"
  must "cloning $SMOKE_REPO failed" test "$CRC" = 0
  must "seeding $SMOKE_REPO failed" test "$SRC" = 0
  [ "$CRC" = 0 ] && [ "$SRC" = 0 ] &&
    as 'timeout 3600 ak run ~/e2e/task.md --rounds 2' >"$WORK/run.log" 2>&1
  RRC=$?
  RUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/run.log" | head -1)
  RESULT="$UH/.agentkit/runs/$RUNID/result.md"
  must "ak run exited $RRC" test "$RRC" = 0
  must "no run directory" test -f "$RESULT"
  must "the reviewer did not say PASS" grep -q '^VERDICT: PASS' "$RESULT"
  must "it was not merged" grep -q '^merged: yes$' "$RESULT"
  must "no PR URL" grep -q '^pr: https://' "$RESULT"
  must "remote done-when failed" as 'python3 ~/agentkit/tests/verify_delivery.py ~/agentkit-smoke ~/e2e/task.md ~/e2e/delivered'
  verdict "f  a real task, orchestrated headlessly" \
    "$(grep -h '^pr: ' "$RESULT" 2>/dev/null) merged, done-when passed on fetched $SMOKE_REPO origin/main"
  [ "$RRC" = 0 ] || tail -15 "$WORK/run.log" | sed 's/^/      /'
fi

# ==== g) the two notifications, never posted ================================
# Here, not later: this runs while the seat from step d is still up, and step d's `x`
# closes it below. The cards are two words and the seat; the text stays in the preview.
if doing g; then
  UID_WANT=$(cat "$UH/.agentkit/secrets/discord_user_id" 2>/dev/null)
  as "AGENTKIT_SESSION=${SEAT:-atoll} ak notify needs 'test' --dry-run" >"$WORK/needs.json" 2>"$WORK/needs.err"
  as "AGENTKIT_SESSION=${SEAT:-atoll} ak notify done 'test' --dry-run" >"$WORK/done.json" 2>"$WORK/done.err"
  must "the needs terminal preview is missing" \
    grep -qxF "terminal notice: Needs you · ${SEAT:-atoll}: test" "$WORK/needs.err"
  must "the done terminal preview is missing" \
    grep -qxF "terminal notice: Done · ${SEAT:-atoll}: test" "$WORK/done.err"
  must "the needs payload is not JSON" jq -e . "$WORK/needs.json"
  must "the done payload is not JSON" jq -e . "$WORK/done.json"
  if [ -n "$UID_WANT" ]; then
    must "the needs payload has no @mention" \
      jq -e --arg m "<@$UID_WANT>" '.content == $m' "$WORK/needs.json"
    must "the done payload has no @mention" \
      jq -e --arg m "<@$UID_WANT>" '.content == $m' "$WORK/done.json"
  else
    skip "g: the @mention: the Discord user id is not on this host"
  fi
  must "the needs embed does not name the session" \
    jq -e --arg s "${SEAT:-atoll}" '.embeds[0].title == ("Needs you · " + $s)' "$WORK/needs.json"
  must "the done embed does not name the session" \
    jq -e --arg s "${SEAT:-atoll}" '.embeds[0].title == ("Done · " + $s)' "$WORK/done.json"
  must "the needs embed is two words and the seat, nothing else" \
    jq -e '(.embeds[0] | has("description") | not) and (.embeds[0] | has("fields") | not)' "$WORK/needs.json"
  verdict "g  ak notify needs/done --dry-run" \
    "${UID_WANT:+mention <@$(printf '%s' "$UID_WANT" | cut -c1-4)...>, }two words and the seat, nothing posted"
fi

# ==== d, closing: x and a number stop the seat ==============================
if doing d && [ -n "$SEATLOGIN" ]; then
  cat >"$WORK/menu3.exp" <<EXP
expect 120 $MENU
send x\n
expect 60 Stop \[atoll\]
send 1\n
expect 60 stop atoll\?
send y\n
expect 60 stopped atoll
send q\n
EXP
  drive menu3 xterm-256color ak
  D3=$?
  as 'ak orch list' >"$WORK/orch-after.txt" 2>&1
  must "x and a number did not stop the seat" test "$D3" = 0
  must "the seat is still running" bash -c "! grep -q '^atoll ' '$WORK/orch-after.txt'"
  verdict "d2 menu: x, 1 stops the session" "atoll stopped, ak orch list is empty again"
  [ "$D3" = 0 ] || { sed 's/^/      /' "$WORK/menu3.log" | tail -4; tail -c 400 "$WORK/pty/menu3.txt" | sed 's/^/      | /'; }
fi

# ==== h) ak update --dry-run ===============================================
if doing h; then
  as 'ak update --dry-run' >"$WORK/update.log" 2>&1
  URC=$?
  must "ak update --dry-run exited $URC" test "$URC" = 0
  for h in claude codex muse grokbuild opencode antigravity; do
    must "the dry run does not name $h" grep -q "^$h " "$WORK/update.log"
  done
  must "it does not say it changed nothing" grep -q 'dry run, nothing changed' "$WORK/update.log"
  verdict "h  ak update --dry-run" "$(grep 'dry run, nothing changed' "$WORK/update.log")"
fi

echo "----"
echo "coverage: throwaway HOME, borrowed logins, existing host packages/services"
echo "NOT EXERCISED: clean disposable host/browser bootstrap; certify in a separate environment"
echo "NOT EXERCISED: network clone of the toolkit (source supplied by a local Git bundle)"
echo "NOT EXERCISED: interactive logins and phone client; not certified by this fresh-HOME gate"
echo "not covered here, and how a newcomer does it:"
echo "  the three device-code logins (claude auth login, codex login --device-auth, muse login)"
echo "    are interactive; this test copied $INVOKER's credentials in instead."
echo "  gh auth login is interactive; this test injected \$GH_TOKEN from \`gh auth token\`."
echo "  the Discord webhook prompt needs a terminal; the secrets were copied and every command"
echo "    here ran with AGENTKIT_DISCORD_WEBHOOK=off and AK_NOTIFY_SINK=dry-run, so nothing was"
echo "    posted, and any attempt would have failed this gate through \$AK_NOTIFY_SINK_LOG."
echo "  the phone was the same forced command run through a pty, not Termius itself."
for step in b d e f g h; do
  doing "$step" || skip "$step: not selected by --steps"
done
finish
