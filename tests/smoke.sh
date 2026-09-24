#!/usr/bin/env bash
# agentkit acceptance gate. Exits 0 only if every check passes.
# Makes real (tiny) model calls on Claude, Codex and Muse -- minus any spent model, or one
# this host has not installed or logged in, which check 3 skips by name; one of the three
# with its login is all the suite needs -- plus one full `ak run`, which merges its
# own PR into a private repository under the caller's own account; the rest drive
# the loop offline through fake adapters, and check 9a waits out the real transient backoff
# (60s + 300s), which is why it starts at the top and is collected at the bottom.
# Self-contained: every `ak` here is this checkout's bin/ak (PATH is prefixed with it, so a
# worktree tests itself), and install.sh is exercised against a throwaway HOME under $WORK, which
# it treats as a sandbox: no packages, no logins, no crontab.  Every tmux server it touches is
# its own, on a socket and in a socket directory of this run's own -- see the block below, and
# check 0, which is what keeps it that way.
# pipefail is on, so `producer | grep -q` is not safe to write here: grep leaves on the first
# match and a producer still writing (git prints a commit at a time) dies of SIGPIPE, which
# pipefail then reports as a failed assertion -- reliably on macOS, almost never on Linux.
# Where the match may come before the end, the output is captured first and grep reads a string.
set -uo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PATH="$REPO/bin:$PATH"
# The suite is nobody's worker and nobody's seat.  A session that executes tasks exports
# AK_RUN_ROLE=worker, which makes every `ak notify` below suppress itself (checks 17, 21, 22,
# 25, 29 and 34 read what it printed), and it may export AGENTKIT_SESSION, which would record
# each throwaway run here against the owner's live seat -- reported to him, typed into his seat,
# shown on his menu row.  AGENTKIT_RUN is the hosting run's marker.  Left set, every background
# `ak run` below is one of that run's processes, and a sweep of the marker -- a killed turn,
# a finished gate -- signals those runs in the middle of their backoff.  Unset once, here:
# the checks that need a role or a seat set it themselves, per command.
unset AK_RUN_ROLE AGENTKIT_SESSION AGENTKIT_RUN
# The slot gate is off for this suite's own runs: AK_MAX_RUNS=0 leaves the count and the
# host readings out of every launch below, so a loaded host never parks a check's run
# behind thirty-second polls. Check 47 exercises the real queue through test_v5am.py, which
# sets its own AK_MAX_RUNS per case; nothing else here asserts on gating.
export AK_MAX_RUNS=0
# A test is not a job, so nothing here may reach the user's Discord.  This marker outranks any
# webhook the environment, the secrets file or a check's own HOME happens to configure, for
# every `ak` this suite runs and everything those runs start in turn; the three checks that
# need a delivered POST point it at a local recorder of their own instead.  Check 5d proves it.

# --- one suite at a time, on everything two suites would share ---------------
# The provider logins and the remote are shared: two suites running at once would use the
# same subscriptions and reset the same remote for that account, so the turn covers the whole suite. A suite
# takes this host-wide lock before its first check and gives it back once its last one has
# reported; a second suite waits its turn rather than overlapping at all.
# The lock file is created world-readable and locked through a read-only descriptor, so suites
# running as different accounts all take it.  $AK_SMOKE_LOCK_WAIT overrides the hour-long wait,
# for tests.
SMOKE_LOCK=/tmp/agentkit-smoke-remote.lock
SMOKE_LOCK_WAIT=${AK_SMOKE_LOCK_WAIT:-3600}
SMOKE_LOCK_WAITING="check 4: waiting for another suite's turn"
SMOKE_LOCK_PID=""
SMOKE_LOCK_HELD=0
# Reports `waiting` at contention and every minute, then exactly one of `held` or `busy`.
# In hold mode it keeps the descriptor -- and so the lock -- until the suite that started it is
# gone, which is what a killed or crashed suite rests on: no pipe another process can inherit.
SMOKE_LOCK_PY='
import fcntl, os, signal, sys, threading, time
path, wait, hold, parent = sys.argv[1], float(sys.argv[2]), sys.argv[3] == "hold", int(sys.argv[4])
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
if hold:
    sys.stdout.close()
    while os.getppid() == parent:
        time.sleep(2)
'
smoke_lock_probe() {   # smoke_lock_probe <wait seconds>: prints held (0) or busy (75)
  local line status=busy
  while IFS= read -r line; do
    case "$line" in
      waiting) printf '%s\n' "$SMOKE_LOCK_WAITING" >&2 ;;
      held|busy) status=$line; break ;;
    esac
  done < <(python3 -c "$SMOKE_LOCK_PY" "$SMOKE_LOCK" "$1" probe $$)
  printf '%s\n' "$status"
  [ "$status" = held ] || return 75
}
smoke_lock_hold() {   # smoke_lock_hold <wait seconds>: 0 and the lock is this suite's, or 75
  local dir line status=busy
  dir=$(mktemp -d "${TMPDIR:-/tmp}/ak-smoke-lock-XXXXXX") || return 75
  if ! mkfifo "$dir/status"; then rm -rf -- "$dir"; return 75; fi
  python3 -c "$SMOKE_LOCK_PY" "$SMOKE_LOCK" "$1" hold $$ >"$dir/status" &
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
# The test hook: take the lock with that wait and report, cloning nothing at all.
if [ "${1:-}" = --lock-probe ]; then
  [ $# = 2 ] || { echo "usage: tests/smoke.sh --lock-probe <seconds>" >&2; exit 2; }
  case "$2" in ''|*[!0-9.]*|*.*.*) echo "tests/smoke.sh: --lock-probe needs seconds" >&2; exit 2 ;; esac
  smoke_lock_probe "$2"
  exit $?
fi
export AK_NOTIFY_SINK=dry-run
if [ "${1:-}" = --projects ]; then
  python3 "$REPO/tests/test_v4z.py"
  exit $?
fi
if [ "${1:-}" = --retention ]; then
  PYTHONDONTWRITEBYTECODE=1 python3 "$REPO/tests/test_audit_retain_state_without_manual_cleanup.py"
  exit $?
fi
if [ "${1:-}" = --auth-watch ]; then
  python3 "$REPO/tests/test_auth_watch.py"
  exit $?
fi
if [ "${1:-}" = --stall-panes ]; then
  [ $# -ge 2 ] || { echo "usage: tests/smoke.sh --stall-panes <out-dir> [harness...]" >&2; exit 2; }
  python3 "$REPO/tests/capture_stall_panes.py" "${@:2}"
  exit $?
fi
smoke_home() {
  # Borrow credential files, never directories: hooks, settings, trust and caches are local.
  local path source target caller_config caller_data caller_claude caller_codex caller_grok
  local caller_opencode caller_gh caller_account
  SMOKE_CALLER_HOME=$HOME
  caller_config=${XDG_CONFIG_HOME:-$HOME/.config}
  caller_data=${XDG_DATA_HOME:-$HOME/.local/share}
  caller_claude=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
  caller_codex=${CODEX_HOME:-$HOME/.codex}
  caller_grok=${GROK_HOME:-$HOME/.grok}
  caller_opencode=${OPENCODE_CONFIG:-${OPENCODE_CONFIG_DIR:-$caller_config/opencode}/opencode.json}
  caller_gh=${GH_CONFIG_DIR:-$caller_config/gh}
  caller_account=${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json
  SMOKE_CLAUDE_CREDS="$caller_claude/.credentials.json"
  SMOKE_GROK_AUTH="$caller_grok/auth.json"
  export HOME="$WORK/home"
  # An inherited override must not send a harness back outside this HOME. Leaving these
  # unset also lets the checks with their own HOME keep their own configs and caches.
  unset XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME CODEX_HOME \
    CLAUDE_CONFIG_DIR GROK_HOME OPENCODE_CONFIG_DIR OPENCODE_CONFIG GH_CONFIG_DIR
  mkdir -p -- "$HOME/.agentkit/secrets" "$HOME/.agentkit/state"
  cp "$REPO/config.default.toml" "$HOME/.agentkit/config.toml" || exit 1
  # gh's saved login is needed by check 4, just as the harness logins are by check 3.
  for path in "$SMOKE_CLAUDE_CREDS:.claude/.credentials.json" \
              "$caller_codex/auth.json:.codex/auth.json" \
              "$caller_config/muse/auth.json:.config/muse/auth.json" \
              "$SMOKE_GROK_AUTH:.grok/auth.json" \
              "$caller_data/opencode/auth.json:.local/share/opencode/auth.json" \
              "$caller_gh/hosts.yml:.config/gh/hosts.yml" \
              "$SMOKE_CALLER_HOME/.agentkit/secrets/claude_oauth_token:.agentkit/secrets/claude_oauth_token" \
              "$SMOKE_CALLER_HOME/.gemini/antigravity-cli/antigravity-oauth-token:.gemini/antigravity-cli/antigravity-oauth-token" \
              "$SMOKE_CALLER_HOME/.local/share/browser-bridge/Xauthority:.local/share/browser-bridge/Xauthority"; do
    source=${path%:*}; target="$HOME/${path##*:}"
    smoke_source "$source" || continue
    mkdir -p -- "${target%/*}" && ln -s -- "$source" "$target" || exit 1
  done
  # Grok flocks this file when refreshing. The same inode must guard both homes, even
  # when the first refresh has yet to create the lock file beside the caller's login.
  if [ -f "$SMOKE_GROK_AUTH" ]; then
    [ ! -d "$SMOKE_GROK_AUTH.lock" ] || { echo "Grok auth lock is a directory" >&2; exit 1; }
    ln -s -- "$SMOKE_GROK_AUTH.lock" "$HOME/.grok/auth.json.lock" || exit 1
  fi
  # Claude needs its account and MCP fields; Git needs its credential helper. Copies let
  # both update their config locally. OpenCode can store its static API key in its config.
  for path in "$caller_account:.claude.json" "$SMOKE_CALLER_HOME/.gitconfig:.gitconfig" \
              "$caller_gh/config.yml:.config/gh/config.yml" \
              "$caller_opencode:.config/opencode/opencode.json" \
              "$SMOKE_CALLER_HOME/.agentkit/secrets/discord_webhook:.agentkit/secrets/discord_webhook"; do
    source=${path%:*}; target="$HOME/${path##*:}"
    smoke_source "$source" || continue
    mkdir -p -- "${target%/*}" && cp -p -- "$source" "$target" || exit 1
  done
  # Find installed executables without linking their writable install directories.
  export PATH="$PATH:$SMOKE_CALLER_HOME/.local/bin:$SMOKE_CALLER_HOME/.npm-global/bin:${GROK_BIN_DIR:-$SMOKE_CALLER_HOME/.grok/bin}:$SMOKE_CALLER_HOME/.opencode/bin"
  # Those binaries still belong to the caller; the sandbox must not auto-update them.
  export DISABLE_AUTOUPDATER=1 MUSE_NO_AUTO_UPDATE=1 MUSE_LAUNCHER_INSTALL=0 OPENCODE_DISABLE_AUTOUPDATE=1
  # The harnesses installed here whose login worker.auth_ok confirms, as it does before a
  # turn: the one harness with its login the suite needs (check 3).  A failed, silent or late
  # answer confirms nothing, and a settings file with no key in it is no login.
  SMOKE_LOGINS=$(PYTHONPATH="$REPO" python3 - <<'PY'
import shutil
from agentkit import worker
for harness, binary in (("claude", "claude"), ("codex", "codex"), ("muse", "muse"),
                        ("grokbuild", "grok"), ("opencode", "opencode"), ("antigravity", "agy")):
    if shutil.which(binary) and worker.auth_ok(harness)[0]:
        print(harness)
PY
)
  # Muse's paid probe keeps its own age. Copy its raw readings, not usage.json's
  # provider selection from the caller's config, and never write back into the host cache.
  for path in usage-meta.json usage-meta-probe.json; do
    [ ! -f "$SMOKE_CALLER_HOME/.agentkit/state/$path" ] ||
      cp -p "$SMOKE_CALLER_HOME/.agentkit/state/$path" "$HOME/.agentkit/state/$path"
  done
}
smoke_source() {   # smoke_source <caller's file>: 0 to borrow it, 1 when nothing is there
  # A file this user cannot read, or cannot reach through a directory or a link, is there and
  # broken, not absent: it ends the suite rather than letting another harness pass without it.
  local dir=$1
  [ -f "$1" ] && [ -r "$1" ] && return 0
  while [ ! -e "$dir" ] && [ ! -L "$dir" ] && [ "$dir" != "${dir%/*}" ]; do dir=${dir%/*}; dir=${dir:-/}; done
  [ "$dir" != "$1" ] && [ -e "$dir" ] && { [ ! -d "$dir" ] || [ -x "$dir" ]; } && return 1
  echo "smoke: cannot read $1" >&2; exit 1
}
smoke_sync_logins() {
  # A harness may rename over its credential link. Return only valid, newer token pairs,
  # never a failed refresh's cleared login, before either exit path removes the sandbox.
  python3 "$REPO/tests/merge_logins.py" "$WORK/home" "${SMOKE_CLAUDE_CREDS:-}" "${SMOKE_GROK_AUTH:-}"
}
# A bounded way to refresh the real Claude fixture without running the GitHub merge check.
# The caller supplies an isolated HOME and output directory when outside writes are forbidden.
if [ "${1:-}" = --claude-stream ]; then
  [ $# = 2 ] || { echo "usage: tests/smoke.sh --claude-stream <out-dir>" >&2; exit 2; }
  STREAM=$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' "$2")
  STREAM_HOME=$(mktemp -d "${TMPDIR:-/tmp}/ak-smoke-stream-XXXXXX") || exit 1
  trap 'rc=$?; WORK="$STREAM_HOME" smoke_sync_logins || exit 1
        rm -rf -- "$STREAM_HOME"; exit "$rc"' EXIT
  WORK="$STREAM_HOME" smoke_home
  mkdir -p -- "$STREAM/workspace"
  printf 'Say STREAM_READY, then use Bash to run pwd, then reply DONE. Do not edit files.\n' >"$STREAM/prompt.txt"
  python3 "$REPO/tests/check_claude_stream.py" "$STREAM/out" \
    ak worker opus "$STREAM/prompt.txt" --workspace "$STREAM/workspace" \
    --role executor-scratch --out "$STREAM/out"
  exit $?
fi
usage_fresh_check() {
  PYTHONPATH="$REPO" python3 - <<'PY'
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from unittest.mock import patch

from agentkit import config, menu, muse_usage, notify, orch, run, terminal, usage, watch

with tempfile.TemporaryDirectory(prefix=".usage-fresh-", dir=config.REPO) as tmp, ExitStack() as stack:
    root = Path(tmp)
    for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
        stack.enter_context(patch.object(config, name, root / name.lower()))
    config.ensure_dirs()
    cfg = config.load()
    now = [1000000.0]
    stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: now[0]))
    # Keep the watch entry point real, including its write and GitHub-failure paths.
    passes = {}
    for module, name in ((watch, "health"), (notify, "retry_pending"), (notify, "tick_cards"),
                         (run, "schedule_gc"), (orch, "stamp"), (orch, "sweep"),
                         (watch.browser, "tidy")):
        passes[name] = stack.enter_context(patch.object(module, name))
    stack.enter_context(patch.object(run, "run_dirs", return_value=[]))
    stack.enter_context(patch.object(watch, "gh_json", return_value=(None, "offline fixture")))

    def meter(name, used):
        return {"name": name, "used": used, "resets_at": now[0] + 604800,
                "window_secs": 604800}

    meters = {"claude": [meter("weekly_all", 8), meter("weekly_scoped", 9)],
              "codex": [meter("weekly", 45)]}
    calls = []
    credits, accept_reset = [2], [True]

    def adapter(argv, **kwargs):
        harness, verb = Path(argv[0]).stem, argv[1]
        calls.append((harness, verb))
        if harness == "grokbuild":
            assert verb == "usage", argv
            return subprocess.CompletedProcess(argv, 0, json.dumps(
                {"provider": "xai", "meters": [], "error": None,
                 "none": "no meter: smoke fake"}))
        if harness == "opencode":
            assert verb == "usage", argv
            return subprocess.CompletedProcess(argv, 0, json.dumps(
                {"provider": "mimo", "meters": [], "error": None,
                 "none": "no meter: smoke fake"}))
        if harness == "antigravity":
            assert verb == "usage", argv
            return subprocess.CompletedProcess(argv, 0, json.dumps(
                {"provider": "google", "meters": [meter("gemini-weekly", 8)], "error": None}))
        assert harness in meters and verb in ("usage", "reset-status", "reset"), argv
        if verb == "reset":
            assert harness == "codex" and credits[0] > 0, argv
            if accept_reset[0]:
                credits[0] -= 1
                meters[harness][0]["used"] = 5
            data = {"code": "reset" if accept_reset[0] else "unavailable",
                    "available": credits[0], "weekly_used": meters[harness][0]["used"]}
        else:
            data = {"meters": meters[harness]} if verb == "usage" else {"available": credits[0]}
        return subprocess.CompletedProcess(argv, 0, json.dumps(data))

    stack.enter_context(patch.object(usage.subprocess, "run", side_effect=adapter))
    # This is the real Muse probe cache, with only the paid request replaced. Reading the
    # adapter every tick must not change its timestamp or issue another model request.
    def muse_adapter(argv):
        assert Path(argv[0]).stem == "muse" and argv[1] == "usage", argv
        return subprocess.CompletedProcess(argv, 0, json.dumps(muse_usage.cached()))

    stack.enter_context(patch.object(usage.usage_probe, "capture", side_effect=muse_adapter))
    paid = stack.enter_context(patch.object(muse_usage, "fresh", side_effect=lambda:
        muse_usage.result([meter("weekly", 100)])))
    probe_cache = config.STATE / "usage-meta-probe.json"
    muse_usage.save(probe_cache, muse_usage.result([meter("weekly", 40)]))
    probe_before = probe_cache.read_bytes()
    cache = config.STATE / "usage.json"
    cache.write_text(json.dumps({"fetched_at": now[0] - 8 * 3600, "providers": {
        "anthropic": {"meters": [meter("weekly_all", 9), meter("weekly_scoped", 9)]}}}))

    def lines(width=100):
        return [re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
                for line in menu.usage_lines(cfg, width)]

    def tick(dry=False):
        with redirect_stdout(io.StringIO()) as output:
            assert watch.main(["--dry-run"] if dry else []) == 0
        said = output.getvalue()
        assert "offline fixture" in said, said      # the fake GitHub, skipped and named
        return said

    # No reading is a dash and the words that say why; a meter read beside an error keeps
    # its bar and gains a `?` with the adapter's own reason. No row says how old its reading
    # is, and on a phone the bar gives way first and then each note that will not fit gives
    # way on its own, never taking a shorter one with it (v5c).
    before = cache.read_bytes()
    for prov, tail40, tail100 in ((None, "—  no reading yet", "—  no reading yet"),
                       ({}, "—  no reading yet", "—  no reading yet"),
                       ({"meters": [], "fetched_at": None}, "—  no reading yet", "—  no reading yet"),
                       ({"meters": [meter("weekly", 40)], "error": "offline", "fetched_at": None},
                        "60% left · ? offline", "? offline"),
                       ({"meters": [{**meter("weekly", 40), "resets_at": now[0] - 1}],
                         "fetched_at": now[0] - 600}, "—  window reset", "—  window reset")):
        if prov is None:
            cache.unlink()
        else:
            cache.write_text(json.dumps({"fetched_at": now[0], "providers": {"meta": prov}}))
        for width, tail in ((40, tail40), (100, tail100)):
            assert lines(width)[3].startswith("  Muse ") and lines(width)[3].endswith(tail), lines(width)
            assert terminal.cells(lines(width)[3]) <= width, lines(width)
    cache.write_bytes(before)
    assert lines()[0] == "  usage left", lines()   # eight hours old, and silent on it
    before = cache.read_bytes()
    tick(dry=True)
    assert cache.read_bytes() == before and not calls and paid.call_count == 0
    tick()
    fresh = json.loads(cache.read_text())
    assert fresh["fetched_at"] == now[0], fresh
    assert fresh["providers"]["openai"]["meters"][0]["used"] == 45, fresh
    assert fresh["providers"]["meta"]["fetched_at"] == 1000000, fresh
    for width in (40, 100):
        screen = lines(width)
        assert screen[0] == "  usage left", screen
        # the shared week, weekly_all, and never Fable's own cap of 91% (v5c)
        assert re.search(r"Claude\s+[█░]+\s+92% left", screen[1]), screen
        # one column of bars, as wide as the row with the least room can afford
        bar = 6 if width == 40 else 12
        assert screen[1].count("█") + screen[1].count("░") == bar, screen
        assert screen[1].count("█") == round(bar * 92 / 100), screen
        assert all(terminal.cells(line) <= width for line in screen), screen
        assert screen[1].endswith("Fable 91%"), screen   # the short note fits on a phone too
        if width == 100:
            assert re.search(r"92% left · resets \w+ \d\d:\d\d · Fable 91%$", screen[1]), screen
    assert paid.call_count == 0 and probe_cache.read_bytes() == probe_before
    # Three minutes later the tick is past the minute's cadence: it reads both free meters
    # again and updates the menu from those reads; Muse's paid cache stays put.
    now[0] += 180
    meters["codex"][0]["used"] = 44
    tick()
    assert calls.count(("claude", "usage")) == calls.count(("codex", "usage")) == 2, calls
    assert json.loads(cache.read_text())["fetched_at"] == now[0]
    assert re.search(r"ChatGPT\s+[█░]+\s+56%", lines()[5]), lines()
    assert paid.call_count == 0 and probe_cache.read_bytes() == probe_before
    # Inside usage.PROBE_EVERY the tick asks no adapter anything: one cadence, host-wide, so
    # it re-assembles the snapshot off the reading already in it.
    now[0] += usage.PROBE_EVERY - 1
    meters["codex"][0]["used"] = 43
    tick()
    assert calls.count(("claude", "usage")) == calls.count(("codex", "usage")) == 2, calls
    assert json.loads(cache.read_text())["fetched_at"] == now[0]
    assert re.search(r"ChatGPT\s+[█░]+\s+56%", lines()[5]), lines()
    # Rendering never updates the snapshot, and never says how old it is.
    now[0] += 300
    assert lines()[0] == "  usage left", lines()
    assert json.loads(cache.read_text())["fetched_at"] == now[0] - 300
    # One second short of Muse's own ten minutes the tick asks its adapter, which answers out
    # of its cache: no model request, and the row carries the reading it has and no age.
    now[0] = 1000000 + muse_usage.CACHE_TTL - 1
    tick()
    assert paid.call_count == 0 and probe_cache.read_bytes() == probe_before
    for width in (40, 100):
        screen = lines(width)
        assert screen[0] == "  usage left", screen
        assert re.search(r"Muse\s+[█░]+\s+60%", screen[3]), screen
        assert "old" not in screen[3], screen
        assert all(terminal.cells(line) <= width for line in screen), screen
    # The next tick past the host's cadence finds that cache past its ten minutes, and spends
    # the one request.
    now[0] += usage.PROBE_EVERY
    tick()
    assert paid.call_count == 1, paid.call_count
    assert json.loads(probe_cache.read_text())["fetched_at"] == now[0]
    assert re.search(r"Muse\s+[█░]+\s+0%", lines()[3]), lines()
    assert "old" not in lines()[3], lines()
    now[0] += 180
    tick()
    assert paid.call_count == 1, paid.call_count
    # From here on the probe cadence is out of the way: what the rest of this check is about is
    # the reset policy's own clock and the row's words, and both want a reading per tick. The
    # cadence itself is checked above and in tests/test_usage_probe.py.
    stack.enter_context(patch.object(usage, "PROBE_EVERY", 0))
    # With no shared week reported there is no provider percentage to draw: Fable's own cap
    # is never shown as Claude's, whatever the row would otherwise have said.
    meters["claude"] = [meter("weekly_scoped", 9)]
    tick()
    assert lines()[1].split() == ["Claude", "—", "no", "shared", "week"], lines()
    # Failed free reads say so, never the previous allowance stamped as fresh.
    meters["claude"] = []
    tick()
    assert lines()[1].endswith("—  no reading yet") and "57% left" in lines()[5], lines()
    assert paid.call_count == 1

    # Watch is read-only, but ordinary consumers still exercise the real reset policy from
    # a continually refreshed cache. Refusals retain the five-minute retry interval too.
    meters["claude"] = [meter("weekly_all", 8), meter("weekly_scoped", 9)]
    meters["codex"][0]["used"] = 95
    tick()
    assert ("codex", "reset") not in calls, calls
    before = json.loads(cache.read_text())["fetched_at"]
    providers = usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 1 and credits[0] == 1, calls
    assert providers["openai"]["meters"][0]["used"] == 5, providers
    assert providers["openai"]["headroom"] == 1.95, providers
    assert json.loads(cache.read_text())["fetched_at"] == before
    checked = json.loads(cache.read_text())["reset_checked_at"]
    # Repeated reads at 100% cannot spend a second credit inside the daily cap. Once it
    # expires, a headless consumer restores eligibility. Watch cannot move the policy clock.
    for _ in range(10):
        now[0] += 180
        meters["codex"][0]["used"] = 100
        tick()
        assert json.loads(cache.read_text())["reset_checked_at"] == checked
        usage.collect(cfg)
        checked = json.loads(cache.read_text())["reset_checked_at"]
        assert calls.count(("codex", "reset")) == 1, calls
    now[0] += usage.RESET_EVERY_SECS
    tick()
    providers = usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 2 and credits[0] == 0, calls
    assert not providers["openai"]["exhausted"] and providers["openai"]["headroom"] == .95

    (config.STATE / "openai-reset.json").unlink()
    credits[0], accept_reset[0] = 2, False
    meters["codex"][0]["used"] = 95
    now[0] += usage.CACHE_TTL + 1
    tick()
    usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 3, calls
    now[0] += 180
    tick()
    for _ in range(3):
        usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 3, calls
    now[0] += usage.CACHE_TTL - 179
    tick()
    usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 4 and credits[0] == 2, calls
    # Expiring the snapshot after a warm policy check must not shorten a refusal's cooldown.
    now[0] += 180
    tick()
    now[0] += 121
    usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 5, calls
    now[0] += 180
    usage.collect(cfg)     # snapshot is 301s old, but the policy check is only 180s old
    assert calls.count(("codex", "reset")) == 5, calls
    now[0] += 121
    usage.collect(cfg)
    assert calls.count(("codex", "reset")) == 6, calls
    # A watch tick with no pre-existing snapshot must also leave a normal read eligible.
    cache.unlink()
    accept_reset[0] = True
    tick()
    assert json.loads(cache.read_text())["reset_checked_at"] == 0
    assert calls.count(("codex", "reset")) == 6, calls
    assert usage.collect(cfg)["openai"]["meters"][0]["used"] == 5
    assert calls.count(("codex", "reset")) == 7 and credits[0] == 1, calls

    # A bad provider response cannot delay finished-run delivery, inbox questions or GC.
    finished = config.RUNS / "finished"
    finished.mkdir()
    for error in (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError):
        receipt = {"state": "pass", "notification_pending": True,
                   "pending_inbox": {"question": "Fixture question", "url": "fixture", "sha": "abc"}}
        run.save_state(finished, receipt)
        for mock in passes.values():
            mock.reset_mock()
        before = cache.read_bytes()
        with patch.object(usage, "collect", side_effect=error("bad usage")), \
                patch.object(run, "run_dirs", return_value=[finished]), \
                patch.object(run, "reap", side_effect=lambda d, state: state), \
                patch.object(run, "announce") as announce, \
                patch.object(watch, "inbox", return_value="inbox"), \
                patch.object(notify, "shaped", return_value=0) as question:
            assert "WARN the usage refresh did not finish" in tick()
            announce.assert_called_once()
            question.assert_called_once()
        assert "pending_inbox" not in run.read_state(finished)
        assert cache.read_bytes() == before
        for name in ("schedule_gc", "stamp", "sweep"):
            passes[name].assert_called_once()
print("PASS  41 watch refresh: correct meters, Muse probe interval, no age, independent reset policy, dry-run and failure isolation")
PY
}
session_state_check() {
  PYTHONPATH="$REPO" python3 - <<'PY'
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from agentkit import config, menu, notify, orch, run, terminal, usage, watch


class SessionState(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix=".session-state-", dir=config.REPO)))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(root),
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_DISCORD_WEBHOOK": "",
            notify.SINK_ENV: "",   # this fixture is the one naming the destination
            "AGENTKIT_DISCORD_USER_ID": "", config.SESSION_ENV: "seat"}))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "seat", "astra", ["opus"])
        self.now = 1000000.0
        self.stack.enter_context(patch.object(notify.time, "time", lambda: self.now))
        self.seat = {"name": "seat", "attached": False, "exited": False,
                     "created": self.now - 60, "path": str(root)}
        self.seats = [self.seat]
        # this seat's harness is Codex, so the chrome under the composer is Codex's own: what
        # counts as chrome is adapters/<harness>.toml's to say, and only that harness's
        self.pane = "Read the patch\nMay I merge?\n›\ngpt-6-astra default · ~"
        self.stack.enter_context(patch.object(orch, "sessions", lambda: self.seats))
        self.stack.enter_context(patch.object(orch, "listing", lambda *_a, **_k: self.seats))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "inside", return_value=True))
        self.stack.enter_context(patch.object(notify, "_attempt", side_effect=self.deliver))
        self.close_needs = notify.close_needs
        self.edits = self.stack.enter_context(patch.object(notify, "close_needs", return_value=[]))
        for module, name in ((usage, "collect"), (run, "schedule_gc"),
                             (orch, "stamp"), (orch, "sweep"), (watch.browser, "tidy")):
            self.stack.enter_context(patch.object(module, name))
        self.stack.enter_context(patch.object(run, "run_dirs", return_value=[]))
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=(None, "offline")))
        # No command, network request or actual attach may escape this fixture; the title's
        # version lookup is stubbed the way the seat listing is (v5c).
        self.stack.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("subprocess")))
        self.stack.enter_context(patch.object(menu, "installed", return_value="abc1234 · 12 Jan"))
        self.stack.enter_context(patch.object(notify.urllib.request, "urlopen",
                                             side_effect=AssertionError("network")))
        self.notice("needs", "May I merge?")

    def tmux(self, *args, **kwargs):
        self.assertEqual(kwargs.get("socket"), "agentkit-test")
        # set-option is the seat's own status bar and title being told the word the row shows:
        # observation, not acknowledgement, and on agentkit's own socket like everything here.
        self.assertIn(args[0], ("capture-pane", "switch-client", "rename-session",
                                "set-environment", "set-option", "list-clients", "list-sessions"))
        return 0, self.pane if args[0] == "capture-pane" else ""

    def deliver(self, event):
        event.update(status="delivered", receipt={"message_id": "123", "webhook":
            hashlib.sha256(b"https://discord.example/hook?thread_id=42").hexdigest()})
        notify._write_event(event)
        return 0

    def notice(self, kind, text):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(notify.shaped(kind, text, session=self.seat["name"]), 0)

    def open(self):
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True):
            self.assertEqual(orch.attach(self.seat["name"], wait=True), 0)

    def tick(self, dry=False):
        with redirect_stdout(io.StringIO()) as said:
            self.assertEqual(watch.main(["--dry-run"] if dry else []), 0)
        self.assertIn("PR checks skipped", said.getvalue())

    def saved(self):
        return config.notify_path(self.seat["name"]).read_bytes()

    def test_a_attached_without_subsequent_progress_stays_needs_you(self):
        self.now += 1
        self.open()
        self.seat["attached"] = True
        before = self.saved()
        self.now += 30
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.seat["attached"] = False
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertEqual(self.saved(), before)
        self.edits.assert_not_called()

    def test_b_open_then_fresh_progress_clears_the_notice_and_edits_discord_once(self):
        self.now += 1
        self.open()
        self.now += 1
        self.pane = "Merging the approved patch\n›"
        self.tick()
        # the question is answered, and the row says what the seat is now: his again,
        # at its prompt with nothing to say why
        self.assertEqual(menu.state(self.seat), "needs you")
        facts = notify.last("seat", include_seen=True)
        self.assertLessEqual(facts["time"], facts["opened_at"])
        self.assertLess(facts["opened_at"], facts["last_progress_at"])
        self.assertNotIn("seen", facts)
        self.edits.assert_called_once()
        self.assertEqual(self.edits.call_args.args[1], "Answered")
        before = self.saved()
        for attached in (True, False, True):
            self.seat["attached"] = attached
            self.tick()
            self.assertEqual(menu.state(self.seat), "needs you")
        self.assertEqual(self.saved(), before)

    def test_c_list_render_capture_and_watch_never_acknowledge(self):
        self.open()
        before = self.saved()
        renders = []
        with patch.object(notify, "clear", side_effect=AssertionError("acknowledged")):
            for _ in range(2):
                with redirect_stdout(io.StringIO()) as output:
                    orch.cmd_list([])
                    menu.draw(self.cfg, self.seats)
                renders.append(output.getvalue())
                watch.pane_text(self.seat)
                self.tick()
                self.tick(dry=True)
        self.assertEqual(renders[0], renders[1])
        self.assertIn("needs you", renders[0])
        self.assertEqual(self.saved(), before)

    def test_d_background_or_transient_attach_without_progress_never_clears(self):
        before = self.saved()
        with patch("sys.stdin.isatty", return_value=False), redirect_stdout(io.StringIO()):
            orch.attach("seat")    # even inside tmux, a headless caller cannot open the seat
        self.assertEqual(self.saved(), before)
        self.seat["attached"] = True
        self.pane += "\nOutput before any interactive open"
        self.tick()
        self.assertEqual(self.saved(), before)
        self.open()
        self.seat["attached"] = False
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")

    def test_e_done_supersedes_open_needs_even_at_the_same_timestamp(self):
        self.open()
        self.notice("done", "Merged and verified")
        before = self.saved()
        self.pane = "Finished"
        self.tick()
        self.assertEqual(menu.state(self.seat), "done")
        self.assertEqual(self.saved(), before)
        self.open()
        self.tick()
        self.assertEqual(menu.state(self.seat), "done")
        self.now += 1
        self.pane = "Starting the next task"
        self.tick()
        self.assertEqual(menu.state(self.seat), "done")   # output after an open answers no done

    def test_f_failed_usage_is_dash_and_real_zero_used_is_100_percent(self):
        def meter(used):
            return {"name": "weekly", "used": used, "window_secs": 604800,
                    "resets_at": self.now + 604800}
        def row(prov):
            (config.STATE / "usage.json").write_text(json.dumps(
                {"fetched_at": self.now, "providers": {"openai": prov}}))
            line = terminal.plain(menu.usage_lines(self.cfg, 100)[5])
            # the reset time is this machine's clock; the row's own words are what this reads
            return re.sub(r" · resets \w+ \d\d:\d\d", "", line).split()
        def dash(why):   # no reading is `—` and the words that say why (v5c)
            return ["ChatGPT", "—", *why.split()]
        for data, rc, expected in (({"meters": [meter(0)]}, 1, dash("not reached")),
                                   ({"meters": [meter(100)]}, 1, dash("not reached")),
                                   # a meter read beside an error keeps its bar and gains a `?`
                                   ({"meters": [meter(0)], "error": "failed"}, 0,
                                    ["ChatGPT", "█" * 12, "100%", "left", "·", "?", "failed"]),
                                   ({}, 0, dash("no reading yet")),
                                   ({"meters": []}, 0, dash("no reading yet")),
                                   ({"meters": "broken"}, 0, dash("not reached")),
                                   ([], 0, dash("not reached")),
                                   ({"meters": [meter(float("nan"))]}, 0, dash("bad reading")),
                                   ({"meters": [meter(float("inf"))]}, 0, dash("bad reading")),
                                   ({"meters": [meter(None)]}, 0, dash("bad reading"))):
            with self.subTest(data=data, rc=rc), patch.object(usage, "_resets", return_value=0), \
                    patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], rc, json.dumps(data))):
                self.assertEqual(row(usage._probe(self.cfg, "openai", self.now)), expected)
        with patch.object(config, "adapter", side_effect=config.Error("adapter missing")):
            self.assertEqual(row(usage._probe(self.cfg, "openai", self.now)), dash("not reached"))
        for empty in ("", "not JSON"):
            with patch.object(usage, "_resets", return_value=0), \
                    patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, empty)):
                self.assertEqual(row(usage._probe(self.cfg, "openai", self.now)), dash("not reached"))
        for failure in (OSError("missing adapter"), subprocess.TimeoutExpired("usage", 30)):
            with patch.object(usage, "_resets", return_value=0), \
                    patch.object(subprocess, "run", side_effect=failure):
                self.assertEqual(row(usage._probe(self.cfg, "openai", self.now)), dash("not reached"))
        for used, expected in ((0, "100%"), (-10, "100%"), (120, "0%")):
            with patch.object(usage, "_resets", return_value=0), \
                    patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps({"meters": [meter(used)]}))):
                self.assertIn(expected, row(usage._probe(self.cfg, "openai", self.now)))

    def test_legacy_notice_without_time_requires_open_and_later_progress(self):
        for stamp in (None, "unknown", True):
            with self.subTest(stamp=stamp):
                notice = {"kind": "needs", "text": "An older question"}
                if stamp is not None:
                    notice["time"] = stamp
                config.notify_path("seat").write_text(json.dumps(notice))
                self.pane = "An older question"
                self.open()
                self.tick()
                self.assertEqual(menu.state(self.seat), "needs you")
                self.assertEqual(notify.last("seat")["time"], self.now)
                self.pane = "Progress after the answer"
                self.tick()
                self.assertEqual(menu.state(self.seat), "needs you")

    def test_two_quick_opens_keep_the_first_baseline(self):
        self.open()
        before = self.saved()
        self.pane = "Resuming after the answer"
        self.open()
        self.assertEqual(self.saved(), before)
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")

    def test_new_needs_requires_its_own_open_and_progress(self):
        self.open()
        self.pane = "Progress on the first decision"
        self.notice("needs", "Another decision?")
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertNotIn("opened_at", notify.last("seat"))

    def test_exit_and_login_outrank_needs_without_acknowledging_it(self):
        self.open()
        before = self.saved()
        self.seat["exited"] = True
        self.pane = "Process exited"
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertEqual(self.saved(), before)
        state = watch.load_state()
        state["stalls"]["seat"] = {"status": "needs login"}
        watch.save_state(state)
        self.assertEqual(menu.state(self.seat), "needs you")

    def test_rename_moves_open_facts_and_stop_latch_without_old_name_resurrection(self):
        self.open()
        state = watch.load_state()
        state["stalls"]["seat"] = {"told": self.now, "since": self.now - 4000}
        watch.save_state(state)
        stale = copy.deepcopy(state)
        before = self.saved()
        self.assertEqual(orch.rename("seat", "renamed"), "renamed")
        self.seat["name"] = "renamed"
        self.assertEqual(self.saved(), before)
        watch.save_state(stale)
        self.assertNotIn("seat", watch.load_state()["stalls"])
        self.assertIn("renamed", watch.load_state()["stalls"])
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.pane = "Continuing in the renamed seat"
        self.now += 1
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertFalse(config.notify_path("seat").exists())

    def test_corrupt_generations_cannot_interrupt_rename_or_restore_old_stalls(self):
        state = {"stalls": {"seat": {"told": self.now, "since": self.now - 4000}},
                 "seen_at": {"seat": "broken", "null": None, "boolean": True,
                             "list": [], "object": {}, "negative": -1,
                             "nan": float("nan"), "infinity": float("inf"),
                             "huge": 10 ** 400, "limit": float.fromhex("0x1.fffffffffffffp+1023")}}
        watch.state_path().write_text(json.dumps(state))
        before = self.saved()
        orch.rename("seat", "renamed")
        self.seat["name"] = "renamed"
        watch.save_state(state)   # a tick carrying the corrupt pre-rename snapshot
        saved = watch.load_state()
        self.assertNotIn("seat", saved["stalls"])
        self.assertIn("renamed", saved["stalls"])
        self.assertTrue(all(watch.generation(v) == v for v in saved["seen_at"].values()))
        self.assertGreater(saved["seen_at"]["renamed"], 0)
        self.assertEqual(self.saved(), before)
        self.assertFalse(config.notify_path("seat").exists())

    def test_watcher_retracts_only_its_own_alert_and_preserves_newer_intent(self):
        text = "The watcher needs login"
        notify.shaped("needs", text, session="seat", event_id="auth:seat:codex:1")
        self.assertTrue(notify.last("seat")["watcher"])
        watch.forget("seat", acknowledge=False, notice=text)
        # the alert is retracted; nobody has opened this seat, so its own screen speaks for it
        self.assertEqual(menu.state(self.seat), "needs you")
        self.edits.assert_called_once()
        for kind in ("needs", "done"):
            self.now += 1
            self.notice(kind, "The orchestrator's latest intent")
            before = self.saved()
            self.edits.reset_mock()
            watch.forget("seat", acknowledge=False, notice=text)
            self.assertEqual(self.saved(), before)
            self.assertFalse(notify.last("seat")["watcher"])
            self.edits.assert_not_called()

    def test_chrome_input_blank_capture_and_viewport_resize_are_not_progress(self):
        self.open()
        for pane in ("Read the patch\nMay I merge?\n› yes\ngpt-6-astra default · ~/code", "",
                     "May I merge?\n›", "Earlier history\nRead the patch\nMay I merge?\n›"):
            self.pane = pane
            self.tick()
            self.assertEqual(menu.state(self.seat), "needs you")
        self.edits.assert_not_called()

    def test_failed_open_capture_needs_a_baseline_before_resolving(self):
        self.pane = ""
        self.open()
        self.pane = "May I merge?"
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.pane = "Now merging"
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")

    def test_needs_you_never_receives_a_resume_nudge(self):
        self.pane = "Selected model is at capacity"
        for _ in range(3):
            self.now += watch.GIVE_UP
            self.tick()             # the fake tmux rejects all send-keys calls
        self.open()
        self.now += watch.GIVE_UP
        self.tick()
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertFalse(watch.type_into(self.seat, "continue", lambda _: None))
        for invalid_tag in ("true", 1, {}, None):
            notice = notify.last("seat")
            notice["watcher"] = invalid_tag
            config.notify_path("seat").write_text(json.dumps(notice))
            self.assertFalse(watch.type_into(self.seat, "continue", lambda _: None))

    def test_done_racing_progress_is_the_final_intent(self):
        self.open()
        captured, release, posting = threading.Event(), threading.Event(), threading.Event()
        def capture():
            captured.set()
            self.assertTrue(release.wait(5))
            return "Resuming"
        def done():
            posting.set()
            self.notice("done", "All verified")
        with ThreadPoolExecutor(max_workers=2) as pool:
            progress = pool.submit(notify.progress, "seat", capture)
            try:
                self.assertTrue(captured.wait(5))
                finished = pool.submit(done)
                self.assertTrue(posting.wait(5))
            finally:
                release.set()
            progress.result(timeout=5)
            finished.result(timeout=5)
        self.assertEqual(menu.state(self.seat), "done")
        self.assertNotIn("opened_at", notify.last("seat"))

    def test_cron_start_preserves_notice_until_a_new_notify(self):
        self.seats = []
        before = self.saved()
        with patch.object(orch, "select", return_value=("astra", "fixture", ["opus"])), \
                patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch"), \
                patch.object(notify, "clear", side_effect=AssertionError("acknowledged")):
            self.assertTrue(orch.ensure(self.cfg, "seat", lambda _: None))
        self.assertEqual(self.saved(), before)
        self.notice("needs", "The new question")
        self.assertEqual(notify.last("seat")["text"], "The new question")

    def test_writer_waiting_on_a_rename_follows_the_live_name(self):
        waiting, owner = threading.Event(), threading.get_ident()
        flock = notify.fcntl.flock
        writes = []
        def locking(fd, mode):
            if mode == notify.fcntl.LOCK_EX and threading.get_ident() != owner:
                waiting.set()
            return flock(fd, mode)
        with ThreadPoolExecutor(max_workers=1) as pool:
            def tmux(*args, **kwargs):
                if args[0] == "rename-session":
                    writes.append(pool.submit(notify.opened, "seat", lambda: "May I merge?"))
                    self.assertTrue(waiting.wait(5))
                return self.tmux(*args, **kwargs)
            with patch.object(notify.fcntl, "flock", side_effect=locking), \
                    patch.object(orch, "tmux_out", side_effect=tmux):
                orch.rename("seat", "renamed")
                writes[0].result(timeout=5)
        self.assertFalse(config.notify_path("seat").exists())
        self.assertEqual(notify.last("renamed")["opened_pane"], "May I merge?")
        self.assertEqual(menu.state({"name": "renamed"}), "needs you")

    def test_discord_ping_once_edit_answered_and_late_receipt_cannot_reopen(self):
        event = json.loads(next(notify.outbox().glob("*.json")).read_text())
        self.notice("needs", "May I merge?")
        self.assertEqual(len(list(notify.outbox().glob("*.json"))), 1)
        with patch.object(notify, "close_needs", wraps=self.close_needs), \
                patch.object(notify, "_secret", return_value="https://discord.example/hook?thread_id=42"), \
                patch.object(notify.urllib.request, "urlopen") as request:
            self.open()
            self.tick()
            request.assert_not_called()
            self.pane = "Merging now"
            self.tick()
            self.tick()
            request.assert_called_once()
            sent = request.call_args.args[0]
            self.assertEqual(sent.method, "PATCH")
            self.assertEqual(sent.full_url, "https://discord.example/hook/messages/123?thread_id=42")
            payload = json.loads(sent.data)
            self.assertEqual(payload["embeds"][0]["title"], "Answered · seat")
            self.assertEqual(payload["content"], "")
            self.assertEqual(payload["allowed_mentions"], {"parse": []})
            self.assertNotIn("fields", payload["embeds"][0])
            before = self.saved()
            notify._remember_retry(event, "seat")
            self.assertEqual(self.saved(), before)
            self.assertEqual(menu.state(self.seat), "needs you")
        self.assertEqual(notify.last("seat", include_seen=True)["open_needs"], [])


unittest.main(verbosity=2)
PY
}
seat_state_check() {
  # (a)-(h) are tests/test_v4y.py, offline on fixtures and fake hook facts, so they can be run
  # on their own as every other suite here can; (g) and (i) are the shell's own below.
  local rc=0 d
  python3 "$REPO/tests/test_v4y.py" || rc=1

  # (g) a hook writes nothing for a worker, or for a call with no seat to write for
  d=$(mktemp -d "$REPO/.seat-hook.XXXXXX") || return 1
  for env_args in "AGENTKIT_SESSION=seat AK_RUN_ROLE=worker" "AK_RUN_ROLE=orchestrator"; do
    # shellcheck disable=SC2086
    printf '{"hook_event_name":"Stop","session_id":"x"}' |
      env -i PATH="$PATH" HOME="$d" IDLE_COMPACT_STATE= $env_args \
        bash "$REPO/hooks/seat-state.sh" || rc=1
  done
  [ -z "$(ls -A "$d/.agentkit/state" 2>/dev/null)" ] || { echo "(g) a hook wrote state it may not" >&2; rc=1; }
  # ... and writes exactly one fact for a seat that may have one
  printf '{"hook_event_name":"Notification","notification_type":"permission_prompt","message":"Claude needs your permission to use Bash"}' |
    env -i PATH="$PATH" HOME="$d" IDLE_COMPACT_STATE= AGENTKIT_SESSION=seat \
      bash "$REPO/hooks/seat-state.sh" || rc=1
  python3 - "$d/.agentkit/state/hook-seat.json" <<'HOOKPY' || rc=1
import json, sys
fact = json.load(open(sys.argv[1]))
assert fact["event"] == "Notification" and fact["kind"] == "permission_prompt", fact
assert fact["session"] == "seat" and isinstance(fact["at"], (int, float)), fact
assert fact["text"].startswith("Claude needs your permission"), fact
HOOKPY

  # (i) every adapter's hooks verb is idempotent, and says what it did
  for h in claude codex muse; do
    HOME="$d" "$REPO/adapters/$h.sh" hooks >"$d/$h.1" 2>&1 || rc=1
    HOME="$d" "$REPO/adapters/$h.sh" hooks >"$d/$h.2" 2>&1 || rc=1
  done
  grep -q 'already runs hooks/seat-state.sh' "$d/claude.2" || { echo "(i) claude.sh hooks is not idempotent" >&2; rc=1; }
  python3 - "$d/.claude/settings.json" <<'IDEMPY' || rc=1
import json, sys
hooks = json.load(open(sys.argv[1]))["hooks"]
# the seat-state hook on every event, and the end-of-turn rule beside it on Stop
for event, scripts in (("UserPromptSubmit", ["seat-state.sh"]),
                       ("Stop", ["seat-state.sh", "orchestrator-stop.sh"]),
                       ("Notification", ["seat-state.sh"])):
    entries = [e for g in hooks[event] for e in g["hooks"]]
    assert [e["command"].rsplit("/", 1)[-1] for e in entries] == scripts, (event, entries)
IDEMPY
  grep -q 'per launch by tools/codex-seat.py' "$d/codex.2" || { echo "(i) codex.sh hooks says nothing" >&2; rc=1; }
  grep -q 'no lifecycle hooks' "$d/muse.2" || { echo "(i) muse.sh hooks says nothing" >&2; rc=1; }
  # a verb with nothing to install configures nothing: only Claude's writes hooks here
  # (`codex --help`, the capability check, makes its own home; that is the harness's doing)
  [ ! -e "$d/.codex/config.toml" ] && [ ! -e "$d/.config/muse" ] ||
    { echo "(i) a no-op hooks verb wrote configuration" >&2; rc=1; }
  rm -rf -- "$d"
  return "$rc"
}

# The v4x lifecycle fixtures live here to keep changes within this task's file scope.
# All inherited cases still run. These three replacements keep the original payload,
# delivery and rename assertions, adding an open-without-progress check before recovery.
lifecycle_check() {
  PYTHONPATH="$REPO:$REPO/tests" python3 - "$1" <<'PY'
from contextlib import redirect_stdout, redirect_stderr
import copy
import io
import os
import sys
import unittest
from unittest.mock import patch

from agentkit import config, menu, notify, orch, watch
import test_notify
import test_v4l


class Notifications(test_notify.Notifications):
    def open_and_progress(self):
        before, messages = menu.state({"name": "seat"}), len(self.requests)
        with patch.object(orch, "find", return_value={"name": "seat"}), \
                patch.object(orch, "inside", return_value=True), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "pane_text", return_value="Waiting for a decision"), \
                patch("sys.stdin.isatty", return_value=True), \
                patch("sys.stdout.isatty", return_value=True):
            menu.open_session(config.load(), {"name": "seat"}, False)
        self.assertEqual(menu.state({"name": "seat"}), before)
        self.assertEqual(len(self.requests), messages)
        notify.progress("seat", lambda: "Fresh output after the answer")

    def test_lifecycle_and_approved_payload(self):
        self.cli("needs", "Merge PR #7? yes/no")
        self.assertEqual(self.requests[0][0:2], ("POST", "/hook?thread_id=42&wait=true"))
        payload = self.requests[0][2]
        self.assertEqual(payload["content"], "<@123456789012345678>")
        self.assertEqual(payload["embeds"][0]["title"], "Needs you · seat")
        self.assertEqual(payload["embeds"][0]["color"], 0xF5A623)
        before = config.notify_path("seat").read_bytes()
        result = self.cli("needs", "  MERGE\nPR   #7? YES/NO ")
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(self.requests), 1)   # same episode: recorded again, posted once
        self.assertEqual(notify.last("seat")["open_needs"][0]["message_id"], "1")
        self.assertNotIn(self.url, before.decode())

        self.cli("needs", "Which branch?")
        self.assertEqual(len(self.requests), 1)   # one card per episode, whatever it asks
        self.assertEqual(menu.state({"name": "seat"}), "needs you")
        self.open_and_progress()
        self.assertEqual(menu.state({"name": "seat"}), "needs you")
        self.assertIsNone(notify.last("seat"))
        self.assertEqual([r[1] for r in self.requests[1:]],
                         ["/hook/messages/1?thread_id=42"])
        for method, _, payload in self.requests[1:]:
            self.assertEqual(method, "PATCH")
            self.assertEqual(payload["embeds"][0]["title"], "Answered · seat")
            self.assertEqual(payload["content"], "")
            self.assertEqual(payload["allowed_mentions"], {"parse": []})
            self.assertNotIn("fields", payload["embeds"][0])

        self.cli("needs", "Which branch?")   # the word never left: still the same episode
        self.assertEqual(len(self.requests), 2)
        self.cli("done", "Shipped", "--pr", "https://github.com/me/repo/pull/7")
        self.assertEqual([r[0] for r in self.requests[-2:]], ["PATCH", "POST"])
        self.assertEqual(self.requests[-2][2]["embeds"][0]["title"], "Done · seat")
        payload = self.requests[-1][2]
        self.assertEqual(payload["content"], "<@123456789012345678>")
        self.assertEqual(payload["username"], "agentkit")
        self.assertEqual(payload["embeds"][0]["title"], "Done · seat")
        self.assertEqual(payload["embeds"][0]["color"], 0x2ECC71)
        self.assertNotIn("fields", payload["embeds"][0])   # the card is two words and the seat
        self.assertNotIn("description", payload["embeds"][0])
        self.assertEqual(notify.last("seat")["text"], "Shipped")   # the words stay on the record
        self.assertEqual(menu.state({"name": "seat"}), "done")
        count = len(self.requests)
        self.cli("done", "Another job, another summary")     # same word: the episode stands
        self.assertEqual(len(self.requests), count)
        self.open_and_progress()
        # a done is no question: opening and reading it leave it, and its episode, standing
        self.assertEqual(menu.state({"name": "seat"}), "done")
        self.cli("done", "Another job, another summary")
        self.assertEqual(len(self.requests), count)
        self.cli("needs", "One more decision?")
        self.cli("done", "Second job finished")
        self.assertEqual(len(self.requests), count + 3)

    def test_edit_failures_are_silent_and_do_not_block_completion(self):
        for status in (404, 500, 0):
            self.cli("needs", f"Question {status}?")
            self.edit_status = status
            result = self.cli("done", f"Finished anyway after {status}")   # a job apiece
            self.assertEqual((result.stdout, result.stderr), ("", ""))
            self.assertEqual([r[0] for r in self.requests[-2:]], ["PATCH", "POST"])
            self.assertEqual(notify.last("seat")["open_needs"], [])
        self.cli("needs", "A changed webhook?")
        count = len(self.requests)
        changed = self.url.replace("/hook", "/new")
        with patch.dict(os.environ, {"AGENTKIT_DISCORD_WEBHOOK": changed,
                                     notify.SINK_ENV: changed}), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            self.open_and_progress()
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertEqual(len(self.requests), count)
        self.assertIsNone(notify.last("seat"))


class Babysitter(test_v4l.Babysitter):
    def test_pruning_an_alias_preserves_the_live_seats_notice_and_latch(self):
        cfg = config.load()
        config.save_session(cfg, "old", "opus", ["astra"])
        notice = '{"kind": "needs", "text": "waiting for you"}\n'
        config.notify_path("old").write_text(notice)
        config.rename_session("old", "seat")
        self.data["stalls"] = {"old": {"since": 1, "told": 10},
                               "seat": {"since": 2, "told": 20}}
        self.data["seen_at"]["seat"] = 5
        watch.save_state(self.data)
        stale = copy.deepcopy(self.data)
        self.tick(dry=True)
        self.assertIn("old", watch.load_state()["stalls"])
        self.data = watch.load_state()
        self.tick()
        watch.save_state(self.data)
        watch.save_state(stale)
        saved = watch.load_state()
        self.assertNotIn("old", saved["stalls"])
        self.assertEqual(saved["stalls"]["seat"], {"since": 2, "told": 20})
        self.assertEqual(saved["seen_at"]["seat"], 5)
        self.assertEqual(config.notify_path("seat").read_text(), notice)
        self.assertEqual(config.resolve_session("old"), "seat")
        self.typed.assert_not_called()
        self.notified.assert_not_called()
        # Opening through an alias preserves the question until real pane progress.
        orch.seen_by_user("old")
        self.assertIn("seat", watch.load_state()["stalls"])
        self.assertEqual(watch.notify.last("seat")["kind"], "needs")
        self.assertFalse(watch.notify.last("seat").get("seen"))
        self.data = watch.load_state()
        self.tail = "Reading the next file after the answer"
        self.tick(1)
        watch.save_state(stale)
        self.assertNotIn("seat", watch.load_state()["stalls"])
        self.assertIsNone(watch.notify.last("seat"))
        self.assertTrue(watch.notify.resolved(watch.notify.last("seat", include_seen=True)))
        self.assertFalse(config.notify_path("old").exists())
        self.typed.assert_not_called()


if sys.argv[1] == "notify":
    module = test_notify
    module.Notifications = Notifications
elif sys.argv[1] == "v4l":
    module = test_v4l
    module.Babysitter = Babysitter
else:
    raise SystemExit("lifecycle_check needs notify or v4l")
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
raise SystemExit(not result.wasSuccessful())
PY
}
# The -m rule, built offline against a `codex` that only records its own argv: Codex on a
# ChatGPT subscription answers every explicit model with HTTP 400, so the model `default` --
# and an empty one -- has to leave -m off on both command lines the adapter builds, while the
# effort, which that account does take, still goes through; a real id still gets its -m.
codex_model_flag_check() {
  local d rc=0 model argv line
  d=$(mktemp -d "${TMPDIR:-/tmp}/codex-mflag-XXXXXX") || return 1
  mkdir -p -- "$d/bin" "$d/ws"
  cat >"$d/bin/codex" <<'SH'
#!/usr/bin/env bash
# one argument a line, so `-m` is matched whole and never inside somebody's value
printf '%s\n' "$@" >>"$CODEX_ARGV"
cat >/dev/null                                     # the prompt comes in on stdin
printf '{"type":"thread.started","thread_id":"t-fake"}\n'
SH
  chmod +x "$d/bin/codex"
  printf 'nothing to do\n' >"$d/prompt.txt"
  for model in default "" gpt-6-astra; do
    argv="$d/argv"; : >"$argv"
    PATH="$d/bin:$PATH" CODEX_ARGV="$argv" "$REPO/adapters/codex.sh" \
      run "$model" xhigh "$d/ws" "$d/prompt.txt" "$d/out" >/dev/null 2>&1 || rc=1
    grep -qx -- '-c' "$argv" && grep -qx -- 'model_reasoning_effort=xhigh' "$argv" || {
      echo "      run ${model:-<empty>}: no -c model_reasoning_effort in $(tr '\n' ' ' <"$argv")"; rc=1; }
    line=$(PATH="$d/bin:$PATH" "$REPO/adapters/codex.sh" interactive "$model" xhigh) || rc=1
    case $line in *"model_reasoning_effort=\"xhigh\""*) ;;
      *) echo "      interactive ${model:-<empty>}: no effort in $line"; rc=1 ;; esac
    if [ "$model" = gpt-6-astra ]; then
      # a real model id -- an API key's, which may choose one -- is still passed as -m
      grep -qx -- '-m' "$argv" && grep -qx -- 'gpt-6-astra' "$argv" || {
        echo "      run $model: no -m $model in $(tr '\n' ' ' <"$argv")"; rc=1; }
      case $line in *"--yolo -m gpt-6-astra -c "*) ;;
        *) echo "      interactive $model: no -m $model in $line"; rc=1 ;; esac
    else
      ! grep -qx -- '-m' "$argv" || {
        echo "      run ${model:-<empty>}: -m is still there in $(tr '\n' ' ' <"$argv")"; rc=1; }
      case $line in *" -m "*) echo "      interactive ${model:-<empty>}: -m is still there in $line"; rc=1 ;; esac
    fi
  done
  # The shipped OpenAI worker uses that sentinel; the caller may pin an API model instead.
  mkdir -p -- "$d/home/.agentkit"
  cp "$REPO/config.default.toml" "$d/home/.agentkit/config.toml" || rc=1
  HOME="$d/home" PYTHONPATH="$REPO" python3 - <<'PY' || rc=1
from agentkit import config
cfg = config.load()
astra = config.model(cfg, "astra")
assert astra["model"] == config.DEFAULT_MODEL, f"config.default.toml: [models.astra] model={astra['model']!r}"
assert config.model_label(astra) == "(default)", config.model_label(astra)
assert config.model_label({"model": ""}) == "(default)"
assert config.model_label({"model": "gpt-6-astra"}) == "gpt-6-astra"
PY
  rm -rf -- "$d"
  return "$rc"
}
# Fake-adapter loops: a second root waits at max_runs=1; a depth-1 test run shares the slot.
slot_queue_check() {
  python3 "$REPO/tests/test_v5am.py" -v \
    Slots.test_v5am_status_menu_and_seat_bar_say_waiting \
    Slots.test_v5am_child_shares_parent_slot_and_exports_next_depth || return 1
  printf '%s\n' 'ok: max_runs=1 waits (ak run status says waiting for a slot · 1 ahead), then starts; depth-1 tests share the parent slot'
}
# Run the offline regressions without entering the live acceptance gates below.
if [ "${AGENTKIT_SMOKE_OFFLINE:-0}" = 1 ]; then
  cd -- "$REPO" || exit 1
  export TMPDIR="$REPO"
  # Keep even the older suites' temporary files in the checkout. tmux canonicalizes
  # TMUX_TMPDIR, so use an explicit short socket path for its isolated pane fixtures.
  if [ -d "/proc/$$/cwd" ]; then
    export TMPDIR="/proc/$$/cwd"
    SMOKE_TOOLS=$(mktemp -d "$REPO/.smoke-tools.XXXXXX") || exit 1
    trap 'rm -rf -- "$SMOKE_TOOLS"' EXIT
    AGENTKIT_SMOKE_TMUX=$(command -v tmux) || exit 1
    export AGENTKIT_SMOKE_TMUX
    cat >"$SMOKE_TOOLS/tmux" <<'SH'
#!/usr/bin/env bash
set -eu
[ "${1:-}" = -L ] && [ "${2:-}" = agentkit-test ] && [ -d "${TMUX_TMPDIR:-}" ] || {
  echo "offline smoke requires -L agentkit-test and a private TMUX_TMPDIR" >&2
  exit 2
}
shift 2
exec "$AGENTKIT_SMOKE_TMUX" -L agentkit-test -S "$TMUX_TMPDIR/agentkit-test" "$@"
SH
    chmod +x "$SMOKE_TOOLS/tmux"
    export PATH="$SMOKE_TOOLS:$PATH"
  fi
  OFFLINE_RC=0
  slot_queue_check || OFFLINE_RC=1
  usage_fresh_check || OFFLINE_RC=1
  session_state_check || OFFLINE_RC=1
  seat_state_check || OFFLINE_RC=1
  python3 "$REPO/tests/test_v4z.py" || OFFLINE_RC=1
  python3 "$REPO/tests/test_v5a.py" || OFFLINE_RC=1
  python3 "$REPO/tests/test_notify_rule.py" || OFFLINE_RC=1
  python3 "$REPO/tests/test_notify_smoke.py" || OFFLINE_RC=1
  codex_model_flag_check || OFFLINE_RC=1
  for test in test_notify.py test_auth_watch.py test_v4l.py test_v4n.py test_v4r.py \
              test_audit_phone_menu_recovery_layout.py \
              test_audit_retry_required_notifications.py; do
    case "$test" in
      test_notify.py) lifecycle_check notify || OFFLINE_RC=1 ;;
      test_v4l.py) lifecycle_check v4l || OFFLINE_RC=1 ;;
      *) python3 "$REPO/tests/$test" || OFFLINE_RC=1 ;;
    esac
  done
  exit "$OFFLINE_RC"
fi
WORK="$HOME/.agentkit/tmp/smoke-$(date +%Y%m%d-%H%M%S)"
SMOKE_CALLER_HOME=$HOME
mkdir -p -- "$HOME/.agentkit/tmp"
# This name is stamped to the second, and two suites can start inside the same second: the
# second of them is here to wait its turn below, not to die on the first one's directory.
mkdir -- "$WORK" 2>/dev/null || WORK=$(mktemp -d -- "$WORK-XXXXXX") || exit 1
PYTHONPATH="$REPO" python3 -m agentkit.retention begin "$WORK" smoke "$$" || :
# The lock is the last thing given back, once every check has reported.  Its holder is started
# well below this line, so the trap has to read a name that may still be unset.  The sandbox is
# settled on the suite's exit status, read before anything else can overwrite it: a passed
# suite takes its own sandbox with it, a failed one keeps its own and takes the older ones,
# so the host holds at most one failed sandbox, the newest, and `ak run gc` takes what is
# a day old.
trap 'SMOKE_RC=$?
      [ ! -d "$WORK/home" ] || smoke_sync_logins || SMOKE_RC=1
      HOME="$SMOKE_CALLER_HOME" PYTHONPATH="$REPO" python3 -m agentkit.retention settle "$WORK" "$SMOKE_RC" || :
      [ -z "${SMOKE_LOCK_PID:-}" ] || kill "$SMOKE_LOCK_PID" 2>/dev/null
      exit "$SMOKE_RC"' EXIT
# --- the suite's own tmux server, and nobody else's -------------------------
# Every tmux command here runs against a throwaway server: a socket of its own, in a socket
# directory of its own under $WORK, with $TMUX cleared so that running the suite from inside a
# tmux session cannot make a command follow the caller's server instead.  `ak` is pointed at the
# same socket with $AGENTKIT_TMUX_SOCKET, so the seats it starts are on it too, and the jobs it
# starts -- updates -- on the sibling socket.  A live orchestrator of the user's is on
# `agentkit`, in another directory again, and nothing here can reach it.  Check 0 greps this file
# and e2e-fresh.sh for a tmux call that goes anywhere else.
# Keep registration and cleanup self-contained above; even a failed HOME setup is settled.
smoke_home
export AGENTKIT_TMUX_SOCKET=agentkit-test
export TMUX_TMPDIR="$WORK/tmux"
mkdir -p -- "$TMUX_TMPDIR"
tm()  { env -u TMUX tmux -L agentkit-test "$@"; }        # the seats
tmj() { env -u TMUX tmux -L agentkit-test-jobs "$@"; }   # the jobs: updates
# the default server, which under $TMUX_TMPDIR above is this suite's too: it stands in for the
# one a user's seats were on before agentkit had a server of its own
tmd() { env -u TMUX tmux "$@"; }
# The checks that build a PATH from scratch (18, 18b) do it to hide the five harnesses, not
# the interpreter: `ak` needs the python3 it is installed against, and /usr/bin/python3 is 3.9
# on macOS, which has no tomllib. This directory holds python3 and the caller's tmux command,
# preserving test socket guards when a check replaces PATH without exposing any harness.
# It links the interpreter itself (sys.executable), never a `python3` on PATH that may be a
# shell wrapper -- a pyenv shim
# is a bash script, and check 18b's PATH has a fake `bash` on it that would swallow the run.
PYBIN="$WORK/pybin"; mkdir -p -- "$PYBIN"
ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "$PYBIN/python3"
ln -sf "$(command -v tmux)" "$PYBIN/tmux"
. "$REPO/tests/acceptance.sh"
newrepo() {
  local d="$WORK/$1"; mkdir -p -- "$d"
  git init -q -b main -- "$d"
  git -C "$d" config user.email smoke@localhost; git -C "$d" config user.name smoke
  : >"$d/.keep"; git -C "$d" add -A; git -C "$d" commit -qm init
  printf '%s' "$d"
}
echo "workdir: $WORK"
# The turn on everything two suites share, taken before the first check and given back by the
# trap above once the last one has reported.  Without it nothing below may run: not check 4,
# whose remote it is, and not the checks that use the same provider logins.
# So this ends the suite the way check 0 does, and
# it is asked before any other reason to skip -- a spent model does not excuse touching a
# remote that is not ours.
if ! smoke_lock_hold "$SMOKE_LOCK_WAIT"; then
  no "4 ak run: another suite still holds the turn after ${SMOKE_LOCK_WAIT}s;\
 its provider logins and remote were never this suite's to take"
  skip_checks 4b/4c/4d "prerequisite run did not happen: another suite holds the turn"
  echo "      stopping here: the provider logins and remote are still in use by the other suite"
  finish
  exit 1
fi
if python3 "$REPO/tests/test_v5a.py"; then
  ok "44 desktop notices and boot recovery: named offline checks a-f"
else
  no "44 desktop notices and boot recovery"
fi
if python3 "$REPO/tests/test_v4z.py"; then
  ok "43 project menus: named checks a-h, fixed rendering state and isolated tmux"
else
  no "43 project menus"
fi
# 41 reads no live meter -- its probes are mocked inside usage_fresh_check -- so a
# throttled provider cannot fail it and it takes no meter-unavailable skip.
if usage_fresh_check; then
  ok "41 provider usage refresh and meter mapping (offline)"
else
  no "41 provider usage refresh and meter mapping"
fi

# --- 0: no test can end a session that is not this suite's own --------------
# A kill-server in a branch test once took down a live orchestrator, so this reads the two test
# files themselves: a line that ends a server or a session has to go through one of the helpers
# above (`tm`, `tmj`, `tmd`, and 20e's two), or name the test socket itself.  A bare tmux kill
# fails here rather than on somebody's running seat.  The isolation those helpers rest on -- a
# socket directory under $WORK -- is checked with them.
#
# This one does not merely count a failure: it ends the run.  The command it found would be run
# later by the very suite that reported it, and the whole point is that it never runs at all.
# `[^-a-z]tmux ` is the command itself and not `-L agentkit-test`, not the tail of a helper's
# name (ovtmux), and not a word in a sentence; every line grep -n prints starts with its path,
# so no line here begins with the command.  Written without an alternation on purpose: ugrep,
# which some boxes install as grep, does not match `(^|[^-])` the way GNU and BSD grep do.
STRAY=$(grep -nE 'kill-(server|session)' "$REPO/tests/smoke.sh" "$REPO/tests/e2e-fresh.sh" \
        | grep -E '[^-a-z]tmux ' | grep -v -- '-L agentkit-test' || true)
ISOLATED=1
grep -q '^export TMUX_TMPDIR="$WORK/tmux"$' "$REPO/tests/smoke.sh" || ISOLATED=0
grep -q '^export AGENTKIT_TMUX_SOCKET=agentkit-test$' "$REPO/tests/smoke.sh" || ISOLATED=0
if [ -n "$STRAY" ] || [ "$ISOLATED" = 0 ]; then
  no "0 a tmux command that could reach another server, or the isolation this suite rests on is gone"
  printf '%s\n' "$STRAY" | sed 's/^/      /' | head -5
  [ "$ISOLATED" = 1 ] || echo "      the test socket or its socket directory is no longer exported"
  echo "      stopping here: nothing else in this file may run"
  finish
  exit 1
fi
ok "0 the suite cannot reach another tmux server: every kill goes through a test socket, in a socket directory under \$WORK"

# --- fakes for checks 9 and 10: an adapter that never calls a model ---------
# `<dir>/<harness>.sh` speaks the adapter contract and answers from a counter file: `flaky`
# dies twice on a transient fault before doing the work, `work` does it first time,
# `mergework` does it and leaves a merge commit behind, `pass` reviews everything as PASS,
# `dead` is spent and never comes back, `meterless` works and reports the [usage] none form
# the real grokbuild and opencode adapters answer, so the sandbox ranks those providers
# neutrally instead of last. They live here, not in the repo tree.
fakeadapter() {   # fakeadapter <dir> <harness> <flaky|work|mergework|pass|dead|meterless>
  local d=$1 h=$2
  printf '%s\n' "$3" >"$d/$h.beh"
  cat >"$d/$h.sh" <<SH
#!/usr/bin/env bash
set -uo pipefail
S="$d/$h"
SH
  cat >>"$d/$h.sh" <<'SH'
if [ "${1:-}" = usage ] && [ "$(cat "$S.beh" 2>/dev/null)" = meterless ]; then printf '%s\n' '{"provider":"xai","meters":[],"error":null,"none":"no meter: smoke fake"}'; exit 0; fi
if [ "${1:-}" = usage ]; then printf '%s\n' '{"meters":[],"error":"unknown: smoke fake"}'; exit 0; fi
if [ "${1:-}" = interactive ]; then echo 'sleep 600'; exit 0; fi   # a seat that paints nothing
if [ "${1:-}" = auth ]; then echo 'the smoke fake needs no login'; exit 0; fi
shift; ws=$3 out=$5
mkdir -p -- "$out"
n=$(($(cat "$S.n" 2>/dev/null || echo 0) + 1)); printf '%s\n' "$n" >"$S.n"
beh=$(cat "$S.beh")
printf 'fake %s adapter, call %s\n' "$beh" "$n" >"$out/stderr.log"
printf 'sid-%s\n' "$beh" >"$out/session_id"
if [ "$beh" = dead ]; then
  # a spent window, not a fault: the round is handed to another provider at once
  printf 'You have hit your usage limit.\n' >"$out/final.md"
  exit 1
fi
if [ "$beh" = flaky ] && [ "$n" -le 2 ]; then
  # an empty final.md first, an API error next: ak run has to retry on either
  [ "$n" = 1 ] && : >"$out/final.md" || printf 'API Error: 500 {"type":"error"}\n' >"$out/final.md"
  exit 1
fi
if [ "$beh" = pass ]; then
  printf 'VERDICT: PASS\n\n## Findings\n- none\n' >"$out/final.md"; exit 0
fi
if [ "$beh" = mergework ]; then
  # the work, plus a merge commit of its own: check 19 needs a branch a rebase would flatten
  b=$(git -C "$ws" rev-parse --abbrev-ref HEAD)
  printf 'hello\n' >"$ws/retry.txt"
  git -C "$ws" add -A >/dev/null 2>&1 && git -C "$ws" commit -qm "add retry.txt" >/dev/null 2>&1
  git -C "$ws" checkout -q -b "side-$n" >/dev/null 2>&1
  printf 'side\n' >"$ws/side.txt"
  git -C "$ws" add -A >/dev/null 2>&1 && git -C "$ws" commit -qm "add side.txt" >/dev/null 2>&1
  git -C "$ws" checkout -q "$b" >/dev/null 2>&1
  git -C "$ws" merge --no-ff -m "Merge side-$n" "side-$n" >/dev/null 2>&1
  printf '## Summary\nwrote retry.txt and merged side-%s\n' "$n" >"$out/final.md"
  exit 0
fi
printf 'hello\n' >"$ws/retry.txt"
git -C "$ws" add -A >/dev/null 2>&1 && git -C "$ws" commit -qm "add retry.txt" >/dev/null 2>&1
# the secret is echoed back so check 14 can see what the worker's environment held
printf '## Summary\nwrote retry.txt on call %s\nSMOKE_SECRET=%s\n' "$n" "${SMOKE_SECRET:-unset}" \
  >"$out/final.md"
SH
  chmod +x "$d/$h.sh"
}
cat >"$WORK/retry-task.md" <<'MD'
---
repo: __REPO__
base: main
rounds: 1
---
# __TITLE__

## Goal
Nothing: the fake adapters do the work.

## Done when
```bash
test -f retry.txt
```
MD
# The pick-order and fallback checks from here on rank spark and grok too, which the shipped
# defaults do not name as workers: their HOMEs take the shipped config with every model but
# fable and gemini working.  These HOMEs borrow no agy login, so gemini could only rank last.
wideworkers() {   # wideworkers <home>
  mkdir -p -- "$1/.agentkit"
  python3 - "$REPO/config.default.toml" "$1/.agentkit/config.toml" <<'PY'
import json, re, sys, tomllib
text = open(sys.argv[1]).read()
names = [name for name in tomllib.loads(text)["models"] if name not in ("fable", "gemini")]
with open(sys.argv[2], "w") as fh:
    fh.write(re.sub(r"(?m)^workers = .*$", "workers = " + json.dumps(names), text, count=1))
PY
}
# The first sleeps out the real 60s + 300s transient backoff, so they both start now,
# alongside the real model calls, and check 9 collects them. Fake HOME + fake adapters: no
# network, no real runs dir -- and --no-merge, because these throwaway repos have no origin
# and check 4 owns the merge.
retrylaunch() {   # retrylaunch <tag> <executor behaviour> <reviewer behaviour>
  ( D="$WORK/ad-$1"; H="$WORK/home-$1"; mkdir -p -- "$D" "$H"; wideworkers "$H"
    fakeadapter "$D" claude "$2"; fakeadapter "$D" codex "$3"; fakeadapter "$D" muse pass
    # no grokbuild or opencode fake here on purpose: every meter in this sandbox errors by
    # design, and a neutral meterless harness would steal check 9b's pinned fallback to spark
    R=$(newrepo "repo-$1")
    # Distinct titles: the run id is the minute plus the slug, and these two start
    # together.  One shared id would make either run's sweep signal the other's turn.
    sed -e "s|__REPO__|$R|" -e "s|__TITLE__|Smoke retry $1|" "$WORK/retry-task.md" >"$WORK/task-$1.md"
    HOME="$H" AGENTKIT_ADAPTER_DIR="$D" ak run "$WORK/task-$1.md" --rounds 1 --exec opus \
      --review astra --no-merge
    echo "rc=$?" ) >"$WORK/$1.log" 2>&1 &
}
retrylaunch retry-exec flaky pass     # executor dies twice, then works
retrylaunch retry-review work dead    # reviewer never comes back -> fall back to another provider

# --- 1: usage --------------------------------------------------------------
model_unavailable() {   # missing binary/login, or nothing; a broken saved login exits 1
  PYTHONPATH="$REPO" python3 - "$@" <<'PY'
import os, re, shutil, sys
from agentkit import config, worker
harness = config.model(config.load(), sys.argv[1])["harness"]
manifest = config.manifest(harness)
binary = manifest.get("update", {}).get("version", [harness])[0]
if not shutil.which(binary):
    print(f"{binary} is not installed")
else:
    authenticated, why = worker.auth_ok(harness, seat="seat" in sys.argv[2:])
    if authenticated is False:
        print(why)
        # Only an explicitly absent credential justifies skipping. An existing but
        # empty, unreadable, malformed or expired credential must still fail the gate.
        missing = re.match(r"^\S+: no (?:OAuth credentials in |provider key in )?(.+?)"
                           r"(?: and no CLAUDE_CODE_OAUTH_TOKEN| and none saved)?; run ", why)
        token = manifest.get("worker_token", {}).get("file")
        if (not missing or os.path.lexists(missing[1])
                or (token and os.path.lexists(config.SECRETS / token))):
            sys.exit(1)
PY
}
skip_unavailable() {   # skip_unavailable <check labels> <required models...>
  local checks=$1 model why
  shift
  for model in "$@"; do
    if ! why=$(model_unavailable "$model"); then
      no "$checks: required model $model login check failed: $why"
      return 0
    fi
    if [ -n "$why" ]; then
      skip_checks "$checks" "required model $model is not on this host: $why"
      return 0
    fi
  done
  return 1
}
U="$WORK/usage.json"
ak usage --json >"$U" 2>"$WORK/usage.err"; USAGERC=$?
# Every provider can be exhausted; only then is an empty pick_order expected here.
checked "$WORK/usage-check.log" jq -e '(.pick_order | type == "array") and
  ((.pick_order | length > 0) or (.providers | length > 0 and all(.[]; .exhausted == true))) and
  (.providers.anthropic.meters | length >= 1) and (.providers.openai.meters | length >= 1)' "$U"
USAGECHECK=$?
# A live meter that answers 429, 5xx or nothing at all is the provider throttling the
# host's probes, not the checkout under test: ask once more a minute later, and skip when
# it still cannot answer.  A meter that answers wrong still fails below.
METER_WHY=""
if { [ "$USAGERC" != 0 ] || [ "$USAGECHECK" != 0 ]; } \
    && METER_WHY=$(meter_unavailable "$U" anthropic openai); then
  sleep "${AK_METER_RETRY_SECS:-60}"
  METER_RETRIED=1   # check 6 re-probes without sleeping again: its minute has passed
  # The retry re-asks the adapters: neither the 5 min cache nor a probe lock's minute answers it.
  rm -f -- "$HOME/.agentkit/state/usage.json" "$HOME/.agentkit/state/"*-probe.lock
  ak usage --json >"$U" 2>"$WORK/usage.err"; USAGERC=$?
  checked "$WORK/usage-check.log" jq -e '(.pick_order | type == "array") and
    ((.pick_order | length > 0) or (.providers | length > 0 and all(.[]; .exhausted == true))) and
    (.providers.anthropic.meters | length >= 1) and (.providers.openai.meters | length >= 1)' "$U"
  USAGECHECK=$?
  if [ "$USAGERC" = 0 ] && [ "$USAGECHECK" = 0 ]; then
    METER_WHY=""   # the retry got an answer; the verdict below is a pass
  else
    METER_WHY=$(meter_unavailable "$U" anthropic openai) || METER_WHY=""
  fi
fi
if skip_unavailable 1 opus astra; then
  :
elif [ "$USAGERC" = 0 ] && [ "$USAGECHECK" = 0 ]; then
  ok "1 ak usage --json: anthropic+openai meters and pick_order $(jq -c .pick_order "$U")"
elif [ -n "$METER_WHY" ]; then
  skip "1: provider meter unavailable ($METER_WHY)"
else
  no "1 ak usage --json"
  diagnose "$USAGERC" "$WORK/usage.err" ak usage --json
fi

# --- 2: muse echo stub (offline harness plumbing) --------------------------
if ! command -v muse >/dev/null; then
  skip "2: muse is not on this host"
else
R=$(newrepo echo-repo)
printf 'Say only: OK\n' >"$WORK/p-echo.txt"
AGENTKIT_MUSE_PROVIDER=echo ak worker spark "$WORK/p-echo.txt" --workspace "$R" --out "$WORK/o-echo" \
  >"$WORK/echo.log" 2>&1
ECHORC=$?
if [ "$ECHORC" = 0 ] && [ -s "$WORK/o-echo/final.md" ] && [ -s "$WORK/o-echo/session_id" ]; then
  ok "2 muse --provider echo: final.md + session_id $(cat "$WORK/o-echo/session_id")"
else
  no "2 muse --provider echo: require exit=0 and nonempty final.md + session_id"
  diagnose "$ECHORC" "$WORK/echo.log" env AGENTKIT_MUSE_PROVIDER=echo ak worker spark "$WORK/p-echo.txt" --workspace "$R" --out "$WORK/o-echo"
fi
fi

# --- 3: one real tiny call + one resume per harness ------------------------
# A model whose subscription window is spent refuses every call until it resets, and `ak
# usage` says so before one is made: that model is skipped by name, with the moment it comes
# back, the way 31d/31e skip a shared browser that is not up.  A spent week is the one thing
# this check can neither prove nor fix -- it is the provider announcing it, not a guess here.
# Missing harnesses or logins skip with their own reason; broken saved logins still fail.
# One harness installed with its login is what the suite needs, and with none here it
# fails rather than skipping everything: a real call below, or a login smoke_home's adapters
# confirmed -- Grok Build, OpenCode and Antigravity count too, though this check makes its
# real calls on Claude, Codex and Muse only.
ak usage --json >"$WORK/usage-real.json" 2>/dev/null || : >"$WORK/usage-real.json"
spent_until() {   # spent_until <model>: "<provider> <when it comes back>", or nothing
  PYTHONPATH="$REPO" python3 - "$1" "$WORK/usage-real.json" <<'PY'
import json, pathlib, sys, time
from agentkit import config, usage
cfg, model = config.load(), sys.argv[1]
try:
    providers = json.loads(pathlib.Path(sys.argv[2]).read_text())["providers"]
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(0)  # unknown usage cannot justify skipping a real call
if not isinstance(providers, dict):
    sys.exit(0)
if usage.model_exhausted(cfg, model, providers)[0]:
    meters, _ = usage._gating_meters(cfg, model, providers)
    ends = max((m["resets_at"] for m in meters if m.get("exhausted")
                and isinstance(m.get("resets_at"), (int, float))), default=None)
    when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(ends)) if ends else "unknown"
    print(config.model(cfg, model)["provider"], when)
PY
}
skip_spent() {   # skip_spent <check labels> <required models...>
  local checks=$1 model spent
  shift
  for model in "$@"; do
    spent=$(spent_until "$model")
    if [ -n "$spent" ]; then
      skip_checks "$checks" "required model $model has a spent ${spent%% *} window until ${spent#* }"
      return 0
    fi
    skip_unavailable "$checks" "$model" && return 0
  done
  return 1
}
printf 'Create a file hello.txt containing exactly: hello\nThen reply with only the word DONE.\n' \
  >"$WORK/p-make.txt"
printf 'What file did you just create? Answer with the filename only.\n' >"$WORK/p-ask.txt"
ABSENT=0
for pair in "opus claude" "astra codex" "spark muse"; do
  set -- $pair; M=$1 H=$2
  SPENT=$(spent_until "$M")
  if [ -n "$SPENT" ]; then
    skip_checks 3a/3b "$M ($H): the ${SPENT%% *} subscription window is spent until"\
         "${SPENT#* }, so every call would be a 429"
    continue
  fi
  skip_unavailable 3a/3b "$M" && { ABSENT=$((ABSENT + 1)); continue; }
  R=$(newrepo "real-$M")
  if [ "$H" = claude ]; then
    python3 "$REPO/tests/check_claude_stream.py" "$WORK/o-$M" \
      ak worker "$M" "$WORK/p-make.txt" --workspace "$R" --out "$WORK/o-$M" >"$WORK/$M.log" 2>&1
  else
    ak worker "$M" "$WORK/p-make.txt" --workspace "$R" --out "$WORK/o-$M" >"$WORK/$M.log" 2>&1
  fi
  CALLRC=$?
  if [ "$CALLRC" = 0 ] && grep -qxF hello "$R/hello.txt" 2>/dev/null && [ -s "$WORK/o-$M/final.md" ]; then
    ok "3a $M ($H): wrote hello.txt, final.md non-empty"
  else
    no "3a $M ($H): hello.txt=$([ -f "$R/hello.txt" ] && echo yes || echo no)"
    diagnose "$CALLRC" "$WORK/$M.log" ak worker "$M" "$WORK/p-make.txt" --workspace "$R" --out "$WORK/o-$M"
    diagnose "$CALLRC" "$WORK/o-$M/stderr.log" "$H"
  fi
  SID=$(cat "$WORK/o-$M/session_id" 2>/dev/null)
  if [ -n "$SID" ]; then
    ak worker "$M" "$WORK/p-ask.txt" --workspace "$R" --out "$WORK/o-$M-2" --session "$SID" \
      >"$WORK/$M-2.log" 2>&1
    RESUMERC=$?
    if [ "$RESUMERC" = 0 ] && grep -qi 'hello\.txt' "$WORK/o-$M-2/final.md" 2>/dev/null; then
      ok "3b $M ($H): resumed session $SID recalled hello.txt"
    else
      no "3b $M ($H) resume: final.md = $(head -c 120 "$WORK/o-$M-2/final.md" 2>/dev/null)"
      diagnose "$RESUMERC" "$WORK/$M-2.log" ak worker "$M" "$WORK/p-ask.txt" --workspace "$R" --out "$WORK/o-$M-2" --session "$SID"
    fi
  else
    no "3b $M ($H) resume: adapter recorded no session_id"
  fi
done
[ "$ABSENT" -lt 3 ] || [ -n "${SMOKE_LOGINS:-}" ] ||
  no "3: no harness here is installed with its login; the suite needs one"

# --- 4: ak run end to end, into a real GitHub repo -------------------------
# The whole pipeline, not just the loop: a task file that names neither `repo:` nor `base:`,
# run from inside a clone, has to find both, pass review, rebase, push, open a PR and merge it.
# The private target stays under the caller's own account. Reset it to its seed and remove
# leftover ak/* branches before every run, so `main` is always exactly the same failing state.
if skip_spent 4/4b/4c/4d opus astra; then
  :   # skip before cloning or resetting the remote baseline, not after a worker's 429
else
SMOKE_LOGIN=$(gh api user --jq .login 2>"$WORK/smoke-login.err" || true)
SMOKE_REPO="$SMOKE_LOGIN/agentkit-smoke"
CLONE="$WORK/agentkit-smoke"
(
  set -e
  [ -n "$SMOKE_LOGIN" ]
  gh repo view "$SMOKE_REPO" >/dev/null 2>&1 || gh repo create "$SMOKE_REPO" --private
  gh repo clone "$SMOKE_REPO" "$CLONE" -- -q
  git -C "$CLONE" config user.email smoke@localhost; git -C "$CLONE" config user.name smoke
  if git -C "$CLONE" rev-parse --verify -q HEAD >/dev/null 2>&1; then
    git -C "$CLONE" reset --hard "$(git -C "$CLONE" rev-list --max-parents=0 HEAD)"
  fi
  # Older targets started with just a README; their root is not the failing-test seed.
  if [ ! -f "$CLONE/tests/test_hello.py" ]; then
    git -C "$CLONE" checkout --orphan seed
    git -C "$CLONE" rm -qrf --ignore-unmatch .
    printf '# agentkit smoke target: one failing test, fixed and reset on every run\n' \
      >"$CLONE/README.md"
    mkdir -p "$CLONE/tests"
    cat >"$CLONE/tests/test_hello.py" <<'PY'
from hello import hello


def test_hello():
    assert hello() == "hello"
PY
    git -C "$CLONE" add -A && git -C "$CLONE" commit -qm "seed the failing test"
  fi
  git -C "$CLONE" branch -M main
  git -C "$CLONE" push -q --force -u origin main
  for branch in $(git -C "$CLONE" for-each-ref --format='%(refname:strip=3)' refs/remotes/origin/ak/); do
    git -C "$CLONE" push -q origin --delete "$branch"
  done
) >"$WORK/seed.log" 2>&1
SRC=$?
cat >"$WORK/task.md" <<'MD'
---
rounds: 2
---
# Smoke make hello pass

## Goal
tests/test_hello.py imports the name hello from a module hello and expects hello() to return
the string "hello". Add the smallest module that makes the test pass. Nothing else.

## Constraints
- Do not modify tests/test_hello.py.
- No new dependencies.

## Done when
```bash
python3 -m pytest -q
```
MD
# A smoke run is not a job, so its own end-of-run notification must not reach Discord: an
# unusable webhook makes `ak notify` print the message instead of posting it, which is also
# how check 4d reads what the run would have said.
( [ "$SRC" = 0 ] || { cat "$WORK/seed.log"; exit "$SRC"; }
  cd "$CLONE" && AGENTKIT_DISCORD_WEBHOOK=off ak run "$WORK/task.md" --rounds 2 \
    --exec opus --review astra ) >"$WORK/run.log" 2>&1
RC=$?
# take the run id from this run's own log, not from a glob that can match an older smoke run
RUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/run.log" | head -1)
RUNDIR=""
[ -n "$RUNID" ] && [ -d "$HOME/.agentkit/runs/$RUNID" ] && RUNDIR="$HOME/.agentkit/runs/$RUNID"
DELIVERYRC=1
if [ "$RC" = 0 ] && [ -n "$RUNDIR" ]; then
  checked "$WORK/delivery.log" python3 "$REPO/tests/verify_delivery.py" \
    "$CLONE" "$WORK/task.md" "$WORK/delivered"
  DELIVERYRC=$?
fi
if [ "$RC" = 0 ] && [ -n "$RUNDIR" ] && grep -q '^VERDICT: PASS' "$RUNDIR/result.md" 2>/dev/null &&
   grep -q '^merged: yes$' "$RUNDIR/result.md" && grep -q '^pr: https://' "$RUNDIR/result.md" &&
   [ "$DELIVERYRC" = 0 ]; then
  ok "4 ak run: $(grep '^pr: ' "$RUNDIR/result.md") merged; done-when passed on fetched origin/main"
else
  no "4 ak run: exit=$RC rundir=${RUNDIR:-none} delivery-exit=$DELIVERYRC"
  diagnose "$RC" "$WORK/run.log" ak run "$WORK/task.md" --rounds 2 --exec opus --review astra
fi

# --- 4b: ak run clean takes the worktree back down -------------------------
# only ever clean a run of this smoke's own throwaway clone
if [ -n "$RUNDIR" ] && [ "$(jq -r '.repo // empty' "$RUNDIR/run.json" 2>/dev/null)" = "$CLONE" ]; then
  WTPATH=$(jq -r '.worktree // empty' "$RUNDIR/run.json" 2>/dev/null)
  if ak run clean "$RUNID" >"$WORK/clean.log" 2>&1 && [ ! -d "$WTPATH" ]; then
    ok "4b ak run clean: removed worktree $WTPATH"
  else
    no "4b ak run clean"; sed 's/^/      /' "$WORK/clean.log" | head -5
  fi
else
  no "4b ak run clean: no run dir to clean"
fi

# --- 4c: the executor's own build junk never reached a commit --------------
# The executor runs pytest itself, so __pycache__ is already there when the leftover sweep
# looks -- before the loop's own done-when snapshot can call it an artifact. Only the repo's
# info/exclude keeps it out of the commit the reviewer then fails the round on.
if [ -n "$RUNDIR" ] && [ -s "$RUNDIR/log.txt" ]; then
  SWEPT=$(grep 'WARN committed uncommitted executor changes:' "$RUNDIR/log.txt" | grep -E '__pycache__|\.pyc')
  if [ -z "$SWEPT" ]; then
    ok "4c ak run: the leftover sweep committed no __pycache__/*.pyc"
  else
    no "4c ak run swept build junk into the reviewed commit: $SWEPT"
  fi
else
  no "4c ak run build junk: no log.txt for run ${RUNID:-none}"
fi

# --- 4d: this run speaks for no seat, because none is gone -----------------
# A smoke run is launched from the terminal, or from a seat that is still up; either way the
# dead-orchestrator fallback is not for it and it must not have said a word.  Check 29 owns the
# orphan.  Match the fallback event, not the preflight line naming the destination it would use.
if [ -z "$RUNDIR" ] || [ ! -s "$RUNDIR/log.txt" ]; then
  skip "4d no dead orchestrator seat: prerequisite run has no log (exit=$RC rundir=${RUNDIR:-none})"
elif grep -qE '^\[[0-9:]*\] the orchestrator session .* is gone; asking the user to continue the task$' "$WORK/run.log"; then
  no "4d the run reported itself although the seat it was launched from is not gone"
  grep -m1 'message: Needs you' "$WORK/run.log" | sed 's/^/      /'
elif grep -q 'message: Needs you' "$WORK/run.log"; then
  no "4d the run sent a needs with no dead seat to speak for: $(grep -m1 'message: Needs you' "$WORK/run.log")"
else
  ok "4d no dead orchestrator seat: the run stayed quiet and left reporting to ak orch"
fi

fi

# --- 5: notify -------------------------------------------------------------
# --check, not a message: notifications are the orchestrator's and a smoke run is not a job.
# It GETs the webhook, which Discord answers with the hook object without posting anything, so
# a revoked hook or a 403 on a missing User-Agent fails here instead of sitting green for days.
ak notify --check >"$WORK/notify.log" 2>&1; NRC=$?
if [ -n "${AGENTKIT_DISCORD_WEBHOOK:-}" ] || [ -s "$HOME/.agentkit/secrets/discord_webhook" ]; then
  if [ "$NRC" = 0 ] && grep -q '^notify: ok (200)$' "$WORK/notify.log"; then
    ok "5 ak notify --check: webhook configured and live ($(cat "$WORK/notify.log"))"
  else
    no "5 ak notify --check: webhook configured but not reachable (exit $NRC)"
    sed 's/^/      /' "$WORK/notify.log" | head -3
  fi
elif [ "$NRC" = 2 ]; then
  ok "5 ak notify --check: no webhook configured, exits 2"
else
  no "5 ak notify --check exited $NRC with no webhook configured; expected 2"
  sed 's/^/      /' "$WORK/notify.log" | head -3
fi

# --- 5b: --check exit codes, offline -----------------------------------------
# 2 means "nothing configured" and nothing else, so the orchestrator can tell an unset webhook
# from a broken one. A fake HOME hides the real secrets file; port 1 always refuses.
NH="$WORK/home-notify"
mkdir -p -- "$NH"
NRC5=0
HOME="$NH" AGENTKIT_DISCORD_WEBHOOK= ak notify --check >"$WORK/n-none.log" 2>&1
[ "$?" = 2 ] || NRC5=1
HOME="$NH" AGENTKIT_DISCORD_WEBHOOK='not-a-url' ak notify --check >"$WORK/n-bad.log" 2>&1
[ "$?" = 1 ] || NRC5=1
HOME="$NH" AGENTKIT_DISCORD_WEBHOOK='http://127.0.0.1:1/hook' ak notify --check >"$WORK/n-down.log" 2>&1
[ "$?" = 1 ] || NRC5=1
if [ "$NRC5" = 0 ]; then
  ok "5b ak notify --check exit codes: 2 unconfigured, 1 malformed, 1 unreachable"
else
  no "5b ak notify --check exit codes: none=$(head -1 "$WORK/n-none.log") bad=$(head -1 "$WORK/n-bad.log") down=$(head -1 "$WORK/n-down.log")"
fi

# --- 5c: enforced notification lifecycle, fake webhook only ------------------
if lifecycle_check notify >"$WORK/notify-lifecycle.log" 2>&1; then
  ok "5c worker silence and audit, episode cards, silent Discord edits, one done per job, --check"
else
  no "5c notification lifecycle"; tail -30 "$WORK/notify-lifecycle.log"
fi

# --- 5d: a test can never reach the user's webhook (offline) -----------------
# The suite's marker outranks whatever destination is configured, and says so on stderr, so a
# scratch run that decides to say `done` cannot post to the user however its own environment
# was set up: its event is disabled and no POST is attempted at all.  Without the marker the
# very same command really does reach for that webhook and queues what it could not deliver --
# both exit 0, because a queued event is a delivered one as far as the caller is concerned.
NGH="$WORK/home-guard"
mkdir -p -- "$NGH"
GUARD=0
# this check is the one diversion the gate expects, so it keeps its own log; every other one
# lands in $AK_NOTIFY_SINK_LOG, which `finish` fails on
HOME="$NGH" AGENTKIT_DISCORD_WEBHOOK='http://127.0.0.1:1/hook' AGENTKIT_SESSION=smoke-guard \
  AK_NOTIFY_SINK_LOG="$WORK/guard-diversions.log" \
  ak notify done "a test must never reach the user" >"$WORK/guard.log" 2>&1
[ "$?" = 0 ] || GUARD=1
grep -q 'AK_NOTIFY_SINK is set' "$WORK/guard.log" || GUARD=1
grep -q 'went to the test sink and not to the configured webhook' "$WORK/guard.log" || GUARD=1
grep -q 'webhook POST failed' "$WORK/guard.log" && GUARD=1     # nothing was even attempted
# the diversion is a fact the gate's own accounting fails on, not only a line on stderr
[ "$(wc -l <"$WORK/guard-diversions.log")" -eq 1 ] || GUARD=1
grep -q 'went to the test sink and not to the configured webhook' "$WORK/guard-diversions.log" || GUARD=1
( NFAIL=0; AK_NOTIFY_SINK_LOG="$WORK/guard-diversions.log" WORK="$WORK"; finish >"$WORK/guard-finish.log" 2>&1
  [ "$?" = 1 ] ) || GUARD=1
grep -q 'FAIL  a notification was aimed at the configured webhook' "$WORK/guard-finish.log" || GUARD=1
HOME="$NGH" AK_NOTIFY_SINK= AGENTKIT_DISCORD_WEBHOOK='http://127.0.0.1:1/hook' \
  AGENTKIT_SESSION=smoke-guard-nosink ak notify done "the same words with no marker" \
  >"$WORK/guard-nosink.log" 2>&1
[ "$?" = 0 ] || GUARD=1
grep -q 'webhook POST failed' "$WORK/guard-nosink.log" || GUARD=1
[ "$(jq -r -s '[.[].status] | sort | join(",")' "$NGH"/.agentkit/state/notification-outbox/*.json 2>/dev/null)" \
  = disabled,pending ] || GUARD=1
if [ "$GUARD" = 0 ]; then
  ok "5d the test sink outranks the configured webhook and fails the gate on the diversion, and is the only reason nothing was attempted: disabled with the marker, queued against the webhook without it"
else
  no "5d the test notification sink"
  sed 's/^/      /' "$WORK/guard.log" "$WORK/guard-nosink.log" | head -8
fi

# --- 6: orch selection -----------------------------------------------------
# The pick stands on check 1's meters; when the provider throttled those probes the pick
# has nothing to stand on either.  One retry a minute later, then the same skip the gate
# counts as passed.  A meter that answers, wrong or right, runs the pick below.
METER_WHY=""
if METER_WHY=$(meter_unavailable "$U" anthropic openai); then
  # Check 1 already waited this minute out when it retried, so this re-probe goes at once.
  [ -n "${METER_RETRIED:-}" ] || sleep "${AK_METER_RETRY_SECS:-60}"
  # The retry re-asks the adapters: neither the 5 min cache nor a probe lock's minute answers it.
  rm -f -- "$HOME/.agentkit/state/usage.json" "$HOME/.agentkit/state/"*-probe.lock
  ak usage --json >"$U" 2>"$WORK/usage.err"
  METER_WHY=$(meter_unavailable "$U" anthropic openai) || METER_WHY=""
fi
# 6b's prerequisites, not the pick verdict: the seed copies whatever $U holds and the
# fable run names its model explicitly, so both work on a throttled meter and stay put.
ORCHHOME="$WORK/orchhome"
mkdir -p -- "$ORCHHOME/.agentkit/state"
python3 - "$U" "$ORCHHOME/.agentkit/state/usage.json" <<'PY'
import json, sys, time

with open(sys.argv[1]) as fh:
    usage = json.load(fh)
with open(sys.argv[2], "w") as fh:
    json.dump({"fetched_at": time.time(), "providers": usage["providers"]}, fh)
PY
printf '\n' | HOME="$ORCHHOME" ak orch --dry-run --model fable smoke-orch-fable >"$WORK/orch-fable.log" 2>&1
if skip_unavailable 6 fable astra spark; then
  :
elif [ -n "$METER_WHY" ]; then
  skip "6: provider meter unavailable ($METER_WHY)"
else
printf '\n\n\n' | HOME="$ORCHHOME" ak orch --dry-run smoke-orch-default >"$WORK/orch.log" 2>&1
PICK=$(sed -n 's/^orch: \([a-z0-9-]*\) .*/\1/p' "$WORK/orch.log" | head -1)
AUSED=$(jq -r '.providers.anthropic.meters[] | select(.name=="weekly_all") | .used' "$U")
SUSED=$(jq -r '.providers.anthropic.meters[] | select(.window_secs==18000) | .used' "$U" | head -1)
# opus, the default orchestrator, wins unless the Claude week or the 5h session window it runs
# in is spent; pace is not consulted at all, so an Opus at 97% used is still the orchestrator.
# Past it the models go in config order, fable, astra, spark, grok, gemini, mimo: a spent Claude week
# or session takes Fable out too and hands the seat to astra, a spent openai as well to spark,
# and a spent meta as well to grok, which reports no meter and is never spent.
WANT=$(python3 - "$U" <<'PY'
import json, sys
u = json.load(open(sys.argv[1]))
def spent(provider, gate=None):
    meters = u["providers"][provider]["meters"]
    return not meters or any(m["used"] >= 100 for m in meters
                             if gate is None or m["name"] in (gate, "weekly_all")
                             or m.get("window_secs") == 18000)
print("opus" if not spent("anthropic", "weekly_all") else "fable" if not spent("anthropic", "weekly_scoped") else "astra" if not spent("openai") else "spark" if not spent("meta") else "grok")
PY
)
CMD=$(tail -1 "$WORK/orch-fable.log")
if grep -q -- '--model' <<<"$CMD" && grep -q -- '--effort' <<<"$CMD" && grep -q '^claude\|claude$\| claude ' <<<"$CMD" &&
   [ "$PICK" = "$WANT" ] && grep -q -- '--model claude-fable-5-1' "$WORK/orch-fable.log"; then
  ok "6 ak orch --dry-run: picked $PICK (Claude weekly_all $AUSED% used, session ${SUSED:-none}%), claude cmd with --model/--effort, --model fable forces fable"
else
  no "6 ak orch --dry-run: picked '$PICK' expected '$WANT' (Claude weekly_all $AUSED% used, session ${SUSED:-none}%)"
  sed 's/^/      /' "$WORK/orch.log"
fi
fi

# --- 6b: any harness can hold the seat -------------------------------------
# The TUI command line comes from the harness's own adapter, so a codex or muse model gets a
# codex or muse command and nothing above the adapter knows what a bypass flag is called.
ORCH2=0
printf '\n' | HOME="$ORCHHOME" ak orch --dry-run --model astra smoke-orch-astra >"$WORK/orch-astra.log" 2>&1 || ORCH2=1
# no -m: a ChatGPT-subscription Codex runs its own model and rejects every other one (check 6e)
grep -q "codex --yolo -c 'model_reasoning_effort" "$WORK/orch-astra.log" || ORCH2=1
grep -q ' -m ' "$WORK/orch-astra.log" && ORCH2=1
printf '\n' | HOME="$ORCHHOME" ak orch --dry-run --model spark smoke-orch-spark >"$WORK/orch-spark.log" 2>&1 || ORCH2=1
grep -q 'muse --yolo --provider meta --model muse-spark' "$WORK/orch-spark.log" || ORCH2=1
grep -q 'idle-compact.py -- claude ' "$WORK/orch-fable.log" || ORCH2=1
[ "$ORCH2" = 0 ] && ok "6b ak orch: astra prints a codex command with no model of ours in it, spark a muse one, fable a claude one" \
                 || no "6b ak orch per-harness command: $(tail -1 "$WORK/orch-astra.log")"

# --- 6c: each new seat records and applies its own models (offline) ---------
# A fresh HOME and a current empty-meter cache ensure selection and usage never probe a provider.
SHOME="$WORK/sessionhome"
mkdir -p -- "$SHOME/.agentkit/state"
python3 - "$SHOME/.agentkit/state/usage.json" <<'PY'
import json, sys, time

providers = {}
for name, harness, via in (("anthropic", "claude", "fable"),
                           ("openai", "codex", "astra"), ("meta", "muse", "spark")):
    providers[name] = {"provider": name, "harness": harness, "via": via, "meters": [],
                       "pace": None, "error": "unknown: smoke cache", "exhausted": False}
with open(sys.argv[1], "w") as fh:
    json.dump({"fetched_at": time.time(), "providers": providers}, fh)
PY
SESSIONRC=0
printf '\n' | HOME="$SHOME" ak orch --dry-run --model astra --workers opus,spark smoke-pick \
  >"$WORK/session-pick.log" 2>&1 || SESSIONRC=1
printf '3\n\n' | HOME="$SHOME" ak orch --dry-run smoke-pick2 \
  >"$WORK/session-pick2.log" 2>&1 || SESSIONRC=1
HOME="$SHOME" AGENTKIT_SESSION=smoke-pick ak usage --json \
  >"$WORK/session-usage.json" 2>"$WORK/session-usage.err" || SESSIONRC=1
HOME="$SHOME" AGENTKIT_SESSION=ghost ak usage --json \
  >"$WORK/session-default-usage.json" 2>"$WORK/session-default-usage.err" || SESSIONRC=1
HOME="$SHOME" PYTHONPATH="$REPO" python3 - <<'PY' || SESSIONRC=1
import io
import json
import re
import time
from contextlib import redirect_stderr, redirect_stdout

from agentkit import config, orch

config.ensure_dirs()
for name, selection in {
    "list-one": {"orchestrator": "astra", "workers": ["opus", "spark"]},
    "list-bad": {"orchestrator": "retired-model", "workers": ["opus", "spark"]},
    "list-three": {"orchestrator": "opus", "workers": ["astra", "spark"]},
}.items():
    config.session_path(name).write_text(json.dumps(selection))
now = int(time.time())
orch.sessions = lambda: [
    {"name": name, "path": f"/repo/{name}", "created": now, "attached": False}
    for name in ("list-one", "list-bad", "list-three")
]
stdout, stderr = io.StringIO(), io.StringIO()
with redirect_stdout(stdout), redirect_stderr(stderr):
    assert orch.cmd_list([]) == 0
listed, warned = stdout.getvalue(), stderr.getvalue()
assert all(name in listed for name in ("list-one", "list-bad", "list-three")), listed
assert "list-bad" in listed and re.search(r"(?m)^list-bad\s+\S+\s+.*\s\?\s+\?\s+\S+$", listed), listed
assert str(config.session_path("list-bad")) in warned and "retired-model" in warned, warned
PY
if [ "$SESSIONRC" = 0 ] &&
   jq -e '.orchestrator == "astra" and .workers == ["opus", "spark"]' \
     "$SHOME/.agentkit/state/session-smoke-pick.json" >/dev/null 2>&1 &&
   jq -e '.orchestrator == "astra" and .workers == ["opus", "astra"]' \
     "$SHOME/.agentkit/state/session-smoke-pick2.json" >/dev/null 2>&1 &&
   jq -e '.pick_order == ["opus", "spark"]' "$WORK/session-usage.json" >/dev/null 2>&1 &&
   jq -e '.pick_order == ["opus", "astra"]' \
     "$WORK/session-default-usage.json" >/dev/null 2>&1; then
  ok "6c session picker: choices persist, usage applies workers or missing-state defaults, list tolerates stale state"
else
  no "6c session picker"; sed 's/^/      /' "$WORK/session-pick.log" | head -8
fi

# --- 6d: a named seat, really started --------------------------------------
# Not a dry run: `ak orch <name>` creates the tmux session, the harness's own TUI paints in it,
# `ak orch list` shows it and `ak orch stop` takes it down. The poll accepts directory trust,
# declines updates (ak update owns those), and continues without trusting new hooks. This seat
# makes no model request and must not approve any of the caller's hooks just to reach the TUI.
# A direct invocation outside ~/code keeps its checkout when Project defaults to none.
if ! SEATWHY=$(model_unavailable astra seat); then
  no "6d: required model astra login check failed: $SEATWHY"
elif [ -n "$SEATWHY" ]; then
  skip "6d: required model astra is not on this host: $SEATWHY"
else
SEAT=$(newrepo seat)
tm kill-session -t =smoke-astra 2>/dev/null    # a seat a previous, interrupted smoke left
printf '\n' | ( cd "$SEAT" && ak orch --model astra smoke-astra ) >"$WORK/seat.log" 2>&1
SEATRC=$?
PANE=""
for _ in $(seq 1 30); do
  PANE=$(tm capture-pane -p -t smoke-astra 2>/dev/null)
  if grep -q 'Hooks need review' <<<"$PANE" &&
     grep -q '3\. Continue without trusting' <<<"$PANE"; then
    tm send-keys -t smoke-astra 3 Enter
    sleep 2
    continue
  fi
  grep -q 'Hooks need review' <<<"$PANE" && { sleep 2; continue; }
  grep -q 'OpenAI Codex' <<<"$PANE" && break
  grep -q 'Do you trust' <<<"$PANE" && tm send-keys -t smoke-astra Enter
  grep -q 'Update available' <<<"$PANE" && tm send-keys -t smoke-astra Down Enter
  sleep 2
done
cp "$HOME/.agentkit/state/session-smoke-astra.json" "$WORK/seat-before-dry-run.json"
# A trusted SessionStart hook can verify ownership; declining new hooks leaves an explicit
# fresh-start record. Neither path may invent an id or claim ownership from directory history.
PYTHONPATH="$REPO" python3 - "$WORK/seat-before-dry-run.json" <<'PYSEAT'
import json, sys
from agentkit.harness import codex
record = json.load(open(sys.argv[1]))
owned = codex.conversation(record)
assert ((record.get("resumable") is True and owned and record.get("conversation") == owned)
        or (record.get("resumable") is False and not record.get("conversation"))), record
PYSEAT
SEATNOPIN=$?
printf '1\n\n' | ak orch --dry-run smoke-astra \
  >"$WORK/seat-dry-run.log" 2>&1
SEATDRY=$?
cmp -s "$WORK/seat-before-dry-run.json" "$HOME/.agentkit/state/session-smoke-astra.json" &&
  grep -q '^orch: attaching to smoke-astra ' "$WORK/seat-dry-run.log" &&
  ! grep -q '^Orchestrator' "$WORK/seat-dry-run.log"
SEATUNCHANGED=$?
# continuations rejoin the row before matching: a long worker list wraps
# instead of cutting, so the names match in order wherever they landed
SEATWANT=$(python3 - "$REPO/config.default.toml" <<'PY'
import re, sys, tomllib
with open(sys.argv[1], "rb") as fh:
    shipped = tomllib.load(fh)
print(r"^smoke-astra .*astra.*" + ",.*".join(map(re.escape, shipped["defaults"]["workers"])) + r"([[:space:]]|$)")
PY
)
SEATLIST=$(COLUMNS=100 ak orch list 2>&1 | sed -e ':a;N;$!ba;s/,\n  /,/g;s/\n  / /g' | grep -Ec "$SEATWANT")
SEATENV=$(tm show-environment -t =smoke-astra AGENTKIT_SESSION 2>/dev/null)
ak orch stop smoke-astra >"$WORK/seat-stop.log" 2>&1; SEATSTOP=$?
# the stop takes the record with the session: there is nothing left to be resumed into
SEATKEPT=0; [ -e "$HOME/.agentkit/state/session-smoke-astra.json" ] && SEATKEPT=1
if [ "$SEATRC" = 0 ] && [ "$SEATDRY" = 0 ] && [ "$SEATUNCHANGED" = 0 ] &&
   [ "$SEATNOPIN" = 0 ] && [ "$SEATKEPT" = 0 ] &&
   grep -q 'OpenAI Codex' <<<"$PANE" && ! grep -q 'Hooks need review' <<<"$PANE" && [ "$SEATLIST" = 1 ] &&
   [ "$SEATENV" = "AGENTKIT_SESSION=smoke-astra" ] && [ "$SEATSTOP" = 0 ] &&
   ! tm has-session -t =smoke-astra 2>/dev/null; then
  ok "6d ak orch: Codex seat exported/listed its models, has either verified Codex ownership or an explicit fresh-start record; dry-run reattach left them unchanged; stopped, record and all"
else
  no "6d ak orch seat: exit=$SEATRC dry=$SEATDRY unchanged=$SEATUNCHANGED listed=$SEATLIST env=$SEATENV stop=$SEATSTOP nopin=$SEATNOPIN record-kept=$SEATKEPT"
  printf '%s\n' "$PANE" | head -12 | sed 's/^/      /'
  tm kill-session -t =smoke-astra 2>/dev/null
fi
fi

# --- 6e: a subscription Codex is given no model of ours (offline) ----------
if codex_model_flag_check >"$WORK/codex-mflag.log" 2>&1; then
  ok "6e codex adapter: the model 'default' (and an empty one) builds a run and a seat command with no -m and the effort intact, a real id still gets its -m, and astra is configured with the sentinel"
else
  no "6e codex adapter -m rule"; sed 's/^/      /' "$WORK/codex-mflag.log"
fi

# --- 6f: a seat's pane runs inside agentkit's own slice --------------------
# tmux 3.4 and newer leave every pane in a scope under the slice its server was started in, so
# a seat started here has to come up under this suite's own `agentkit-test.slice` -- a corner
# of `agentkit.slice`, which is what the owner's seats and the install's ceiling use.  A box
# with no user systemd manager (a Mac, a container) starts its seats plainly, and there is
# nothing to read.
SLICE_STATE=$(systemctl --user is-system-running 2>/dev/null || true)
case "$SLICE_STATE" in
  initializing|starting|running|degraded|maintenance|stopping)
    tm kill-session -t =smoke-slice 2>/dev/null
    PYTHONPATH="$REPO" python3 - <<'PYSLICE' >"$WORK/slice.log" 2>&1
from pathlib import Path
from agentkit import config, orch
config.ensure_dirs()
config.save_session(config.load(), "smoke-slice", "astra", ["opus"])
orch.start("smoke-slice", Path("/tmp"), ["sleep", "600"], "astra")
PYSLICE
    SLICERC=$?
    PANEPID=$(tm list-panes -t =smoke-slice -F '#{pane_pid}' 2>/dev/null | head -1)
    SLICECG=$(cat "/proc/${PANEPID:-0}/cgroup" 2>/dev/null || true)
    ak orch stop smoke-slice >>"$WORK/slice.log" 2>&1 || :
    if [ "$SLICERC" = 0 ] && grep -q 'agentkit-test[.]slice' <<<"$SLICECG"; then
      ok "6f the slice: a seat's pane runs in agentkit-test.slice, under agentkit.slice"
    else
      no "6f the slice: pane cgroup=$SLICECG"; sed 's/^/      /' "$WORK/slice.log" | head -8
    fi ;;
  *) skip "6f the slice: a user systemd manager is not on this host, so seats start plainly" ;;
esac

# --- 6g: a detached run is really in its own scope -------------------------
# This is the one live check for the run wrapper: a scope must accept the weights and the
# loop's pid must be under its throwaway unit, rather than under the seat that launched it.
case "$SLICE_STATE" in
  initializing|starting|running|degraded|maintenance|stopping)
    SCOPE_HOME="$WORK/scope-home"
    mkdir -p -- "$SCOPE_HOME"
    HOME="$SCOPE_HOME" PYTHONPATH="$REPO" python3 - <<'PYRUNSCOPE' >"$WORK/run-scope.log" 2>&1
from pathlib import Path
import os
import signal
import sys
import time
from agentkit import config, orch

config.ensure_dirs()
unit = f"agentkit-run-smoke-{os.getpid()}"
output = config.TMP / "scope.log"
child_file = config.TMP / "escaped-child.pid"
placement = {}
pid = None
try:
    executor = [sys.executable, "-c",
                "import subprocess,sys,time; "
                "child=subprocess.Popen(['setsid','sleep','600']); "
                "open(sys.argv[1],'w').write(str(child.pid)); "
                "time.sleep(600)", str(child_file)]
    pid = orch.start_in_slice(executor, unit, dict(os.environ), output,
                              target_slice=orch.run_slice_name(),
                              properties=("-p", "CPUWeight=40", "-p", "IOWeight=40"),
                              nice=True, placement=placement)
    cgroup = Path(f"/proc/{pid}/cgroup").read_text()
    assert f"{unit}.scope" in cgroup, (pid, cgroup, placement)
    deadline = time.monotonic() + 5
    while not child_file.exists() and time.monotonic() < deadline:
        time.sleep(.05)
    assert child_file.exists(), child_file
finally:
    scope = placement.get("scope")
    if scope and scope != "none" and not str(scope).startswith("none ("):
        orch.stop_scope(scope, wait=True)
    elif pid:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        if child_file.exists():
            try:
                os.kill(int(child_file.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
if child_file.exists():
    child = int(child_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and Path(f"/proc/{child}").exists():
        time.sleep(.05)
    assert not Path(f"/proc/{child}").exists(), child
PYRUNSCOPE
    SCOPERC=$?
    if [ "$SCOPERC" = 0 ]; then
      ok "6g a detached run loop is under its agentkit-run scope"
    else
      no "6g detached run scope"; sed 's/^/      /' "$WORK/run-scope.log"
    fi ;;
  *) skip "6g the run scope: a user systemd manager is not on this host, so detached runs start plainly" ;;
esac

# --- 7: syntax + install into a throwaway HOME ------------------------------
SYN=0
for f in "$REPO"/adapters/*.sh "$REPO"/hooks/*.sh "$REPO"/install.sh "$REPO"/tests/*.sh "$REPO"/bin/[a-z]*; do
  head -1 "$f" | grep -q 'bash\|sh' && { bash -n "$f" || SYN=1; }
done
for f in "$REPO"/agentkit/*.py "$REPO"/tools/*.py "$REPO"/bin/ak; do
  python3 -m py_compile "$f" || SYN=1
done
# never install into the real HOME: that would repoint ~/.local/bin/ak at this checkout
FAKE="$WORK/home"
mkdir -p -- "$FAKE/.local/bin" "$WORK/oldbin"
: >"$WORK/oldbin/ak"
for stale in usage worker run; do
  ln -sfn -- "$REPO/bin/$stale" "$FAKE/.local/bin/$stale"      # link from this checkout
done
ln -sfn -- "$WORK/oldbin/orch" "$FAKE/.local/bin/orch"         # link from an older checkout
ln -sfn -- "$WORK/gone/bin/notify" "$FAKE/.local/bin/notify"   # link from a deleted checkout
HOME="$FAKE" bash "$REPO/install.sh" >"$WORK/install1.log" 2>&1 || SYN=1
HOME="$FAKE" bash "$REPO/install.sh" >"$WORK/install2.log" 2>&1 || SYN=1
[ "$(readlink -- "$FAKE/.local/bin/ak")" = "$REPO/bin/ak" ] || SYN=1
for stale in usage worker run notify orch; do
  if [ -e "$FAKE/.local/bin/$stale" ] || [ -L "$FAKE/.local/bin/$stale" ]; then SYN=1; fi
done
[ "$SYN" = 0 ] && ok "7 bash -n + py_compile clean; install.sh idempotent, links only ak, drops the stale shim symlinks" \
               || no "7 syntax or install.sh"

# --- 7b: the yolo defaults landed in that same throwaway HOME --------------
# Both install runs above were against $FAKE, so this reads what they wrote: bypassPermissions
# for claude, a top-level never/danger-full-access for codex, and the alias block.
YOLO=0
jq -e '.permissions.defaultMode == "bypassPermissions" and .skipDangerousModePermissionPrompt == true
       and .env.DISABLE_AUTOUPDATER == "1"' \
  "$FAKE/.claude/settings.json" >/dev/null 2>&1 || YOLO=1
# The hooks are the adapter's, wired by `adapters/claude.sh hooks` from install.sh: a turn
# began, a turn ended, a prompt is waiting.  Stop is still the half of the idle auto-compact
# that lives outside the wrapper.  Both installs ran, so exactly one entry on each event also
# proves a re-run does not append a second.
jq -e --arg c "bash $REPO/hooks/seat-state.sh" '.hooks as $h
   | ["UserPromptSubmit", "Stop", "Notification"]
   | map([$h[.][]?.hooks[]? | select(.type == "command" and .command == $c)] | length)
   | . == [1, 1, 1]' "$FAKE/.claude/settings.json" >/dev/null 2>&1 || YOLO=1
python3 - "$FAKE/.codex/config.toml" <<'PY' || YOLO=1
import pathlib, sys, tomllib
cfg = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
sys.exit(0 if cfg.get("approval_policy") == "never"
         and cfg.get("sandbox_mode") == "danger-full-access" else 1)
PY
case "$(uname -s)" in Darwin) YRC="$FAKE/.zshrc" ;; *) YRC="$FAKE/.bashrc" ;; esac
grep -qxF -- "alias orch='ak orch'" "$YRC" 2>/dev/null || YOLO=1
grep -qF 'export MUSE_NO_AUTO_UPDATE=1' "$YRC" 2>/dev/null || YOLO=1
# written once, not once per run: the second install must not have appended a second block
[ "$(grep -cxF '# agentkit aliases' "$YRC" 2>/dev/null)" = 1 ] || YOLO=1
[ "$YOLO" = 0 ] && ok "7b install.sh yolo defaults and update pins: claude bypassPermissions + DISABLE_AUTOUPDATER + one seat-state hook on each of UserPromptSubmit/Stop/Notification, codex never/danger-full-access, MUSE_NO_AUTO_UPDATE and one alias block in $(basename "$YRC")" \
                || no "7b install.sh yolo defaults in $FAKE"

# --- 7c: a config.toml whose last line has no newline ----------------------
# The anchor is "after model_reasoning_effort", which on a file saved without a trailing
# newline is the end of the file: appending there without closing that line first writes
# `model_reasoning_effort = "xhigh"approval_policy = "never"` and the TOML no longer parses.
NNL="$WORK/home-nonl"
mkdir -p -- "$NNL/.codex"
printf 'model = "gpt-6-astra"\nmodel_reasoning_effort = "xhigh"' >"$NNL/.codex/config.toml"
NRC7=0
HOME="$NNL" bash "$REPO/install.sh" >"$WORK/install-nonl.log" 2>&1 || NRC7=1
HOME="$NNL" bash "$REPO/install.sh" >"$WORK/install-nonl2.log" 2>&1 || NRC7=1
python3 - "$NNL/.codex/config.toml" <<'PY' || NRC7=1
import pathlib, sys, tomllib
raw = pathlib.Path(sys.argv[1]).read_text()
try:
    cfg = tomllib.loads(raw)
except tomllib.TOMLDecodeError as exc:
    sys.exit(f"unparsable: {exc}")
# the effort line has to survive intact, not be swallowed by the key appended after it
sys.exit(0 if cfg.get("approval_policy") == "never"
         and cfg.get("sandbox_mode") == "danger-full-access"
         and cfg.get("model_reasoning_effort") == "xhigh"
         and cfg.get("model") == "gpt-6-astra"
         and raw.count("approval_policy") == 1 else 1)
PY
[ "$NRC7" = 0 ] && ok "7c install.sh: a config.toml with no trailing newline stays valid TOML and is written once" \
                || no "7c install.sh on a config.toml with no trailing newline: $(sed -n '1,2p' "$NNL/.codex/config.toml" | tail -1)"

# --- 7d: a codex key that carries an inline comment ------------------------
# Rewriting `approval_policy` must not throw away what the user wrote next to it, and a `#`
# inside the value is part of the value, not the start of a comment.
CMT="$WORK/home-comment"
mkdir -p -- "$CMT/.codex"
cat >"$CMT/.codex/config.toml" <<'TOML'
model = "gpt-6-astra"
approval_policy = "untrusted"   # ask me first
sandbox_mode = "read-only"
model_reasoning_effort = "xhigh"
TOML
NRC7D=0
HOME="$CMT" bash "$REPO/install.sh" >"$WORK/install-comment.log" 2>&1 || NRC7D=1
python3 - "$CMT/.codex/config.toml" <<'PY' || NRC7D=1
import pathlib, sys, tomllib
raw = pathlib.Path(sys.argv[1]).read_text()
try:
    cfg = tomllib.loads(raw)
except tomllib.TOMLDecodeError as exc:
    sys.exit(f"unparsable: {exc}")
sys.exit(0 if cfg.get("approval_policy") == "never"
         and cfg.get("sandbox_mode") == "danger-full-access"
         and "# ask me first" in raw
         and cfg.get("model_reasoning_effort") == "xhigh" else 1)
PY
[ "$NRC7D" = 0 ] && ok "7d install.sh: rewriting approval_policy kept its inline comment" \
                 || no "7d install.sh dropped the inline comment: $(sed -n 2p "$CMT/.codex/config.toml")"

# --- 7e: the phone key's forced command becomes `ak attach` ----------------
# One line in authorized_keys is the phone's, and its forced command is the whole session that
# key can have. Only that line may change, only its command=, and the second install must find
# nothing left to do.
PHONE="$WORK/home-phone"
mkdir -p -- "$PHONE/.ssh"
cat >"$PHONE/.ssh/authorized_keys" <<'KEYS'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmokeone laptop
command="tmux attach 2>/dev/null || tmux new -A -s orch",no-agent-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmoketwo phone-termius
KEYS
chmod 600 "$PHONE/.ssh/authorized_keys"
NRC7E=0
HOME="$PHONE" bash "$REPO/install.sh" >"$WORK/install-phone.log" 2>&1 || NRC7E=1
HOME="$PHONE" bash "$REPO/install.sh" >"$WORK/install-phone2.log" 2>&1 || NRC7E=1
grep -q 'already runs `ak attach`' "$WORK/install-phone2.log" || NRC7E=1
grep -qx 'command="ak attach",no-agent-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmoketwo phone-termius' \
  "$PHONE/.ssh/authorized_keys" || NRC7E=1
grep -qx 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmokeone laptop' \
  "$PHONE/.ssh/authorized_keys" || NRC7E=1
[ "$(grep -c 'ak attach' "$PHONE/.ssh/authorized_keys")" = 1 ] || NRC7E=1
KEYMODE=$(stat -c %a "$PHONE/.ssh/authorized_keys" 2>/dev/null ||
          stat -f %Lp "$PHONE/.ssh/authorized_keys" 2>/dev/null)
[ "$KEYMODE" = 600 ] || NRC7E=1
[ "$NRC7E" = 0 ] && ok "7e install.sh: the phone-termius key now forces \`ak attach\`, the other key untouched, mode $KEYMODE" \
                 || no "7e install.sh on authorized_keys: $(grep phone-termius "$PHONE/.ssh/authorized_keys" | cut -c1-60)"

# --- 8: pace ranking and orch selection, offline on a hand-written usage cache ---
# A fake HOME puts a fresh state/usage.json in front of `ak`, so these make no model calls
# and never touch the real cache. fixture <weekly_all used,pace> <weekly_scoped used,pace>
# <openai used,pace> [<5h session used>]; meta stays meterless.
PHOME="$WORK/pacehome"
mkdir -p -- "$PHOME/.agentkit/state"
wideworkers "$PHOME"
fixture() {
  python3 - "$PHOME/.agentkit/state/usage.json" "$@" <<'PY'
import json, sys, time
path, au, ap, fu, fp, ou, op = sys.argv[1:8]
su = sys.argv[8] if len(sys.argv) > 8 else None
now = time.time()
def meter(name, used, pace, window=604800):
    # elapsed is what the pace says it is: pace = used - elapsed, and `ak usage` reads the
    # elapsed side to work out how fast the window is being spent
    return {"name": name, "used": float(used), "resets_at": now + 3600, "window_secs": window,
            "elapsed": float(used) - float(pace), "pace": float(pace), "exhausted": False}
def prov(name, harness, via, meters):
    return {"provider": name, "harness": harness, "via": via, "meters": meters, "pace": None,
            "resets": 0, "error": None if meters else "unknown: no meters", "exhausted": False}
anthropic = [meter("weekly_all", au, ap), meter("weekly_scoped", fu, fp)]
if su is not None:
    anthropic.insert(0, meter("session", su, 0, 18000))
providers = {
    "anthropic": prov("anthropic", "claude", "fable", anthropic),
    "openai": prov("openai", "codex", "astra", [meter("primary_window", ou, op)]),
    "meta": prov("meta", "muse", "spark", []),
}
with open(path, "w") as fh:
    json.dump({"fetched_at": now, "providers": providers}, fh)
PY
}
orderof() { HOME="$PHOME" ak usage --json 2>/dev/null | jq -c '.pick_order'; }
# an explicit session name every time: a bare `ak orch` would find a live seat by the same
# name and attach to it instead of picking, and the check would pass on nothing
pickof() {   # pickof <log> <session name>
  printf '\n\n\n' | HOME="$PHOME" ak orch --dry-run "$2" >"$1" 2>&1
  echo "rc=$?" >>"$1"
  grep '^orch:' "$1" | head -1
}

# 8a: openai, with less of its week left than opus has (0.37 meters against 0.48),
# is ranked behind opus and not dropped -- and opus, the default orchestrator, at 94% used
# still runs the seat, where the old 100 - pace_margin ceiling would have skipped it
fixture 52 -34.3  94 7.7  63 18.2
ORDER=$(orderof)
fixture 94 7.7  94 7.7  63 18.2
LINE=$(pickof "$WORK/orch-94.log" smoke-pace-94)
if [ "$ORDER" = '["opus","astra","spark","grok"]' ] &&
   grep -q '^orch: opus (weekly_all 94\.0% used < 100' <<<"$LINE" &&
   ! grep -q WARN <<<"$LINE" && grep -q '^rc=0$' "$WORK/orch-94.log"; then
  ok "8a pick order ranks openai (0.4 meters left) after opus (0.5) instead of dropping it ($ORDER), and opus at 94% used still runs the seat: $LINE"
else
  no "8a pick order got $ORDER expected [\"opus\",\"astra\",\"spark\",\"grok\"]; orch: $LINE"
fi

# 8b: the orchestrator choice does not read pace at all -- opus at +40 is still the pick, and
# no WARN
fixture 50 40  50 40  63 18.2
LINE=$(pickof "$WORK/orch-overpace.log" smoke-pace-over)
if grep -q '^orch: opus (' <<<"$LINE" && ! grep -q WARN <<<"$LINE" &&
   grep -q '^rc=0$' "$WORK/orch-overpace.log"; then
  ok "8b the orchestrator choice ignores pace: anthropic +40 over pace and the default opus still wins: $LINE"
else
  no "8b default orchestrator over pace: $LINE"; sed 's/^/      /' "$WORK/orch-overpace.log" | head -4
fi

# 8c: anthropic and openai both at 100% used -> spark takes the seat (meta reports nothing), exit 0
fixture 100 40  100 40  100 40
LINE=$(pickof "$WORK/orch-exhausted.log" smoke-pace-spent)
if grep -q '^orch: spark (' <<<"$LINE" && ! grep -q WARN <<<"$LINE" &&
   grep -q '^rc=0$' "$WORK/orch-exhausted.log"; then
  ok "8c anthropic and openai exhausted, spark takes the seat: $LINE"
else
  no "8c anthropic and openai exhausted: $LINE"; sed 's/^/      /' "$WORK/orch-exhausted.log" | head -4
fi

# 8d: the 5h session window gates the orchestrator choice too: opus, and fable, whose `meter =`
# names a weekly cap its own gate would otherwise answer from alone
fixture 50 0  50 0  63 18.2  100
LINE=$(pickof "$WORK/orch-session.log" smoke-pace-session)
if grep -q '^orch: astra (' <<<"$LINE" && grep -q 'skipped fable: session 100.0% used' <<<"$LINE" &&
   ! grep -q WARN <<<"$LINE" && grep -q '^rc=0$' "$WORK/orch-session.log"; then
  ok "8d a spent 5h session meter takes Opus and Fable out with both weekly caps at 50%, and astra takes the seat: $LINE"
else
  no "8d spent session meter: $LINE"; sed 's/^/      /' "$WORK/orch-session.log" | head -4
fi

# 8e: the same numbers in words -- one row per provider, what it has left in meters, and when
# it runs dry at the rate the window has actually been spent. anthropic is 94% through the cap
# that gates it with 13.7% of the week to go (0.06 meters left, real outlook hours); openai is 63%
# through with 55% of the week to go (0.4 meters, about two days); meta says nothing at all.
fixture 52 -34.3  94 7.7  63 18.2
UT="$WORK/usage-words.txt"
# 140 columns so the full headings are what is checked; `resets` is when the shared week opens
# again, the same answer the menu row gives, and `resets held` is the credits in hand.
HOME="$PHOME" COLUMNS=140 ak usage >"$UT" 2>&1
WHEN='(-|[A-Za-z]+ [0-9][0-9]:[0-9][0-9])'
if grep -qi 'week elapsed' "$UT" && grep -q 'session  *resets held  *headroom  *budget  *outlook' "$UT" &&
   grep -q ' left  *resets  *week elapsed' "$UT" && ! grep -q 'this week' "$UT" &&
   grep -qE "^anthropic .*fable, opus +6% +$WHEN +86% +- +0 +0\.1 +[0-9]+\.[0-9] slack +runs out in ~1d$" "$UT" &&
   grep -qE "^openai +astra +37% +$WHEN +45% +- +0 +0\.4 +[0-9]+\.[0-9] slack +runs out in ~2d$" "$UT" &&
   grep -qE '^meta +spark +- +- +- +- +0 +- +unknown +unknown$' "$UT" &&
   grep -q '^pick order: opus, astra, spark, grok$' "$UT" && ! grep -qw sol "$UT"; then
  ok "8e ak usage in words: $(grep '^openai ' "$UT")"
else
  no "8e ak usage table"; sed 's/^/      /' "$UT" | head -6
fi

# 8o: fake weekly meters exercise the executor/reviewer picker without any model calls.
balancecheck() {   # balancecheck <named check> <test script> <test names...>
  local label=$1 script=$2 log="$WORK/usage-${1%% *}.log"
  shift 2
  if python3 "$REPO/tests/$script" -v "$@" >"$log" 2>&1; then
    ok "$label"
  else
    no "$label"; tail -30 "$log"
  fi
}
balancecheck "8o-a Fable behind (80/53): Fable executes only if listed or seatless, astra or spark reviews" \
  test_usage_balance.py WeeklyBalance.test_behind_prefers_fable_executor_with_cross_provider_reviewer
balancecheck "8o-b Opus retains real headroom and remains selectable across the provider boundary" \
  test_usage_balance.py WeeklyBalance.test_behind_keeps_opus_selectable_for_normal_cross_provider_pick
balancecheck "8o-c Fable ahead, in step or within the margin: normal selection" \
  test_usage_balance.py WeeklyBalance.test_ahead_in_step_and_margin_use_normal_selection
balancecheck "8o-d one funded provider: Fable executes with Opus reviewing; Fable never reviews Opus" \
  test_usage_balance.py WeeklyBalance.test_same_provider_headroom_allows_fable_with_opus_review
balancecheck "8o-e real exhaustion, session gates, payg, cache refresh and unchanged single meters" \
  test_usage_balance.py WeeklyBalance.test_requested_balance_cases \
  WeeklyBalance.test_only_real_meters_exhaust_models WeeklyBalance.test_session_still_gates_and_contributes_to_pace \
  WeeklyBalance.test_real_pace_controls_payg_overflow WeeklyBalance.test_single_meter_and_real_outlook_unchanged \
  WeeklyBalance.test_split_comes_from_config_and_requires_both_meters \
  WeeklyBalance.test_cached_and_fresh_reads_drop_effective_without_changing_real_meters \
  WeeklyBalance.test_preference_respects_worker_selection_payg_and_real_session_gate
balancecheck "8o-f saved Fable executors remain resumable after the meters catch up" \
  test_usage_balance.py WeeklyBalance.test_fable_seat_resume_keeps_executor_after_meters_catch_up
balancecheck "8o-g reviewers keep the normal ranking when Fable is behind" \
  test_usage_balance.py WeeklyBalance.test_reviewers_keep_normal_order_when_fable_is_behind
balancecheck "8o-h the launch banner agrees with the new seat's executor order" \
  test_usage_balance.py WeeklyBalance.test_launch_banner_matches_the_new_seats_executor_order
balancecheck "8o-i unavailable Fable preferences display normal selection" \
  test_usage_balance.py WeeklyBalance.test_verdict_reports_normal_selection_when_preference_cannot_apply
balancecheck "8o-j ak run resume --rounds preserves a listed Fable executor in its own seat" \
  test_audit_enforce_review_contract.py ReviewContract.test_fable_executor_resumes_review_from_its_seat_with_more_rounds

# 8f: budget ranks workers, the resets in hand in it; headroom counts them too (offline, fakes)
# No cache and no network: four adapters of the suite's own answer `usage`, and the codex one
# also speaks `reset-status`/`reset` off a counter file, so the resets are read where the real
# ones are -- beside the meters, on the probe that fetches them.
HD="$WORK/ad-headroom"; HH="$WORK/home-headroom"
mkdir -p -- "$HD" "$HH/.agentkit/state"
wideworkers "$HH"
headroomadapter() {   # headroomadapter <dir> <harness> <weekly used%|none|meterless> [resets in hand]
  local d=$1 h=$2
  printf '%s\n' "${4:-0}" >"$d/$h.resets"
  printf '%s\n' "$3" >"$d/$h.used"
  cat >"$d/$h.sh" <<SH
#!/usr/bin/env bash
set -uo pipefail
S="$d/$h"
SH
  cat >>"$d/$h.sh" <<'SH'
used=$(cat "$S.used"); half=$(( $(date +%s) + 302400 ))   # half the week still to go
case "${1:-}" in
usage)
  [ "$used" = none ] && { printf '{"meters":[],"error":"unknown: no usage endpoint"}\n'; exit 0; }
  # meterless is the [usage] none form grokbuild and opencode answer, neutral in the picker.
  # The provider name in this JSON is ignored: the probe records its own.
  [ "$used" = meterless ] && { printf '{"provider":"xai","meters":[],"error":null,"none":"no meter: smoke fake"}\n'; exit 0; }
  printf '{"meters":[{"name":"weekly","used":%s,"resets_at":%s,"window_secs":604800}]}\n' \
    "$used" "$half" ;;
reset-status)
  printf '{"available":%s,"applicable":null,"weekly_used":%s,"resets_at":%s,"error":null}\n' \
    "$(cat "$S.resets")" "$used" "$half" ;;
reset)
  n=$(cat "$S.resets")
  [ "$n" -gt 0 ] || { printf '{"error":"no usage-limit reset is available to spend"}\n'; exit 1; }
  printf '%s\n' "$((n - 1))" >"$S.resets"
  # the week this fake reports does not move, so the only thing the check reads is the count
  printf '{"code":"reset","available":%s,"weekly_used":%s,"resets_at":%s,"error":null}\n' \
    "$((n - 1))" "$used" "$half" ;;
*) echo "fake adapter: no $1" >&2; exit 2 ;;
esac
SH
  chmod +x "$d/$h.sh"
}
headroom() {   # headroom: a cold `ak usage --json`, cache dropped so the adapters are asked
  # and a minute on: each provider's last ask is its probe lock, and inside that minute a
  # dropped cache is answered by nobody
  rm -f -- "$HH/.agentkit/state/usage.json" "$HH/.agentkit/state/"*-probe.lock
  HOME="$HH" AGENTKIT_ADAPTER_DIR="$HD" ak usage --json 2>/dev/null
}
headroomadapter "$HD" claude 20; headroomadapter "$HD" codex 60 2
headroomadapter "$HD" muse none; headroomadapter "$HD" grokbuild meterless
headroomadapter "$HD" opencode meterless
HEAD=0
headroom >"$WORK/headroom-resets.json"
# At half a week remaining, 20% used has budget 1.6, while 60% used with two resets in hand
# carries two whole weeks more and ranks 4.8, so openai goes first. The provider that reports
# nothing still sorts last.
jq -e '.pick_order == ["astra", "opus", "grok", "spark"] and .providers.openai.headroom == 2.4
       and (.providers.openai.budget | . > 4.79 and . < 4.81)
       and (.providers.openai.budget_from_resets | . > 3.99 and . < 4.01)
       and (.providers.anthropic.budget | . > 1.59 and . < 1.61)
       and .providers.anthropic.budget_from_resets == 0
       and .providers.anthropic.headroom == 0.8 and .providers.meta.headroom == null
       and .providers.openai.resets == 2' "$WORK/headroom-resets.json" >/dev/null || HEAD=1
# spending one costs a whole meter of headroom: a reset counts only while it is unspent
"$HD/codex.sh" reset >"$WORK/headroom-spend.json" 2>&1 || HEAD=1
jq -e '.code == "reset" and .available == 1' "$WORK/headroom-spend.json" >/dev/null || HEAD=1
headroom >"$WORK/headroom-spent.json"
jq -e '.providers.openai.headroom == 1.4 and .providers.openai.resets == 1
       and (.providers.openai.budget | . > 2.79 and . < 2.81)
       and .pick_order == ["astra", "opus", "grok", "spark"]' "$WORK/headroom-spent.json" >/dev/null || HEAD=1
# and a spent meter is still the one hard exclusion, resets or no resets
headroomadapter "$HD" claude 100
headroom >"$WORK/headroom-exhausted.json"
jq -e '.providers.anthropic.exhausted == true and .pick_order == ["astra", "grok", "spark"]' \
  "$WORK/headroom-exhausted.json" >/dev/null || HEAD=1
[ "$HEAD" = 0 ] && ok "8f budget: openai at 60% used with 2 resets in hand outranks anthropic at 20% used (4.8 against 1.6); spending one drops openai from 2.4 meters of headroom and 4.8 of budget to 1.4 and 2.8, first either way, unknown stays last, and 100% is excluded" \
                || { no "8f headroom and resets"; for f in resets spent exhausted; do
                       jq -c '{pick_order, headroom: [.providers | to_entries[] | {(.key): (.value.headroom)}]}' \
                         "$WORK/headroom-$f.json" 2>/dev/null | sed "s/^/      $f /"; done; }

# 8g: a reset the adapter confirmed and then could not count again is still counted (offline)
# The policy spends one at 95% used; the credits list is a second request and this codex fake
# fails it from then on, so after the spend the only number left for the reset in hand is the
# one `reset` itself came back with. Headroom retains that credit, and so does the budget that
# ranks: openai's fresh week and the credit (3.9) go ahead of anthropic's 98% left (1.96) in
# equal windows.
KD="$WORK/ad-reset-kept"; KH="$WORK/home-reset-kept"
mkdir -p -- "$KD" "$KH/.agentkit/state"
wideworkers "$KH"
headroomadapter "$KD" claude 2; headroomadapter "$KD" muse none
headroomadapter "$KD" grokbuild meterless
headroomadapter "$KD" opencode meterless
printf '2\n' >"$KD/codex.resets"; printf '95\n' >"$KD/codex.used"
cat >"$KD/codex.sh" <<SH
#!/usr/bin/env bash
set -uo pipefail
S="$KD/codex"
SH
cat >>"$KD/codex.sh" <<'SH'
used=$(cat "$S.used"); half=$(( $(date +%s) + 302400 ))
case "${1:-}" in
usage)
  printf '{"meters":[{"name":"weekly","used":%s,"resets_at":%s,"window_secs":604800}]}\n' \
    "$used" "$half" ;;
reset-status)
  # the credits list answers once, and never again once a credit has been spent
  [ -f "$S.spent" ] && { printf '{"error":"HTTP 502 from the credits list"}\n'; exit 1; }
  printf '{"available":%s,"applicable":null,"weekly_used":%s,"resets_at":%s,"error":null}\n' \
    "$(cat "$S.resets")" "$used" "$half" ;;
reset)
  : >"$S.spent"; printf '1\n' >"$S.resets"; printf '5\n' >"$S.used"   # the fresh week it opens
  printf '{"code":"reset","available":1,"weekly_used":5,"resets_at":%s,"error":null}\n' "$half" ;;
*) echo "fake adapter: no $1" >&2; exit 2 ;;
esac
SH
chmod +x "$KD/codex.sh"
HOME="$KH" AGENTKIT_ADAPTER_DIR="$KD" ak usage >"$WORK/reset-kept-note.txt" 2>&1
HOME="$KH" AGENTKIT_ADAPTER_DIR="$KD" ak usage --json >"$WORK/reset-kept.json" 2>&1
if jq -e '.providers.openai.resets == 1 and .providers.openai.headroom == 1.95
          and (.providers.openai.budget | . > 3.89 and . < 3.91)
          and (.providers.openai.budget_from_resets | . > 1.99 and . < 2.01)
          and .providers.anthropic.headroom == 0.98
          and .pick_order == ["astra", "opus", "grok", "spark"]' "$WORK/reset-kept.json" >/dev/null &&
   grep -q '^openai: usage-limit reset applied (1 left)$' "$WORK/reset-kept-note.txt" &&
   grep -q '^openai: 1 reset in hand counted as one full week (budget 1.9 without it)$' \
     "$WORK/reset-kept-note.txt"; then
  ok "8g a reset spent at 95% used is still counted when the credits list fails on the re-read: openai keeps 1.95 meters of headroom and ranks first on the budget the credit raises (3.9), ahead of anthropic at 2% used (1.96)"
else
  no "8g the confirmed reset count after a failed re-read"
  sed 's/^/      /' "$WORK/reset-kept-note.txt" | head -6
fi

# --- 9: transient worker failures are retried, not scored (offline) --------
wait   # the two runs launched at the top; the first spent 60s + 300s of real transient backoff
if grep -q '^rc=0$' "$WORK/retry-exec.log" && grep -q 'retrying in 60s' "$WORK/retry-exec.log" &&
   grep -q 'retrying in 300s' "$WORK/retry-exec.log" && grep -q ' PASS, .* -> ' "$WORK/retry-exec.log"; then
  ok "9a ak run retried an executor that died on an API error twice, then passed"
else
  no "9a ak run executor retry"; grep -E 'WARN|ERROR|rc=' "$WORK/retry-exec.log" | head -6 | sed 's/^/      /'
fi
if grep -q '^rc=0$' "$WORK/retry-review.log" &&
   grep -q 'reviewer fell back to spark' "$WORK/retry-review.log" &&
   grep -q ' PASS, .* -> ' "$WORK/retry-review.log"; then
  ok "9b ak run fell back to a reviewer on another provider when the first one stayed down"
else
  no "9b ak run reviewer fallback"; grep -E 'WARN|ERROR|rc=' "$WORK/retry-review.log" | head -6 | sed 's/^/      /'
fi

# --- 10: a muse 429 with a reset time feeds ak usage (offline) -------------
MH="$WORK/home-429" MB="$WORK/bin-429" MD="$WORK/ad-429"
mkdir -p -- "$MH" "$MB" "$MD" "$MH/.config/muse"
wideworkers "$MH"
# The real adapter is asked whether it can authenticate before every headless turn, and this
# HOME is a throwaway with no login in it.  Give it one, and pin XDG_CONFIG_HOME inside the
# sandbox below so the adapter can only ever read this file and never the owner's own: the
# check is about the 429 the fake `muse` prints, not about logging in.
printf '{"api_key":"smoke fixture; never a real key"}\n' >"$MH/.config/muse/auth.json"
cat >"$MB/muse" <<'SH'
#!/usr/bin/env bash
echo "429 Subscription quota exhausted for muse-spark-1.3-contributor; resets 2099-01-02T03:04:05Z" >&2
exit 1
SH
chmod +x "$MB/muse"
cp -- "$REPO/adapters/muse.sh" "$MD/"                        # the real adapter over a fake `muse`
fakeadapter "$MD" claude pass; fakeadapter "$MD" codex pass  # so `ak usage` needs no network
fakeadapter "$MD" grokbuild meterless
fakeadapter "$MD" opencode meterless
R=$(newrepo repo-429)
printf 'hi\n' >"$WORK/p-429.txt"
# prime the 5 min meter cache first, the way a real run does: the 429 has to invalidate it,
# or `ak usage` keeps answering "meta reports nothing" long after the quota is gone
HOME="$MH" AGENTKIT_ADAPTER_DIR="$MD" ak usage --json >"$WORK/usage-429pre.json" 2>&1
HOME="$MH" XDG_CONFIG_HOME="$MH/.config" PATH="$MB:$PATH" AGENTKIT_ADAPTER_DIR="$MD" \
  ak worker spark "$WORK/p-429.txt" \
  --workspace "$R" --out "$WORK/o-429" >"$WORK/muse429.log" 2>&1
WANT=$(python3 -c "import calendar, time
print(calendar.timegm(time.strptime('2099-01-02T03:04:05Z', '%Y-%m-%dT%H:%M:%SZ')))")
META="$MH/.agentkit/state/usage-meta.json"
HOME="$MH" AGENTKIT_ADAPTER_DIR="$MD" ak usage --json >"$WORK/usage-429.json" 2>&1
if jq -e --argjson w "$WANT" \
      '.meters == [{name:"quota", used:100, resets_at:$w, window_secs:604800}]' "$META" >/dev/null 2>&1 &&
   [ "$(jq -r '.providers.meta.exhausted' "$WORK/usage-429.json" 2>/dev/null)" = true ] &&
   [ "$(jq -r '.pick_order | index("spark")' "$WORK/usage-429.json" 2>/dev/null)" = null ] &&
   [ "$(jq -r '.providers.meta.meters | length' "$WORK/usage-429pre.json" 2>/dev/null)" = 0 ]; then
  ok "10a muse 429: usage-meta.json quota 100% until $WANT in a weekly window, sized from a reset further off than the 5h one, and a primed cache is dropped so meta reads EXHAUSTED and spark leaves the pick order"
else
  no "10a muse 429: $(cat "$META" 2>/dev/null || echo 'no usage-meta.json')"
  sed 's/^/      /' "$WORK/muse429.log" | head -3
fi
if [ -s "$META" ]; then
  python3 - "$META" <<'PY'
import json, pathlib, sys, time
path = pathlib.Path(sys.argv[1])
blob = json.loads(path.read_text())
blob["meters"][0]["resets_at"] = int(time.time()) - 60       # the quota has since reset
path.write_text(json.dumps(blob))
PY
fi
# else the 5 min cache answers, and inside the minute nobody does: a minute on, the adapter
rm -f -- "$MH/.agentkit/state/usage.json" "$MH/.agentkit/state/"*-probe.lock
HOME="$MH" AGENTKIT_ADAPTER_DIR="$MD" ak usage --json >"$WORK/usage-429b.json" 2>&1
if [ "$(jq -r '.providers.meta.meters | length' "$WORK/usage-429b.json" 2>/dev/null)" = 0 ] &&
   [ "$(jq -r '.providers.meta.exhausted' "$WORK/usage-429b.json" 2>/dev/null)" = false ]; then
  ok "10b muse 429: past its reset the quota file is ignored and meta is unknown again"
else
  no "10b muse 429 after reset: $(jq -c '.providers.meta' "$WORK/usage-429b.json" 2>/dev/null)"
fi

# --- 11: a cached meter past its reset is dropped on read (offline) --------
# The 5 min cache must never answer with a meter whose window has already rolled over -- and
# it must manage that without the cache file being deleted first, the way check 10b does it.
# Only meta's meter is expired, so only its adapter is re-read, and that needs no network.
EHOME="$WORK/expiredhome"
ECACHE="$EHOME/.agentkit/state/usage.json"
mkdir -p -- "$EHOME/.agentkit/state"
wideworkers "$EHOME"
expiredcache() {   # anthropic, openai, xai and mimo fresh, meta's quota 60s past its reset
  python3 - "$ECACHE" <<'PY'
import json, sys, time
now = time.time()
def meter(name, used, resets_at):
    return {"name": name, "used": used, "resets_at": resets_at, "window_secs": 604800,
            "elapsed": 0.0, "pace": 0.0, "exhausted": False}
def prov(name, harness, via, meters):
    return {"provider": name, "harness": harness, "via": via, "meters": meters, "pace": 0.0,
            "error": None, "exhausted": False}
providers = {
    "anthropic": prov("anthropic", "claude", "fable", [meter("weekly_all", 40.0, now + 3600),
                                                       meter("weekly_scoped", 40.0, now + 3600)]),
    "openai": prov("openai", "codex", "astra", [meter("primary_window", 40.0, now + 3600)]),
    "meta": prov("meta", "muse", "spark", [meter("quota", 100.0, now - 60)]),
    # xai and mimo were read before and have no window to roll over, so the fresh cache
    # serves them as-is and no probe runs: a missing subscription provider would rank last,
    # never neutrally.  mimo is payg, so while any subscription is at or behind pace it
    # stays out of the order below; the none mark is what keeps that rank when it is in.
    "xai": {**prov("xai", "grokbuild", "grok", []), "none": True,
            "none_reason": "no meter: smoke fixture"},
    "mimo": {**prov("mimo", "opencode", "mimo", []), "none": True,
             "none_reason": "no meter: smoke fixture"},
}
with open(sys.argv[1], "w") as fh:
    json.dump({"fetched_at": now, "providers": providers}, fh)
PY
}
expiredcache
HOME="$EHOME" ak usage --json >"$WORK/usage-expired.json" 2>&1
if [ "$(jq -r '.providers.meta.meters | length' "$WORK/usage-expired.json" 2>/dev/null)" = 0 ] &&
   [ "$(jq -r '.providers.meta.exhausted' "$WORK/usage-expired.json" 2>/dev/null)" = false ] &&
   [ "$(jq -rc '.pick_order' "$WORK/usage-expired.json" 2>/dev/null)" = '["opus","astra","grok","spark"]' ] &&
   jq -e '.providers.anthropic.meters[0].used == 40' "$WORK/usage-expired.json" >/dev/null 2>&1 &&
   [ -s "$ECACHE" ] && jq -e '.providers.meta.meters | length == 0' "$ECACHE" >/dev/null 2>&1; then
  ok "11a usage cache: a meta meter 60s past its reset reads as meta unknown and spark is back in the pick order, cache kept and healed"
else
  no "11a usage cache expired meter: $(jq -c '.providers.meta' "$WORK/usage-expired.json" 2>/dev/null)"
  head -3 "$WORK/usage-expired.json" | sed 's/^/      /'
fi

# 11b: re-reading must not put the rolled-over window straight back. This adapter hands back
# the meter that just expired, the way a provider late to roll its window over would.
XD="$WORK/ad-expired"
mkdir -p -- "$XD"
cat >"$XD/muse.sh" <<'SH'
#!/usr/bin/env bash
printf '{"provider":"meta","meters":[{"name":"quota","used":100,"resets_at":%s,"window_secs":18000}],"error":null}\n' \
  "$(( $(date -u +%s) - 60 ))"
SH
chmod +x "$XD/muse.sh"
expiredcache
HOME="$EHOME" AGENTKIT_ADAPTER_DIR="$XD" ak usage --json >"$WORK/usage-expired2.json" 2>&1
if [ "$(jq -r '.providers.meta.meters | length' "$WORK/usage-expired2.json" 2>/dev/null)" = 0 ] &&
   [ "$(jq -r '.providers.meta.exhausted' "$WORK/usage-expired2.json" 2>/dev/null)" = false ] &&
   jq -e '.providers.meta.meters | length == 0' "$ECACHE" >/dev/null 2>&1; then
  ok "11b usage cache: an adapter re-reporting the window that just rolled over does not get it back into the cache"
else
  no "11b usage re-read: $(jq -c '.providers.meta' "$WORK/usage-expired2.json" 2>/dev/null)"
  head -3 "$WORK/usage-expired2.json" | sed 's/^/      /'
fi

# 11c: the same meter, but on a cold cache, where the full refresh probes every adapter.
# That path reports and caches whatever the adapter says, so it needs the same rule: an
# already-expired meter is dropped there too, and the provider reads unknown, not exhausted.
fakeadapter "$XD" claude pass; fakeadapter "$XD" codex pass   # so the cold refresh needs no network
fakeadapter "$XD" grokbuild meterless
fakeadapter "$XD" opencode meterless
rm -f -- "$ECACHE"
HOME="$EHOME" AGENTKIT_ADAPTER_DIR="$XD" ak usage --json >"$WORK/usage-expired3.json" 2>&1
if [ "$(jq -r '.providers.meta.meters | length' "$WORK/usage-expired3.json" 2>/dev/null)" = 0 ] &&
   jq -e '.providers.meta.error | strings | startswith("unknown:")' "$WORK/usage-expired3.json" \
     >/dev/null 2>&1 &&
   [ "$(jq -r '.providers.meta.exhausted' "$WORK/usage-expired3.json" 2>/dev/null)" = false ] &&
   [ "$(jq -r '.pick_order | index("spark")' "$WORK/usage-expired3.json" 2>/dev/null)" != null ] &&
   jq -e '.providers.meta.meters | length == 0' "$ECACHE" >/dev/null 2>&1; then
  ok "11c usage cold cache: an adapter reporting a meter 60s past its reset reads as meta unknown and is not cached"
else
  no "11c usage cold cache expired meter: $(jq -c '.providers.meta' "$WORK/usage-expired3.json" 2>/dev/null)"
  head -3 "$WORK/usage-expired3.json" | sed 's/^/      /'
fi

# --- 12: a run that cannot exclude build junk stops instead (offline) ------
# `.git/info` as a plain file stands in for an exclude file that cannot be written: git still
# works, the append cannot. The guarantee is unconditional, so the run must end there -- before
# it spends a model call on work whose junk the sweep would commit.
XAD="$WORK/ad-noexclude"; XAH="$WORK/home-noexclude"
mkdir -p -- "$XAD" "$XAH"
fakeadapter "$XAD" claude work; fakeadapter "$XAD" codex pass; fakeadapter "$XAD" muse pass
fakeadapter "$XAD" grokbuild meterless
fakeadapter "$XAD" opencode meterless
R=$(newrepo repo-noexclude)
rm -rf -- "$R/.git/info"; : >"$R/.git/info"
sed "s|__REPO__|$R|" "$WORK/retry-task.md" >"$WORK/task-noexclude.md"
HOME="$XAH" AGENTKIT_ADAPTER_DIR="$XAD" ak run "$WORK/task-noexclude.md" --rounds 1 \
  --exec opus --review astra >"$WORK/noexclude.log" 2>&1
XRC=$?
if [ "$XRC" != 0 ] && grep -q 'cannot exclude build junk' "$WORK/noexclude.log" &&
   [ ! -f "$XAD/claude.n" ]; then
  ok "12 ak run stopped (exit $XRC) with an unwritable exclude file, before any model call"
else
  no "12 ak run with an unwritable exclude file: exit=$XRC, model calls=$(cat "$XAD/claude.n" 2>/dev/null || echo 0)"
  tail -3 "$WORK/noexclude.log" | sed 's/^/      /'
fi

# --- 12b: the worktree that run left behind is still `ak run clean`-able ---
# run.json has to name repo and worktree from the moment `git worktree add` returns: a run that
# dies before its first round otherwise leaves a worktree no command knows about. Cleaning it
# must not depend on the run's state either -- this one ended in `error`, never `pass`/`fail`.
XRUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/noexclude.log" | head -1)
XRUNJSON="$XAH/.agentkit/runs/$XRUNID/run.json"
XWT=$(jq -r '.worktree // empty' "$XRUNJSON" 2>/dev/null)
if [ -n "$XRUNID" ] && [ -n "$XWT" ] &&
   [ "$(jq -r '.repo // empty' "$XRUNJSON" 2>/dev/null)" = "$R" ] &&
   [ "$(jq -r '.state // empty' "$XRUNJSON" 2>/dev/null)" = error ] &&
   HOME="$XAH" ak run clean "$XRUNID" >"$WORK/clean-noexclude.log" 2>&1 && [ ! -d "$XWT" ]; then
  ok "12b ak run clean removed the worktree of the run that stopped in state error: $XWT"
else
  no "12b ak run clean after a stopped run: runid=${XRUNID:-none} state=$(jq -r '.state // "none"' "$XRUNJSON" 2>/dev/null) wt=${XWT:-none}"
  sed 's/^/      /' "$WORK/clean-noexclude.log" 2>/dev/null | head -5
fi

# --- 13: interrupted runs, resume, and gc (offline) ------------------------
# A run.json that says `running` with nothing behind it is the shape a killed run leaves. All
# three checks run against a fake HOME on a throwaway repo, so no real run is ever touched.
IHOME="$WORK/home-interrupt"; IAD="$WORK/ad-interrupt"
mkdir -p -- "$IHOME" "$IAD"
fakeadapter "$IAD" claude work; fakeadapter "$IAD" codex pass; fakeadapter "$IAD" muse pass
fakeadapter "$IAD" grokbuild meterless
fakeadapter "$IAD" opencode meterless
R=$(newrepo repo-interrupt)
sed "s|__REPO__|$R|" "$WORK/retry-task.md" >"$WORK/task-interrupt.md"
HOME="$IHOME" AGENTKIT_ADAPTER_DIR="$IAD" ak run "$WORK/task-interrupt.md" --rounds 1 \
  --exec opus --review astra --no-merge >"$WORK/interrupt.log" 2>&1
IRUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/interrupt.log" | head -1)
IJSON="$IHOME/.agentkit/runs/$IRUNID/run.json"
# rewind it to a run that was killed mid-round: state running, no rounds done, a pid long gone
python3 - "$IJSON" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]); s = json.loads(p.read_text())
s.update(state="running", pid=999999, verdict=None, round_summaries=[], merged=False)
p.write_text(json.dumps(s, indent=2))
PY
ISTAT=$(HOME="$IHOME" ak run status --plain "$IRUNID" 2>&1)
if grep -q ' interrupted ' <<<"$ISTAT" &&
   [ "$(jq -r .state "$IJSON" 2>/dev/null)" = interrupted ]; then
  ok "13a ak run status: a run that says running with a dead pid reads as interrupted"
else
  no "13a ak run status on a dead pid: $ISTAT"
fi

# 13b: and it can be picked back up, in the worktree and the sessions it left behind
if HOME="$IHOME" AGENTKIT_ADAPTER_DIR="$IAD" ak run resume "$IRUNID" \
     >"$WORK/resume.log" 2>&1 && grep -q ' PASS, .* -> ' "$WORK/resume.log" &&
   grep -q '^\[[0-9:]*\] resuming at round 1/1' "$WORK/resume.log"; then
  ok "13b ak run resume: restarted the interrupted run at round 1 and finished it"
else
  no "13b ak run resume"; tail -4 "$WORK/resume.log" | sed 's/^/      /'
fi

# 13c: gc takes down an old merged worktree while retaining the result and branch
python3 - "$IJSON" <<'PY'
import json, pathlib, sys, time
p = pathlib.Path(sys.argv[1]); s = json.loads(p.read_text())
s.update(merged=True, finished_at=time.time() - 8 * 86400)
p.write_text(json.dumps(s, indent=2))
PY
IWT=$(jq -r '.worktree // empty' "$IJSON")
HOME="$IHOME" ak run gc >"$WORK/gc.log" 2>&1
if grep -q "remove merged-worktree" "$WORK/gc.log" && [ ! -d "$IWT" ] &&
   [ -f "$IHOME/.agentkit/runs/$IRUNID/result.md" ] &&
   ! grep -qF "$IWT" <<<"$(git -C "$R" worktree list)"; then
  ok "13c ak run gc: a merged run 8 days old lost its worktree and retained its result"
else
  no "13c ak run gc: $(cat "$WORK/gc.log")"
fi

# --- 14: a repo's env file reaches the workers and the done-when commands ---
# ~/.agentkit/env/<repo-basename>.env is where a machine keeps a repo's test secrets. The fake
# adapter echoes $SMOKE_SECRET into its final.md, and the done-when command reads it too, so
# one run proves both halves.
SECHOME="$WORK/home-env"; EAD="$WORK/ad-env"
mkdir -p -- "$SECHOME/.agentkit/env" "$EAD"
fakeadapter "$EAD" claude work; fakeadapter "$EAD" codex pass; fakeadapter "$EAD" muse pass
fakeadapter "$EAD" grokbuild meterless
fakeadapter "$EAD" opencode meterless
R=$(newrepo repo-secrets)
printf '# a repo secret, never in the repo\nSMOKE_SECRET="smoke-value"\n' \
  >"$SECHOME/.agentkit/env/repo-secrets.env"
cat >"$WORK/task-env.md" <<MD
---
repo: $R
base: main
rounds: 1
---
# Smoke env file

## Goal
Nothing: the fake adapters do the work.

## Done when
\`\`\`bash
test -f retry.txt
[ "\${SMOKE_SECRET:-}" = smoke-value ]
\`\`\`
MD
HOME="$SECHOME" AGENTKIT_ADAPTER_DIR="$EAD" ak run "$WORK/task-env.md" --rounds 1 \
  --exec opus --review astra --no-merge >"$WORK/envfile.log" 2>&1
ERUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/envfile.log" | head -1)
if grep -q ' PASS, .* -> ' "$WORK/envfile.log" &&
   grep -q 'env: .*repo-secrets.env -> SMOKE_SECRET' "$WORK/envfile.log" &&
   grep -q '^SMOKE_SECRET=smoke-value$' \
     "$SECHOME/.agentkit/runs/$ERUNID/round-1/executor/final.md" 2>/dev/null; then
  ok "14 ~/.agentkit/env/repo-secrets.env reached the worker and the done-when commands"
else
  no "14 repo env file"; grep -E 'env:|done-when|WARN' "$WORK/envfile.log" | head -4 | sed 's/^/      /'
fi

# --- 16: a task with no repository at all (offline) ------------------------
# `repo: none` is a scratch workspace: no worktree, no branch, no PR, no merge. The reviewer is
# handed the files instead of a diff, and result.md links them as the deliverable. The workspace
# is the delivery: it stays after the run ends, and goes only with its run directory.
SCRH="$WORK/home-scratch"; SCRAD="$WORK/ad-scratch"
mkdir -p -- "$SCRH" "$SCRAD"
fakeadapter "$SCRAD" claude work; fakeadapter "$SCRAD" codex pass; fakeadapter "$SCRAD" muse pass
fakeadapter "$SCRAD" grokbuild meterless
fakeadapter "$SCRAD" opencode meterless
cat >"$WORK/task-scratch.md" <<'MD'
---
repo: none
rounds: 1
---
# Smoke scratch workspace

## Goal
Nothing: the fake adapters do the work.

## Done when
```bash
test -f retry.txt
```
MD
HOME="$SCRH" AGENTKIT_ADAPTER_DIR="$SCRAD" ak run "$WORK/task-scratch.md" --rounds 1 \
  --exec opus --review astra >"$WORK/scratch.log" 2>&1
SCRC=$?
SCRID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/scratch.log" | head -1)
SCRDIR="$SCRH/.agentkit/runs/$SCRID"
SCRWORK="$SCRH/.agentkit/work/$SCRID"
if [ "$SCRC" = 0 ] && grep -q ' PASS, .* -> ' "$WORK/scratch.log" &&
   [ "$(jq -r '.scratch' "$SCRDIR/run.json" 2>/dev/null)" = true ] &&
   [ "$(jq -r '.repo // "null"' "$SCRDIR/run.json" 2>/dev/null)" = null ] &&
   [ -f "$SCRWORK/retry.txt" ] && [ ! -d "$SCRH/.agentkit/wt/$SCRID" ] &&
   grep -q "^workspace: $SCRWORK\$" "$SCRDIR/result.md" &&
   grep -q '^## Deliverables$' "$SCRDIR/result.md" &&
   grep -q 'retry.txt' "$SCRDIR/result.md" &&
   grep -q '^## Workspace (' "$SCRDIR/round-1/reviewer/prompt.md"; then
  ok "16 ak run on a task with repo: none: worked in $SCRWORK, no worktree, deliverables linked, workspace kept with its run"
else
  no "16 ak run scratch workspace: exit=$SCRC run=${SCRID:-none}"
  tail -4 "$WORK/scratch.log" | sed 's/^/      /'
fi

# --- 17: ak notify --file is refused (offline) --------------------------------
# Cards carry no attachments: --file is an error wherever it appears, and nothing
# is recorded.
NFH="$WORK/home-notifyfile"
mkdir -p -- "$NFH"
printf 'deliverable\n' >"$WORK/attach.txt"
NF=0
HOME="$NFH" AGENTKIT_DISCORD_WEBHOOK= ak notify needs "smoke attachment" --file "$WORK/attach.txt" \
  >"$WORK/nf-needs.log" 2>&1
[ "$?" = 2 ] || NF=1
grep -q 'was removed' "$WORK/nf-needs.log" || NF=1
HOME="$NFH" AGENTKIT_DISCORD_WEBHOOK= ak notify done "smoke done" --file "$WORK/attach.txt" \
  >"$WORK/nf-done.log" 2>&1
[ "$?" = 2 ] || NF=1
HOME="$NFH" AGENTKIT_DISCORD_WEBHOOK= ak notify "smoke" --file "$WORK/nope.txt" \
  >"$WORK/nf-missing.log" 2>&1
[ "$?" = 2 ] || NF=1
[ -z "$(find "$NFH/.agentkit/state" -maxdepth 1 -name 'notify-*.json' 2>/dev/null)" ] || NF=1
[ "$NF" = 0 ] && ok "17 ak notify --file: refused for needs, done and freeform, and nothing recorded" \
              || no "17 ak notify --file: $(head -1 "$WORK/nf-needs.log")"

# --- 18: ak update --dry-run -----------------------------------------------
# The six harnesses, the version each is on, the command that would move it -- and muse
# saying up front that rollback requires a complete local snapshot.  A fresh HOME, so the
# plan is the shipped default's six and not whatever the owner's config names today; the
# versions are still the real installed ones, found through smoke_home's caller binary paths.
mkdir -p -- "$WORK/home-update-dry"
HOME="$WORK/home-update-dry" ak update --dry-run \
  >"$WORK/update.log" 2>&1
URC=$?
# and a PATH with none of the six on it: nothing can be upgraded, so nothing is verified
# either -- an unchanged box must not be reported as a successful update, and the gate (two
# hours of real model calls) must not run to prove that the box is still what it was.
mkdir -p -- "$WORK/home-update"
env PATH="$REPO/bin:$PYBIN:/usr/bin:/bin" HOME="$WORK/home-update" ak update >"$WORK/update-none.log" 2>&1
UNRC=$?
if [ "$URC" = 0 ] && grep -q '^claude .*: claude install latest$' "$WORK/update.log" &&
   grep -q '^codex .*: npm i -g @openai/codex@latest$' "$WORK/update.log" &&
   grep -q '^muse .*requires a complete local snapshot for rollback' "$WORK/update.log" &&
   grep -q '^grokbuild .*: grok update$' "$WORK/update.log" &&
   grep -q '^opencode .*: opencode upgrade$' "$WORK/update.log" &&
   grep -q '^antigravity .*cannot be reverted: .*: agy update$' "$WORK/update.log" &&
   grep -q 'dry run, nothing changed' "$WORK/update.log" &&
   [ "$UNRC" = 1 ] && grep -q 'nothing was upgraded' "$WORK/update-none.log" &&
   grep -q 'the gate was not run' "$WORK/update-none.log"; then
  ok "18 ak update: --dry-run names all six, and an upgrade that cannot run exits 1 without running the gate"
else
  no "18 ak update: dry-run exit=$URC, no-harness exit=$UNRC"
  sed 's/^/      /' "$WORK/update.log" "$WORK/update-none.log" 2>/dev/null | head -6
fi

# --- 18b: a partial upgrade is put back, and named per harness (offline) ---
# Fake harnesses on PATH, and a fake `bash` standing in for the gate -- no model is called, and
# the real smoke.sh (this file, already running) is never started a second time; the point is
# which commands run and which do not. First all six upgrade and the gate is green, so the new
# versions stay. Then muse's launcher replaces the binary and only then fails: claude, codex,
# grokbuild, antigravity and opencode have moved, nothing has verified that mixture and nothing
# will, so the five that can go back to what they were do, Muse restores its saved
# launcher/build/metadata, antigravity -- whose `agy update` takes no version -- says it cannot,
# and the gate is never started.
AKF="$WORK/fakeharness"; UPH="$WORK/home-updatefake"
mkdir -p -- "$AKF/bin" "$UPH"
cat >"$AKF/bin/claude" <<'SH'
#!/bin/bash
case "${1:-}" in
  --version) cat "$AKFAKE/claude.v" ;;
  install) if [ "${2:-}" = latest ]; then printf '9.9.9\n' >"$AKFAKE/claude.v"
           else printf '%s\n' "$2" >"$AKFAKE/claude.v"; fi ;;
  *) exit 2 ;;
esac
SH
cat >"$AKF/bin/codex" <<'SH'
#!/bin/bash
[ "${1:-}" = --version ] || exit 2
cat "$AKFAKE/codex.v"
SH
cat >"$AKF/bin/npm" <<'SH'
#!/bin/bash
# npm i -g @openai/codex@<version|latest>
[ "${1:-}" = i ] || exit 2
v=${3##*@}; [ "$v" = latest ] && v=9.9.9
printf '%s\n' "$v" >"$AKFAKE/codex.v"
SH
cat >"$AKF/bin/muse" <<'SH'
#!/bin/bash
dir="$AKFAKE/bin"
if [ "${1:-}" = --version ]; then
  [ "${MUSE_NO_AUTO_UPDATE:-}" = 1 ] && [ "${MUSE_LAUNCHER_INSTALL:-}" = 0 ] || exit 2
  exec "$dir/muse-bin-$(cat "$dir/.muse-version")" --version
fi
[ "${MUSE_LAUNCHER_INSTALL:-}" = 1 ] || exit 2
# Like the vendor launcher, publish a new build and metadata and delete the prior binary.
printf '%s\n' "${MUSE_LAUNCHER_INSTALL:-unset}" >"$AKFAKE/muse.env"
old=$(cat "$dir/.muse-version")
printf '#!/bin/bash\nprintf "9.9.9-R2\\n"\n' >"$dir/muse-bin-9.9.9-R2"
chmod 755 "$dir/muse-bin-9.9.9-R2"
printf '9.9.9-R2\n' >"$dir/.muse-version"
printf '{"version":"9.9.9-R2"}\n' >"$dir/.muse-release-info.json"
rm -f -- "$dir/muse-bin-$old" "$dir/muse-bin"
printf '\n# replaced launcher\n' >>"$dir/muse"
chmod 700 "$dir/muse"
exit "$(cat "$AKFAKE/muse.rc")"
SH
cat >"$AKF/bin/grok" <<'SH'
#!/bin/bash
case "${1:-}" in
  --version) cat "$AKFAKE/grok.v" ;;
  update) if [ "${2:-}" = --version ]; then printf '%s\n' "$3" >"$AKFAKE/grok.v"
          else printf '9.9.9\n' >"$AKFAKE/grok.v"; fi ;;
  *) exit 2 ;;
esac
SH
cat >"$AKF/bin/opencode" <<'SH'
#!/bin/bash
case "${1:-}" in
  --version) cat "$AKFAKE/opencode.v" ;;
  upgrade) if [ -z "${2:-}" ]; then printf '9.9.9\n' >"$AKFAKE/opencode.v"
           else printf '%s\n' "$2" >"$AKFAKE/opencode.v"; fi ;;
  *) exit 2 ;;
esac
SH
cat >"$AKF/bin/agy" <<'SH'
#!/bin/bash
case "${1:-}" in
  --version) cat "$AKFAKE/agy.v" ;;
  update) printf '9.9.9\n' >"$AKFAKE/agy.v" ;;
  *) exit 2 ;;
esac
SH
cat >"$AKF/bin/bash" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >>"$AKFAKE/gate.log"
exit "$(cat "$AKFAKE/gate.rc")"
SH
chmod +x "$AKF/bin/"*
cp "$AKF/bin/muse" "$AKF/muse-launcher.before"
akupdate() {   # akupdate <muse exit> <gate exit> <log>: all six back on their old versions
  printf '1.0.0\n' >"$AKF/claude.v"; printf '2.0.0\n' >"$AKF/codex.v"
  printf '4.0.0\n' >"$AKF/grok.v"
  printf '4.0.0\n' >"$AKF/opencode.v"; printf '4.0.0\n' >"$AKF/agy.v"
  cp "$AKF/muse-launcher.before" "$AKF/bin/muse"
  chmod 751 "$AKF/bin/muse"
  rm -f -- "$AKF/bin/"muse-bin-*
  printf '#!/bin/bash\nprintf "3.0.0-R1\\n"\n' >"$AKF/bin/muse-bin-3.0.0-R1"
  chmod 711 "$AKF/bin/muse-bin-3.0.0-R1"
  cp "$AKF/bin/muse-bin-3.0.0-R1" "$AKF/muse-bin.before"
  ln -sfn muse-bin-3.0.0-R1 "$AKF/bin/muse-bin"
  printf '3.0.0-R1\n' >"$AKF/bin/.muse-version"
  printf '{"version":"3.0.0-R1"}\n' >"$AKF/bin/.muse-release-info.json"
  chmod 640 "$AKF/bin/.muse-version" "$AKF/bin/.muse-release-info.json"
  printf '%s\n' "$1" >"$AKF/muse.rc"; printf '%s\n' "$2" >"$AKF/gate.rc"; : >"$AKF/gate.log"
  env PATH="$AKF/bin:$REPO/bin:$PYBIN:/usr/bin:/bin" HOME="$UPH" AKFAKE="$AKF" PYTHONPATH="$REPO" \
    python3 -c 'from agentkit import update; update.fresh_unavailable = lambda: ""; raise SystemExit(update.main([]))' >"$3" 2>&1
}
akvers() { printf '%s %s %s %s %s %s' "$(cat "$AKF/claude.v")" "$(cat "$AKF/codex.v")" "$(cat "$AKF/bin/.muse-version")" "$(cat "$AKF/grok.v")" "$(cat "$AKF/opencode.v")" "$(cat "$AKF/agy.v")"; }
akupdate 0 0 "$WORK/update-all.log"; UALL=$?
UAV=$(akvers); UGATE=$(cat "$AKF/gate.log")
akupdate 1 0 "$WORK/update-part.log"; UPART=$?
UPV=$(akvers)
UP=0
[ "$UALL" = 0 ] || UP=1
[ "$UAV" = "9.9.9 9.9.9 9.9.9-R2 9.9.9 9.9.9 9.9.9" ] || UP=1
case "$UGATE" in
  *tests/smoke.sh*tests/e2e-fresh.sh) grep -q 'fresh-install gate passed' "$WORK/update-all.log" || UP=1 ;;
  *) UP=1 ;;
esac
# A snapshot is assured before any harness moves; a failed Muse upgrade restores that copy.
grep -q 'update: upgrading muse from 3.0.0-R1 (local rollback snapshot: ' "$WORK/update-all.log" || UP=1
grep -q 'update: upgrading claude from 1.0.0$' "$WORK/update-all.log" || UP=1
grep -q 'update: upgrading opencode from 4.0.0$' "$WORK/update-all.log" || UP=1
grep -q 'update: claude: upgraded, 1.0.0->9.9.9' "$WORK/update-all.log" || UP=1
grep -q 'update: codex: upgraded, 2.0.0->9.9.9' "$WORK/update-all.log" || UP=1
grep -q 'update: muse: upgraded, 3.0.0-R1->9.9.9-R2' "$WORK/update-all.log" || UP=1
grep -q 'update: upgrading grokbuild from 4.0.0$' "$WORK/update-all.log" || UP=1
grep -q 'update: grokbuild: upgraded, 4.0.0->9.9.9' "$WORK/update-all.log" || UP=1
grep -q 'update: opencode: upgraded, 4.0.0->9.9.9' "$WORK/update-all.log" || UP=1
grep -q 'update: antigravity: upgraded, 4.0.0->9.9.9' "$WORK/update-all.log" || UP=1
[ "$UPART" = 1 ] || UP=1
[ "$UPV" = "1.0.0 2.0.0 3.0.0-R1 4.0.0 4.0.0 9.9.9" ] || UP=1
[ -s "$AKF/gate.log" ] && UP=1                       # the gate must not have run at all
[ "$(cat "$AKF/muse.env")" = 1 ] || UP=1             # MUSE_LAUNCHER_INSTALL reached the launcher
grep -q 'update: claude: reverted, back on 1.0.0' "$WORK/update-part.log" || UP=1
grep -q 'update: codex: reverted, back on 2.0.0' "$WORK/update-part.log" || UP=1
grep -q 'update: muse: reverted, back on 3.0.0-R1' "$WORK/update-part.log" || UP=1
grep -q 'update: grokbuild: reverted, back on 4.0.0' "$WORK/update-part.log" || UP=1
grep -q 'update: opencode: reverted, back on 4.0.0' "$WORK/update-part.log" || UP=1
grep -q 'update: antigravity: cannot revert, .*agy update installs the latest release only' \
  "$WORK/update-part.log" || UP=1
python3 - "$AKF" <<'PY' || UP=1
import pathlib, stat, sys
root = pathlib.Path(sys.argv[1])
binary = root / "bin"
assert (binary / "muse").read_bytes() == (root / "muse-launcher.before").read_bytes()
assert (binary / "muse-bin-3.0.0-R1").read_bytes() == (root / "muse-bin.before").read_bytes()
assert (binary / ".muse-release-info.json").read_text() == '{"version":"3.0.0-R1"}\n'
assert (binary / "muse-bin").readlink() == pathlib.Path("muse-bin-3.0.0-R1")
for name, mode in (("muse", 0o751), ("muse-bin-3.0.0-R1", 0o711),
                   (".muse-version", 0o640), (".muse-release-info.json", 0o640)):
    assert stat.S_IMODE((binary / name).stat().st_mode) == mode
assert not (binary / "muse-bin-9.9.9-R2").exists()
PY
grep -q 'the gate was not run' "$WORK/update-part.log" || UP=1
if [ "$UP" = 0 ]; then
  ok "18b ak update: a green gate keeps all six, and a failed upgrade restores the five that can go back, including Muse's exact saved build, and antigravity says it cannot"
else
  no "18b ak update revert: all=$UALL ($UAV) partial=$UPART ($UPV) gate=$(wc -c <"$AKF/gate.log")"
  grep '^update: ' "$WORK/update-part.log" | sed 's/^/      /' | head -6
fi

# --- 19: base is where the run starts, target is where it ships (offline) ---
# The whole merge pipeline against a bare repo standing in for origin and a fake `gh` that only
# records what it was called with. The run is cut from `feature` and targets `main`, which has
# moved on since -- the shape that got rebased onto its own base and failed. Two things have to
# hold: the PR is opened `--base main`, and because the executor left a merge commit on the
# branch, `origin/main` comes in through `git merge` rather than a rebase that would replay the
# side branch and flatten it. The clean merge keeps the passed review: the done-when runs again
# on the integrated commit, and nothing reviews it a second time.
THOME="$WORK/home-target"; TAD="$WORK/ad-target"; TBIN="$WORK/bin-target"
GHLOG="$WORK/gh-args.log"
mkdir -p -- "$THOME" "$TAD" "$TBIN"
fakeadapter "$TAD" claude mergework; fakeadapter "$TAD" codex pass; fakeadapter "$TAD" muse pass
fakeadapter "$TAD" grokbuild meterless
fakeadapter "$TAD" opencode meterless
cat >"$TBIN/gh" <<SH
#!/usr/bin/env bash
GHLOG="$GHLOG"
SH
cat >>"$TBIN/gh" <<'SH'
printf '%s\n' "$*" >>"$GHLOG"
case "${1:-} ${2:-}" in
  "pr create") printf 'https://github.com/smoke/smoke/pull/7\n' ;;
  "api graphql") printf '{"data":{"repository":{"ref":{"branchProtectionRule":null}}}}\n' ;;
  "api --paginate") printf '[]\n' ;;   # target requires no checks
  "pr merge")  printf 'merged\n' ;;
esac
exit 0
SH
chmod +x "$TBIN/gh"
TORIGIN="$WORK/target-origin.git"; git init -q --bare -b main -- "$TORIGIN"
TR=$(newrepo repo-target)
git -C "$TR" remote add origin "$TORIGIN"
git -C "$TR" push -q -u origin main
git -C "$TR" checkout -q -b feature
printf 'feature\n' >"$TR/feature.txt"; git -C "$TR" add -A; git -C "$TR" commit -qm "on feature"
git -C "$TR" push -q -u origin feature
git -C "$TR" checkout -q main    # main moves on after the branch is cut, so it really has to come in
printf 'moved\n' >"$TR/main.txt"; git -C "$TR" add -A; git -C "$TR" commit -qm "main moved on"
git -C "$TR" push -q origin main
git -C "$TR" fetch -q origin
cat >"$WORK/task-target.md" <<MD
---
repo: $TR
base: feature
target: main
rounds: 2
---
# Smoke target branch

## Goal
Nothing: the fake adapters do the work.

## Done when
\`\`\`bash
test -f retry.txt
\`\`\`
MD
HOME="$THOME" AGENTKIT_ADAPTER_DIR="$TAD" AGENTKIT_DISCORD_WEBHOOK=off PATH="$TBIN:$PATH" \
  ak run "$WORK/task-target.md" --rounds 2 --exec opus --review astra >"$WORK/target.log" 2>&1
TRC=$?
TRUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/target.log" | head -1)
TJSON="$THOME/.agentkit/runs/$TRUNID/run.json"
TWT=$(jq -r '.worktree // empty' "$TJSON" 2>/dev/null)
TBR=$(jq -r '.branch // empty' "$TJSON" 2>/dev/null)
TG=0
[ "$TRC" = 0 ] || TG=1
[ -n "$TBR" ] || TG=1
[ "$(jq -r '.base // empty' "$TJSON" 2>/dev/null)" = feature ] || TG=1
[ "$(jq -r '.target // empty' "$TJSON" 2>/dev/null)" = main ] || TG=1
[ "$(jq -r '.merged // empty' "$TJSON" 2>/dev/null)" = true ] || TG=1
grep -q "^pr create --base main --head ${TBR:-?} " "$GHLOG" || TG=1
grep -q -- "--- merge: merging origin/main into ${TBR:-?}\$" "$WORK/target.log" || TG=1
TSHA=$(jq -r '.review.head_sha // empty' "$TJSON" 2>/dev/null)
if [ -n "$TWT" ] && [ -n "$TSHA" ]; then
  # the side merge is still in the delivered history, so the branch was merged
  # into and not replayed onto origin; the checkout itself went with the merge
  grep -qx 'Merge side-1' <<<"$(git -C "$TR" log --format=%s "$TSHA")" || TG=1
  git -C "$TR" merge-base --is-ancestor origin/main "$TSHA" || TG=1
  [ "$TSHA" = "$(jq -r '.delivery_sha // empty' "$TJSON")" ] || TG=1  # reviewed == delivered tip
  [ ! -e "$TWT" ] || TG=1
  git -C "$TR" rev-parse --verify --quiet "refs/heads/${TBR:-?}" >/dev/null 2>&1 && TG=1
  [ "$(cat "$TAD/codex.n")" = 1 ] || TG=1  # one review, kept through the clean merge
else
  TG=1
fi
if [ "$TG" = 0 ]; then
  ok "19 ak run: cut from feature, PR opened --base main, and origin/main merged in with the branch's merge commit intact"
else
  no "19 ak run base/target: exit=$TRC base=$(jq -r '.base // "none"' "$TJSON" 2>/dev/null) target=$(jq -r '.target // "none"' "$TJSON" 2>/dev/null) merged=$(jq -r '.merged // "none"' "$TJSON" 2>/dev/null)"
  diagnose "$TRC" "$WORK/target.log" ak run "$WORK/task-target.md" --rounds 2 --exec opus --review astra
  diagnose trace "$GHLOG" gh
fi

# --- 20: the menu (offline) --------------------------------------------------
# `ak` with no arguments. A fresh HOME with a current empty-meter cache, so nothing probes a
# provider; `--dry-run` skips the pull and never attaches or starts anything. tmux is real, so
# whatever seats are live show up in the rows -- the checks read the parts that do not depend
# on them: the key line, the two new-session prompts and their defaults, and no session file.
MHOME="$WORK/home-menu"
mkdir -p -- "$MHOME/.agentkit/state"
python3 - "$MHOME/.agentkit/state/usage.json" <<'PY'
import json, sys, time
providers = {}
for name, harness, via in (("anthropic", "claude", "fable"),
                           ("openai", "codex", "astra"), ("meta", "muse", "spark")):
    providers[name] = {"provider": name, "harness": harness, "via": via, "meters": [],
                       "pace": None, "error": "unknown: smoke cache", "exhausted": False}
with open(sys.argv[1], "w") as fh:
    json.dump({"fetched_at": time.time(), "providers": providers}, fh)
PY
MENU=0
printf 'q\n' | HOME="$MHOME" ak --dry-run >"$WORK/menu-q.log" 2>&1 || MENU=1
# the key line is those five letter keys and nothing else; numbers open seats
grep -q '^  n new   x stop   c config   i info   q leave' "$WORK/menu-q.log" || MENU=1
grep -q 'p preview\|b browser\|r runs\|u update\|s shell' "$WORK/menu-q.log" && MENU=1
# `c` lists the config with its values and `i` is one screen; `r`/`p`/`b`/`s`/`u` are not keys
printf 'c\nq\nq\n' | HOME="$MHOME" ak --dry-run >"$WORK/menu-c.log" 2>&1 || MENU=1
grep -q 'orchestrator  worker  effort' "$WORK/menu-c.log" || MENU=1
printf 'i\nq\nq\n' | HOME="$MHOME" ak --dry-run >"$WORK/menu-i.log" 2>&1 || MENU=1
grep -q '^agentkit: you talk to one orchestrator' "$WORK/menu-i.log" || MENU=1
for key in r p b s u; do
  printf "$key\nq\n" | HOME="$MHOME" ak --dry-run >"$WORK/menu-$key.log" 2>&1 || MENU=1
  grep -q "not a key: '$key'" "$WORK/menu-$key.log" || MENU=1
done
printf 'q\n' | HOME="$MHOME" ak attach --dry-run >"$WORK/menu-attach.log" 2>&1 || MENU=1
grep -q 'n new' "$WORK/menu-attach.log" || MENU=1
# from a pipe `n` asks Orchestrator and Workers a line at a time, and no Name: Enter takes each
# default, the seat is named for its orchestrator, and a dry run only says what it would start
printf 'n\n\n\n' | HOME="$MHOME" ak --dry-run >"$WORK/menu-n.log" 2>&1 || MENU=1
grep -q '^Workers \[opus astra\]:' "$WORK/menu-n.log" || MENU=1
grep -q '^Orchestrator \[opus\]:' "$WORK/menu-n.log" || MENU=1
grep -q '^Name' "$WORK/menu-n.log" && MENU=1
MSESSION=$(sed -n 's/^would start \(opus\(-[0-9]*\)\{0,1\}\): opus, workers opus astra$/\1/p' "$WORK/menu-n.log")
[ -n "$MSESSION" ] && grep -q "^would attach $MSESSION\$" "$WORK/menu-n.log" || MENU=1
# EOF takes the defaults as well; and neither starts a session: no record, no rulebook
printf 'n\n' | HOME="$MHOME" ak --dry-run >"$WORK/menu-n-eof.log" 2>&1 || MENU=1
grep -q '^would start opus' "$WORK/menu-n-eof.log" || MENU=1
ls "$MHOME/.agentkit/state" | grep -qE '^(session|rulebook)-' && MENU=1
printf 'zz\nq\n' | HOME="$MHOME" ak --dry-run >"$WORK/menu-bad.log" 2>&1 || MENU=1
grep -q "not a key: 'zz'" "$WORK/menu-bad.log" || MENU=1
[ "$MENU" = 0 ] && ok "20 the menu: numbers and n/x/c/i/q on the line, c placeholder and i info, r/p/b/s/u refused, q quits, n asks Orchestrator and Workers with defaults and would start ${MSESSION:-?} creating no session, and a stray key is refused" \
              || no "20 the menu"; [ "$MENU" = 0 ] || sed 's/^/      /' "$WORK/menu-n.log" | head -12

# --- 20c: the menu offers only what makes sense, and works from any terminal (offline) ---
# Every shipped model -- fable,opus,astra,spark,grok,gemini,mimo -- is offered as orchestrator and as
# worker, and Enter takes the defaults, opus orchestrating for opus and astra; sol is no model
# and is never listed. An unknown TERM becomes xterm-256color for tmux.
OHOME="$WORK/home-offer"
mkdir -p -- "$OHOME/.agentkit/state"
python3 - "$OHOME/.agentkit/state/usage.json" <<'PY'
import json, sys, time
providers = {}
for name, harness, via in (("anthropic", "claude", "fable"),
                           ("openai", "codex", "astra"), ("meta", "muse", "spark")):
    providers[name] = {"provider": name, "harness": harness, "via": via, "meters": [],
                       "pace": None, "error": "unknown: smoke cache", "exhausted": False}
with open(sys.argv[1], "w") as fh:
    json.dump({"fetched_at": time.time(), "providers": providers}, fh)
PY
OFFER=0
printf 'n\n\n\n' | HOME="$OHOME" ak --dry-run >"$WORK/offer-n.log" 2>&1 || OFFER=1
grep -q '^Workers \[opus astra\]:' "$WORK/offer-n.log" || OFFER=1
grep -q '^Orchestrator \[opus\]:' "$WORK/offer-n.log" || OFFER=1
grep -q '^would start opus\(-[0-9]*\)\{0,1\}: opus, workers opus astra$' "$WORK/offer-n.log" || OFFER=1
# the orchestrator choices are every model in file order, no sol
grep -q ' 1 fable ' "$WORK/offer-n.log" || OFFER=1
grep -q ' 2 opus ' "$WORK/offer-n.log" || OFFER=1
grep -q ' 3 astra ' "$WORK/offer-n.log" || OFFER=1
grep -q ' 4 spark' "$WORK/offer-n.log" || OFFER=1
grep -q ' 5 grok' "$WORK/offer-n.log" || OFFER=1
grep -q ' 6 gemini' "$WORK/offer-n.log" || OFFER=1
grep -q ' 7 mimo' "$WORK/offer-n.log" || OFFER=1
! grep -qw sol "$WORK/offer-n.log" || OFFER=1
# choosing astra (3) keeps the default workers, astra itself among them
printf '3\n\n' | HOME="$OHOME" ak orch --dry-run smoke-offer-astra >"$WORK/offer-astra.log" 2>&1 || OFFER=1
grep -q '^Orchestrator \[opus\]:' "$WORK/offer-astra.log" || OFFER=1
grep -q '^Workers' "$WORK/offer-astra.log" || OFFER=1
jq -e '.orchestrator == "astra" and .workers == ["opus", "astra"]' \
  "$OHOME/.agentkit/state/session-smoke-offer-astra.json" >/dev/null 2>&1 || OFFER=1
# choosing spark (4) keeps the same two
printf '4\n\n' | HOME="$OHOME" ak orch --dry-run smoke-offer-spark >"$WORK/offer-spark.log" 2>&1 || OFFER=1
grep -q '^Orchestrator \[opus\]:' "$WORK/offer-spark.log" || OFFER=1
grep -q '^Workers' "$WORK/offer-spark.log" || OFFER=1
jq -e '.orchestrator == "spark" and .workers == ["opus", "astra"]' \
  "$OHOME/.agentkit/state/session-smoke-offer-spark.json" >/dev/null 2>&1 || OFFER=1
# choosing fable (1), `all` takes all seven workers, fable itself included
printf '1\nall\n' | HOME="$OHOME" ak orch --dry-run smoke-offer-fable >"$WORK/offer-fable.log" 2>&1 || OFFER=1
grep -q '^Orchestrator \[opus\]:' "$WORK/offer-fable.log" || OFFER=1
grep -q '^Workers' "$WORK/offer-fable.log" || OFFER=1
jq -e '.orchestrator == "fable" and .workers == ["fable", "opus", "astra", "spark", "grok", "gemini", "mimo"]' \
  "$OHOME/.agentkit/state/session-smoke-offer-fable.json" >/dev/null 2>&1 || OFFER=1
# --workers sol is rejected with a one-line message
HOME="$OHOME" ak orch --dry-run --model astra --workers sol smoke-offer-sol >"$WORK/offer-sol.log" 2>&1
[ "$?" = 2 ] || OFFER=1
grep -q 'sol' "$WORK/offer-sol.log" || OFFER=1
# -eq, not =: BSD wc pads its count with spaces, GNU wc does not
[ "$(wc -l <"$WORK/offer-sol.log")" -eq 1 ] || OFFER=1
printf '\n' | HOME="$OHOME" ak orch --dry-run --model astra --workers astra smoke-offer-self >"$WORK/offer-self.log" 2>&1 || OFFER=1
grep -q '^orch: astra (' "$WORK/offer-self.log" || OFFER=1
jq -e '.orchestrator == "astra" and .workers == ["astra"]' \
  "$OHOME/.agentkit/state/session-smoke-offer-self.json" >/dev/null 2>&1 || OFFER=1
HOME="$OHOME" ak usage >"$WORK/offer-usage.log" 2>&1 || OFFER=1
! grep -qw sol "$WORK/offer-usage.log" || OFFER=1
# an unknown terminal type is exported as xterm-256color for the tmux command
printf '\n\n\n' | TERM=bogus-term HOME="$OHOME" ak orch --dry-run smoke-offer-term >"$WORK/offer-term.log" 2>&1 || OFFER=1
grep -q 'TERM=xterm-256color' "$WORK/offer-term.log" || OFFER=1
[ "$OFFER" = 0 ] && ok "20c the menu offers every model as orchestrator and as worker with the defaults on Enter, rejects sol, and an unknown TERM runs as xterm-256color" \
               || no "20c menu offering"; [ "$OFFER" = 0 ] || sed 's/^/      /' "$WORK/offer-astra.log" "$WORK/offer-spark.log" "$WORK/offer-sol.log" "$WORK/offer-self.log" "$WORK/offer-term.log" | head -16

# --- 20b: on a client the menu runs over ssh ------------------------------------
# A fake `ssh` stands in for the server: the menu runs once and returns.
CHOME="$WORK/home-client"; CBIN="$WORK/bin-client"; SSHLOG="$WORK/ssh-args.log"
mkdir -p -- "$CHOME/.agentkit/state" "$CBIN"
printf 'srv\n' >"$CHOME/.agentkit/state/server"
cat >"$CBIN/ssh" <<SH
#!/usr/bin/env bash
SSHLOG="$SSHLOG"
SH
cat >>"$CBIN/ssh" <<'SH'
printf '%s\n' "$*" >>"$SSHLOG"
case "$*" in
  "-t srv ak --client") exit 0 ;;
  *) echo "fake ssh: unexpected $*" >&2; exit 9 ;;
esac
SH
chmod +x "$CBIN"/*
: >"$SSHLOG"
CLIENT=0
printf 'q\n' | HOME="$CHOME" PATH="$CBIN:$PATH" ak >"$WORK/client.log" 2>&1 || CLIENT=1
HOME="$CHOME" ak --dry-run >"$WORK/client-dry.log" 2>&1 || CLIENT=1
grep -q '^would run ssh -t srv ak --client$' "$WORK/client-dry.log" || CLIENT=1
[ "$(cat "$SSHLOG")" = "-t srv ak --client" ] || CLIENT=1
[ "$CLIENT" = 0 ] && ok "20b client: ak ran the menu over ssh -t srv ak --client once and came back" \
                || { no "20b client menu"; sed 's/^/      ssh /' "$SSHLOG" | head -8; sed 's/^/      /' "$WORK/client.log" | head -6; }

# --- 20d: finished-run receipts stay off the menu entirely (offline) --------
# Drive startup through the menu: warnings appear once before the header and never enter the
# main screen, and an ending owned by a live seat -- including one older than the runs list --
# is nowhere on it, because that seat reports it.  The notice line keeps its phone shape, so
# that is still checked -- against run.summary_line, which is where it is made.
NOTICEH="$WORK/home-notice"
mkdir -p -- "$NOTICEH/.agentkit/state"
NOTICERC=0
HOME="$NOTICEH" PYTHONPATH="$REPO" python3 - >"$WORK/menu-notice.log" 2>&1 <<'PY' || NOTICERC=1
import io
import re
import time
from contextlib import redirect_stdout

from agentkit import config, menu, orch, run

config.ensure_dirs()
LONG = ("Rewrite the finished-run notice so a phone can read it "
        "without scrolling through a merge error")
PR = "https://github.com/caller/agentkit-smoke/pull/41"
HUGE = ("https://github.enterprise.example.invalid/an-organisation-with-a-long-name/"
        "a-repository-with-a-longer-name-still/pull/1702")
cfg = config.load()
review = {"executor": "opus", "reviewer": "astra", "returncode": 0,
          "executor_provider": config.model(cfg, "opus")["provider"],
          "reviewer_provider": config.model(cfg, "astra")["provider"],
          "verdict": "PASS", "done_when": True}
for name, extra in {
    # named in launch order, which is the order run_dirs() sorts them into
    "run-1-by-hand": {"title": "Launched by hand over ssh", "state": "fail", "verdict": "FAIL",
                      "pr": PR},
    "run-2-owned": {"title": LONG, "state": "pass", "verdict": "PASS", "pr": PR,
                    "launched_session": "orch-notice", "finished_at": time.time() - 8 * 3600},
    "run-3-broken": {"title": "The run that could not merge", "state": "error", "verdict": "PASS",
                     "launched_session": "orch-notice",
                     "error": "gh pr merge failed: /home/me/.agentkit/runs/run-3-broken/log.txt\n"
                              "GraphQL: Pull request is not mergeable (mergePullRequest)"},
    "run-4-huge": {"title": LONG, "state": "pass", "verdict": "PASS", "pr": HUGE,
                   "launched_session": "orch-notice"},
    "run-5-path": {"title": "Fix ~/code/atoll/parser.py and tools/idle-compact.py",
                   "state": "pass", "verdict": "PASS", "pr": PR,
                   "launched_session": "orch-notice"},
}.items():
    d = config.RUNS / name
    d.mkdir()
    run.save_state(d, dict({"run_id": name, "merged": False, "reported": False,
                            "executor": "opus", "reviewer": "astra", "review": review,
                            "finished_at": time.time()}, **extra))

WARNING = "WARN could not check the runs: a run record could not be read"
starts = [["agentkit: reaped a loop whose process was gone", WARNING], []]
real_maintenance = orch.maintenance
def maintenance(log):                          # the notices a menu opening prints, injected:
    for line in starts.pop(0):                 # nothing on this path touches git any more
        log(line)
    real_maintenance(log)
orch.maintenance = maintenance
assert config.RUNS / "run-2-owned" in [path for path, _ in menu.run_records()]
orch.sessions = lambda: [{"name": "orch-notice", "path": str(config.CODE), "attached": False,
                          "created": int(time.time()) - 600}]


def menu_lines():
    """Every non-empty line one menu printed, the trailing `> ` prompt included."""
    out = io.StringIO()
    with redirect_stdout(out):
        assert menu.main([]) == 0
    return [line for line in out.getvalue().splitlines() if line.strip()]


lines = menu_lines()
header = next(i for i, line in enumerate(lines) if line.startswith("agentkit"))
before, screen = lines[:header], lines[header:]
assert " agentkit: reaped a loop whose process was gone" in before, lines
assert f" {WARNING}" in before and WARNING not in "\n".join(screen), lines
assert not [line for line in before if " — " in line], before   # no ending is handed back here
notices = [run.summary_line(run.read_state(config.RUNS / name))
           for name in ("run-2-owned", "run-3-broken", "run-4-huge", "run-5-path")]
owned, broken, huge, path = notices
# the notice is written with one space in front of it, and that space is in the budget
assert not any(f" {notice}" in lines for notice in notices), lines
assert all(len(f" {notice}") <= 100 for notice in notices), [len(n) for n in notices]
assert len(f" {owned}") == 100, owned                          # this one fills the line exactly
assert owned.endswith(f" — PASS — PR {PR}") and "..." in owned and LONG not in owned, owned
assert owned.startswith("Rewrite the finished-run notice so"), owned
assert broken == "The run that could not merge — ERROR — not merged", broken
# a URL too long for the line is never cut: the title gives way, then the URL becomes a number
assert huge.endswith(" — PASS — PR #1702") and HUGE not in huge, huge
assert "http" not in huge and "..." in huge, huge
# a title's path tokens are dropped, whatever separator they carry
assert path == f"Fix and — PASS — PR {PR}", path
assert any(line.strip().startswith("1  orch-notice") for line in screen), screen
assert any("usage left" in line for line in screen), screen
# The menu at rest is the projects and their seats: a run of nobody's is neither a
# heading nor a row, whatever its repository, and `ak run status` is where it is looked up.
assert not any("scratch" in line for line in screen), screen
assert not any("Launched by hand" in line or "\u21b3" in line for line in screen), screen
assert any(line == "no project" for line in screen), screen
assert not any("seats" in line for line in screen), screen
# the count is said once, on the top line; each needing row says its own word
assert sum(line.lstrip().startswith("your projects") and "need" in line
           for line in screen) <= 1, screen
# a usage row with no reading is `—` and why (v5c); a receipt is `— PASS`, `— FAIL`, `— ERROR`
RECEIPT = re.compile(r" — (?:PASS|FAIL|ERROR)\b")
assert not any(RECEIPT.search(line) or "Rewrite the finished" in line
               for line in screen), screen
second = menu_lines()
assert not [line for line in second if RECEIPT.search(line) or WARNING in line], second
assert not any("reaped a loop whose process was gone" in line for line in second), second
# opening the menu tells nobody anything, so nothing on it is marked told: `r` still owes them
assert not any(run.read_state(config.RUNS / n)["reported"] for n in
               ("run-1-by-hand", "run-2-owned", "run-3-broken", "run-4-huge", "run-5-path"))
print("\n".join(notices))
PY
[ "$NOTICERC" = 0 ] && ok "20d warnings shown once before the menu; a live seat's endings -- an eight-hour-old result included -- are nowhere on it and stay unreported, and the notice line keeps its phone shape" \
                  || { no "20d the menu's finished-run notice"; sed 's/^/      /' "$WORK/menu-notice.log" | head -14; }

# --- 20e: the menu as a popup inside a seat (offline, real tmux seats) --------
# Every seat `ak orch` starts is dressed on the way up, out of agentkit's own tmux config and
# never the user's ~/.tmux.conf: a one-line status bar, and `Ctrl-b m` bound to the same menu in
# a `display-popup` sized for the client that presses it -- the whole screen on a phone, 80% by
# 70% anywhere larger. Two seats holding a `sleep` stand in for two orchestrators, and a second
# tmux server on a socket of its own is the terminal that attaches one of them -- a popup needs
# a real client to open on, and this is the one that presses the key and reads what it drew.
# TMUX_TMPDIR puts both servers under $WORK, so the seats the popup lists are this check's own
# two and never whatever the box is running: the number to press is then always 2, and nothing
# here binds a key or starts a session on the tmux server the user's own seats live on. The
# seat's environment carries that directory and the throwaway HOME, and the popup inherits both.
OVH="$WORK/home-overlay"; OVTMP="$WORK/ovt"
mkdir -p -- "$OVH/.agentkit/state" "$OVTMP"
cp "$MHOME/.agentkit/state/usage.json" "$OVH/.agentkit/state/usage.json"
OVERLAY=0
# 20e's two servers, both throwaway: the seats on the suite's own socket in a directory of this
# check's own -- so the seats the popup lists are these two and never another check's -- and the
# terminal that attaches one of them on a socket beside it.
# The pinned UTF-8 formats need a UTF-8 client as well, even when the caller uses LANG=C.
ovtmux() { env -u TMUX LC_ALL=C.UTF-8 TMUX_TMPDIR="$OVTMP" tmux -L agentkit-test "$@"; }
ovhost() { env -u TMUX LC_ALL=C.UTF-8 TMUX_TMPDIR="$OVTMP" tmux -L agentkit-test-outer "$@"; }
TMUX_TMPDIR="$OVTMP" HOME="$OVH" PYTHONPATH="$REPO" TERM=xterm-256color LC_ALL=C.UTF-8 \
  env -u NO_COLOR python3 - >"$WORK/overlay-start.log" 2>&1 <<'PY' || OVERLAY=1
from agentkit import config, orch

config.ensure_dirs()
cfg = config.load()
config.save_session(cfg, "smoke-ov-1", "fable", ["opus"])
config.save_session(cfg, "smoke-ov-2", "astra", ["opus"])
orch.start("smoke-ov-1", "/tmp", ["sleep", "600"], "fable")
orch.start("smoke-ov-2", "/tmp", ["sleep", "600"], "astra")
PY
# the status bar, set on the sessions themselves and on nothing else. Both halves are
# plain text: the name and the orchestrator until the first classification, the one key on
# the right, the name as the title. The tick and every menu draw rewrite them through the
# one writer; a rename writes them at once. What they come to on screen is asserted
# further down.
[ "$(ovtmux show-options -t smoke-ov-1 -v status 2>/dev/null)" = on ] || OVERLAY=1
[ "$(ovtmux show-options -t smoke-ov-1 -v status-left 2>/dev/null)" = " smoke-ov-1 · fable " ] || OVERLAY=1
[ "$(ovtmux show-options -t smoke-ov-2 -v status-left 2>/dev/null)" = " smoke-ov-2 · astra " ] || OVERLAY=1
[ "$(ovtmux show-options -t smoke-ov-1 -v status-right 2>/dev/null)" = " Ctrl-b m  menu " ] || OVERLAY=1
[ "$(ovtmux show-options -t smoke-ov-1 -v set-titles-string 2>/dev/null)" = "smoke-ov-1" ] || OVERLAY=1
# the binding and the three server options, out of agentkit's own file and into the server
grep -q '^bind-key m if-shell -F .*display-popup -E -w 100% -h 100% .*attach --overlay.*display-popup -E -w 80% -h 70% .*attach --overlay' \
  "$OVH/.agentkit/state/tmux.conf" || OVERLAY=1
grep -q '^set -g mouse on$' "$OVH/.agentkit/state/tmux.conf" || OVERLAY=1
grep -q '^set -g history-limit 50000$' "$OVH/.agentkit/state/tmux.conf" || OVERLAY=1
ovtmux list-keys -T prefix 2>/dev/null | grep -q 'display-popup' || OVERLAY=1
# a phone scrolls with its finger, and has 50000 lines to scroll
[ "$(ovtmux show-options -gv mouse 2>/dev/null)" = on ] || OVERLAY=1
[ "$(ovtmux show-options -gv history-limit 2>/dev/null)" = 50000 ] || OVERLAY=1
[ "$(ovtmux show-options -t smoke-ov-1 -v remain-on-exit 2>/dev/null)" = on ] || OVERLAY=1
# a terminal for smoke-ov-1: its own tmux server, so nothing here nests, and a TERM every box has
ovtmux set-environment -t smoke-ov-1 HOME "$OVH"
ovtmux set-environment -t smoke-ov-1 TMUX_TMPDIR "$OVTMP"
ovhost new-session -d -x 130 -y 40 -s ovhost \
  "env -u TMUX TMUX_TMPDIR=$OVTMP TERM=xterm-256color tmux -L agentkit-test attach -t =smoke-ov-1" \
  || OVERLAY=1
sleep 2
ovhost send-keys -t ovhost C-b m
: >"$WORK/overlay-popup.txt"
for _ in $(seq 1 30); do
  ovhost capture-pane -p -t ovhost >"$WORK/overlay-popup.txt" 2>/dev/null
  grep -q 'n start a session   r rename this session   x stop this session   q close' "$WORK/overlay-popup.txt" && break
  sleep 1
done
# the popup drew this server's two seats, in order, under the overlay's own key line
grep -q 'n start a session   r rename this session   x stop this session   q close' "$WORK/overlay-popup.txt" || OVERLAY=1
NEEDS_GLYPH=$(LC_ALL=C.UTF-8 PYTHONPATH="$REPO" python3 -c 'from agentkit import terminal; print(terminal.glyph("needs you"))')
grep -q "1  smoke-ov-1  fable  $NEEDS_GLYPH needs you" "$WORK/overlay-popup.txt" || OVERLAY=1
grep -q "2  smoke-ov-2  astra  $NEEDS_GLYPH needs you" "$WORK/overlay-popup.txt" || OVERLAY=1
grep -q 'p preview' "$WORK/overlay-popup.txt" && OVERLAY=1   # not offered over a running session
# 2 switches this client to that seat, and the popup comes down behind it. switch-client, the
# popup closing and the seat drawing its own bar are three redraws, in that order and none of
# them instant, so this waits for the last of them and not for the first.
ovhost send-keys -t ovhost 2 Enter
OVWHERE=0
: >"$WORK/overlay-after.txt"
for _ in $(seq 1 30); do
  OVWHERE=$(ovtmux list-clients -F '#{session_name}' 2>/dev/null | grep -c '^smoke-ov-2$')
  ovhost capture-pane -p -t ovhost >"$WORK/overlay-after.txt" 2>/dev/null
  [ "$OVWHERE" = 1 ] && ! grep -q 'n start a session' "$WORK/overlay-after.txt" &&
    grep -q 'smoke-ov-2 · astra' "$WORK/overlay-after.txt" && break
  sleep 1
done
[ "$OVWHERE" = 1 ] || OVERLAY=1
grep -q 'n start a session' "$WORK/overlay-after.txt" && OVERLAY=1        # the popup came down with it
grep -q 'smoke-ov-2 · astra' "$WORK/overlay-after.txt" || OVERLAY=1   # the seat's own status bar
ovhost kill-server 2>/dev/null
ovtmux kill-server 2>/dev/null
[ "$OVERLAY" = 0 ] && ok "20e Ctrl-b m: the popup drew both seats under the overlay's own keys, 2 switched the client to smoke-ov-2 and closed the popup behind it; each seat carried the status bar agentkit's own tmux.conf dressed it with" \
                 || { no "20e the menu overlay (clients on smoke-ov-2: $OVWHERE)"; sed 's/^/      /' "$WORK/overlay-start.log" | head -4; sed 's/^/      popup /' "$WORK/overlay-popup.txt" | head -8; sed 's/^/      after /' "$WORK/overlay-after.txt" | head -8; }

# --- 20f: the name is the user's, and a seat outlives the process in it -------
# Real tmux seats on the suite's own server, driven through the menu and through `ak orch`.  A
# fake adapter stands in for the harness: a fresh seat gets `true` -- a harness that exits the
# instant it starts, which is exactly what `remain-on-exit` is there to survive -- and a resumed
# one gets a command that echoes the conversation id it was handed.  So one check reads the name
# the menu gives and the one the user gives, the refusal of a name renamed away (and its release
# once that seat is stopped),
# a seat somebody made with `tmux new`, a legacy seat on the default server, the exited seat and
# its resume, the conversation each seat is launched with -- including two seats opened in the
# same second, and a harness whose TUI can be given no id at all -- and the week-old record.
NH="$WORK/home-name"; NAD="$WORK/ad-name"; NSEAT="$NH/code/name-cwd"
mkdir -p -- "$NH/.agentkit/state" "$NAD" "$NSEAT"
git init -q -b main -- "$NSEAT"
cp "$MHOME/.agentkit/state/usage.json" "$NH/.agentkit/state/usage.json"
fakeadapter "$NAD" codex work; fakeadapter "$NAD" muse pass; fakeadapter "$NAD" grokbuild meterless
fakeadapter "$NAD" opencode meterless
cat >"$NAD/claude.sh" <<'SH'
#!/usr/bin/env bash
[ "${1:-}" = usage ] && { printf '%s\n' '{"meters":[],"error":"unknown: smoke fake"}'; exit 0; }
if [ "${1:-}" = interactive ]; then
  shift
  # <model> <effort> [<conversation> [new]], written down so a check can read what the
  # launcher handed the harness and when it handed it over
  printf '%s\n' "$*" >>"$AGENTKIT_ADAPTER_DIR/claude.args"
  # a new seat gets `true`, a harness that exits the instant it starts -- which is what
  # remain-on-exit is there to survive; a resumed one echoes the conversation it was given
  if [ -n "${3:-}" ] && [ "${4:-}" != new ]; then printf 'sh -c %q\n' "echo resumed=$3; sleep 600"
  else echo true; fi
  exit 0
fi
exit 0
SH
chmod +x "$NAD/claude.sh"
akn() { HOME="$NH" AGENTKIT_ADAPTER_DIR="$NAD" ak "$@"; }
NAME=0
for seat in my-big-task resume-seat by-hand pair-one pair-two nopin-seat; do
  tm kill-session -t "=$seat" 2>/dev/null
done
# (a) the menu's `n` names the seat for its orchestrator, and the user's own name is the one
# `ak orch rename` gives it -- in tmux, in its environment and on its bar
printf 'n\n\n\nq\n' | akn >"$WORK/name-new.log" 2>&1 || NAME=1
NAUTO=$(sed -n 's/^session \(opus\(-[0-9]*\)\{0,1\}\) is running; .*/\1/p' "$WORK/name-new.log")
jq -e '.orchestrator == "opus"' "$NH/.agentkit/state/session-$NAUTO.json" >/dev/null 2>&1 || NAME=1
akn orch rename "$NAUTO" '  My Big/Task  ' >"$WORK/name-rename.log" 2>&1 || NAME=1
tm has-session -t =my-big-task 2>/dev/null || NAME=1
# `=name:` -- that session exactly, and its current window: a display or a capture wants a pane
[ "$(tm display-message -p -t '=my-big-task:' '#S' 2>/dev/null)" = my-big-task ] || NAME=1
[ "$(tm show-environment -t =my-big-task AGENTKIT_SESSION 2>/dev/null)" \
  = "AGENTKIT_SESSION=my-big-task" ] || NAME=1
jq -e '.orchestrator == "opus"' "$NH/.agentkit/state/session-my-big-task.json" >/dev/null 2>&1 || NAME=1
# (b) a second `n` takes the next number: the first seat's name still leads to it
printf 'n\n\n\nq\n' | akn >"$WORK/name-dup.log" 2>&1 || NAME=1
NSECOND=$(sed -n 's/^session \(opus\(-[0-9]*\)\{0,1\}\) is running; .*/\1/p' "$WORK/name-dup.log")
[ -n "$NSECOND" ] && [ "$NSECOND" != "$NAUTO" ] || NAME=1
tm has-session -t "=$NSECOND" 2>/dev/null || NAME=1
# (c) `true` exited the moment the seat opened, and the seat is still there, saying so
akn orch list >"$WORK/name-list.log" 2>&1 || NAME=1
grep -qE '^my-big-task .* needs you .* opus +' <(sed -e ':a;N;$!ba;s/,\n  /,/g;s/\n  / /g' "$WORK/name-list.log") || NAME=1
[ "$(tm display-message -p -t '=my-big-task:' '#{?pane_dead,dead,alive}' 2>/dev/null)" = dead ] || NAME=1
# (d) a seat somebody made by hand is listed too, with no models to its name, for the agent in
# it: a script named for the harness an adapter launches, where a bare `sleep` would be nobody's
printf '#!/bin/sh\nwhile :; do sleep 1; done\n' >"$NAD/claude"; chmod +x "$NAD/claude"
tm new-session -d -s by-hand "$NAD/claude" || NAME=1
akn orch list >"$WORK/name-list2.log" 2>&1 || NAME=1
grep -qE '^by-hand .* [?] +[?] +' <(sed -e ':a;N;$!ba;s/,\n  /,/g;s/\n  / /g' "$WORK/name-list2.log") || NAME=1
# (e) a marked seat on the default server is listed once, as legacy; the user's own is not
tmd new-session -d -s legacy-seat sleep 600 || NAME=1
tmd set-option -t legacy-seat @ak_orch 1 >/dev/null 2>&1 || NAME=1
tmd new-session -d -s not-a-seat sleep 600 || NAME=1
akn orch list >"$WORK/name-list3.log" 2>&1 || NAME=1
grep -qE '^legacy-seat .*  legacy$' <(sed -e ':a;N;$!ba;s/,\n  /,/g;s/\n  / /g' "$WORK/name-list3.log") || NAME=1
grep -q '^not-a-seat ' "$WORK/name-list3.log" && NAME=1
# (f) the conversation a seat holds is the one it was launched with: the launcher generates the
# id, hands it to the harness as one to open (`interactive ... <id> new`) and writes it into the
# record before the seat starts.  Nothing goes looking for one afterwards, so a transcript that
# turns up in that directory later belongs to whoever wrote it and the seat keeps its own.
printf '\n\n\n' | ( cd "$NSEAT" && akn orch resume-seat ) >"$WORK/name-resume-new.log" 2>&1 || NAME=1
CONV=$(jq -r '.conversation // ""' "$NH/.agentkit/state/session-resume-seat.json" 2>/dev/null)
case "$CONV" in [0-9a-f]*-*-*-*-*) ;; *) NAME=1; CONV="not-a-conversation" ;; esac
# and it says where that id came from, because only one the launcher handed over is an id
# this seat may ever be resumed into
jq -e '.id_source == "launcher"' "$NH/.agentkit/state/session-resume-seat.json" \
  >/dev/null 2>&1 || NAME=1
ARGS=$(cat "$NAD/claude.args" 2>/dev/null)
case "$ARGS" in *"$CONV new"*) ;; *) NAME=1 ;; esac
jq -e --arg d "$NSEAT" '.cwd == $d' "$NH/.agentkit/state/session-resume-seat.json" \
  >/dev/null 2>&1 || NAME=1
# a seat nobody has typed into yet has no transcript at all -- a harness writes one when it has
# something to record -- so the id it owns is handed back as one to open rather than one to
# resume, because resuming a conversation that was never begun is an error and not a seat
akn orch resume-seat >"$WORK/name-untyped.log" 2>&1 || NAME=1
ARGS=$(cat "$NAD/claude.args" 2>/dev/null)
case "$ARGS" in *"$CONV new") ;; *) NAME=1 ;; esac
SLUG=$(printf '%s' "$NSEAT" | sed 's/[^A-Za-z0-9]/-/g')
mkdir -p -- "$NH/.claude/projects/$SLUG"
printf '{"type":"mode"}\n' >"$NH/.claude/projects/$SLUG/$CONV.jsonl"    # what the harness wrote
printf '{"type":"mode"}\n' >"$NH/.claude/projects/$SLUG/conv-1111.jsonl"   # somebody else's
printf 'q\n' | akn >"$WORK/name-menu.log" 2>&1 || NAME=1
jq -e --arg c "$CONV" '.conversation == $c' "$NH/.agentkit/state/session-resume-seat.json" \
  >/dev/null 2>&1 || NAME=1
# (f2) two seats started in the same second, in one directory, on the harness whose TUI takes
# an id: the launcher generates one for each before either process exists, so neither can be
# confused for the other, and each comes back on the conversation it was launched with
NPAIR="$NH/code/name-pair"; mkdir -p -- "$NPAIR"
git init -q -b main -- "$NPAIR"
printf '\n' | ( cd "$NPAIR" && akn orch pair-one --model fable --workers opus ) >"$WORK/name-pair1.log" 2>&1 &
printf '\n' | ( cd "$NPAIR" && akn orch pair-two --model fable --workers opus ) >"$WORK/name-pair2.log" 2>&1 &
wait
P1=$(jq -r '.conversation // ""' "$NH/.agentkit/state/session-pair-one.json" 2>/dev/null)
P2=$(jq -r '.conversation // ""' "$NH/.agentkit/state/session-pair-two.json" 2>/dev/null)
case "$P1" in [0-9a-f]*-*-*-*-*) ;; *) NAME=1; P1="not-a-conversation" ;; esac
case "$P2" in [0-9a-f]*-*-*-*-*) ;; *) NAME=1; P2="not-another" ;; esac
[ "$P1" = "$P2" ] && NAME=1
SLUGP=$(printf '%s' "$NPAIR" | sed 's/[^A-Za-z0-9]/-/g')
mkdir -p -- "$NH/.claude/projects/$SLUGP"
for pair in "pair-one:$P1" "pair-two:$P2"; do
  # what each harness wrote once it had something to record, under the id it was given
  printf '{"type":"mode"}\n' >"$NH/.claude/projects/$SLUGP/${pair#*:}.jsonl"
done
for pair in "pair-one:$P1" "pair-two:$P2"; do
  seat=${pair%%:*}
  akn orch "$seat" >"$WORK/name-$seat.log" 2>&1 || NAME=1
  grep -q "(conversation ${pair#*:})\$" "$WORK/name-$seat.log" || NAME=1
  SEEN=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    PANE=$(tm capture-pane -p -t "=$seat:" 2>/dev/null || true)
    case "$PANE" in *"resumed=${pair#*:}"*) SEEN=1 ;; esac
    [ "$SEEN" = 1 ] && break
    sleep 1
  done
  [ "$SEEN" = 1 ] || NAME=1
done
# (f3) the harness whose TUI takes no id -- Codex, Muse -- is given none, and the seat has no
# conversation at all: the record says `resumable: false`, its status bar carries the one key
# like every seat's, and a transcript that turns up in its directory afterwards is never
# claimed for it, because nothing goes looking.  Once tmux has lost that seat there is no row
# to press.
NAD3="$WORK/ad-nopin"; NNOPIN="$NH/code/name-nopin"; mkdir -p -- "$NAD3" "$NNOPIN"
git init -q -b main -- "$NNOPIN"
cat >"$NAD3/claude.sh" <<'SH'
#!/usr/bin/env bash
[ "${1:-}" = usage ] && { printf '%s\n' '{"meters":[],"error":"unknown: smoke fake"}'; exit 0; }
[ "${1:-}" = interactive ] || exit 0
# no id of anybody else's making: what the Codex and Muse adapters answer
[ "${5:-}" = new ] && { echo "this TUI cannot be given a session id" >&2; exit 3; }
echo 'sleep 600'
SH
chmod +x "$NAD3/claude.sh"
cp "$NAD/codex.sh" "$NAD/muse.sh" "$NAD3/"   # only the seat's harness is fake here, not the meters
akp() { HOME="$NH" AGENTKIT_ADAPTER_DIR="$NAD3" ak "$@"; }
printf '\n' | ( cd "$NNOPIN" && akp orch nopin-seat --model fable --workers opus ) \
  >"$WORK/name-nopin.log" 2>&1 || NAME=1
jq -e '.resumable == false and (has("conversation") | not)' \
  "$NH/.agentkit/state/session-nopin-seat.json" >/dev/null 2>&1 || NAME=1
tm show-options -t nopin-seat -v status-right 2>/dev/null \
  | grep -q 'Ctrl-b m  menu' || NAME=1
tm show-options -t pair-one -v status-right 2>/dev/null \
  | grep -q 'Ctrl-b m  menu' || NAME=1    # every seat carries the one key
SLUGX=$(printf '%s' "$NNOPIN" | sed 's/[^A-Za-z0-9]/-/g')
mkdir -p -- "$NH/.claude/projects/$SLUGX"
printf '{"type":"mode"}\n' >"$NH/.claude/projects/$SLUGX/conv-later.jsonl"   # somebody else's
printf 'q\n' | akp >"$WORK/name-nopin-menu.log" 2>&1 || NAME=1
jq -e '.resumable == false and (has("conversation") | not)' \
  "$NH/.agentkit/state/session-nopin-seat.json" >/dev/null 2>&1 || NAME=1
tm kill-session -t =nopin-seat 2>/dev/null
printf 'q\n' | akp --dry-run >"$WORK/name-nopin-gone.log" 2>&1 || NAME=1
grep -q ' nopin-seat ' "$WORK/name-nopin-gone.log" && NAME=1
# ... and its name still starts it again, fresh, where it ran
( cd "$WORK" && akp orch nopin-seat ) >"$WORK/name-nopin-restart.log" 2>&1 || NAME=1
grep -q "^orch: resuming nopin-seat on fable in $NNOPIN (no conversation recorded; it starts fresh)\$" \
  "$WORK/name-nopin-restart.log" || NAME=1
tm has-session -t =nopin-seat 2>/dev/null || NAME=1
jq -e '.resumable == false and (has("conversation") | not)' \
  "$NH/.agentkit/state/session-nopin-seat.json" >/dev/null 2>&1 || NAME=1
akp orch stop nopin-seat >/dev/null 2>&1 || NAME=1
# (f4) a record from the discovery era carries an id nobody handed the seat: back then it was
# read out of the harness's own store once the seat was running, and resuming into one is
# walking into whatever that store happened to hold.  So the read that finds it strips it: the
# record says `resumable: false`, the menu offers no row for a seat tmux has lost, and the name
# opens the seat fresh where it ran -- on a harness that can be given no id, so its status bar
# carries the one key like every seat's.
NOLD="$WORK/name-old"; mkdir -p -- "$NOLD"
python3 - "$NH/.agentkit/state/session-old-seat.json" "$NOLD" <<'OLD'
import json, sys, time
json.dump({"orchestrator": "fable", "workers": ["opus"], "cwd": sys.argv[2],
           "created": int(time.time()), "seen": int(time.time()),
           "conversation": "conv-5555", "resumable": True}, open(sys.argv[1], "w"))
OLD
printf 'q\n' | akp --dry-run >"$WORK/name-old-menu.log" 2>&1 || NAME=1
grep -q ' old-seat ' "$WORK/name-old-menu.log" && NAME=1
jq -e '.resumable == false and (has("conversation") | not)' \
  "$NH/.agentkit/state/session-old-seat.json" >/dev/null 2>&1 || NAME=1
akp orch old-seat >"$WORK/name-old-open.log" 2>&1 || NAME=1
grep -q "^orch: resuming old-seat on fable in $NOLD (no conversation recorded; it starts fresh)\$" \
  "$WORK/name-old-open.log" || NAME=1
tm show-options -t old-seat -v status-right 2>/dev/null \
  | grep -q 'Ctrl-b m  menu' || NAME=1
grep -rqF conv-5555 "$NH/.agentkit/state" 2>/dev/null && NAME=1
# (f5) and `stop` ends that seat once tmux has lost it too: what holds a name is the record,
# so stopping takes the record and the names the seat was renamed from whether or not there is
# a session left to kill and whether or not there was ever a conversation to resume into.
akp orch rename old-seat old-renamed >"$WORK/name-old-rename.log" 2>&1 || NAME=1
jq -e '.renamed == "old-renamed"' "$NH/.agentkit/state/session-old-seat.json" \
  >/dev/null 2>&1 || NAME=1
tm kill-session -t =old-renamed 2>/dev/null
akp orch stop old-renamed >"$WORK/name-old-stop.log" 2>&1 || NAME=1
grep -q '^stopped old-renamed$' "$WORK/name-old-stop.log" || NAME=1
[ -e "$NH/.agentkit/state/session-old-renamed.json" ] && NAME=1
[ -e "$NH/.agentkit/state/session-old-seat.json" ] && NAME=1   # the pointer went with it
# (g) its number -- here its name -- puts the orchestrator back in that same window, on that
# same conversation, and the seat is alive again
akn orch resume-seat >"$WORK/name-resume.log" 2>&1 || NAME=1
grep -q "^orch: resuming resume-seat on opus in the same window (conversation $CONV)\$" \
  "$WORK/name-resume.log" || NAME=1
RESUMED=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  RESUMED=$(tm capture-pane -p -t '=resume-seat:' 2>/dev/null | grep -c "resumed=$CONV" || true)
  [ "${RESUMED:-0}" -ge 1 ] && break
  sleep 1
done
[ "${RESUMED:-0}" -ge 1 ] || NAME=1
[ "$(tm display-message -p -t '=resume-seat:' '#{?pane_dead,dead,alive}' 2>/dev/null)" = alive ] || NAME=1
# (h) tmux loses the session, the record does not: the menu offers it back, and it comes back
# in the directory it ran in
tm kill-session -t =resume-seat 2>/dev/null
printf 'q\n' | akn --dry-run >"$WORK/name-ghost.log" 2>&1 || NAME=1
RESUME_GLYPH=$(PYTHONPATH="$REPO" python3 -c 'from agentkit import terminal; print(terminal.glyph("needs you"))')
grep -qE "^ +[0-9]+  resume-seat +opus +$RESUME_GLYPH needs you" "$WORK/name-ghost.log" || NAME=1
grep -q "session closed: press" "$WORK/name-ghost.log" || NAME=1
akn orch resume-seat >"$WORK/name-reopen.log" 2>&1 || NAME=1
grep -q "^orch: resuming resume-seat on opus in $NSEAT (conversation $CONV)\$" \
  "$WORK/name-reopen.log" || NAME=1
[ "$(tm display-message -p -t '=resume-seat:' '#{session_path}' 2>/dev/null)" = "$NSEAT" ] || NAME=1
# (h2) a record that names no conversation -- one written before any of this, or a seat whose
# harness never named one -- opens a conversation of its own as it comes back, and owns that one
# from then on.  A transcript somebody else left in that directory is still nobody's business.
NLOST="$WORK/name-lost"; mkdir -p -- "$NLOST"
SLUGL=$(printf '%s' "$NLOST" | sed 's/[^A-Za-z0-9]/-/g')
mkdir -p -- "$NH/.claude/projects/$SLUGL"
printf '{"type":"mode"}\n' >"$NH/.claude/projects/$SLUGL/conv-4444.jsonl"
python3 - "$NH/.agentkit/state/session-lost-seat.json" "$NLOST" <<'LOST'
import json, sys, time
json.dump({"orchestrator": "fable", "workers": ["opus"], "cwd": sys.argv[2],
           "created": int(time.time()), "seen": int(time.time())}, open(sys.argv[1], "w"))
LOST
akn orch lost-seat >"$WORK/name-lost-open.log" 2>&1 || NAME=1
grep -q "^orch: resuming lost-seat on fable in $NLOST (no conversation recorded; it starts fresh)\$" \
  "$WORK/name-lost-open.log" || NAME=1
LCONV=$(jq -r '.conversation // ""' "$NH/.agentkit/state/session-lost-seat.json" 2>/dev/null)
case "$LCONV" in [0-9a-f]*-*-*-*-*) ;; *) NAME=1; LCONV="not-a-conversation" ;; esac
[ "$LCONV" = conv-4444 ] && NAME=1
ARGS=$(cat "$NAD/claude.args" 2>/dev/null)
case "$ARGS" in *"$LCONV new"*) ;; *) NAME=1 ;; esac
akn orch stop lost-seat >/dev/null 2>&1 || NAME=1
# (h3) a harness that exits in the instant it starts, on a server that was up before agentkit
# ever configured it: the seat has to survive that too, so the options go into the server before
# the seat does
tm set -g remain-on-exit off >/dev/null 2>&1
printf '\n\n\n' | ( cd "$NSEAT" && akn orch fast-exit ) >"$WORK/name-fast.log" 2>&1 || NAME=1
sleep 1
tm has-session -t =fast-exit 2>/dev/null || NAME=1
[ "$(tm display-message -p -t '=fast-exit:' '#{?pane_dead,dead,alive}' 2>/dev/null)" = dead ] || NAME=1
akn orch stop fast-exit >/dev/null 2>&1 || NAME=1
# (h4) the legacy seat renames where it lives, on the default server and not on ours
akn orch rename legacy-seat legacy-renamed >"$WORK/name-legacy-rename.log" 2>&1 || NAME=1
tmd has-session -t =legacy-renamed 2>/dev/null || NAME=1
tmd has-session -t =legacy-seat 2>/dev/null && NAME=1
tm has-session -t =legacy-renamed 2>/dev/null && NAME=1     # never on the toolkit's own server
# (h5) and the name it used to have is not free: the orchestrator in there still answers to it
printf '\n' | akn orch legacy-seat >"$WORK/name-alias-orch.log" 2>&1; [ "$?" = 2 ] || NAME=1
grep -q "used to be called" "$WORK/name-alias-orch.log" || NAME=1
jq -e '.renamed == "legacy-renamed"' "$NH/.agentkit/state/session-legacy-seat.json" \
  >/dev/null 2>&1 || NAME=1
# (h6) ... until that seat is stopped: the pointer goes with the record it led to, and the name
# it used to be called is free again for `ak orch`, which makes a seat under it
akn orch stop legacy-renamed >"$WORK/name-legacy-stop.log" 2>&1 || NAME=1
[ -e "$NH/.agentkit/state/session-legacy-seat.json" ] && NAME=1
printf '\n' | ( cd "$NSEAT" && akn orch legacy-seat --model fable --workers opus ) \
  >"$WORK/name-alias-free.log" 2>&1 || NAME=1
jq -e --arg d "$NSEAT" '.cwd == $d and .repo == $d' \
  "$NH/.agentkit/state/session-legacy-seat.json" >/dev/null 2>&1 || NAME=1
tm has-session -t =legacy-seat 2>/dev/null || NAME=1
tm kill-session -t =legacy-seat 2>/dev/null
# (i) stop is the one thing that ends a seat: the session, and the record it could come back
# from -- the conversation id with it, so that nothing can be resumed into it ever again
akn orch stop resume-seat >"$WORK/name-stop.log" 2>&1 || NAME=1
tm has-session -t =resume-seat 2>/dev/null && NAME=1
[ -e "$NH/.agentkit/state/session-resume-seat.json" ] && NAME=1
grep -rqF "$CONV" "$NH/.agentkit/state" 2>/dev/null && NAME=1
# (j) a record whose seat has been gone for over a week is forgotten, and its name is free again
python3 - "$NH/.agentkit/state/session-stale-seat.json" <<'STALE'
import json, sys, time
json.dump({"orchestrator": "fable", "workers": ["opus"], "cwd": "/tmp",
           "created": time.time() - 9 * 86400, "seen": time.time() - 8 * 86400,
           "conversation": "conv-old"}, open(sys.argv[1], "w"))
STALE
printf 'q\n' | akn >"$WORK/name-sweep.log" 2>&1 || NAME=1
# The sweep is reported once before the header, and stays off the main screen.
python3 - "$WORK/name-sweep.log" <<'SWEEP' || NAME=1
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
lines = text.splitlines()
header_at = next(i for i, line in enumerate(lines) if line.startswith("agentkit"))
before, screen = "\n".join(lines[:header_at]), "\n".join(lines[header_at:])
assert before.count("forgot the session stale-seat, gone for 8d") == 1, text
assert "forgot the session stale-seat" not in screen, text
SWEEP
printf 'q\n' | akn >"$WORK/name-sweep-again.log" 2>&1 || NAME=1
grep -q 'forgot the session stale-seat' "$WORK/name-sweep-again.log" && NAME=1
[ -e "$NH/.agentkit/state/session-stale-seat.json" ] && NAME=1
for seat in my-big-task "$NSECOND" resume-seat by-hand pair-one pair-two old-seat old-renamed; do
  tm kill-session -t "=$seat" 2>/dev/null
done
tmd kill-session -t =not-a-seat 2>/dev/null
[ "$NAME" = 0 ] && ok "20f the seat is what it was called: n names it for its orchestrator and a second one ${NSECOND:-?}, a rename makes My Big/Task my-big-task in tmux and on its own status bar, a name renamed away is refused until that seat is stopped, a hand-made seat and a legacy one are listed and the legacy one renames on its own server, a harness that exits at once leaves the seat standing, a seat holds the conversation it was launched with and two started at once hold their own, a harness that can be given no id leaves a seat that restarts rather than resumes, an id no launcher ever handed out is stripped from the record that carries it, a stopped one is gone with its conversation -- and one tmux has already lost is stopped just the same, record and rename pointer with it -- and a week-old record is swept" \
             || { no "20f naming, exit and resume"; sed 's/^/      /' "$WORK/name-new.log" "$WORK/name-rename.log" "$WORK/name-dup.log" "$WORK/name-list3.log" "$WORK/name-resume.log" "$WORK/name-reopen.log" "$WORK/name-pair1.log" "$WORK/name-nopin.log" "$WORK/name-old-open.log" "$WORK/name-old-stop.log" 2>/dev/null | head -24; }

# --- 20g: the update runs where the connection cannot take it down --------
# `orch.start_update` starts `ak update` detached, in a tmux session of its own on the jobs
# server, and comes straight back; the result appears once, as a notice, whenever the menu is
# next drawn.  A PATH with the four harnesses hidden is what makes that update finish in a second
# and fail honestly: with nothing installed it upgrades nothing, puts nothing back, and never
# reaches the gate -- so no model is called and no version on this box moves.
UH2="$WORK/home-update"
mkdir -p -- "$UH2/.agentkit/state"
cp "$MHOME/.agentkit/state/usage.json" "$UH2/.agentkit/state/usage.json"
UPD=0
tmj kill-session -t =update 2>/dev/null
env -i HOME="$UH2" PATH="$REPO/bin:$PYBIN:/usr/bin:/bin" TERM=dumb \
  TMUX_TMPDIR="$TMUX_TMPDIR" AGENTKIT_TMUX_SOCKET=agentkit-test PYTHONPATH="$REPO" \
  python3 -c 'from agentkit import orch; print(orch.start_update())' \
  >"$WORK/update-u.log" 2>&1 || UPD=1
grep -q '^update started; result will show here$' "$WORK/update-u.log" || UPD=1
for _ in $(seq 1 60); do
  [ -s "$UH2/.agentkit/state/update-result" ] && break
  sleep 1
done
grep -qE '^ ?update: (done|FAILED) \(.*update-job-[0-9]+-[0-9]+-[a-f0-9]+\.log\)$' \
  "$UH2/.agentkit/state/update-result" 2>/dev/null || UPD=1
# the job ran there and not here: an update log under that HOME, and the gate never started
grep -q 'nothing was upgraded' "$UH2"/.agentkit/tmp/update-*.log 2>/dev/null || UPD=1
# the result is a notice line, once, and then it is gone
printf 'q\n' | HOME="$UH2" ak --dry-run >"$WORK/update-notice.log" 2>&1 || UPD=1
[ "$(grep -c '^ update: ' "$WORK/update-notice.log")" -eq 1 ] || UPD=1
printf 'q\n' | HOME="$UH2" ak --dry-run >"$WORK/update-notice2.log" 2>&1 || UPD=1
[ "$(grep -c '^ update: ' "$WORK/update-notice2.log")" -eq 0 ] || UPD=1
[ -e "$UH2/.agentkit/state/update-result" ] && UPD=1
# and the jobs server it ran on is not the menu's: no `update` row was ever drawn
grep -qE '^ +[0-9]+  update ' "$WORK/update-notice.log" && UPD=1
[ "$UPD" = 0 ] && ok "20g the detached update: it runs on the jobs server, the starter comes back at once, and its one-line result shows once as a notice" \
             || { no "20g the detached update"; sed 's/^/      /' "$WORK/update-u.log" | tail -6
                  cat "$UH2/.agentkit/state/update-result" 2>/dev/null | sed 's/^/      /'; }

# --- 21: the two notification shapes (offline) --------------------------------
# `--dry-run` prints the payload and posts nothing; without a webhook the real form prints to
# stderr and records the session's last message, which is what the menu shows. The card itself
# is two words and the seat: the question lives in the record and the log line, never on it.
NSH="$WORK/home-notify-shapes"
mkdir -p -- "$NSH/.agentkit/state"
tm kill-session -t =smoke-shape 2>/dev/null
HOME="$NSH" PYTHONPATH="$REPO" python3 - <<'PY'
from agentkit import config, orch
config.ensure_dirs()
config.save_session(config.load(), "smoke-shape", "astra", ["opus", "spark"])
orch.start("smoke-shape", "/tmp", ["sleep", "600"], "astra")
PY
SHAPE=0
printf 'shape\n' >"$WORK/shape-attach.txt"
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK=off AGENTKIT_DISCORD_USER_ID=424242 AGENTKIT_SESSION=smoke-shape \
  ak notify needs "Merge PR #7 by bob? yes/no" --dry-run >"$WORK/needs.json" 2>"$WORK/needs.err" || SHAPE=1
# Resumable seats come from HOME too, so count the same rows as this check's notify and menu.
# The listing's last line says which slice the agents run in; it is not a seat, so it is not
# counted with them.
NUM=$(HOME="$NSH" ak orch list 2>/dev/null | sed -e '/^\(no \)\?slice /d' | sed -e ':a;N;$!ba;s/,\n  /,/g;s/\n  / /g' | awk 'NR>1{print $1}' | sort | grep -n '^smoke-shape$' | cut -d: -f1)
jq -e '.content == "<@424242>" and .username == "agentkit" and (.embeds | length == 1)
  and .embeds[0].title == "Needs you · smoke-shape"
  and .embeds[0].color == 16098851
  and (has("description") | not) and (has("fields") | not) and (has("footer") | not)
  and (.embeds[0] | has("description") | not) and (.embeds[0] | has("fields") | not)
  and (.embeds[0] | has("footer") | not)' "$WORK/needs.json" >/dev/null 2>&1 || SHAPE=1
[ "$(cat "$WORK/needs.err")" = 'terminal notice: Needs you · smoke-shape: Merge PR #7 by bob? yes/no' ] || SHAPE=1
[ -e "$NSH/.agentkit/state/notify-smoke-shape.json" ] && SHAPE=1   # and records nothing
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK=off AGENTKIT_SESSION=smoke-shape ak notify done "Parser fixed" \
  --pr https://example.invalid/o/r/pull/7 --dry-run \
  >"$WORK/done.json" 2>"$WORK/done.err" || SHAPE=1
[ "$(cat "$WORK/done.err")" = 'terminal notice: Done · smoke-shape: Parser fixed' ] || SHAPE=1
jq -e '.username == "agentkit"
  and .embeds[0].title == "Done · smoke-shape" and .embeds[0].color == 3066993
  and (.embeds[0] | has("description") | not) and (.embeds[0] | has("fields") | not)
  and (.embeds[0] | has("footer") | not)
  and (has("content") | not)' "$WORK/done.json" >/dev/null 2>&1 || SHAPE=1
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK=off AGENTKIT_SESSION=smoke-shape ak notify done "FAIL: tests red" --dry-run \
  >"$WORK/done-fail.json" 2>"$WORK/done-fail.err" || SHAPE=1
[ "$(cat "$WORK/done-fail.err")" = 'terminal notice: Done · smoke-shape: FAIL: tests red' ] || SHAPE=1
jq -e '.embeds[0].color == 15158332' "$WORK/done-fail.json" >/dev/null 2>&1 || SHAPE=1
# the real form, with no webhook: stderr, exit 0, and the record the menu reads
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK= AGENTKIT_SESSION=smoke-shape ak notify needs "Which branch?" \
  >"$WORK/needs-real.log" 2>&1 || SHAPE=1
grep -q 'no webhook configured; message: Needs you . smoke-shape: Which branch?' "$WORK/needs-real.log" || SHAPE=1
jq -e '.session == "smoke-shape" and .kind == "needs" and .text == "Which branch?" and (.time | type == "number")' \
  "$NSH/.agentkit/state/notify-smoke-shape.json" >/dev/null 2>&1 || SHAPE=1
printf 'q\n' | HOME="$NSH" ak --dry-run >"$WORK/menu-shape.log" 2>&1 || SHAPE=1
grep -qE "^ *$NUM  smoke-shape +astra +! needs you +Which branch\?$" "$WORK/menu-shape.log" || SHAPE=1
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK= ak notify needs "no text" --file "$WORK/shape-attach.txt" >"$WORK/needs-file.log" 2>&1
[ "$?" = 2 ] || SHAPE=1
# the freeform message went with the attachments: needs, done or --check
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK= ak notify "plain old message" >"$WORK/plain.log" 2>&1
[ "$?" = 2 ] || SHAPE=1
[ "$SHAPE" = 0 ] && ok "21 ak notify: needs is amber, done is green and red on FAIL, every card two words and the seat, --dry-run posts nothing, the record reaches the menu row" \
               || { no "21 ak notify shapes"; head -c 600 "$WORK/needs.json" | sed 's/^/      /'; sed 's/^/      /' "$WORK/menu-shape.log" | head -5; }

# --- 22: ak orch rename follows the old name (offline, a real tmux seat) ------
# The orchestrator inside was started with the old name in $AGENTKIT_SESSION and hands it to
# every `ak` it runs, so after the rename the old name has to keep landing on the same seat:
# its selection, its notifications, its menu row.
RN=0
HOME="$NSH" AGENTKIT_SESSION=smoke-shape ak orch rename smoke-shape-renamed >"$WORK/rename.log" 2>&1 || RN=1
grep -q '^renamed smoke-shape -> smoke-shape-renamed$' "$WORK/rename.log" || RN=1
tm has-session -t =smoke-shape-renamed 2>/dev/null || RN=1
tm has-session -t =smoke-shape 2>/dev/null && RN=1
[ "$(tm show-environment -t =smoke-shape-renamed AGENTKIT_SESSION 2>/dev/null)" = "AGENTKIT_SESSION=smoke-shape-renamed" ] || RN=1
jq -e '.renamed == "smoke-shape-renamed"' "$NSH/.agentkit/state/session-smoke-shape.json" >/dev/null 2>&1 || RN=1
jq -e '.orchestrator == "astra"' "$NSH/.agentkit/state/session-smoke-shape-renamed.json" >/dev/null 2>&1 || RN=1
[ -e "$NSH/.agentkit/state/notify-smoke-shape-renamed.json" ] || RN=1
[ "$(HOME="$NSH" AGENTKIT_SESSION=smoke-shape ak usage --json 2>/dev/null | jq -c .pick_order)" = '["opus","spark"]' ] || RN=1
HOME="$NSH" AGENTKIT_DISCORD_WEBHOOK= AGENTKIT_SESSION=smoke-shape ak notify needs "still me?" >"$WORK/rename-notify.log" 2>&1 || RN=1
[ ! -s "$WORK/rename-notify.log" ] || RN=1   # same needs-you episode across the rename: recorded, not reposted
jq -e '.text == "still me?"' "$NSH/.agentkit/state/notify-smoke-shape-renamed.json" >/dev/null 2>&1 || RN=1
HOME="$NSH" ak orch rename smoke-shape-renamed smoke-shape-final >"$WORK/rename2.log" 2>&1 || RN=1
[ "$(HOME="$NSH" AGENTKIT_SESSION=smoke-shape ak usage --json 2>/dev/null | jq -c .pick_order)" = '["opus","spark"]' ] || RN=1
HOME="$NSH" ak orch rename nosuch-seat other >"$WORK/rename-bad.log" 2>&1; [ "$?" = 2 ] || RN=1
HOME="$NSH" ak orch stop smoke-shape-final >"$WORK/rename-stop.log" 2>&1 || RN=1
tm kill-session -t =smoke-shape-final 2>/dev/null
[ "$RN" = 0 ] && ok "22 ak orch rename: tmux, the selection and the notifications moved, and the old name still resolves through two renames" \
            || { no "22 ak orch rename"; sed 's/^/      /' "$WORK/rename.log" "$WORK/rename-notify.log" | head -6; }

# --- 23: ak watch --dry-run lists and does nothing (offline) -----------------
# A fake `gh` answers for GitHub: this account owns the repo, one PR is somebody else's, one is
# ours, one is a draft. The dry run names the one it would review and launches nothing, and
# names what it would hand on about our own PR elsewhere -- to a seat or a run, never Discord.
WH="$WORK/home-watch"; WBIN="$WORK/bin-watch"
mkdir -p -- "$WH/.agentkit" "$WBIN" "$WH/code"
WR=$(newrepo "home-watch/code/owned")
git -C "$WR" remote add origin https://github.com/me/owned.git
cat >"$WBIN/gh" <<'SH'
#!/usr/bin/env bash
case "$*" in
  "api user") printf '{"login":"me"}\n' ;;
  "repo view --json nameWithOwner,owner") printf '{"nameWithOwner":"me/owned","owner":{"login":"me"}}\n' ;;
  "api --paginate repos/me/owned/pulls?state=open&per_page=100")
    printf '[]\n[{"number":3,"user":{"login":"bob"},"title":"Fix parser","html_url":"https://github.com/me/owned/pull/3","head":{"sha":"abcdef1234567890"},"draft":false},'
    printf '{"number":4,"user":{"login":"me"},"title":"Mine","html_url":"https://github.com/me/owned/pull/4","head":{"sha":"1111111111111111"},"draft":false},'
    printf '{"number":5,"user":{"login":"eve"},"title":"Draft","html_url":"https://github.com/me/owned/pull/5","head":{"sha":"2222222222222222"},"draft":true}]\n' ;;
  "pr view https://github.com/me/owned/pull/3 --json reviews") printf '{"reviews":[]}\n' ;;
  # our own open PRs anywhere: one on a repo we do not own, opened by hand, with changes requested
  "api --paginate search/issues?q=is:pr+is:open+author:@me&per_page=100")
    printf '{"total_count":2,"incomplete_results":false,"items":[{"pull_request":{"html_url":"https://github.com/me/owned/pull/4"}}]}\n'
    printf '{"total_count":2,"incomplete_results":false,"items":[{"pull_request":{"html_url":"https://github.com/other/theirs/pull/8"}}]}\n' ;;
  "pr view https://github.com/other/theirs/pull/8 --json state,reviewDecision,title,number")
    printf '{"state":"OPEN","reviewDecision":"CHANGES_REQUESTED","title":"Their thing","number":8}\n' ;;
  *) echo "fake gh: unexpected $*" >&2; exit 1 ;;
esac
SH
chmod +x "$WBIN/gh"
WATCH=0
HOME="$WH" PATH="$WBIN:$PATH" ak watch --dry-run >"$WORK/watch.log" 2>&1 || WATCH=1
grep -q '^would review https://github.com/me/owned/pull/3 (#3 by bob: Fix parser) at abcdef123456$' "$WORK/watch.log" || WATCH=1
grep -q 'pull/4\|pull/5' "$WORK/watch.log" && WATCH=1
grep -q '^would hand on: PR #8 Their thing: the maintainer requested changes (https://github.com/other/theirs/pull/8)$' "$WORK/watch.log" || WATCH=1
[ "$(ls "$WH/.agentkit/runs" 2>/dev/null | wc -l)" -eq 0 ] || WATCH=1
[ -e "$WH/.agentkit/state/watch.json" ] && WATCH=1
[ "$WATCH" = 0 ] && ok "23 ak watch --dry-run: names bob's PR #3, skips ours and the draft, would hand the changes requested on our PR #8 elsewhere to its seat or its run and not to Discord, launches nothing, writes nothing" \
               || { no "23 ak watch --dry-run"; sed 's/^/      /' "$WORK/watch.log" | head -6; }

# --- 23b: a launched review settles its head only once it has posted (offline) ---
# watch.json remembers the run it launched, not a review. Whatever that run became decides the
# next tick: active and interrupted work wait, posted is done, and completed failures or missing
# runs retry after backoff. Interrupted work requires a recovery choice in `r`; `launch` is
# stubbed so this checks what a tick decides without starting another run.
HOME="$WH" PATH="$WBIN:$PATH" PYTHONPATH="$REPO" python3 - >"$WORK/watch-settled.log" 2>&1 <<'PY'
import json
import os
import time
from pathlib import Path

from agentkit import config, run, watch

config.ensure_dirs()
URL = "https://github.com/me/owned/pull/3"
SHA = "abcdef1234567890"
bad = []


def want(cond, why):
    if not cond:
        bad.append(why)


def run_dir(name, **state):
    d = config.RUNS / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({"run_id": name, "head_sha": SHA, **state}))
    return name


# settled(): every state a review run can be left in
want(watch.settled({"run": None}) == "done", "a review found on GitHub is settled")
want(watch.settled({"run": "gone"}) == "failed", "a run directory that is gone failed")
want(watch.settled({"run": run_dir("r-err", state="error")}) == "failed", "error failed")
want(watch.settled({"run": run_dir("r-dead", state="running", pid=999999)}) == "pending",
     "running with a dead pid waits for explicit recovery")
want(watch.settled({"run": run_dir("r-live", state="running", **run.process_owner())}) == "pending",
     "running with a live pid is pending")
want(watch.settled({"run": run_dir("r-ok", state="pass", review_posted=True)}) == "done",
     "passed and posted is done")
want(watch.settled({"run": run_dir("r-fail-ok", state="fail", review_posted=True)}) == "done",
     "failed verdict, posted, is done")
want(watch.settled({"run": run_dir("r-unposted", state="pass", review_posted=False)}) == "failed",
     "passed but never posted failed")
want(watch.settled({"run": run_dir("r-q", state="queued", queued_at=time.time()),
                    "at": time.time()}) == "pending",
     "just queued is pending")
want(watch.settled({"run": run_dir("r-q-old", state="queued", queued_at=time.time() - 7200),
                    "at": time.time() - 7200}) == "pending",
     "queued for two hours waits for explicit recovery")
for name in ("r-dead", "r-q-old"):
    want(run.needs_recovery(run.read_state(config.RUNS / name)), f"{name} kept for recovery")
want(run.read_state(config.RUNS / "r-live")["state"] == "running", "live run was not interrupted")
want(run.read_state(config.RUNS / "r-q")["state"] == "queued", "fresh launcher keeps its grace period")

# incoming(): backoff persists between ticks and never abandons a head
launched = []
watch.launch = lambda url: launched.append(url) or f"stub-{len(launched)}"
lines = []
now = [time.time()]
watch.time.time = lambda: now[0]
state = {"reviewed": {URL: {"sha": SHA, "run": "r-err", "at": now[0], "attempts": 1}}, "own": {}}
for count, delay in enumerate((600, 1800, 3600, 3600), 1):
    watch.incoming(state, "me", False, lines.append)
    want(len(launched) == count - 1, "retried before the delay")
    want(state["reviewed"][URL]["retry_at"] == now[0] + delay, "wrong delay")
    now[0] += delay
    watch.incoming(state, "me", False, lines.append)
    want(len(launched) == count, "retry was not launched")
    want(state["reviewed"][URL]["attempts"] == count + 1, "attempt not recorded")
    state["reviewed"][URL]["run"] = "r-err"

# Active, posted and interrupted runs are left alone even after the retry delays.
for name in ("r-live", "r-ok", "r-dead", "r-q-old"):
    state = {"reviewed": {URL: {"sha": SHA, "run": name, "at": time.time()}}, "own": {}}
    before = len(launched)
    watch.incoming(state, "me", False, lines.append)
    want(len(launched) == before, f"{name} was launched again")

for why in bad:
    print(f"BAD  {why}")
raise SystemExit(1 if bad else 0)
PY
WSRC=$?
[ "$WSRC" = 0 ] && ok "23b ak watch: a launched review settles only once posted; failed runs retry after 10, 30, 60 minutes, then hourly" \
                || { no "23b ak watch relaunch: exit=$WSRC"; diagnose "$WSRC" "$WORK/watch-settled.log" python3 'check 23b embedded fixture'; }

# --- 24: no push rights -> fork, push there, PR upstream, wait (offline) -----
# The fake `gh` says READ on the upstream and, asked to fork, adds the remote the way the real
# one does; a second bare repo is the fork. The run has to push there, open the PR against the
# upstream from `me:<branch>`, and end a PASS that is `waiting for the maintainer`, exit 0.
FH="$WORK/home-fork"; FAD="$WORK/ad-fork"; FBIN="$WORK/bin-fork"; FGHLOG="$WORK/gh-fork.log"
mkdir -p -- "$FH" "$FAD" "$FBIN"
fakeadapter "$FAD" claude work; fakeadapter "$FAD" codex pass; fakeadapter "$FAD" muse pass
fakeadapter "$FAD" grokbuild meterless
fakeadapter "$FAD" opencode meterless
FUP="$WORK/fork-upstream.git"; git init -q --bare -b main -- "$FUP"
FFORK="$WORK/fork-fork.git"; git init -q --bare -b main -- "$FFORK"
cat >"$FBIN/gh" <<SH
#!/usr/bin/env bash
GHLOG="$FGHLOG"; FFORK="$FFORK"
SH
cat >>"$FBIN/gh" <<'SH'
printf '%s\n' "$*" >>"$GHLOG"
case "${1:-} ${2:-}" in
  "repo view") printf '{"nameWithOwner":"someone/theirs","viewerPermission":"READ"}\n' ;;
  "repo fork") git remote add fork "$FFORK" ;;
  "api user")  printf 'me\n' ;;
  "pr create") printf 'https://github.com/someone/theirs/pull/9\n' ;;
  *) echo "fake gh: unexpected $*" >&2; exit 1 ;;
esac
SH
chmod +x "$FBIN/gh"
FR=$(newrepo repo-fork)
git -C "$FR" remote add origin "$FUP"; git -C "$FR" push -q -u origin main
sed "s|__REPO__|$FR|" "$WORK/retry-task.md" >"$WORK/task-fork.md"
HOME="$FH" AGENTKIT_ADAPTER_DIR="$FAD" AGENTKIT_DISCORD_WEBHOOK=off PATH="$FBIN:$PATH" \
  ak run "$WORK/task-fork.md" --rounds 1 --exec opus --review astra >"$WORK/fork.log" 2>&1
FRC=$?
FRUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/fork.log" | head -1)
FJSON="$FH/.agentkit/runs/$FRUNID/run.json"
FBR=$(jq -r '.branch // empty' "$FJSON" 2>/dev/null)
FORK=0
[ "$FRC" = 0 ] || FORK=1
[ "$(jq -r '.foreign' "$FJSON" 2>/dev/null)" = true ] || FORK=1
[ "$(jq -r '.merged' "$FJSON" 2>/dev/null)" = false ] || FORK=1
[ "$(jq -r '.merge_note' "$FJSON" 2>/dev/null)" = "waiting for the maintainer" ] || FORK=1
[ "$(jq -r '.pr' "$FJSON" 2>/dev/null)" = "https://github.com/someone/theirs/pull/9" ] || FORK=1
grep -q '^repo view --json nameWithOwner,viewerPermission$' "$FGHLOG" || FORK=1
grep -q '^repo fork --remote --remote-name fork$' "$FGHLOG" || FORK=1
grep -q "^pr create --repo someone/theirs --base main --head me:${FBR:-?} " "$FGHLOG" || FORK=1
grep -q 'READ permission on someone/theirs; pushing to a fork' "$WORK/fork.log" || FORK=1
git -C "$FFORK" rev-parse --verify -q "refs/heads/${FBR:-nope}" >/dev/null 2>&1 || FORK=1   # on the fork
git -C "$FUP" rev-parse --verify -q "refs/heads/${FBR:-nope}" >/dev/null 2>&1 && FORK=1      # not upstream
grep -q '^merge: waiting for the maintainer$' "$FH/.agentkit/runs/$FRUNID/result.md" 2>/dev/null || FORK=1
[ "$FORK" = 0 ] && ok "24 ak run without push rights: forked, pushed $FBR to the fork, opened the PR upstream from me:$FBR, exit 0 waiting for the maintainer" \
              || { no "24 fork decision: exit=$FRC foreign=$(jq -r .foreign "$FJSON" 2>/dev/null) note=$(jq -r .merge_note "$FJSON" 2>/dev/null)"; sed 's/^/      gh /' "$FGHLOG" 2>/dev/null | head -5; grep -- '--- merge\|WARN\|ERROR' "$WORK/fork.log" | sed 's/^/      /' | head -5; }

# --- 25: ak run --review-pr: the reviewer alone, posted back, offered to inbox (offline) ---
# The PR head exists only as refs/pull/7/head on a bare origin, the way GitHub serves it. The
# fake `gh` describes the PR, records the review it is asked to post and reports no checks. The
# fake adapters answer PASS, so the question has to reach an inbox seat -- pointed at a smoke
# name, never the real `inbox` -- and the user through `ak notify needs`.
PH="$WORK/home-prreview"; PAD="$WORK/ad-prreview"; PBIN="$WORK/bin-prreview"; PGHLOG="$WORK/gh-pr.log"
mkdir -p -- "$PH/.agentkit/state" "$PAD" "$PBIN" "$PH/code"
fakeadapter "$PAD" claude pass; fakeadapter "$PAD" codex pass; fakeadapter "$PAD" muse pass
fakeadapter "$PAD" grokbuild meterless
fakeadapter "$PAD" opencode meterless
python3 - "$PH/.agentkit/state/usage.json" <<'PY'
import json, sys, time
providers = {}
for name, harness, via in (("anthropic", "claude", "fable"),
                           ("openai", "codex", "astra"), ("meta", "muse", "spark")):
    providers[name] = {"provider": name, "harness": harness, "via": via, "meters": [],
                       "pace": None, "error": "unknown: smoke cache", "exhausted": False}
# The executor preference must not leak into watched PR reviews, even at 80/53.
for name, meters in (("anthropic", (("weekly_all", 80), ("weekly_scoped", 53))),
                     ("openai", (("weekly", 50),)), ("meta", (("weekly", 55),))):
    providers[name].update(error=None, resets=0, meters=[
        {"name": meter, "used": used, "pace": used - 50, "elapsed": 50,
         "window_secs": 604800, "resets_at": time.time() + 3600} for meter, used in meters])
with open(sys.argv[1], "w") as fh:
    json.dump({"fetched_at": time.time(), "providers": providers}, fh)
PY
PORIGIN="$WORK/gh-remote/smokeowner/smokerepo.git"; mkdir -p -- "$(dirname "$PORIGIN")"
git init -q --bare -b main -- "$PORIGIN"
PR=$(newrepo home-prreview/code/smokerepo)
git -C "$PR" remote add origin "$PORIGIN"
printf -- '---\ntests: test -f contrib.txt\n---\n# smokerepo\n' >"$PR/AGENTS.md"
git -C "$PR" add -A; git -C "$PR" commit -qm "declare tests"; git -C "$PR" push -q -u origin main
git -C "$PR" checkout -q -b contrib; printf 'c\n' >"$PR/contrib.txt"; git -C "$PR" add -A
git -C "$PR" commit -qm "add contrib.txt"; PHEAD=$(git -C "$PR" rev-parse HEAD)
git -C "$PR" push -q origin "contrib:refs/pull/7/head"; git -C "$PR" checkout -q main; git -C "$PR" branch -qD contrib
cat >"$PBIN/gh" <<SH
#!/usr/bin/env bash
GHLOG="$PGHLOG"; PHEAD=$PHEAD
SH
cat >>"$PBIN/gh" <<'SH'
printf '%s\n' "$*" >>"$GHLOG"
case "${1:-} ${2:-}" in
  "pr view") printf '{"number":7,"title":"Add contrib","body":"adds a file","author":{"login":"bob"},"baseRefName":"main","headRefOid":"%s","url":"https://github.com/smokeowner/smokerepo/pull/7","state":"OPEN","isDraft":false}\n' "$PHEAD" ;;
  "api repos/smokeowner/smokerepo/pulls/7/reviews") cp -- "${10#body=@}" "${GHLOG%.log}-review.md" ;;
  "api graphql") printf '{"data":{"repository":{"ref":{"branchProtectionRule":null}}}}\n' ;;
  "api --paginate") printf '[]\n' ;;
  *) echo "fake gh: unexpected $*" >&2; exit 1 ;;
esac
SH
chmod +x "$PBIN/gh"
tm kill-session -t =smoke-inbox 2>/dev/null
HOME="$PH" AGENTKIT_INBOX_SESSION=smoke-inbox AGENTKIT_ADAPTER_DIR="$PAD" AGENTKIT_DISCORD_WEBHOOK= \
  PATH="$PBIN:$PATH" ak run --review-pr https://github.com/smokeowner/smokerepo/pull/7 >"$WORK/prreview.log" 2>&1
PRC=$?
PRUNID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/prreview.log" | head -1)
PJSON="$PH/.agentkit/runs/$PRUNID/run.json"
PRR=0
[ "$PRC" = 0 ] || PRR=1
[ "$(jq -r '.verdict' "$PJSON" 2>/dev/null)" = PASS ] || PRR=1
[ "$(jq -r '.executor' "$PJSON" 2>/dev/null)" = null ] || PRR=1
[ "$(jq -r '.reviewer' "$PJSON" 2>/dev/null)" = astra ] || PRR=1
[ "$(jq -r '.review_pr' "$PJSON" 2>/dev/null)" = "https://github.com/smokeowner/smokerepo/pull/7" ] || PRR=1
[ "$(jq -r '.review_posted' "$PJSON" 2>/dev/null)" = true ] || PRR=1
[ "$(jq -r '.head_sha' "$PJSON" 2>/dev/null)" = "$PHEAD" ] || PRR=1
grep -q "^api repos/smokeowner/smokerepo/pulls/7/reviews --method POST -f commit_id=$PHEAD -f event=COMMENT -F body=@" "$PGHLOG" || PRR=1
grep -q "^agentkit review of ${PHEAD:0:12} by " "${PGHLOG%.log}-review.md" 2>/dev/null || PRR=1
grep -q '^VERDICT: PASS' "${PGHLOG%.log}-review.md" 2>/dev/null || PRR=1
grep -q '^\$ test -f contrib.txt' "$PH/.agentkit/runs/$PRUNID/round-1/donewhen.log" 2>/dev/null || PRR=1
grep -q 'You are the reviewer of a pull request by another author' \
  "$PH/.agentkit/runs/$PRUNID/round-1/reviewer/prompt.md" 2>/dev/null || PRR=1
grep -q '^+c$' "$PH/.agentkit/runs/$PRUNID/round-1/reviewer/prompt.md" 2>/dev/null || PRR=1   # the diff
git -C "$PH/.agentkit/wt/$PRUNID" rev-parse HEAD 2>/dev/null | grep -q "^$PHEAD$" || PRR=1
tm has-session -t =smoke-inbox 2>/dev/null || PRR=1
grep -q 'asked the smoke-inbox seat: PR #7 by bob: Add contrib. Merge? yes/no' "$WORK/prreview.log" || PRR=1
# the seat holds a `sleep`, so what was typed sits echoed in its pane: the merge is pinned to the head
tm capture-pane -p -J -t =smoke-inbox: 2>/dev/null | grep -q -- "--match-head-commit $PHEAD" || PRR=1
grep -q 'message: Needs you . smoke-inbox: PR #7 by bob: Add contrib. Merge? yes/no' "$WORK/prreview.log" || PRR=1
jq -e '.kind == "needs" and .text == "PR #7 by bob: Add contrib. Merge? yes/no"' \
  "$PH/.agentkit/state/notify-smoke-inbox.json" >/dev/null 2>&1 || PRR=1
tm kill-session -t =smoke-inbox 2>/dev/null
[ "$PRR" = 0 ] && ok "25 ak run --review-pr: astra reviews despite Fable lagging 80/53, PR head checked out, tests: run, PASS posted as a comment, smoke-inbox seat asked to merge --match-head-commit ${PHEAD:0:12}, user pinged" \
             || { no "25 ak run --review-pr: exit=$PRC verdict=$(jq -r .verdict "$PJSON" 2>/dev/null)"; sed 's/^/      /' "$WORK/prreview.log" | tail -8; }

# --- 25b: a review that cannot be posted is an error, not a PASS (offline) ---
# Same PR, same PASS from the fake reviewer, but GitHub refuses the review. Nobody can read a
# verdict that never got there, so the run ends in error, exit 2, offers nothing to any inbox
# seat and pings nobody -- and `ak watch` will launch it again.
PBIN2="$WORK/bin-prreview-refused"
mkdir -p -- "$PBIN2"
sed 's|  "api repos/smokeowner/smokerepo/pulls/7/reviews") cp .*|  "api repos/smokeowner/smokerepo/pulls/7/reviews") echo "HTTP 502: bad gateway" >\&2; exit 1 ;;|' \
  "$PBIN/gh" >"$PBIN2/gh"
chmod +x "$PBIN2/gh"
grep -q 'HTTP 502' "$PBIN2/gh" || echo "      (25b: the refusing gh was not written)"
tm kill-session -t =smoke-inbox-refused 2>/dev/null
HOME="$PH" AGENTKIT_INBOX_SESSION=smoke-inbox-refused AGENTKIT_ADAPTER_DIR="$PAD" AGENTKIT_DISCORD_WEBHOOK= \
  PATH="$PBIN2:$PATH" ak run --review-pr https://github.com/smokeowner/smokerepo/pull/7 >"$WORK/prreview-refused.log" 2>&1
PRC2=$?
PRUNID2=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/prreview-refused.log" | head -1)
PJSON2="$PH/.agentkit/runs/$PRUNID2/run.json"
PRF=0
[ "$PRC2" = 2 ] || PRF=1
[ "$(jq -r '.state' "$PJSON2" 2>/dev/null)" = error ] || PRF=1
[ "$(jq -r '.verdict' "$PJSON2" 2>/dev/null)" = PASS ] || PRF=1          # the reviewer did say PASS
[ "$(jq -r '.review_posted' "$PJSON2" 2>/dev/null)" = false ] || PRF=1
jq -r '.error' "$PJSON2" 2>/dev/null | grep -q 'the review was not posted to .*pull/7: gh api review COMMENT exited 1: HTTP 502' || PRF=1
grep -q '\] ERROR the review was not posted' "$WORK/prreview-refused.log" || PRF=1
grep -q 'pr checks\|asked the' "$WORK/prreview-refused.log" && PRF=1
tm has-session -t =smoke-inbox-refused 2>/dev/null && PRF=1
[ -e "$PH/.agentkit/state/notify-smoke-inbox-refused.json" ] && PRF=1
grep -q '^## Why this run stopped' "$PH/.agentkit/runs/$PRUNID2/result.md" 2>/dev/null || PRF=1
tm kill-session -t =smoke-inbox-refused 2>/dev/null
[ "$PRF" = 0 ] && ok "25b ak run --review-pr with GitHub refusing the review: exit 2, state error, no checks, no inbox seat, nobody pinged" \
             || { no "25b review not posted: exit=$PRC2 state=$(jq -r .state "$PJSON2" 2>/dev/null)"; sed 's/^/      /' "$WORK/prreview-refused.log" | tail -6; }

# --- 26: retention under disk pressure (offline) ----------------------------
# The focused regression checks one-day minimum retention, old merged worktrees, history,
# automatic watch ticks, exited seats, dry-run identity and preserved unique work.
if PYTHONDONTWRITEBYTECODE=1 python3 "$REPO/tests/test_audit_retain_state_without_manual_cleanup.py" >"$WORK/gc-pressure.log" 2>&1; then
  ok "26 automatic retention under disk pressure preserves recent diagnostics and unique work"
else
  no "26 disk-pressure gc"; tail -30 "$WORK/gc-pressure.log"
fi

# --- 27: install.sh roles in a sandbox HOME -----------------------------------
# --client records the alias a bare `ak` will ssh to; --server removes it and, under a sandbox
# HOME, says out loud that the cron is not installed -- the real crontab must not change.
RH="$WORK/home-roles"
mkdir -p -- "$RH/.claude"
# what an older install left in this HOME: our symlink over the user's own file, and the
# backup it displaced.  The install undoes both -- the rulebook is the session's now.
ln -sfn -- "$REPO/AGENTS.md" "$RH/.claude/CLAUDE.md"
printf 'the memory this user had all along\n' >"$RH/.claude/CLAUDE.md.bak-20250601"
CRON_BEFORE=$(crontab -l 2>/dev/null | md5sum)
ROLES=0
HOME="$RH" bash "$REPO/install.sh" --client mybox >"$WORK/install-client.log" 2>&1 || ROLES=1
[ "$(cat "$RH/.agentkit/state/server" 2>/dev/null)" = mybox ] || ROLES=1
grep -q 'client: the server is `ssh mybox`' "$WORK/install-client.log" || ROLES=1
# The remembered alias is told apart from this box by its name, so the box gets a fixed one
# and no tailscale: a host that happens to be called mybox must not turn this into a server.
RHBIN="$WORK/bin-roles"; mkdir -p -- "$RHBIN"
printf '#!/bin/sh\necho smoke-host\n' >"$RHBIN/hostname"; printf '#!/bin/sh\nexit 1\n' >"$RHBIN/tailscale"
chmod +x "$RHBIN/hostname" "$RHBIN/tailscale"
HOME="$RH" PATH="$RHBIN:$PATH" bash "$REPO/install.sh" >"$WORK/install-client2.log" 2>&1 || ROLES=1     # remembered
grep -q 'client: the server is `ssh mybox`' "$WORK/install-client2.log" || ROLES=1
HOME="$RH" bash "$REPO/install.sh" --server >"$WORK/install-server.log" 2>&1 || ROLES=1
[ -e "$RH/.agentkit/state/server" ] && ROLES=1
grep -q 'sandbox HOME, so the ak watch cron is not installed' "$WORK/install-server.log" || ROLES=1
grep -q 'sandbox HOME .*: packages, harness installs and logins, and the cron are skipped' "$WORK/install-server.log" || ROLES=1
[ "$(crontab -l 2>/dev/null | md5sum)" = "$CRON_BEFORE" ] || ROLES=1
[ -d "$RH/code" ] || ROLES=1
[ ! -L "$RH/.claude/CLAUDE.md" ] || ROLES=1
[ "$(cat "$RH/.claude/CLAUDE.md" 2>/dev/null)" = "the memory this user had all along" ] || ROLES=1
[ ! -e "$RH/.codex/AGENTS.md" ] || ROLES=1
grep -q '^# agentkit PATH' "$RH/.bashrc" 2>/dev/null || grep -q '^# agentkit PATH' "$RH/.zshrc" 2>/dev/null || ROLES=1
HOME="$RH" bash "$REPO/install.sh" --phone-key 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmokephone me@phone' \
  >"$WORK/install-key.log" 2>&1 || ROLES=1
grep -qx 'command="ak attach",no-agent-forwarding,no-port-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmokephone phone-termius' \
  "$RH/.ssh/authorized_keys" 2>/dev/null || ROLES=1
HOME="$RH" bash "$REPO/install.sh" --phone-key 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAsmokephone me@phone' \
  >"$WORK/install-key2.log" 2>&1 || ROLES=1
[ "$(grep -c smokephone "$RH/.ssh/authorized_keys" 2>/dev/null)" = 1 ] || ROLES=1
[ "$ROLES" = 0 ] && ok "27 install.sh: --client records mybox and is remembered, --server drops it and skips the cron in a sandbox, old doctrine link undone and the user's own file back, PATH line, phone key appended once" \
               || { no "27 install.sh roles"; sed 's/^/      /' "$WORK/install-server.log" | tail -4; }

# --- 27b: the two tmux options install.sh sets on a server already up ---------
# tmux's own flags come before the subcommand: `tmux -L <socket> set -g mouse on` is the command
# and `tmux set -L <socket> -g mouse on` is an error -- one that used to be swallowed, so both
# options stayed unset on every server that was already up, which is exactly the server the
# oldest seats are on.  This runs the real install.sh against the suite's own tmux and reads the
# options back off it; then again with a tmux that refuses, where the install has to stop and
# say what tmux said instead of reporting success.
TOPT=0; TH="$WORK/home-tmuxopt"; mkdir -p -- "$TH"
tm new-session -d -s tmuxopt-seat sleep 600 || TOPT=1
tm set -g mouse off >/dev/null 2>&1 || TOPT=1
tm set -g history-limit 2000 >/dev/null 2>&1 || TOPT=1
HOME="$TH" bash "$REPO/install.sh" >"$WORK/install-tmux.log" 2>&1 || TOPT=1
grep -q '^tmux: mouse on, 50000 lines of history, remain-on-exit on the agentkit server (agentkit-test)$' \
  "$WORK/install-tmux.log" || TOPT=1
[ "$(tm show-options -gv mouse 2>/dev/null)" = on ] || TOPT=1
[ "$(tm show-options -gv history-limit 2>/dev/null)" = 50000 ] || TOPT=1
[ "$(tm show-options -gv remain-on-exit 2>/dev/null)" = on ] || TOPT=1
tm kill-session -t =tmuxopt-seat 2>/dev/null
TBIN="$WORK/bin-tmuxopt"; mkdir -p -- "$TBIN"
cat >"$TBIN/tmux" <<'SH'
#!/usr/bin/env bash
# every tmux command but `set` works, which is the one this check is about
for arg in "$@"; do [ "$arg" = set ] && { echo "unknown option" >&2; exit 1; }; done
exit 0
SH
chmod +x "$TBIN/tmux"
HOME="$TH" PATH="$TBIN:$PATH" bash "$REPO/install.sh" >"$WORK/install-tmux-bad.log" 2>&1 && TOPT=1
grep -q 'install.sh: tmux rejected `set -g mouse on` on the agentkit server' \
  "$WORK/install-tmux-bad.log" || TOPT=1
[ "$TOPT" = 0 ] && ok "27b install.sh: mouse and 50000 lines of history read back as set on the server that was already up, and a tmux that rejects the command stops the install" \
              || { no "27b install.sh tmux options"; grep -i tmux "$WORK/install-tmux.log" "$WORK/install-tmux-bad.log" 2>/dev/null | sed 's/^/      /' | head -4; }

# --- 28: watcher correctness and honest delivery, fake gh only ----------------
if python3 "$REPO/tests/test_v4c.py" >"$WORK/v4c.log" 2>&1; then
  ok "28 watcher SHA, backoff, dry-run; required checks, delivery, roles and session age"
else
  no "28 v4c regressions"; tail -30 "$WORK/v4c.log"
fi

# --- 29: the fallback speaks for an orphaned run, and for no other (offline) ---
# The rule: a run reports itself only when the seat that launched it is gone.  A run started by
# hand, over ssh or from cron belongs to the terminal it was started from -- pinging the user
# about one is noise, and "Needs you . -" about a failure they have already handled is worse
# than silence.  A local webhook that only records stands in for Discord here, so "nothing was
# posted" is a fact about POSTs and not about a log line.
FBH="$WORK/home-fallback"; FBAD="$WORK/ad-fallback"
mkdir -p -- "$FBH" "$FBAD"
fakeadapter "$FBAD" claude work; fakeadapter "$FBAD" codex pass; fakeadapter "$FBAD" muse pass
fakeadapter "$FBAD" grokbuild meterless
fakeadapter "$FBAD" opencode meterless
cat >"$WORK/hookd.py" <<'HOOKD'
"""A webhook that only records: it prints its own URL, then one line per POST body."""
import http.server
import socketserver
import sys

record = sys.argv[1]


class Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with open(record, "ab") as fh:
            fh.write(body.replace(b"\n", b" ") + b"\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


srv = socketserver.TCPServer(("127.0.0.1", 0), Hook)
print(f"http://127.0.0.1:{srv.server_address[1]}/hook", flush=True)
srv.serve_forever()
HOOKD
: >"$WORK/hook-posts.txt"
python3 "$WORK/hookd.py" "$WORK/hook-posts.txt" >"$WORK/hook-url.txt" 2>"$WORK/hookd.err" &
HOOKPID=$!
HOOKURL=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  HOOKURL=$(head -1 "$WORK/hook-url.txt" 2>/dev/null); [ -n "$HOOKURL" ] && break; sleep 0.3
done
cat >"$WORK/orphan-template.md" <<'MD'
---
repo: __REPO__
base: main
rounds: 1
---
# Smoke orphan run

## Goal
Nothing: the fake adapters do the work.

## Done when
```bash
test -f never-written.txt
```
MD
FBREPO=$(newrepo "repo-fallback")
sed "s|__REPO__|$FBREPO|" "$WORK/orphan-template.md" >"$WORK/task-orphan.md"
FB=0
[ -n "$HOOKURL" ] || FB=1
# (a) launched from no seat at all: the done-when fails, and still nobody is told
HOME="$FBH" AGENTKIT_ADAPTER_DIR="$FBAD" AGENTKIT_SESSION= AGENTKIT_DISCORD_USER_ID= \
  AGENTKIT_DISCORD_WEBHOOK="$HOOKURL" AK_NOTIFY_SINK="$HOOKURL" \
  ak run "$WORK/task-orphan.md" --rounds 1 --exec opus \
  --review astra --no-merge >"$WORK/orphan.log" 2>&1
[ "$?" = 1 ] || FB=1
ORPHID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/orphan.log" | head -1)
ORPHDIR="$FBH/.agentkit/runs/$ORPHID"
[ "$(jq -r '.state' "$ORPHDIR/run.json" 2>/dev/null)" = fail ] || FB=1
[ "$(jq -r '.launched_session // "null"' "$ORPHDIR/run.json" 2>/dev/null)" = null ] || FB=1
[ "$(jq -r '.reported' "$ORPHDIR/run.json" 2>/dev/null)" = false ] || FB=1
grep -q 'notification: none: no orchestrator session launched this run' "$WORK/orphan.log" || FB=1
grep -q 'Needs you' "$WORK/orphan.log" && FB=1
[ ! -s "$WORK/hook-posts.txt" ] || FB=1
ls "$FBH/.agentkit/state"/notify-*.json >/dev/null 2>&1 && FB=1
# (b) launched from a seat that is gone: exactly one needs, titled with that seat
tm has-session -t =orch-x 2>/dev/null && FB=1     # a live orch-x would answer for this run
HOME="$FBH" AGENTKIT_ADAPTER_DIR="$FBAD" AGENTKIT_SESSION=orch-x AGENTKIT_DISCORD_USER_ID= \
  AGENTKIT_DISCORD_WEBHOOK="$HOOKURL" AK_NOTIFY_SINK="$HOOKURL" \
  ak run "$WORK/task-orphan.md" --rounds 1 --exec opus \
  --review astra --no-merge >"$WORK/orphan-dead.log" 2>&1
[ "$?" = 1 ] || FB=1
DEADID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/orphan-dead.log" | head -1)
DEADDIR="$FBH/.agentkit/runs/$DEADID"
[ "$(jq -r '.launched_session' "$DEADDIR/run.json" 2>/dev/null)" = orch-x ] || FB=1
[ "$(jq -r '.reported' "$DEADDIR/run.json" 2>/dev/null)" = true ] || FB=1
grep -qE '^\[[0-9:]*\] the orchestrator session orch-x this run was launched from is gone; asking the user to continue the task$' \
  "$WORK/orphan-dead.log" || FB=1
[ "$(wc -l <"$WORK/hook-posts.txt")" -eq 1 ] || FB=1
jq -e '.username == "agentkit"
  and .embeds[0].title == "Needs you · orch-x" and .embeds[0].color == 16098851
  and (.embeds[0] | has("description") | not)
  and ((.embeds[0].fields // []) | length == 0)' "$WORK/hook-posts.txt" >/dev/null 2>&1 || FB=1
jq -e '.session == "orch-x" and .kind == "needs" and (.text | startswith("Its orchestrator session orch-x is gone."))' \
  "$FBH/.agentkit/state/notify-orch-x.json" >/dev/null 2>&1 || FB=1
# (c) `ak notify` outside a seat: the message names itself, never a dash
HOME="$FBH" AGENTKIT_SESSION= AGENTKIT_DISCORD_USER_ID= AGENTKIT_DISCORD_WEBHOOK="$HOOKURL" \
  ak notify needs "Merge PR #9 by bob? yes/no" --dry-run \
  >"$WORK/orphan-needs.json" 2>"$WORK/orphan-needs.err" || FB=1
[ "$(cat "$WORK/orphan-needs.err")" = 'terminal notice: Needs you · Merge PR #9 by bob? yes/no: Merge PR #9 by bob? yes/no' ] || FB=1
jq -e '.embeds[0].title == "Needs you · Merge PR #9 by bob? yes/no"' "$WORK/orphan-needs.json" \
  >/dev/null 2>&1 || FB=1
FBLONG="a summary with no seat behind it, longer by some way than any title a phone shows whole"
HOME="$FBH" AGENTKIT_SESSION= AGENTKIT_DISCORD_USER_ID= AGENTKIT_DISCORD_WEBHOOK="$HOOKURL" \
  ak notify done "$FBLONG" --dry-run >"$WORK/orphan-done.json" 2>"$WORK/orphan-done.err" || FB=1
[ "$(cat "$WORK/orphan-done.err")" = "terminal notice: Done · ${FBLONG:0:60}: $FBLONG" ] || FB=1
jq -e --arg t "Done · ${FBLONG:0:60}" '.embeds[0].title == $t' "$WORK/orphan-done.json" \
  >/dev/null 2>&1 || FB=1
[ "$(wc -l <"$WORK/hook-posts.txt")" -eq 1 ] || FB=1   # and --dry-run posted nothing either
kill "$HOOKPID" 2>/dev/null
[ "$FB" = 0 ] && ok "29 the dead-seat fallback: nothing from a run nobody launched from a seat, one needs titled with the gone orch-x for its orphan, and a title of its own outside a session" \
             || { no "29 the dead-seat fallback (webhook ${HOOKURL:-none}, posts $(wc -l <"$WORK/hook-posts.txt"))"
                  tail -3 "$WORK/orphan.log" | sed 's/^/      /'
                  tail -3 "$WORK/orphan-dead.log" | sed 's/^/      /'
                  cut -c1-200 "$WORK/hook-posts.txt" | sed 's/^/      /'; }

# --- 30: the OpenAI usage-limit reset policy (offline) ------------------------
# A codex adapter that answers `reset-status` and `reset` from files, so the policy can be
# driven over the threshold and back with no ChatGPT account behind it.  A reset is the one
# thing `ak usage` does that spends something, so both halves are checked: that a nearly spent
# week spends exactly one and never a second within the day, and that a half-spent week
# spends nothing at all.
RD="$WORK/ad-reset"
mkdir -p -- "$RD"
fakeadapter "$RD" claude pass; fakeadapter "$RD" muse pass   # anthropic and meta, no network
fakeadapter "$RD" grokbuild meterless
fakeadapter "$RD" opencode meterless
cat >"$RD/codex.sh" <<SH
#!/usr/bin/env bash
set -uo pipefail
S="$RD/codex"
SH
cat >>"$RD/codex.sh" <<'SH'
used=$(cat "$S.used" 2>/dev/null || echo 95)
avail=$(cat "$S.avail" 2>/dev/null || echo 2)
case "${1:-}" in
usage)        printf '{"provider":"openai","error":null,"meters":[{"name":"primary_window","used":%s,"resets_at":%s,"window_secs":604800}]}\n' \
                "$used" "$(( $(date -u +%s) + 300000 ))" ;;
reset-status) printf '{"available":%s,"applicable":0,"weekly_used":%s,"resets_at":%s,"error":null}\n' \
                "$avail" "$used" "$(( $(date -u +%s) + 300000 ))" ;;
reset)        echo spent >>"$S.calls"; echo 5 >"$S.used"; printf '%s\n' "$((avail - 1))" >"$S.avail"
              printf '{"code":"reset","available":%s,"weekly_used":5,"resets_at":%s,"error":null}\n' \
                "$((avail - 1))" "$(( $(date -u +%s) + 604800 ))" ;;
*)            echo "fake codex.sh: no $1" >&2; exit 2 ;;
esac
SH
chmod +x "$RD/codex.sh"
# 30a: 95% used with two resets in hand -- one is spent, the meters are read again, and the
# next read, with the 5 min cache out of the way, must not spend the second one.
RH="$WORK/home-reset"; mkdir -p -- "$RH/.agentkit/state"
echo 95 >"$RD/codex.used"; echo 2 >"$RD/codex.avail"; rm -f -- "$RD/codex.calls"
HOME="$RH" AGENTKIT_ADAPTER_DIR="$RD" ak usage >"$WORK/reset-95.txt" 2>&1
HOME="$RH" AGENTKIT_ADAPTER_DIR="$RD" ak usage --json >"$WORK/reset-95.json" 2>&1
rm -f -- "$RH/.agentkit/state/usage.json"
HOME="$RH" AGENTKIT_ADAPTER_DIR="$RD" ak usage >"$WORK/reset-95b.txt" 2>&1
RS="$RH/.agentkit/state/openai-reset.json"
if [ "$(wc -l <"$RD/codex.calls" 2>/dev/null || echo 0)" -eq 1 ] &&
   grep -qx 'openai: usage-limit reset applied (1 left)' "$WORK/reset-95.txt" &&
   [ "$(jq -r '.providers.openai.meters[0].used' "$WORK/reset-95.json" 2>/dev/null)" = 5 ] &&
   jq -e '.outcome == "reset" and .weekly_before == 95 and .weekly_after == 5
          and .available_after == 1 and (.applied_at | type) == "number"' "$RS" >/dev/null 2>&1 &&
   ! grep -q 'reset applied' "$WORK/reset-95b.txt"; then
  ok "30a usage-limit reset: at 95% used one reset is spent, the meters are re-read to 5%, and the next read does not spend the second"
else
  no "30a usage-limit reset at 95%: $(wc -l <"$RD/codex.calls" 2>/dev/null || echo 0) reset call(s), state $(cat "$RS" 2>/dev/null || echo none)"
  sed 's/^/      /' "$WORK/reset-95.txt" | head -8
fi
# 30b: half a week gone is not a reason to throw the other half away
RH2="$WORK/home-reset-half"; mkdir -p -- "$RH2/.agentkit/state"
echo 50 >"$RD/codex.used"; echo 2 >"$RD/codex.avail"; rm -f -- "$RD/codex.calls"
HOME="$RH2" AGENTKIT_ADAPTER_DIR="$RD" ak usage >"$WORK/reset-50.txt" 2>&1
if [ ! -e "$RD/codex.calls" ] && [ ! -e "$RH2/.agentkit/state/openai-reset.json" ] &&
   ! grep -q 'reset applied' "$WORK/reset-50.txt"; then
  ok "30b usage-limit reset: at 50% used nothing is spent, and no reset state is written at all"
else
  no "30b usage-limit reset at 50%: $(wc -l <"$RD/codex.calls" 2>/dev/null || echo 0) reset call(s)"
  sed 's/^/      /' "$WORK/reset-50.txt" | head -8
fi

# --- 31: the shared browser and the desktop ---------------------------------
# 31a-c are offline and run on every machine. 31d and 31e make real model calls through the
# MCP servers `ak browser mcp-register` wrote, so they only run where the shared Chromium is
# actually listening on 9222 -- the server. On a Mac they are skipped, not failed.
BST=0
ak browser status >"$WORK/browser-status.txt" 2>&1 || BST=$?
BSO=$(cat "$WORK/browser-status.txt")
if [ "$BST" = 0 ] &&
   printf '%s' "$BSO" | grep -q '^cdp  *http://127\.0\.0\.1:9222' &&
   printf '%s' "$BSO" | grep -q '^desktop  *DISPLAY=:99' &&
   printf '%s' "$BSO" | grep -q '^novnc '; then
  ok "31a ak browser status: units, cdp, desktop and the noVNC URL, exit 0"
else
  no "31a ak browser status exited $BST"
  sed 's/^/      /' "$WORK/browser-status.txt" | head -8
fi

# 31b: mcp-register writes both servers into a claude and a codex config that already hold
# somebody else's keys, twice, without a second copy of either and without losing a comment.
MR=0
BH="$WORK/home-browser"; mkdir -p -- "$BH/.codex"
cat >"$BH/.claude.json" <<'J'
{
  "numStartups": 3,
  "mcpServers": {"existing": {"type": "stdio", "command": "true", "args": []}},
  "projects": {"/tmp": {"allowedTools": []}}
}
J
cat >"$BH/.codex/config.toml" <<'T'
approval_policy = "never"   # kept
sandbox_mode = "danger-full-access"

[projects."/home/x/code"]
trust_level = "trusted"
T
HOME="$BH" ak browser mcp-register >"$WORK/mcp-register1.log" 2>&1 || MR=1
HOME="$BH" ak browser mcp-register >"$WORK/mcp-register2.log" 2>&1 || MR=1
grep -q 'already registered in .*\.claude\.json' "$WORK/mcp-register2.log" || MR=1
grep -q 'already registered in .*config\.toml' "$WORK/mcp-register2.log" || MR=1
python3 - "$BH" <<'PY' || MR=1
import json, pathlib, sys, tomllib
home = pathlib.Path(sys.argv[1])
claude = json.loads((home / ".claude.json").read_text())
servers = claude.get("mcpServers", {})
raw = (home / ".codex" / "config.toml").read_text()
codex = tomllib.loads(raw)
problems = []
if sorted(servers) != ["browser", "desktop", "existing"]:
    problems.append(f"claude mcpServers={sorted(servers)}")
if claude.get("numStartups") != 3 or list(claude.get("projects", {})) != ["/tmp"]:
    problems.append("claude.json lost keys it did not own")
browser = servers.get("browser", {})
if browser.get("command") != "npx" or "--isolated" in browser.get("args", []):
    problems.append(f"claude browser server = {browser}")
if browser.get("args", [])[-2:] != ["--cdp-endpoint", "http://127.0.0.1:9222"]:
    problems.append("claude browser server does not point at the CDP endpoint")
if browser.get("env", {}).get("DISPLAY") != ":99":
    problems.append("claude browser server has no DISPLAY")
if not servers.get("desktop", {}).get("args", [""])[0].endswith("desktop-mcp.py"):
    problems.append(f"claude desktop server = {servers.get('desktop')}")
if sorted(codex.get("mcp_servers", {})) != ["browser", "desktop"]:
    problems.append(f"codex mcp_servers={sorted(codex.get('mcp_servers', {}))}")
if codex.get("approval_policy") != "never" or list(codex.get("projects", {})) != ["/home/x/code"]:
    problems.append("config.toml lost keys it did not own")
if "# kept" not in raw:
    problems.append("config.toml lost an inline comment")
if raw.count("agentkit browser bridge: managed") != 1:
    problems.append(f"{raw.count('agentkit browser bridge: managed')} managed blocks")
if problems:
    print("; ".join(problems), file=sys.stderr)
sys.exit(1 if problems else 0)
PY
[ "$MR" = 0 ] && ok "31b ak browser mcp-register: browser+desktop into claude user scope and one codex block, idempotent, foreign keys and comments intact" \
              || no "31b ak browser mcp-register in $BH"

# 31c: the desktop server speaks MCP on stdio -- initialize, then the nine actions.
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' >"$WORK/desktop-in.jsonl"
python3 "$REPO/tools/desktop-mcp.py" <"$WORK/desktop-in.jsonl" >"$WORK/desktop-out.jsonl" 2>"$WORK/desktop-err.log"
if python3 - "$WORK/desktop-out.jsonl" <<'PY'
import json, pathlib, sys
lines = [json.loads(l) for l in pathlib.Path(sys.argv[1]).read_text().splitlines() if l.strip()]
by_id = {m.get("id"): m for m in lines}
init = by_id.get(1, {}).get("result", {})
tools = {t["name"] for t in by_id.get(2, {}).get("result", {}).get("tools", [])}
wanted = {"screenshot", "click", "double_click", "move", "drag", "type", "key", "scroll",
          "cursor_position"}
sys.exit(0 if len(lines) == 2 and init.get("serverInfo", {}).get("name") == "desktop"
         and init.get("protocolVersion") == "2025-06-18" and tools == wanted else 1)
PY
then
  ok "31c tools/desktop-mcp.py answers initialize and tools/list over stdio, with screenshot/click/type/key/scroll"
else
  no "31c tools/desktop-mcp.py over stdio: $(head -c 200 "$WORK/desktop-err.log")"
fi

# 31d/31e: real calls, only where the shared browser is up.
if python3 -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=3).read()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
  # Codex's config is private to this suite, so give it the same MCP servers locally.
  checked "$WORK/mcp-register.log" ak browser mcp-register || no "31d/31e MCP registration"
  if skip_spent 31d opus; then
    :
  else
  BP='Use the browser MCP server to list the open tabs of the shared Chromium, and the desktop MCP server to take one screenshot of the desktop. Then print one final line, exactly: BROWSER_TABS=<number of tabs> DESKTOP=<ok if the screenshot came back, else fail>'
  CMODEL=$(PYTHONPATH="$REPO" python3 -c 'from agentkit import config; print(config.model(config.load(), "opus")["model"])')
  ( tok=$(cat "$HOME/.agentkit/secrets/claude_oauth_token" 2>/dev/null) &&
      [ -n "$tok" ] && export CLAUDE_CODE_OAUTH_TOKEN="$tok"
    claude -p --model "$CMODEL" --dangerously-skip-permissions "$BP"
  ) >"$WORK/mcp-claude.txt" 2>&1
  MCPRC=$?
  if [ "$MCPRC" = 0 ] && grep -qE 'BROWSER_TABS=[0-9]+ DESKTOP=ok' "$WORK/mcp-claude.txt"; then
    ok "31d claude reached the shared browser and the desktop over MCP: $(grep -oE 'BROWSER_TABS=[0-9]+ DESKTOP=ok' "$WORK/mcp-claude.txt" | tail -1)"
  else
    no "31d claude over MCP: $(tail -c 200 "$WORK/mcp-claude.txt")"
  fi
  fi
  if skip_spent 31e astra; then
    :
  else
  CMODEL=$(PYTHONPATH="$REPO" python3 -c 'from agentkit import config; print(config.model(config.load(), "astra")["model"])')
  # the model flag the adapter would build, by the same rule (check 6e): a ChatGPT-subscription
  # Codex is given none.  In a subshell, so the suite's own arguments survive `set --`.
  ( case $CMODEL in ""|default) set -- exec ;; *) set -- exec -m "$CMODEL" ;; esac
    codex "$@" --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
      'Use the browser MCP server to list the open tabs of the shared Chromium. Then print one final line, exactly: BROWSER_TABS=<number of tabs>' \
    ) >"$WORK/mcp-codex.txt" 2>&1
  MCPRC=$?
  if [ "$MCPRC" = 0 ] && grep -qE 'BROWSER_TABS=[0-9]+' "$WORK/mcp-codex.txt"; then
    ok "31e codex reached the shared browser over MCP: $(grep -oE 'BROWSER_TABS=[0-9]+' "$WORK/mcp-codex.txt" | tail -1)"
  else
    no "31e codex over MCP: $(tail -c 200 "$WORK/mcp-codex.txt")"
  fi
  fi
else
  skip_checks 31d/31e "the shared browser is not on this host: nothing listens on 127.0.0.1:9222"
fi

# --- 32: a notification resolves only after an interactive open and fresh progress (offline) ---
if session_state_check >"$WORK/session-state.log" 2>&1; then
  ok "32 stable session state: named fake-state checks for open/progress, observation, rename and usage failures"
else
  no "32 stable session state"; tail -40 "$WORK/session-state.log"
fi

# --- 33: a run with no repository is `delivered`, not `not merged` (offline) ------------------
# `not merged` is an answer about a branch, and a scratch run never had one. Four fabricated
# runs cover the four endings, and the real scratch run of check 16 is read as well, so this is
# about what a run actually writes and not only about what the function returns.
DELH="$WORK/home-delivered"
mkdir -p -- "$DELH/.agentkit/state"
DEL=0
HOME="$DELH" PYTHONPATH="$REPO" python3 - >"$WORK/delivered.log" 2>&1 <<'PY' || DEL=1
import time

from agentkit import config, run

config.ensure_dirs()
now = time.time()
made = {
    "20260101-0900-scratch": {"title": "Write the quarterly summary", "scratch": True,
                              "no_merge": True, "worktree": str(config.WORK / "scratch")},
    "20260101-0901-merged": {"title": "Fix the parser", "merged": True,
                             "branch": "ak/fix-the-parser",
                             "pr": "https://github.com/me/atoll/pull/12"},
    "20260101-0902-waiting": {"title": "Add the exporter", "branch": "ak/add-the-exporter",
                              "merge_note": "waiting for the maintainer",
                              "pr": "https://github.com/them/atoll/pull/13"},
    "20260101-0903-nomerge": {"title": "Try the idea", "no_merge": True,
                              "branch": "ak/try-the-idea"},
}
cfg = config.load()
review = {"executor": "opus", "reviewer": "astra", "returncode": 0,
          "executor_provider": config.model(cfg, "opus")["provider"],
          "reviewer_provider": config.model(cfg, "astra")["provider"],
          "verdict": "PASS", "done_when": True}
for name, extra in made.items():
    (config.RUNS / name).mkdir()
    run.save_state(config.RUNS / name,
                   dict({"run_id": name, "state": "pass", "verdict": "PASS", "executor": "opus",
                         "reviewer": "astra", "rounds": 1, "round_summaries": [], "merged": False,
                         "review": review,
                         "started_at": now - 300, "finished_at": now, "reported": False}, **extra))
was = {name: run.read_state(config.RUNS / name) for name in made}
scratch = was["20260101-0900-scratch"]
assert run.delivery(scratch) == "PASS, delivered", run.delivery(scratch)
assert run.whereabouts(scratch) == "delivered", run.whereabouts(scratch)
assert run.status_word(scratch) == "delivered", run.status_word(scratch)
# the finished-run notice the menu and `ak orch` print
assert run.summary_line(scratch) == "Write the quarterly summary — PASS — delivered", \
    run.summary_line(scratch)
# ... and `merged` / `not merged: <reason>` are still the repository run's answer
assert run.delivery(was["20260101-0901-merged"]) == "PASS, merged"
assert run.delivery(was["20260101-0902-waiting"]) == "PASS, not merged: waiting for the maintainer"
assert run.delivery(was["20260101-0903-nomerge"]) == "PASS, not merged: --no-merge"
assert run.status_word(was["20260101-0903-nomerge"]) == "not merged: --no-merge"
assert run.whereabouts(was["20260101-0903-nomerge"]) == "not merged"
# a run that is still going has become nothing yet
going = dict(scratch, state="running", finished_at=None)
assert run.status_word(going) == "", run.status_word(going)
print("ok")
PY
HOME="$DELH" ak run status --plain >"$WORK/delivered-status.log" 2>&1 || DEL=1
grep -qE '^20260101-0900-scratch +pass +PASS +opus/astra +scratch +delivered$' "$WORK/delivered-status.log" || DEL=1
grep -qE '^20260101-0901-merged .+ merged https://github.com/me/atoll/pull/12$' "$WORK/delivered-status.log" || DEL=1
grep -qE '^20260101-0902-waiting .+ PR open https://github.com/them/atoll/pull/13$' "$WORK/delivered-status.log" || DEL=1
grep -qE '^20260101-0903-nomerge .+ not merged: --no-merge$' "$WORK/delivered-status.log" || DEL=1
# and the run check 16 really made says it too, in its result and in its own status line
grep -q '^# PASS, delivered — Smoke scratch workspace$' "$SCRDIR/result.md" || DEL=1
grep -q 'not merged' "$SCRDIR/result.md" && DEL=1
HOME="$SCRH" ak run status --plain "$SCRID" >"$WORK/delivered-scratch.log" 2>&1 || DEL=1
grep -q ' scratch  delivered$' "$WORK/delivered-scratch.log" || DEL=1
[ "$DEL" = 0 ] && ok "33 a run with no repository is delivered: result.md, \`ak run status\` and the finished-run notice all say it, while merged and \`not merged: <reason>\` stay the repository run's answers" \
              || { no "33 delivered instead of not merged"; sed 's/^/      /' "$WORK/delivered.log" "$WORK/delivered-status.log" | head -10; }
# --- 34: the session babysitter types the stalled seats back into motion (offline) ------------
# Six real seats on a tmux server of this check's own, replaying captured TUI panes and writing
# down whatever is typed into it -- so what the babysitter did is a file, not a guess. Fake
# adapters answer for the meters: codex with a nearly spent week and resets in hand, muse with
# the window a 429 leaves behind, claude with nothing. What has to hold is the whole policy: a
# fresh stall is left alone, a three-minute-old one is typed back into motion with the word its
# harness understands, a second pass inside three minutes types nothing, Muse's window is waited
# out and OpenAI's is spent out of the reset policy first, an hour of it asks the user once and
# stops, a seat that is working and a seat that is nobody's are never touched at all.
STALLH="$WORK/home-stall"; STALLT="$WORK/stall-tmux"; STALLAD="$WORK/ad-stall"
STALLBIN="$WORK/bin-stall"; STALLTYPED="$WORK/stall-typed"
mkdir -p -- "$STALLH/.agentkit/state" "$STALLT" "$STALLAD" "$STALLBIN" "$STALLTYPED"
STALL=0
cat >"$STALLAD/claude.sh" <<'SH'
#!/usr/bin/env bash
[ "${1:-}" = usage ] && printf '%s\n' '{"meters":[],"error":"unknown: smoke fake"}'
exit 0
SH
cat >"$STALLAD/muse.sh" <<SH
#!/usr/bin/env bash
W="$STALLAD/muse.window"
SH
cat >>"$STALLAD/muse.sh" <<'SH'
# the meta window a 429 leaves behind, which for the real adapter is state/usage-meta.json
if [ "${1:-}" = usage ]; then
  when=$(cat "$W" 2>/dev/null || echo 0)
  if [ "$when" = 0 ]; then printf '%s\n' '{"meters":[],"error":"unknown: smoke fake"}'
  else printf '{"provider":"meta","error":null,"meters":[{"name":"quota","used":100,"resets_at":%s,"window_secs":604800}]}\n' "$when"; fi
fi
exit 0
SH
cat >"$STALLAD/codex.sh" <<SH
#!/usr/bin/env bash
set -uo pipefail
S="$STALLAD/codex"
SH
cat >>"$STALLAD/codex.sh" <<'SH'
used=$(cat "$S.used" 2>/dev/null || echo 95)
avail=$(cat "$S.avail" 2>/dev/null || echo 2)
case "${1:-}" in
usage)        printf '{"provider":"openai","error":null,"meters":[{"name":"primary_window","used":%s,"resets_at":%s,"window_secs":604800}]}\n' \
                "$used" "$(( $(date -u +%s) + 300000 ))" ;;
reset-status) printf '{"available":%s,"applicable":0,"weekly_used":%s,"resets_at":%s,"error":null}\n' \
                "$avail" "$used" "$(( $(date -u +%s) + 300000 ))" ;;
reset)        echo spent >>"$S.calls"; echo 5 >"$S.used"; printf '%s\n' "$((avail - 1))" >"$S.avail"
              printf '{"code":"reset","available":%s,"weekly_used":5,"resets_at":%s,"error":null}\n' \
                "$((avail - 1))" "$(( $(date -u +%s) + 604800 ))" ;;
*)            exit 0 ;;
esac
SH
chmod +x "$STALLAD"/*.sh
TMUX_TMPDIR="$STALLT" HOME="$STALLH" AGENTKIT_ADAPTER_DIR="$STALLAD" AGENTKIT_DISCORD_WEBHOOK= \
  TYPEDIR="$STALLTYPED" ADAPTERS="$STALLAD" PYTHONPATH="$REPO" \
  python3 - >"$WORK/stall.log" 2>&1 <<'PY' || STALL=1
import json
import os
import pathlib
import time

from agentkit import config, notify, orch, watch

typed = pathlib.Path(os.environ["TYPEDIR"])
cfg = config.load()
config.ensure_dirs()


def seat(name, line, model, record=True):
    """Replay a captured pane and write down whatever the watcher types into it."""
    import shlex
    pane = typed / f"{name}.pane"
    pane.write_text(line + "\n")
    if record:
        config.save_session(cfg, name, model, ["opus", "astra"],
                            {"cwd": str(typed), "created": int(time.time())})
    orch.start(name, str(typed), ["sh", "-c",
               f"stty -echo; sleep .3; cat {shlex.quote(str(pane))}; "
               f"cat > {shlex.quote(str(typed / (name + '.txt')))}"], model)
    orch.tmux_out("resize-window", "-t", f"={name}:", "-x", "100", "-y", "40")


def typed_into(name):
    path = typed / f"{name}.txt"
    return path.read_text() if path.exists() else ""


def meta_window(seconds_from_now):
    """Tell the fake muse adapter when meta's spent window resets, the way a 429 does."""
    pathlib.Path(os.environ["ADAPTERS"], "muse.window").write_text(
        str(int(time.time() + seconds_from_now)))
    (config.STATE / "usage.json").unlink(missing_ok=True)   # so the next read is the adapter's


fixtures = config.REPO / "tests/fixtures"
claude_pane = (fixtures / "claude-stall-pane.txt").read_text()
codex_pane = (fixtures / "codex-stall-pane.txt").read_text()
seat("stall-claude", claude_pane, "opus")
seat("stall-codex-goal", codex_pane.replace("exceeded retry limit, last status: 429 Too Many Requests",
                                          "Goal stalled: no progress after three attempts"), "astra")
seat("stall-codex-quota", codex_pane, "astra")
seat("stall-muse", (fixtures / "muse-stall-pane.txt").read_text(), "spark")
seat("fine-seat", "reading the tests", "opus")
seat("by-hand", claude_pane, "opus", record=False)
time.sleep(1.5)                     # the panes have to have painted before anything reads them

meta_window(3600)                   # muse's window is open, so its seat is not to be typed into
state, said = {"stalls": {}}, []
watch.health(cfg, state, False, said.append)
stalled = {"stall-claude", "stall-codex-goal", "stall-codex-quota", "stall-muse"}
assert set(state["stalls"]) == stalled, state
assert all(typed_into(name) == "" for name in stalled), "typed into a stall three seconds old"
assert all("stood for 3 minutes" in line for line in said), said

# three minutes on, and every stall but the one waiting on a window is typed back into motion
for entry in state["stalls"].values():
    for key in ("since", "stall_at", "changed_at"):
        entry[key] -= 240
said = []
watch.health(cfg, state, False, said.append)
time.sleep(1.0)
assert typed_into("stall-claude") == "continue\n", typed_into("stall-claude")
assert typed_into("stall-codex-goal") == "/goal resume\n", typed_into("stall-codex-goal")
assert typed_into("stall-codex-quota") == "continue\n", typed_into("stall-codex-quota")
assert typed_into("stall-muse") == "", "typed into a seat whose provider window is still open"
assert typed_into("fine-seat") == "", "typed into a seat that is working"
assert typed_into("by-hand") == "", "typed into a seat nothing here started"
assert any("waiting until" in line for line in said), said
# the OpenAI quota went to the usage-limit reset policy before that seat was resumed
assert any("usage-limit reset applied" in line for line in said), said
assert (config.STATE / "openai-reset.json").exists()

# a second pass straight after types nothing: one resume per seat per three minutes
watch.health(cfg, state, False, said.append)
time.sleep(0.5)
assert typed_into("stall-claude") == "continue\n", typed_into("stall-claude")

# Muse's window has passed, so now that seat is resumed too
meta_window(-60)
state["stalls"]["stall-muse"].update(since=time.time() - 240, nudged_at=0)
state["stalls"]["stall-muse"]["resets_at"] = time.time() - 60
watch.health(cfg, state, False, said.append)
time.sleep(1.0)
assert typed_into("stall-muse") == "continue\n", typed_into("stall-muse")

# an hour of the same stall on seats at their prompts: nobody is asked, and nothing more
# is typed -- an idle seat sends nothing, however long its stall line stands
before = {name: typed_into(name) for name in stalled}
for entry in state["stalls"].values():
    entry["since"] -= watch.GIVE_UP
    entry.pop("nudged_at", None)
said = []
watch.health(cfg, state, False, said.append)
time.sleep(0.5)
assert all(typed_into(name) == before[name] for name in stalled), "nudged after the hour was up"
assert not (config.STATE / "notify-stall-claude.json").exists(), "asked an idle seat"
assert state["stalls"]["stall-claude"]["told"], state    # the hour is latched, not asked
said = []
watch.health(cfg, state, False, said.append)
assert not [line for line in said if "asked the user" in line], said    # silent, and stays silent

# The user takes over this watcher-authored capacity alert; orchestrator questions
# retain their separate open-plus-progress contract, exercised by check 32.
watch.save_state({"reviewed": {}, "own": {}, "stalls": dict(state["stalls"])})
orch.seen_by_user("stall-claude")
assert "stall-claude" not in watch.load_state()["stalls"], watch.load_state()
assert notify.last("stall-claude") is None

# a seat whose pane shows no signature at all is forgotten, and never typed into
said, moving = [], {"stalls": {"fine-seat": {"since": time.time() - 600,
                                             "signature": "API Error"}}}
watch.health(cfg, moving, False, said.append)
time.sleep(0.5)
assert "fine-seat" not in moving["stalls"], moving
assert any("fine-seat: moving again" in line for line in said), said
assert typed_into("fine-seat") == "", "typed into a seat that is working"

# Pruning the old name after a rename must leave the live seat's stall latch intact.
# (The seat is idle, so there is no needs-you record: nothing was ever asked.)
watch.save_state(state)
assert not config.notify_path("stall-muse").exists()
told = state["stalls"]["stall-muse"]["told"]
renamed = orch.rename("stall-muse", "stall-muse-renamed")
assert config.resolve_session("stall-muse") == renamed
watch.health(cfg, state, False, said.append)
watch.save_state(state)
migrated = watch.load_state()["stalls"]
assert "stall-muse" not in migrated, migrated
assert migrated[renamed]["told"] == told, "pruning an alias cleared the live latch"
assert typed_into("stall-muse") == before["stall-muse"], "typed into the renamed seat"
print("ok")
PY
[ "$(wc -l <"$STALLAD/codex.calls" 2>/dev/null || echo 0)" -eq 1 ] || STALL=1
# and the pass runs from the command itself: a dry run says what it would type and types nothing
cat >"$STALLBIN/gh" <<'SH'
#!/usr/bin/env bash
case "$*" in
  "api user") printf '{"login":"me"}\n' ;;
  *search/issues*) printf '{"total_count":0,"incomplete_results":false,"items":[]}\n' ;;
  *) printf '[]\n' ;;
esac
SH
chmod +x "$STALLBIN/gh"
HOME="$STALLH" TMUX_TMPDIR="$STALLT" PYTHONPATH="$REPO" python3 - <<'PY'
import time
from agentkit import orch, watch
pane = watch.pane_text(orch.find("stall-claude"))
state = watch.load_state()
entry = {"signature": "API Error"}
watch.observe(entry, pane, "claude", time.time() - 600)
state["stalls"] = {"stall-claude": entry}
watch.save_state(state)
PY
STALLWAS=$(md5sum <"$STALLH/.agentkit/state/watch.json")
STALLTYPEDWAS=$(cat "$STALLTYPED/stall-claude.txt" 2>/dev/null || echo none)
HOME="$STALLH" TMUX_TMPDIR="$STALLT" AGENTKIT_ADAPTER_DIR="$STALLAD" PATH="$STALLBIN:$PATH" \
  ak watch --dry-run >"$WORK/stall-dry.log" 2>&1 || STALL=1
grep -q "^would resume stall-claude, stalled on API Error, with 'continue'\$" "$WORK/stall-dry.log" || STALL=1
[ "$(md5sum <"$STALLH/.agentkit/state/watch.json")" = "$STALLWAS" ] || STALL=1
[ "$(cat "$STALLTYPED/stall-claude.txt" 2>/dev/null || echo none)" = "$STALLTYPEDWAS" ] || STALL=1
env -u TMUX TMUX_TMPDIR="$STALLT" tmux -L agentkit-test kill-server 2>/dev/null
[ "$STALL" = 0 ] && ok "34 the session babysitter: a fresh stall is left alone, a three-minute-old one gets 'continue' (Codex goal mode '/goal resume'), one resume per three minutes, Muse's window waited out and OpenAI's reset spent first, an hour of it asks the user once, and a working seat and a seat nothing started are never typed into" \
                || { no "34 the session babysitter"; sed 's/^/      /' "$WORK/stall.log" "$WORK/stall-dry.log" 2>/dev/null | head -12; }
# --- 35: the menu is projects, their sessions by state, and six keys (offline) ------
# One seat working with a plan and a going run, one needing with a question, one done,
# and one of the smoke suite's own runs, newer than both. The menu is what a phone needs:
# projects with needing first, rows number/name/orchestrator/state/last, the plan bar,
# six keys, `c` config and `i` info -- and no runs list, no follow, no pager.
RUNSH="$WORK/home-runs"
mkdir -p -- "$RUNSH/.agentkit/state"
cp "$MHOME/.agentkit/state/usage.json" "$RUNSH/.agentkit/state/usage.json"
HOME="$RUNSH" PYTHONPATH="$REPO" COLUMNS=100 python3 - "$$" >"$WORK/runs.log" 2>&1 <<'PY'
import io
import sys
import time
from contextlib import redirect_stdout

from agentkit import config, menu, orch, run, watch

config.ensure_dirs()
now = time.time()
owner = run.process_owner(int(sys.argv[1]))
GOING, SMOKE = "20260101-1000-teach-the-menu", "20260101-1100-smoke-make-hello-pass"
d = config.RUNS / GOING
d.mkdir(parents=True)
run.save_state(d, {"run_id": GOING, "title": "Teach the menu the plan bar", "state": "running",
                   "verdict": None, "executor": "opus", "reviewer": "astra", "rounds": 3,
                   "round_summaries": [{"round": 1}], "launched_session": "atoll-fix",
                   "started_at": now - 900, **owner, "merged": False, "reported": True})
(config.RUNS / SMOKE).mkdir()
run.save_state(config.RUNS / SMOKE, {"run_id": SMOKE, "title": "Smoke make hello pass",
                                     "state": "running", "verdict": None, "executor": "opus",
                                     "reviewer": "astra", "rounds": 2, "round_summaries": [],
                                     "started_at": now - 60, **owner, "merged": False,
                                     "reported": True})
cfg = config.load()
for name, repo in (("atoll-fix", "atoll"), ("ask-seat", "atoll"), ("done-seat", "atoll")):
    checkout = config.CODE / repo
    (checkout / ".git").mkdir(parents=True, exist_ok=True)
    config.save_session(cfg, name, "fable", ["opus"],
                        {"repo": str(checkout), "cwd": str(checkout)})
(config.STATE / "plan-atoll-fix.md").write_text("- [x] a\n- [x] b\n- [ ] c\n"
                                                "- [ ] d\n- [ ] e\n")
from agentkit import notify
notify.record("ask-seat", "needs", "Merge the MOV helper before or after?")
notify.record("done-seat", "done", "hero swapped and published")
import agentkit.watch as watch_mod
watch_mod.live_state = lambda seat, *a, **kw: {"state": "working"
    if seat["name"] == "atoll-fix" else "at_prompt", "rule": "smoke",
    "evidence": "", "began": now - 600, "since": now - 600}
orch.sessions = lambda: [{"name": n, "repo": str(config.CODE / "atoll"),
                          "path": str(config.CODE / "atoll"), "live": "working"
                          if n == "atoll-fix" else "at_prompt", "since": now - 600,
                          "created": now - 5 * 86400} for n in
                         ("atoll-fix", "ask-seat", "done-seat")]


def menu_lines(keys):
    """Every non-empty line one run of the menu printed, driven by `keys`."""
    out = io.StringIO()
    sys.stdin = io.StringIO(keys)
    with redirect_stdout(out):
        assert menu.main([]) == 0
    return [line.rstrip() for line in out.getvalue().splitlines() if line.strip()]


assert menu.KEYS == "n new   x stop   c config   i info   q leave", menu.KEYS
assert not hasattr(menu, "runs_listing") and not hasattr(menu, "runs")
assert not hasattr(menu, "recover_run") and not hasattr(menu, "watch_run")
lines = menu_lines("q\n")
assert any(line == "atoll" for line in lines), lines
assert not any("seats" in line for line in lines), lines
assert any("your projects" in line for line in lines), lines
row = next(line for line in lines if "atoll-fix" in line)
assert "fable" in row and "working" in row and "tasks " in row and "2/5" in row, row
assert not any("Teach the menu" in line for line in lines), lines
assert not any("Smoke" in line or SMOKE in line for line in lines), lines
status = io.StringIO()
with redirect_stdout(status):
    assert run.cmd_status([]) == 0
assert SMOKE in status.getvalue(), status.getvalue()
assert "Merge the MOV helper" in "\n".join(lines), lines
assert "hero swapped" in "\n".join(lines), lines
assert not any("press r" in line for line in lines), lines
for key in ("r", "p", "b", "s", "u"):
    out = menu_lines(f"{key}\nq\n")
    assert any(f"not a key: {key!r}" in line for line in out), (key, out)
assert any("orchestrator  worker  effort" in line for line in menu_lines("c\nq\nq\n")), lines
info = menu_lines("i\nq\nq\n")
assert any("agentkit: you talk to one orchestrator" in line for line in info), info
assert watch.plan_progress("atoll-fix") == (2, 5)
assert watch.plan_progress("no-such-seat") == (0, 0)
print("ok")
PY
RENDERRC=$?
if [ "$RENDERRC" = 0 ]; then
  ok "35a menu renderer: projects, rows, plan bar, six keys, c/i, no runs"
else
  no "35a menu renderer"
  diagnose "$RENDERRC" "$WORK/runs.log" python3 'check 35 embedded fixture'
fi

# --- result ----------------------------------------------------------------
if python3 "$REPO/tests/test_auth_watch.py" >"$WORK/auth-watch.log" 2>&1; then
  ok "40 auth watchdog: immediate needs-login, one alert per episode, no auth nudge, recovery and unknown stuck escalation"
else
  no "40 auth watchdog"; cat "$WORK/auth-watch.log"
fi
if python3 "$REPO/tests/test_stop_hook.py" >"$WORK/stop-hook.log" 2>&1; then
  ok "48 the end of a turn: a question, a done or a run to wait on allows the stop, anything else is blocked with the rule it broke, twice per turn and never for a worker; a harness with no blocking hook has the same test typed at its prompt once"
else
  no "48 end-of-turn rule"; tail -30 "$WORK/stop-hook.log"
fi
if seat_state_check >"$WORK/seat-state.log" 2>&1; then
  ok "42 seat states: a session is working, needs you or done -- (a) a turn-ended hook fact reads 'needs you', (b) a newer turn-began fact reads 'working' since it began, (c) every harness's dialog fixture reads the 'asking' fact and a transcript quoting it does not, (d) a notified seat reads 'needs you' with its question for a reason and a newer turn outranks it, (e) two renders and a watch tick agree on the word and the since and no live state is ever a reason to type into a seat, (f) the babysitter reads every stall/quota/auth signature from adapters/*.toml and no harness is named in watch.py, (g) a hook writes nothing for a worker or without a seat, (h) ak orch list --why names the word, the authority, the rule and the evidence, (i) every adapter's hooks verb is idempotent"
else
  no "42 seat states"; tail -30 "$WORK/seat-state.log"
fi
if lifecycle_check v4l >"$WORK/v4l.log" 2>&1; then
  ok "36 exact stall timing, attach races, quota windows, real Claude stream and narrow runs"
else
  no "36 v4l regressions"; tail -30 "$WORK/v4l.log"
fi
if python3 "$REPO/tests/test_v4n.py" >"$WORK/v4n.log" 2>&1; then
  ok "37 readable menus at 40/80/100 columns, run reporting, Codex resume and launch/cache edges"
else
  no "37 v4n regressions"; tail -30 "$WORK/v4n.log"
fi
if python3 "$REPO/tests/test_macbridge.py" >"$WORK/macbridge.log" 2>&1; then
  ok "38 Mac files: local paths, queue/serve/inbox, timeout/missing, singleton SSH and LaunchAgent"
else
  no "38 Mac file bridge"; tail -30 "$WORK/macbridge.log"
fi
if python3 "$REPO/tests/test_notify_rule.py" >"$WORK/notify-rule.log" 2>&1; then
  ok "45 what Discord hears: a PR of ours goes to its seat or its run and never to Discord, the hourly alerts only while the seat is working, auth and the inbox question still ask, workers stay silent, a done per job, the test sink outranks the webhook, and the card names its seat"
else
  no "45 the Discord rule"; tail -30 "$WORK/notify-rule.log"
fi
if python3 "$REPO/tests/test_v4r.py" >"$WORK/v4r.log" 2>&1; then
  ok "39 usage left at 40/100 columns: Claude 21% · resets Sun 00:00 · Fable 47%, ChatGPT 69%, Muse spent; the notes give way on a phone; project counts fold run details, all lines fit"
else
  no "39 provider usage-left menu"; tail -30 "$WORK/v4r.log"
fi
# --- 46: a fourth harness plugs in (offline) -------------------------------
# A config.toml line and an adapter pair, and nothing else: tests/fixtures/adapters/echo.sh
# answers every verb the contract names and echo.toml says everything else about it -- its
# screen, its update, what its usage call needs -- with no agentkit/harness/echo.py at all.
# A checkout of its own holds the config that names it; the five real harnesses keep
# their own .toml beside the suite's fake scripts, so nothing here calls a harness, spends a
# reset or reaches a network.
EHOME="$WORK/home-echo"; EAD2="$WORK/ad-echo"; ERP="$WORK/echo-repo"
mkdir -p -- "$EHOME" "$EAD2" "$ERP/tests"
fakeadapter "$EAD2" claude pass; fakeadapter "$EAD2" codex pass; fakeadapter "$EAD2" muse pass
fakeadapter "$EAD2" grokbuild meterless
fakeadapter "$EAD2" opencode meterless
cp "$REPO/adapters/claude.toml" "$REPO/adapters/codex.toml" "$REPO/adapters/muse.toml" \
  "$REPO/adapters/grokbuild.toml" "$REPO/adapters/opencode.toml" "$EAD2/"
cp "$REPO/tests/fixtures/adapters/echo.sh" "$REPO/tests/fixtures/adapters/echo.toml" "$EAD2/"
cp -R "$REPO/agentkit" "$REPO/bin" "$REPO/templates" "$REPO/hooks" "$REPO/tools" "$ERP/"
printf '# the fourth-harness fixture never runs a gate; ak update --dry-run only names it\n' \
  >"$ERP/tests/smoke.sh"
python3 - "$REPO/config.default.toml" "$ERP/config.default.toml" <<'PY'
import pathlib, sys
source, target = (pathlib.Path(arg) for arg in sys.argv[1:3])
# one [models.*] block and its provider: the whole cost of a fourth harness
target.write_text(source.read_text() + '\n[models.echo]\nharness = "echo"\nmodel = "echo-1"\n'
                  'effort = "low"\nprovider = "test"\n\n[providers.test]\nmode = "subscription"\n')
PY
akecho() { env -u TMUX -u AGENTKIT_SESSION HOME="$EHOME" AGENTKIT_ADAPTER_DIR="$EAD2" "$ERP/bin/ak" "$@"; }
ECHORC=0
# (a) a seat is planned on it, and its TUI is told no conversation id (echo.sh exits 3)
printf '\n' | (cd "$WORK" && akecho orch echo-seat --model echo --dry-run) \
  >"$WORK/echo-orch.log" 2>&1 || ECHORC=1
grep -q '^orch: echo (--model)$' "$WORK/echo-orch.log" || ECHORC=1
grep -q '^session echo-seat in ' "$WORK/echo-orch.log" || ECHORC=1
jq -e '.orchestrator == "echo" and (has("conversation") | not)' \
  "$EHOME/.agentkit/state/session-echo-seat.json" >/dev/null || ECHORC=1
# (b) a whole loop executes through it, reviewed on another provider
cat >"$WORK/task-echo.md" <<'MD'
---
repo: none
rounds: 1
---
# Smoke fourth harness

## Goal
Nothing: the echo adapter answers with the prompt's last line.

## Done when
```bash
true
```
MD
akecho run "$WORK/task-echo.md" --rounds 1 --exec echo --review astra \
  >"$WORK/echo-run.log" 2>&1 || ECHORC=1
ERID=$(sed -n 's/^\[[0-9:]*\] run \([^:]*\): .*$/\1/p' "$WORK/echo-run.log" | head -1)
jq -e '.state == "pass" and .verdict == "PASS" and .executor == "echo" and .reviewer == "astra"' \
  "$EHOME/.agentkit/runs/$ERID/run.json" >/dev/null || ECHORC=1
# (c) its meter is in the table, and (d) the update plan names it and what it cannot do
akecho usage >"$WORK/echo-usage.txt" 2>&1 || ECHORC=1
grep -qE '^test +echo +58% ' "$WORK/echo-usage.txt" || ECHORC=1
# a PATH with none of the six harnesses on it: the plan still names all seven
(PATH="$PYBIN:/usr/bin:/bin"; akecho update --dry-run) >"$WORK/echo-update.log" 2>&1 || ECHORC=1
grep -q '^echo 1\.0.*cannot be reverted: it is a fixture' "$WORK/echo-update.log" || ECHORC=1
grep -q '^muse .*requires a complete local snapshot for rollback' "$WORK/echo-update.log" || ECHORC=1
# (e) and the menu draws its seat with the screen rules of its own toml
(cd "$WORK" && env -u TMUX -u AGENTKIT_SESSION PYTHONPATH="$ERP" HOME="$EHOME" \
  AGENTKIT_ADAPTER_DIR="$EAD2" python3 - >"$WORK/echo-menu.log" 2>&1 <<'PY'
from unittest.mock import patch
from agentkit import config, menu, notify, orch, terminal, watch

PANES = {"idle": "reading the prompt\n❯\n? for shortcuts\n",
         "working": "thinking about it\nesc to interrupt\n? for shortcuts\n",
         "asking": "Overwrite it?\n1. yes\n2. no\npress enter to choose\n"}
cfg = config.load()
record = config.session_records()["echo-seat"]
seat = {"name": "echo-seat", "path": record["cwd"], "created": record["created"],
        "attached": False, "exited": False, "legacy": False, "resumable": False, "repo": None}
bad = []
for kind, state, word, rule in (("idle", "at_prompt", "needs you", "prompt.composer"),
                                ("working", "working", "working", "working.interrupt"),
                                ("asking", "asking", "needs you", "asking.chooser")):
    with patch.object(watch, "pane_text", return_value=PANES[kind]), \
            patch.object(orch, "tmux_out", return_value=(1, "")), \
            patch.object(terminal, "width", return_value=100):
        found = watch.live_state(seat, cfg=cfg)
        row = menu.row(cfg, 1, seat)
        why = "\n".join(orch.explain(seat, cfg))
    if (found["state"], found["rule"], found["authority"]) != (state, rule, "screen"):
        bad.append(f"{kind}: {found}")
    if row[:4] != ["1", "echo-seat", "echo", word]:
        bad.append(f"{kind} row: {row}")
    if rule not in why:
        bad.append(f"{kind} why: {why}")
print("\n".join(bad) or "the menu reads echo.toml")
raise SystemExit(1 if bad else 0)
PY
) || ECHORC=1
if [ "$ECHORC" = 0 ]; then
  ok "46 a fourth harness plugs in: one config.toml line and tests/fixtures/adapters/echo.{sh,toml} -- a seat planned on it, a scratch run executed through it and reviewed by astra, its meter in ak usage, its update plan saying what it cannot revert, and the menu reading its screen rules, with no Python of its own"
else
  no "46 a fourth harness plugs in"
  for log in echo-orch echo-run echo-update echo-menu; do
    [ ! -f "$WORK/$log.log" ] || tail -3 "$WORK/$log.log" | sed "s/^/      $log: /"
  done
  grep -E '^(test|echo|muse) ' "$WORK/echo-usage.txt" "$WORK/echo-update.log" 2>/dev/null | sed 's/^/      /'
fi

# --- 46b: Grok Build plugs in the same way, with no meter -----------------
# The shipped fourth harness, not a fixture: a seat planned on it, its meterless provider
# neutral in `ak usage`, its update plan naming its versioned reinstall, and the menu
# reading its screen rules off its own captures.  A current cache for all four providers,
# the xai record exactly as its probe writes it, so nothing is probed at all.
GHOME="$WORK/home-grok"
mkdir -p -- "$GHOME/.agentkit/state"
wideworkers "$GHOME"
python3 - "$GHOME/.agentkit/state/usage.json" <<'PY'
import json, sys, time
providers = {}
for name, harness, via in (("anthropic", "claude", "fable"),
                           ("openai", "codex", "astra"), ("meta", "muse", "spark")):
    providers[name] = {"provider": name, "harness": harness, "via": via, "meters": [],
                       "pace": None, "error": "unknown: smoke cache", "exhausted": False}
# the meterless provider exactly as its probe writes it: answers, no meters, neutral
providers["xai"] = {"provider": "xai", "harness": "grokbuild", "via": "grok", "meters": [],
                    "pace": None, "error": None, "exhausted": False, "none": True,
                    "none_reason": "no meter"}
with open(sys.argv[1], "w") as fh:
    json.dump({"fetched_at": time.time(), "providers": providers}, fh)
PY
GROKRC=0
# (a) a seat is planned on it, and the command is the TUI's own flags
printf '\n' | (cd "$WORK" && HOME="$GHOME" ak orch smoke-grok --model grok --dry-run) \
  >"$WORK/grok-orch.log" 2>&1 || GROKRC=1
grep -q '^orch: grok (--model)$' "$WORK/grok-orch.log" || GROKRC=1
grep -q 'idle-compact.py --harness grokbuild -- grok ' "$WORK/grok-orch.log" || GROKRC=1
grep -q -- '--rules ' "$WORK/grok-orch.log" || GROKRC=1
grep -q -- '--trust --always-approve --model grok-4.7 --reasoning-effort xhigh' \
  "$WORK/grok-orch.log" || GROKRC=1
jq -e '.orchestrator == "grok"' \
  "$GHOME/.agentkit/state/session-smoke-grok.json" >/dev/null || GROKRC=1
# (b) its provider is neutral, never last, and says `no meter` where the menu draws it
HOME="$GHOME" ak usage --json >"$WORK/grok-usage.json" 2>&1 || GROKRC=1
jq -e '.providers.xai.none == true and .providers.xai.error == null
       and .providers.xai.budget == 1.0
       and (.pick_order | index("grok") != null)' "$WORK/grok-usage.json" >/dev/null || GROKRC=1
HOME="$GHOME" ak usage >"$WORK/grok-usage.txt" 2>&1 || GROKRC=1
grep -q '1\.0 in step' "$WORK/grok-usage.txt" || GROKRC=1
(cd "$WORK" && HOME="$GHOME" PYTHONPATH="$REPO" python3 - >"$WORK/grok-menu-usage.log" 2>&1 <<'PY'
from agentkit import config, menu
for line in menu.usage_lines(config.load(), 100):
    print(line)
PY
) || GROKRC=1
grep -q 'Grok' "$WORK/grok-menu-usage.log" || GROKRC=1
grep -q 'no meter' "$WORK/grok-menu-usage.log" || GROKRC=1
# (c) the update plan names it with its versioned reinstall
HOME="$GHOME" ak update --dry-run >"$WORK/grok-update.log" 2>&1 || GROKRC=1
grep -q '^grokbuild .*versioned reinstall available' "$WORK/grok-update.log" || GROKRC=1
# (d) and the menu draws its seat with the screen rules of its own toml
(cd "$WORK" && env -u TMUX -u AGENTKIT_SESSION PYTHONPATH="$REPO" HOME="$GHOME" \
  AKFIX="$REPO/tests/fixtures" python3 - >"$WORK/grok-menu.log" 2>&1 <<'PY'
import os
from pathlib import Path
from unittest.mock import patch
from agentkit import config, menu, orch, terminal, watch

FIX = Path(os.environ["AKFIX"])
PANES = {kind: (FIX / f"grok-{name}-pane.txt").read_text(encoding="utf-8",
                                                         errors="replace")
         for kind, name in (("idle", "prompt"), ("working", "working"),
                            ("asking", "dialog"))}
cfg = config.load()
record = config.session_records()["smoke-grok"]
seat = {"name": "smoke-grok", "path": record["cwd"], "created": record["created"],
        "attached": False, "exited": False, "legacy": False, "resumable": False, "repo": None}
bad = []
for kind, state, word, rule in (("idle", "at_prompt", "needs you", "prompt.composer"),
                                ("working", "working", "working", "working.turn"),
                                ("asking", "asking", "needs you", "asking.trust")):
    with patch.object(watch, "pane_text", return_value=PANES[kind]), \
            patch.object(orch, "tmux_out", return_value=(1, "")), \
            patch.object(terminal, "width", return_value=100):
        found = watch.live_state(seat, cfg=cfg)
        row = menu.row(cfg, 1, seat)
        why = "\n".join(orch.explain(seat, cfg))
    if (found["state"], found["rule"], found["authority"]) != (state, rule, "screen"):
        bad.append(f"{kind}: {found}")
    if row[:4] != ["1", "smoke-grok", "grok", word]:
        bad.append(f"{kind} row: {row}")
    if rule not in why:
        bad.append(f"{kind} why: {why}")
print("\n".join(bad) or "the menu reads grokbuild.toml")
raise SystemExit(1 if bad else 0)
PY
) || GROKRC=1
if [ "$GROKRC" = 0 ]; then
  ok "46b Grok Build plugs in: a seat planned on it with the TUI's own flags, its meterless provider neutral in ak usage with \`no meter\` on the menu row, its update plan naming its versioned reinstall, and the menu reading its screen rules"
else
  no "46b Grok Build plugs in"
  for log in grok-orch grok-menu-usage grok-update grok-menu; do
    [ ! -f "$WORK/$log.log" ] || tail -3 "$WORK/$log.log" | sed "s/^/      $log: /"
  done
  jq -c '.providers.xai' "$WORK/grok-usage.json" 2>/dev/null | sed 's/^/      xai: /'
fi

# --- 46c: OpenCode plugs in as a harness (offline) --------------------------
# The real adapters/opencode.sh and adapters/opencode.toml against a stub `opencode` binary:
# a seat planned on mimo with the rulebook pinned per launch, a worker turn through the
# adapter, its unknown meter in ak usage, and its versioned update plan.  The home is a
# temporary directory holding a dummy provider key, and no provider is contacted; the one
# live proof, a real headless turn through the adapter, is the task's proof command, run by
# hand on the host.
OCHOME="$WORK/home-oc"; OCBIN="$WORK/bin-oc"
mkdir -p -- "$OCHOME/.config/opencode" "$OCBIN" "$WORK/oc-ws"
printf '{"provider":{"mimo":{"options":{"apiKey":"tp-dummy"}}}}\n' \
  >"$OCHOME/.config/opencode/opencode.json"
cat >"$OCBIN/opencode" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  run) printf '%s\n' '{"type":"step_start","timestamp":1,"sessionID":"ses_smoke","part":{"type":"step-start"}}' '{"type":"text","timestamp":2,"sessionID":"ses_smoke","part":{"type":"text","text":"smoke says hi"}}'; exit 0 ;;
  session) printf '%s\n' '{"info":{"id":"ses_smoke","tokens":{"input":10,"output":4,"reasoning":1,"cache":{"read":2,"write":0}}}}' ;;
  auth) printf '[]' ;;
  --version) echo "opencode v9.9.9-smoke" ;;
  *) echo "stub opencode: $*" >&2; exit 2 ;;
esac
STUB
chmod +x "$OCBIN/opencode"
# The adapter reads OPENCODE_CONFIG_DIR, then XDG_CONFIG_HOME, before HOME: either one set
# on the smoke host would send it at the owner's real config instead of the sandbox.
akoc() { env -u TMUX -u AGENTKIT_SESSION -u XDG_CONFIG_HOME -u OPENCODE_CONFIG_DIR HOME="$OCHOME" PATH="$OCBIN:/usr/bin:/bin" AK_RUN_ROLE=seat "$REPO/bin/ak" "$@"; }
OCHRC=0
# (a) a seat is planned on mimo, and the dry run prints a valid pinned command line
printf '\n' | (cd "$WORK" && akoc orch oc-seat --model mimo --dry-run) \
  >"$WORK/oc-orch.log" 2>&1 || OCHRC=1
grep -q '^orch: mimo (--model)$' "$WORK/oc-orch.log" || OCHRC=1
grep -q -- '--harness opencode' "$WORK/oc-orch.log" || OCHRC=1
grep -q 'OPENCODE_CONFIG_CONTENT=' "$WORK/oc-orch.log" || OCHRC=1
grep -q 'opencode --standalone --auto' "$WORK/oc-orch.log" || OCHRC=1
jq -e '.orchestrator == "mimo"' \
  "$OCHOME/.agentkit/state/session-oc-seat.json" >/dev/null || OCHRC=1
python3 - "$WORK/oc-orch.log" <<'PY' || OCHRC=1
import json, shlex, sys
line = [ln for ln in open(sys.argv[1]).read().splitlines() if ln.startswith("python3 ")][0]
words = shlex.split(line)
content = next(w for w in words if w.startswith("OPENCODE_CONFIG_CONTENT=")).split("=", 1)[1]
doc = json.loads(content)
assert doc["model"] == "mimo/mimo-v2.6-pro", doc["model"]   # at `none`, bare
assert doc["agents"]["build"]["system"].startswith("# You are the orchestrator"), "rulebook"
assert doc["plugins"][0].endswith("hooks/opencode-seat"), doc["plugins"]
PY
# (b) a worker turn executes through the adapter: final, session and appended usage
echo "say hello" >"$WORK/oc-prompt.md"
akoc worker mimo "$WORK/oc-prompt.md" --workspace "$WORK/oc-ws" --out "$WORK/oc-out" \
  >"$WORK/oc-worker.log" 2>&1 || OCHRC=1
grep -q "smoke says hi" "$WORK/oc-out/final.md" 2>/dev/null || OCHRC=1
[ "$(cat "$WORK/oc-out/session_id" 2>/dev/null)" = ses_smoke ] || OCHRC=1
tail -1 "$WORK/oc-out/events.jsonl" 2>/dev/null | \
  jq -e '.type == "result" and .usage.input_tokens == 10 and .usage.output_tokens == 5' \
  >/dev/null || OCHRC=1
# (c) a configured key and no meter is neutral: none, budget 1.0, `no meter` on the row.
# mimo is payg, so while any subscription reports no pace it stays out of the order;
# the neutral budget is what puts it in once every subscription is ahead of pace.
akoc usage --json >"$WORK/oc-usage.json" 2>&1 || OCHRC=1
jq -e '.providers.mimo.none == true and .providers.mimo.error == null
       and .providers.mimo.budget == 1.0' "$WORK/oc-usage.json" >/dev/null || OCHRC=1
akoc usage >"$WORK/oc-usage.txt" 2>&1 || OCHRC=1
grep -qE '^mimo +mimo ' "$WORK/oc-usage.txt" || OCHRC=1
grep -q '1\.0 in step' "$WORK/oc-usage.txt" || OCHRC=1
(cd "$WORK" && HOME="$OCHOME" PYTHONPATH="$REPO" python3 - >"$WORK/oc-menu-usage.log" 2>&1 <<'PY'
from agentkit import config, menu
for line in menu.usage_lines(config.load(), 100):
    print(line)
PY
) || OCHRC=1
grep -q 'no meter' "$WORK/oc-menu-usage.log" || OCHRC=1
akoc update --dry-run >"$WORK/oc-update.log" 2>&1 || OCHRC=1
grep -q '^opencode .*versioned reinstall available' "$WORK/oc-update.log" || OCHRC=1
if [ "$OCHRC" = 0 ]; then
  ok "46c OpenCode plugs in: a seat planned on mimo with the rulebook, model and plugin pinned per launch in the dry-run command line, a worker turn through the adapter with its session totals appended, its meterless provider neutral at budget 1.0 in ak usage, and opencode upgrade with a versioned revert in the update plan"
else
  no "46c OpenCode plugs in"
  for log in oc-orch oc-worker oc-usage oc-update; do
    [ ! -f "$WORK/$log.log" ] && [ ! -f "$WORK/$log.txt" ] || tail -5 "$WORK/$log".* 2>/dev/null | sed "s/^/      $log: /"
  done
fi

if slot_queue_check >"$WORK/v5am.log" 2>&1; then
  ok "47 max_runs=1: ak run status says waiting for a slot · 1 ahead for the queued fake run, which starts when the first ends; depth-1 tests share the parent slot"
else
  no "47 host run queue"; cat "$WORK/v5am.log"
fi

echo "coverage: offline fixtures plus the live harness/GitHub/browser checks labeled above"
echo "NOT EXERCISED: clean-host installation or interactive logins (separate certification)"
finish
