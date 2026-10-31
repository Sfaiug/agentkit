"""Upgrade the harnesses with acceptance gates and a restorable local snapshot.

Which harnesses, and how each one moves, is `[update]` in `adapters/<harness>.toml` -- the
version command, the upgrade, the versioned reinstall that puts it back and the environment it
needs.  A harness whose manifest names no version and upgrade command is not one `ak update`
moves.

A harness whose installer deletes the build it replaces, with no versioned reinstall, is put
back from the local snapshot its plugin takes before any upgrade (`snapshot`).
Failures attempt rollback and verify the resulting identities; a failed restore is reported
explicitly, with its snapshot retained. Ordinary launches and version checks remain frozen.

A gate that cannot run on this host is a skipped line, never a refusal: the upgrade runs
against the gates that are available, and the report says which ran.  Only the harnesses
this host has are upgraded, and by `ak update` none while a session is working; the tick
upgrades one that is behind its latest release in the background, sessions or not (see
`keep_current`), and no two upgrades ever run at once.  Agentkit itself moves after the
harnesses either way, and the three-minute tick moves it on its own, in both cases only to a
commit whose `tests/live.sh` has no regression where it has one (`live_target`), and never while
a harness upgrade runs: its gates test one agentkit commit from start to end.  The tick starts a
check only once the logins it lends will outlast it (`_waits_for_login`), `ak update` at once.
"""

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from . import (command_help, config, gitcall, host, lend, orch, owner, retention,
               transitions, versions, worker)
from . import record as run_record
from .harness import load as harness_plugin

VERSION = re.compile(r"\d+\.\d+\.\d+[^\s()]*")
PINS = {"DISABLE_AUTOUPDATER": "1", "MUSE_NO_AUTO_UPDATE": "1", "MUSE_LAUNCHER_INSTALL": "0"}
STEP_CAP = 30 * 60          # an upgrade that is not done in half an hour is not going to be
LIVE_CAP = 2 * 60 * 60      # the gate makes real model calls and waits out two retry backoffs
E2E_CAP = 90 * 60           # a fresh account, three harness installs and one real merged run
FETCH_CAP = 60              # the tick's look at origin; one not back by then is offline
START_WAIT = 2              # the detached start-up check's deadline for origin
UPDATE_TAIL = 10            # how many of a failed start-up update's last lines the menu shows
ASK_EVERY = 60 * 60         # how often the tick asks a harness's latest release, at most
RETRY_AFTER = 24 * 60 * 60  # a gate can fail for what the release did not cause: try it daily

VERSION_KEY = "{version}"   # `[update] revert`: where the version to reinstall goes
MOVING = "agentkit-update.lock"  # under config.TMP: held by each move of ~/agentkit
SWAPS = "harness-swaps.json"  # the latest installs and reverts, [harness, began, ended]
SWAPS_KEPT = 16               # far more than can begin between a turn's end and the look at it
LIVE = "live-checks"          # under config.STATE: one directory per check, `<commit>-<started>`
HARNESS_GATES = "harness-gates"  # under config.STATE: one failure episode per harness
FRESH_FAULTS = "fresh-gate-faults"  # under config.STATE: the fresh-install gate's standing faults
# A check of agentkit's tests/live.sh, detached: a throwaway worktree of exactly the commit,
# the script in it, then the output and the exit code, each written whole.  Both run in the
# process group of a holder, a `sleep` this runner starts first and reaps last, after every
# signal to the group, so the group's id names no other process while it signals it.  Once the
# script exits, KILL to the group ends whatever it left there; at the check's cap, or as soon
# as the tick's TERM tells it to, TERM, then KILL after the grace, and a red exit code: so a
# check ends on a host with no /proc for `worker.kill_marked` to read.  The exit code waits,
# up to the grace, until signal 0 finds the group gone, zombies reaped; past the holder's
# reaping it only probes, so an id named anew costs that wait and nothing else.
# The worktree is added under `MOVING`, shared: one added while a move adopts ~/agentkit
# (`versions.adopt`) names a repository that move takes away.  The script's fd 3 holds it, a
# flock outliving the python that took it, until the add ends; git gets no fd 3, so nothing it
# leaves running keeps it.
# This script is the only writer of both files; the tick only creates the directory and reads it.
LIVE_RUN = r'''import os, signal, subprocess, sys, time
check, repo, commit, cap, grace, moving = sys.argv[1:]
os.chdir(check)
os.environ["AK_LIVE_FAILED"] = f"{check}/failed"
holder = subprocess.Popen(["sleep", "99999999"], process_group=0)
with open("output.tmp", "w") as out:
    script = subprocess.Popen(["sh", "-c", 'exec 3>>"$3" && "$4" -c "import fcntl; fcntl.flock(3, '
                               'fcntl.LOCK_SH)" && git -C "$0" worktree add --quiet --detach "$1" "$2" '
                               '3>&- && exec 3>&- && cd "$1" && bash tests/live.sh',
                               repo, f"{check}/tree", commit, moving, sys.executable],
                              stdout=out, stderr=out, process_group=holder.pid)


def end(sig):
    try:
        os.killpg(holder.pid, sig)
    except OSError:     # macOS finds no group where only zombies are left
        pass


try:
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    code = script.wait(max(0, float(cap) - time.time()))
except (KeyboardInterrupt, subprocess.TimeoutExpired):
    code = None
signal.signal(signal.SIGTERM, lambda *_: None)
if code is None:
    end(signal.SIGTERM)
    try:
        script.wait(float(grace))
    except subprocess.TimeoutExpired:
        pass
    code = 124      # as timeout(1) says of what it ended
end(signal.SIGKILL)
script.wait()
holder.wait()
gone = time.monotonic() + float(grace)
while time.monotonic() < gone:  # a busy host runs what KILL reached only later
    try:
        os.killpg(holder.pid, 0)
    except OSError:
        break
    time.sleep(0.01)
subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", f"{check}/tree"],
               capture_output=True)
with open("output.tmp", "a") as out:
    out.write(f"[exit {code}]\n")
os.replace("output.tmp", "output")
with open("exit.tmp", "w") as out:
    out.write(f"{code}\n")
os.replace("exit.tmp", "exit")
'''


def _argv(harness, facts, key):
    """One `[update]` command line out of a manifest, or [] where it names none."""
    value = facts.get(key)
    if value is None or value == []:
        return []
    if not isinstance(value, list) or not all(isinstance(word, str) and word for word in value):
        raise config.Error(f"adapters/{harness}.toml: [update].{key} must be a list of words")
    return list(value)


def harnesses(cfg=None):
    """Every configured harness that says how it is upgraded, in config.toml order.

    The table this used to carry, read off `adapters/<name>.toml` instead, so a fourth harness
    is upgraded, reverted and reported with the three without a line of code here.  A harness
    whose manifest names no `[update] version` and `upgrade` is left out of the plan, the gate
    and the report alike: nothing here knows how to move it, and saying nothing is the truth.
    """
    cfg = config.load() if cfg is None else cfg
    found = {}
    for entry in cfg["models"].values():
        name = entry.get("harness")
        if not isinstance(name, str) or name in found:
            continue
        facts = harness_plugin(name).update
        version, upgrade = _argv(name, facts, "version"), _argv(name, facts, "upgrade")
        if not version or not upgrade:
            continue
        env = facts.get("env") if isinstance(facts.get("env"), dict) else {}
        found[name] = {"name": name, "version": version, "upgrade": upgrade,
                       "revert": _argv(name, facts, "revert") or None,
                       "latest": _argv(name, facts, "latest"),
                       "env": {str(key): str(value) for key, value in env.items()},
                       "cannot": str(facts.get("cannot") or "")}
    return tuple(found.values())


def say(message):
    print(message, flush=True)


def version(harness):
    """Full release/build identity; an unsuccessful version command cannot identify a build."""
    argv = [config.harness_binary(harness["version"][0]) or harness["version"][0],
           *harness["version"][1:]]
    try:
        proc = subprocess.run(argv, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=120, env={**config.child_env(), **PINS})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    identity = "; ".join(line.strip() for output in (proc.stdout, proc.stderr)
                         for line in output.splitlines() if line.strip())
    if proc.returncode or not VERSION.search(identity):
        return ""
    # a harness whose release label does not identify a build says so itself
    return harness_plugin(harness["name"]).identity(identity, harness["version"])


def step(cmd, fh, env=None, timeout=STEP_CAP, *, target_slice=None):
    """Run one command into the log; True when it exited 0.

    Its stdin is /dev/null: an update runs unattended, and a gate started from a terminal
    must not wait on it -- a suite that did held the host's suite lock for hours.
    """
    cmd = [config.harness_binary(cmd[0]) or cmd[0], *cmd[1:]]
    fh.write(f"\n$ {shlex.join(cmd)}\n")
    fh.flush()
    environment = {**config.child_env(), **PINS, **(env or {})}
    try:
        if target_slice:
            code = orch.call_in_slice(cmd, f"agentkit-update-{time.time_ns()}", environment,
                                      fh, timeout=timeout, log=say, target_slice=target_slice)
        else:
            with subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                  start_new_session=True, env=environment) as proc:
                try:
                    code = proc.wait(timeout=timeout)
                finally:
                    # A timed-out installer can leave a subshell of its own writing.
                    # Signal only while the child is still ours: wait()/poll() may already have
                    # reaped an exited launcher, after which its PID/PGID could be reused.
                    if proc.returncode is None and proc.poll() is None:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait()
    except subprocess.TimeoutExpired:
        fh.write(f"[timed out after {timeout}s]\n")
        code = "timeout"
    except OSError as exc:
        fh.write(f"[{exc}]\n")
        code = "could not start"
    fh.write(f"[exit {code}]\n")
    fh.flush()
    if code != 0:
        say(f"update: command={shlex.join(cmd)} exit={code} log={fh.name}")
        for line in Path(fh.name).read_text(errors="replace").splitlines()[-20:]:
            say(f"  {line}")
    return code == 0


@contextmanager
def swapping(name):
    """Record an install or revert of harness `name` as begun, and as ended when it returns.

    Between the two its command is missing or half-installed, and a worker turn that starts
    then fails for it: `swap_end` is how `turns.call_retrying` tells that failure from a harness
    that cannot run.  The gates after it are not a swap, the harness is whole while they run.
    A mark that cannot be written costs a turn its retry, never the upgrade.
    """
    began = time.time()
    _mark_swap(name, began, None)
    try:
        yield
    finally:
        _mark_swap(name, began, time.time())


def _mark_swap(name, began, ended):
    path = config.STATE / SWAPS
    try:
        swaps = [swap for swap in json.loads(path.read_text()) if swap[:2] != [name, began]]
    except (OSError, ValueError, TypeError, KeyError):
        swaps = []
    try:
        path.with_suffix(".tmp").write_text(
            json.dumps([*swaps[1 - SWAPS_KEPT:], [name, began, ended]]))
        os.replace(path.with_suffix(".tmp"), path)
    except OSError:
        pass


def swap_end(name, since, until):
    """When the swaps of harness `name` that overlapped an attempt from `since` to `until` end.

    None when none did.  One that never recorded its end ends `STEP_CAP` after it began, when
    its step is killed: until then it is taken as still running, and after it holds nothing.
    """
    try:
        swaps = [(began, ended or began + STEP_CAP) for harness, began, ended
                 in json.loads((config.STATE / SWAPS).read_text()) if harness == name]
        return max((ended for began, ended in swaps if began <= until and ended > since),
                   default=None)
    except (OSError, ValueError, TypeError):
        return None


def moved(before, after):
    """The harnesses whose version actually changed, as `name old->new`."""
    return [f"{n} {before[n] or '?'}->{after[n] or '?'}" for n in before if before[n] != after[n]]


RELEASE = re.compile(r"\d+\.\d+\.\d+")
BUILD = re.compile(r"\d+\.\d+\.\d+-R\d+(?:\.\d+)*")   # 1.4.1-R4503.1: build 4503.1 of 1.4.1


def _release(text):
    """The build a version identity names, else its first X.Y.Z, or "" when it names neither.

    A label may say `1.4.1` before its build `1.4.1-R4503.1`, and a newer build of the same
    X.Y.Z is a newer release.
    """
    match = BUILD.search(text or "") or RELEASE.search(text or "")
    return match.group(0) if match else ""


def _downgrade(old, new):
    """True when both identities name a release and the new one is the lower.

    A build is compared only with a build: a label without one says nothing about which build
    of its release is installed.
    """
    old_key, new_key = ([int(part) for part in re.findall(r"\d+", _release(text))]
                        for text in (old, new))
    if len(old_key) == 3 or len(new_key) == 3:
        old_key, new_key = old_key[:3], new_key[:3]
    return bool(old_key and new_key) and new_key < old_key


def kept(before, after):
    """Where each harness ended up when nothing had to be put back.  {name: (state, detail)}."""
    landed = {}
    for name in before:
        old, now = before[name], after[name]
        if not old:
            landed[name] = ("unchanged", "not installed here")
        elif now == old:
            landed[name] = ("unchanged", f"still on {old}")
        elif _downgrade(old, now):
            landed[name] = ("kept", f"installed {_release(old)} is newer than "
                                    f"the channel's {_release(now)}")
        else:
            landed[name] = ("upgraded", f"{old}->{now or '?'}")
    return landed


def revert(plan, before, after, fh, log, snapshot=None, attempted=False):
    """Put every harness that moved back where it was.  {name: (state, detail)}.

    A harness that will not go back, or has no command that could, is named with the version it
    is stuck on and with the command to try by hand, because from here on nothing else will.
    """
    landed = kept(before, after)
    for harness in plan:
        name = harness["name"]
        old, now = before[name], after[name]
        if snapshot is not None and attempted and snapshot.harness["name"] == name:
            # A failed installer can replace bytes and still report the old release label.
            log(f"update: restoring {name} from {snapshot.path}")
            try:
                with swapping(name):
                    snapshot.restore()
            except (OSError, RuntimeError, config.Error) as exc:
                landed[name] = ("cannot revert", f"{exc}; snapshot retained at {snapshot.path}")
            else:
                landed[name] = ("reverted", f"back on {old}")
            continue
        if not old or now == old:
            continue
        if harness["revert"] is None:
            landed[name] = ("cannot revert", f"on {now or '?'} and not back on {old}: "
                                             f"{harness['cannot']}, so no command puts it back")
            continue
        log(f"update: reverting {name} to {old}")
        command = [word.replace(VERSION_KEY, VERSION.search(old).group(0))
                   for word in harness["revert"]]
        with swapping(name):
            ok = step(command, fh, harness["env"])
        back = version(harness)
        if ok and back == old:
            landed[name] = ("reverted", f"back on {old}")
        else:
            landed[name] = ("cannot revert",
                            f"on {back or '?'} and not back on {old}; run "
                            f"`{shlex.join(command)}` by hand")
    return landed


def fresh_unavailable():
    """Why the fresh-HOME gate cannot even be attempted here, or "" when it can.

    Missing file and wrong platform are known without running anything.  Whether this
    host can run it is the gate's own to say when it runs: it exits before its first
    check where it cannot, and that is a skip, not a verdict on the upgrade.
    """
    e2e = config.REPO / "tests" / "e2e-fresh.sh"
    if not e2e.is_file():
        return f"no {e2e}"
    if not sys.platform.startswith("linux"):
        return f"Linux only (this is {sys.platform})"
    return ""


def fresh_gate(fh, log):
    """Run the fresh-HOME gate where it can run; where it cannot, skip it.

    This covers borrowed logins, not a clean host.  The script leaves before its first
    check where the host cannot run it, with no acceptance line of its own;
    a run that reached its checks says so there, and a non-zero exit from one is a
    failure, however it ended.  Only what this gate appended is read back: the live
    gate that passed first wrote its own acceptance line to the same log.
    """
    why = fresh_unavailable()
    if why:
        return False, f"skipped: {why}"
    e2e = config.REPO / "tests" / "e2e-fresh.sh"
    log(f"update: running {e2e.name}, the fresh-install gate")
    mark = _end(fh)
    if step(["bash", str(e2e)], fh, {"AGENTKIT_ACCEPTANCE_REQUIRED": "1",
                                     "AK_LIVE_FAILED": str(_failed_path(fh))}, timeout=E2E_CAP):
        return True, "passed (throwaway HOME with borrowed logins; clean host and interactive logins not exercised)"
    text = _since(fh, mark)
    if "acceptance:" not in text and "[exit 2]" in text:
        reason = ""
        for line in text.splitlines():
            if "e2e-fresh.sh:" in line:
                reason = line.split("e2e-fresh.sh:", 1)[1].strip()
        return False, f"skipped: {reason or 'the fresh-install gate could not run on this host'}"
    return False, "failed"


def _end(fh):
    """Where the log `fh` ends now: its gates write to it straight, not through `fh`."""
    try:
        return os.fstat(fh.fileno()).st_size
    except OSError:
        return 0


def _since(fh, mark):
    """What was written to the log `fh` from `mark` on."""
    try:
        with open(fh.name, "rb") as gate_log:
            gate_log.seek(mark)
            return gate_log.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _failed_path(fh):
    """Where a gate logging to `fh` puts the labels of the checks it failed (tests/acceptance.sh)."""
    return Path(f"{fh.name}.failed")


def run_gate(key, fh):
    """Run gate `key` ("live" or "fresh") on the box as it stands: (passed, failed labels,
    its own `FAIL` lines, why).

    A fresh-install gate that cannot run on this host is skipped, which passes; one that ran
    and failed no check clears its standing faults once they are told (`fresh_standing`).
    """
    failed = _failed_path(fh)
    failed.unlink(missing_ok=True)
    mark, began = _end(fh), time.time()
    if key == "live":
        passed = step(["bash", str(live_gate())], fh,
                      {"AGENTKIT_ACCEPTANCE_REQUIRED": "1", "AK_LIVE_FAILED": str(failed)},
                      timeout=LIVE_CAP, target_slice=orch.slice_name())
        why = "passed" if passed else "failed"
    else:
        passed, why = fresh_gate(fh, say)
    if passed:
        _note_pass(key, began, time.time())
    try:
        labels = set(failed.read_text().splitlines()) - {""}
        failed.unlink()
    except (OSError, UnicodeError):
        labels = set()
    if key == "fresh":
        faults = config.STATE / FRESH_FAULTS
        if passed and not labels and (_handed(faults) or {}).get("told"):
            (faults / "handed").unlink()
        passed = passed or why.startswith("skipped:")
    return passed, labels, _fail_titles(_since(fh, mark)), why


def report(landed, out):
    """One line per harness: what happened to it, and where that leaves it."""
    for name, (state, detail) in landed.items():
        print(f"update: {name}: {state}, {detail}", file=out)


def working_sessions(cfg=None):
    """The sessions whose word is `working` now: no harness is upgraded while there are any."""
    from . import orch, watch
    if cfg is None:
        try:
            cfg = config.load()
        except config.Error:
            return []
    try:
        sessions = orch.listing(reconcile=False)
    except (config.Error, OSError, ValueError, TypeError, KeyError):
        return []
    working = []
    for session in sessions:
        try:
            answer = watch.session_state(session["name"], session=session, cfg=cfg)
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            continue     # what cannot be read cannot prove anything is working
        # one out of usage, waiting for it to come back, has no turn an upgrade could break
        if answer["word"] == "working":
            working.append(session["name"])
    return working


def agentkit_dir():
    """The checkout the menu updates: ~/agentkit, whatever checkout this runs from."""
    return Path.home() / "agentkit"


def outdated():
    """Was newer agentkit put in place since this process read its code: by the tick, above
    all, under a menu left open (`notify.installed_at`)?"""
    from . import notify
    return notify.installed_at() > config.STARTED


def publishes():
    """May this process write what every seat's bar shows?  Only the live checkout as it is now
    does -- or anything where there is none, a test's sandbox: a worktree's menu, or one open
    across an install, wrote its own design over the live one's, so bars flipped between the
    two."""
    live = agentkit_dir()
    return not outdated() and (not live.exists() or live.resolve() == config.REPO)


def agentkit_version():
    """That checkout's short commit and its date, `abc1234 · 2026-09-29`, or "" when it is no
    checkout at all."""
    code, said = _git("log", "-1", "--format=%h · %cs")
    return "" if code else said


def behind(timeout=START_WAIT):
    """Whether origin's main has a commit that checkout lacks, as origin itself says.

    `ls-remote` fetches nothing, and an answer not back within `timeout` seconds -- offline,
    or slow -- is not behind, so `ak` opens as it is.  Its process group is killed whole: the
    ssh git starts would otherwise go on waiting on the network after it.
    """
    try:
        with subprocess.Popen(["git", "-C", str(agentkit_dir()), "ls-remote", "origin",
                               "refs/heads/main"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              encoding="utf-8", errors="replace", start_new_session=True,
                              env={**config.child_env(), **PINS}) as proc:
            try:
                head = proc.communicate(timeout=timeout)[0].split()[:1]
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                return False
    except OSError:
        return False
    return bool(not proc.returncode and head
                and _git("merge-base", "--is-ancestor", head[0], "HEAD")[0])


def _git(*args, timeout=60):
    """One git command in that checkout: its exit code and output, 1 when it could not run."""
    try:
        proc = subprocess.run(["git", "-C", str(agentkit_dir()), *args], capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env={**config.child_env(), **PINS})
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def left_as_is():
    """Why ~/agentkit is somebody's work -- `dirty`, or on another branch -- or "" when it is
    main as origin left it, or a version ak swapped in (`versions`), which a move may swap."""
    if versions.owned(agentkit_dir()):
        return ""
    _, branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    code, changes = _git("status", "--porcelain", "--untracked-files=normal")
    return (f"on {branch or 'a detached HEAD'}, not main" if branch != "main"
            else "dirty" if code or changes else "")


def startup():
    """The menu's detached check and update; JSON steps and a result on its pipe, no terminal.

    A closed pipe means the menu left, not that the update should stop. Capturing command
    output happens only here, so no thread in the menu redirects another screen's stdout.
    """
    def send(**news):
        try:
            os.write(sys.__stdout__.fileno(), (json.dumps(news) + "\n").encode("utf-8"))
        except OSError:
            pass            # the update still belongs to the checkout after its menu has gone

    said, failed, moved = io.StringIO(), 0, False
    with redirect_stdout(said), redirect_stderr(said):
        try:
            if agentkit_dir().resolve() == config.REPO and not left_as_is() and behind():
                before = agentkit_version()
                failed = update_agentkit(lambda done, total: send(progress=done / total))
                moved = agentkit_version() != before   # even if install.sh then failed
        except Exception as exc:    # detached: the notice is the only way to hear a failure
            say(f"update: {exc!r}")
            failed = 1
    send(moved=moved, lines=said.getvalue().splitlines()[-UPDATE_TAIL:] if failed else [])
    return failed


def update_agentkit(progress=None, pull=True):
    """Move ~/agentkit forward and reinstall from it; the exit code.

    Forward on main only, the new version swapped in whole (`versions.switch`): a clone with
    its own commits, changes of its own or another branch out is somebody's work, and is left
    as it is, saying so.
    Everything both commands print is said out loud, because the menu shows the last lines
    of it; stdout is a pipe, so install.sh sees no tty and asks no questions.
    `progress(done, total)` hears of each step as it begins and of the last one's end: `ak`'s
    start fills the rule under its header from it, and the fetch is a step of its own, so the
    rule moves through the network wait.  The move goes to `live_target`, and with none
    nothing moves or reinstalls.  `pull=False` only reinstalls what is checked out; a commit
    moves to exactly it, already fetched.
    """
    config.ensure_dirs()
    with (config.TMP / MOVING).open("a") as lock:
        # one at a time, the tick's retry included: otherwise an install.sh that passes clears
        # the pending mark of another still running, which then fails with nothing to retry it
        fcntl.flock(lock, fcntl.LOCK_EX)
        directory = agentkit_dir()
        why = left_as_is()
        if why:
            say(f"update: agentkit: left as it is: {directory} is {why}")
            return 1
        if upgrading():
            # asked under this lock, which `upgrade` waits for before it begins, so its gates
            # test one commit from start to end; the next tick after it moves this one (go_live)
            say("update: agentkit: moves once the harness upgrade running now ends")
            return 0
        install = [str(directory / "install.sh")]
        swap = ["swap"]     # to a commit known later, by `versions.switch`: no command of its own
        steps = ([["git", "-C", str(directory), "fetch", "--quiet", "origin", "main"], swap]
                 if pull is True else [swap] if pull else []) + [install]
        pending = config.STATE / "agentkit-install-pending"
        for done, cmd in enumerate(steps):
            if progress:
                progress(done, len(steps))
            if cmd is swap:
                target = pull if isinstance(pull, str) else live_target()
                if not target:
                    say("update: agentkit: origin/main moves here once its tests/live.sh passed")
                    return 0
                say(f"update: {directory} goes to {target[:12]}")
                pending.touch()     # a tick cut off once it is swapped in still owes the install
                why = versions.switch(directory, target)
                if why:
                    say(f"update: {why}")
                    return 1
                continue
            if cmd is install:
                # here until install.sh passes: the pull has already moved HEAD, so origin/main
                # is no longer ahead of it, and only this tells the tick to run it again (go_live)
                pending.touch()
            say(f"update: $ {shlex.join(cmd)}")
            try:
                proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                                      timeout=STEP_CAP, env={**config.child_env(), **PINS})
            except (OSError, subprocess.TimeoutExpired) as exc:
                say(f"update: {exc}")
                return 1
            for line in proc.stdout.splitlines() + proc.stderr.splitlines():
                say(line)
            if proc.returncode != 0:
                say(f"update: {shlex.join(cmd)} exited {proc.returncode}")
                return proc.returncode
        pending.unlink(missing_ok=True)
        if progress:
            progress(len(steps), len(steps))
        return 0


def self_unavailable():
    """Why agentkit itself cannot move now, or an empty string when it can.

    A working session is no reason: on a busy host one always is, and merged agentkit sat
    hours behind main waiting for none to be.
    """
    if not (agentkit_dir() / ".git").exists():
        return f"no checkout at {agentkit_dir()}"
    return ""


def update_self():
    """Fast-forward agentkit itself; the exit code.

    No checkout where one belongs is a skipped line rather than a failure: the harness
    result already reported stands either way.
    """
    why = self_unavailable()
    if why:
        print(f"update: agentkit: skipped: {why}")
        return 0
    code, lines = update_once("update")
    for line in lines:
        say(line)
    return code


def update_once(where, **kw):
    """`update_agentkit`, and what it said, a failure only the first time: the exit code and lines.

    A checkout left as it is, and a pull or install.sh that failed, is said once per origin
    commit -- by `ak update` and in the tick's log alike, each keeping its own record -- so
    a checkout somebody is working in is not the same lines every three minutes.
    """
    said = io.StringIO()
    with redirect_stdout(said):
        code = update_agentkit(**kw)
    if code:
        # a refusal comes before any pull, so origin is asked afresh: a stale origin/main
        # would hold a new commit to the one already said
        _git("fetch", "--quiet", "origin", "main", timeout=FETCH_CAP)
        head = _git("rev-parse", "origin/main")[1]
        record = config.STATE / f"agentkit-said-{where}"
        try:
            if record.read_text().strip() == head:
                return code, []
        except OSError:
            pass
        record.write_text(head + "\n")
    return code, said.getvalue().splitlines()


def go_live(log, now=None):
    """The tick's half of `update_self`: agentkit live within one tick of origin/main moving,
    or of its `tests/live.sh` passing (`live_tick`).

    Only the checkout this tick runs from moves -- the cron line runs ~/agentkit/bin/ak --
    so a tick from a worktree, a test's above all, never touches the live one.  A fetch that
    fails is offline, silent, and the next tick fetches again.  An install.sh that has not
    passed since the last pull runs again every tick, without a pull and offline too, until it
    passes; an origin/main that moved meanwhile is pulled and installed instead, so a merge
    that fixes install.sh goes live.
    """
    if agentkit_dir().resolve() != config.REPO:
        return
    versions.finish(agentkit_dir())
    fetched = not _git("fetch", "--quiet", "origin", "main", timeout=FETCH_CAP)[0]
    live_tick(log, time.time() if now is None else now, fetched)
    target = live_target() if fetched else ""
    # exit 1 is the target ahead of HEAD; anything else, a failed fetch above all, is not
    moved = bool(target) and _git("merge-base", "--is-ancestor", target, "HEAD")[0] == 1
    pending = config.STATE / "agentkit-install-pending"
    if not (moved or pending.exists()):
        return
    head = target if moved else _git("rev-parse", "HEAD")[1]
    failed, lines = update_once("watch", pull=moved and target)
    if not failed:
        # one a harness upgrade held back moved nothing: a tick after that upgrade says this
        if not pending.exists() and _git("rev-parse", "HEAD")[1] == head:
            log(f"agentkit is live at {head[:12]}")
    elif lines:
        log(f"WARN agentkit did not go live at {head[:12]}:")
        for line in lines:
            log(f"  {line}")


def _last_pass(key):
    """Check `key`'s ("live" or "fresh") last pass on record: when it ended and how long it took,
    (0, None) while it has none."""
    try:
        ended, took = json.loads((config.STATE / f"{key}-check-passed").read_text())
        return float(ended), float(took)
    except (OSError, ValueError, TypeError):
        return 0, None


def _note_pass(key, began, ended):
    """Keep a pass of check `key` for `margin`, unless a later one is kept: the tick reads one
    check until the install moves, past any upgrade's run since, so each looks and writes under
    one lock.  A failed write costs a margin."""
    record = config.STATE / f"{key}-check-passed"
    try:
        with record.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if ended > _last_pass(key)[0]:
                _put(record, json.dumps([ended, ended - began]))
    except OSError:
        pass


def margin(key):
    """How long the logins a run of check `key` borrows must last: its last pass's time doubled,
    never past its cap, which alone would hold a quarter of go-lives; the cap where none passed."""
    cap = {"live": LIVE_CAP, "fresh": E2E_CAP}[key]
    took = _last_pass(key)[1]
    return cap if took is None else min(2 * took, cap)


def _waits_for_login(key, what, seconds, log, now):
    """Whether `what` waits for a later tick: a login lent to it lapses within `seconds` of when
    it would start, failing all that needs it for no fault of the code, until it is renewed (by its
    harness on use, the tick's usage probes or `auth seat`) or lapsed and lends none.  The log hears
    it once: `key` names the record of what it heard, gone when `what` starts."""
    said = config.STATE / f"{key}-check-held"
    first = lend.first_lapse()
    # it starts once all asking ends, never before the tick's `now`: a release's lookup, `auth
    # seat` and lending can each take minutes of a login's life
    now = max(now, time.time())
    if first is None or first[0] >= now + seconds:
        said.unlink(missing_ok=True)
        return False
    line = (f"{what} waits: {first[1]}'s login lapses at "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(first[0]))}, before it could end")
    if not said.exists() or said.read_text() != line:
        log(line)
        _put(said, line)
    return True


def live_checks():
    """Every check of tests/live.sh, oldest first: (started, commit, directory).

    The tick makes the directory, named for both, and `stopped` and `handed` in it; the
    check's own `LIVE_RUN` writes `output` and `exit`, and its suite writes `failed` labels.
    """
    found = []
    for check in (config.STATE / LIVE).glob("*-*"):
        commit, _, started = check.name.partition("-")
        if started.isdigit():
            found.append((int(started), commit, check))
    return sorted(found)


def _exit(check, started):
    """A check's exit code, or None while it has none: one written after `LIVE_CAP` is none,
    and so is any once the tick wrote `stopped`, so every reader counts that check red."""
    try:
        if (not (check / "stopped").exists()
                and (check / "exit").stat().st_mtime < started + LIVE_CAP):
            return int((check / "exit").read_text())
    except (OSError, ValueError):
        pass
    return None


def _alive(check, started, now):
    """Whether anything of that check still runs: whatever carries its marker, whatever its
    script said -- where there is no /proc to read that, until it has an exit code or its cap
    and the grace its runner gives the group after it have passed.

    Every reader asks this before it reads the check's verdict: the tick writes `stopped`
    before it signals anything, so a check it capped that is found ended reads `stopped`, never
    the exit code it wrote before its cap.
    """
    if host.PROC.is_dir():
        return bool(worker.marked_pids(str(check)))
    return _exit(check, started) is None and now < started + LIVE_CAP + worker.MARK_KILL_GRACE


def _put(path, text):
    """`text` into `path` whole: a reader sees the old file or the new one, never half."""
    path.with_suffix(".tmp").write_text(text)
    os.replace(path.with_suffix(".tmp"), path)


def _handed(check):
    """That check's hand-back record, or None while it has none."""
    try:
        return json.loads((check / "handed").read_text())
    except (OSError, ValueError):
        return None


def _live_failed(check):
    try:
        return set((check / "failed").read_text().splitlines()) - {""}
    except (OSError, UnicodeError):
        return set()


def _live_passed(check, started):
    code = _exit(check, started)
    # `baseline` records the tick's comparison of immutable results, before either is pruned.
    return code == 0 or (code is not None and bool(_live_failed(check))
                        and (check / "baseline").exists())


def _live_ended(check, code):
    return (float((check / "stopped").read_text()) if code is None
            else (check / "exit").stat().st_mtime)


def live_target():
    """The commit a move of ~/agentkit goes to, or "" while there is none.

    origin/main when the checkout has it already, when it has no `tests/live.sh`, or when a
    check of it passed or failed only where HEAD also failed; else the newest such commit,
    so what moves is exactly what passed, however far origin/main has gone on since.
    """
    tip = _git("rev-parse", "--verify", "--quiet", "origin/main")[1]
    passed = {commit for started, commit, check in live_checks()
              if not _alive(check, started, time.time()) and _live_passed(check, started)}
    if (not tip or tip in passed or _git("cat-file", "-e", f"{tip}:tests/live.sh")[0]
            or not _git("merge-base", "--is-ancestor", tip, "HEAD")[0]):
        return tip
    newer = _git("rev-list", "--topo-order", f"HEAD..{tip}")[1].split() if passed else []
    return next((commit for commit in newer if commit in passed), "")


def owed_live(now):
    """(commit, since) for the commit ~/agentkit has owed going live at the longest, or None
    while it owes none: one whose tests/live.sh passed, the fast-forward's target, or HEAD while
    its install.sh is owed, from that pass, else from its landing.  What `stuck.stalls` reads, so
    a move that fails however it fails is not quiet.
    """
    if agentkit_dir().resolve() != config.REPO:
        return None
    passed = {}
    for started, commit, check in live_checks():
        try:
            if not _alive(check, started, now) and _live_passed(check, started):
                passed[commit] = min(passed.get(commit, now), (check / "exit").stat().st_mtime)
        except OSError:
            continue
    # exit 1 is a commit HEAD lacks; anything else, one this checkout never fetched, is not owed
    owed = {commit for commit in {*passed, live_target()}
            if commit and _git("merge-base", "--is-ancestor", commit, "HEAD")[0] == 1}
    if (config.STATE / "agentkit-install-pending").exists():
        owed.add(_git("rev-parse", "HEAD")[1])
    since = {commit: passed.get(commit) or float(_git("log", "-1", "--format=%ct", commit)[1] or now)
             for commit in owed if commit}
    return min(since.items(), key=lambda found: found[1], default=None)


def live_tick(log, now, fetched):
    """The tick's half of tests/live.sh: it starts the checks and ends them at their cap.

    One past `LIVE_CAP` is ended by its runner (`LIVE_RUN`); that, or one of a commit the
    checkout already has, is ended by its marker too, for whatever left its group -- out of
    reach on a host with no /proc, as for every ak run there -- and its directory goes,
    worktree and all, only once nothing of it runs.  One the cap ends, or that ended with no
    exit code in time, is `stopped` before anything is signalled: red from then on, whatever
    it says later.  While origin/main has a `tests/live.sh` and no check of it passed, one is
    started, detached, as soon as none runs; a red one is started again on
    `watch.RETRY_BACKOFF` from its end.  As `watch.after_merge_checks` does, the newest red
    check no later check passed is handed back (`live_hand_back`), wherever main went since,
    once it is the second red in a row (a first red is only logged and waits for its retry),
    unless an older one's notice was typed or told already.
    A red tip with an exit code and failed labels first checks HEAD, reusing a result ended
    since the tip check began; any other red is held and retried as it is. Only failed labels
    shared with that result can pass the tip; those standing faults are handed back without
    holding the move. The comparison stays with the tip result in `baseline`.
    Offline, the tick decides on the origin/main it fetched last, but no check starts: origin
    may have moved on from it since; nor does one a login would not last (`_waits_for_login`).
    """
    from . import watch     # here, not at the top: watch imports this module
    tip = _git("rev-parse", "--verify", "--quiet", "origin/main")[1]
    head = _git("rev-parse", "HEAD")[1]
    had, running, pruned, done = {}, False, False, []
    for started, commit, check in live_checks():
        if commit not in had:
            had[commit] = not _git("merge-base", "--is-ancestor", commit, "HEAD")[0]
        baseline = commit == head and tip != head
        notice = _handed(check)
        notice = notice and (check / "baseline").exists() and not notice["told"]
        capped, alive = now >= started + LIVE_CAP, _alive(check, started, now)
        stop = ((not had[commit] or baseline) and not (check / "stopped").exists()
                and (capped if alive else _exit(check, started) is None))
        if stop:
            _put(check / "stopped", f"{now}\n")
        if (alive or stop) and (capped or (had[commit] and not baseline)):
            # its runner, told to, ends its group within one grace and writes its exit in the next
            worker.kill_marked(str(check), grace=2 * worker.MARK_KILL_GRACE)
            alive = _alive(check, started, now)
        if not alive and _live_passed(check, started):
            # before the pruning below takes a pass the install has already; one `baseline` makes
            # is kept where that is written
            _note_pass("live", started, _live_ended(check, _exit(check, started)))
        if alive:
            running = True
        elif had[commit] and not (baseline or notice):
            # a pass dates the install it leaves owed (owed_live), so it stays until that passes
            if not (config.STATE / "agentkit-install-pending").exists():
                shutil.rmtree(check, ignore_errors=True)
                pruned = True
        else:
            done.append((started, commit, check, _exit(check, started)))   # read once it ended
    if pruned:
        _git("worktree", "prune")
    mine = [(started, check, code) for started, commit, check, code in done if commit == tip]
    base, needs_base = [], False
    if mine and mine[-1][2] != 0:
        started, check, code = mine[-1]
        failed = _live_failed(check)
        base = [(s, c, rc) for s, commit, c, rc in done if commit == head
                and _live_ended(c, rc) >= started]
        # without an exit code or a failed label, no HEAD result could pass the tip
        needs_base = (not base and code is not None and bool(failed)
                      and not _git("cat-file", "-e", f"{head}:tests/live.sh")[0])
        if base and code is not None and failed and base[-1][2] not in (None, 0):
            s, other, rc = base[-1]
            # Upgrades between the two checks make them incomparable, even after a revert.
            try:
                same = not any(began <= max(_live_ended(check, code), _live_ended(other, rc))
                               and (ended or began + STEP_CAP) > min(started, s)
                               for _, began, ended in json.loads((config.STATE / SWAPS).read_text()))
            except FileNotFoundError:
                same = True
            except (OSError, ValueError, TypeError):
                same = False
            if same and failed <= _live_failed(other):
                _put(check / "baseline", other.name + "\n")
                _note_pass("live", started, _live_ended(check, code))
    episode = None      # a pass ends what was red before it; one typed or told stands until then
    reds = 0            # red checks in a row since the last pass, whichever commits they checked
    for started, commit, check, code in done:
        if commit == head and not (check / "baseline").exists():
            continue
        record = _handed(episode[1]) if episode else None
        if _live_passed(check, started):
            if code != 0:
                live_hand_back(commit, check, code, log, standing=True)
            episode, reds = None, 0
            continue
        reds += 1
        if not (record and (record["typed"] or record["told"])):
            episode = (commit, check, code)
    if episode:
        # A first red is logged and waits for its retry: the gate makes real model calls, and
        # one provider blip is not main broken.  The second red in a row goes to a seat.
        live_hand_back(*episode, log, hand=reds > 1 and (episode[0] != tip or not needs_base))
    if (running or not fetched or not tip
            or any(_live_passed(check, started) for started, check, _ in mine)
            or _git("merge-base", "--is-ancestor", tip, "HEAD")[0] != 1
            or _git("cat-file", "-e", f"{tip}:tests/live.sh")[0]):
        return
    if mine:
        started, check, code = mine[-1]
        if needs_base:
            tip = head
        ended = _live_ended(check, code)
        if tip != head and now < ended + watch.RETRY_BACKOFF[
                min(len(mine), len(watch.RETRY_BACKOFF)) - 1]:
            return
    if _waits_for_login("live", "tests/live.sh", margin("live"), log, now):
        return
    gitcall.no_auto_gc(agentkit_dir())
    log(f"checking agentkit at {tip[:12]} with tests/live.sh before it goes live")
    check = config.STATE / LIVE / f"{tip}-{int(now)}"
    check.mkdir(parents=True)
    orch.start_in_slice(
        [sys.executable, "-c", LIVE_RUN, str(check), str(agentkit_dir()), tip,
         str(int(now) + LIVE_CAP), str(worker.MARK_KILL_GRACE), str(config.TMP / MOVING)],
        f"agentkit-live-{check.name}",
        {**config.child_env(), **PINS, "AGENTKIT_ACCEPTANCE_REQUIRED": "1",
         worker.RUN_MARKER: str(check)}, os.devnull, log, target_slice=orch.slice_name())


def _fitted(head, titles, tail):
    """`head`, the failed checks' `titles` and `tail` as one line a composer shows whole
    (`watch.too_long`): each title whole or left out, and those left out counted."""
    from . import watch     # here, not at the top: watch imports this module
    for shown in range(len(titles), -1, -1):
        left = len(titles) - shown
        named = [*titles[:shown], *([f"{left} more failed checks left out"] if left else [])]
        line = f"{head}: {' / '.join(named)}. {tail}" if named else f"{head}. {tail}"
        refusal = watch.too_long(line)
        if not refusal:
            return line
    raise config.Error(refusal)     # its fixed words alone are too long: a fault to fix here


def _fail_titles(said):
    """Each failed check's `FAIL` line, without the output its check printed under it."""
    return [line.rstrip() for line in said.splitlines() if line.startswith("FAIL  ")]


def live_hand_back(commit, check, code, log, hand=True, *, standing=False):
    """Hand that red check of that commit back to fix, once, with its failed checks' titles
    and its output's path; with `hand` false it is only logged, as a first red waiting for its
    retry is.

    Its record is `handed` in the check's directory, the tick's own file: the line, the
    composer's mark while its Enter has not landed, so it is entered and never typed twice,
    and `told` once it has.  A red that holds the install also records the seat told and
    when, which its first place is read from (`first_place`).
    """
    record = _handed(check)
    if record is None or (standing and not record.get("standing")
                          and not (record["typed"] or record["told"])):
        output = check / "output"
        output = output if output.exists() else check / "output.tmp"  # one never finished
        try:
            said = output.read_text(errors="replace")
        except OSError:
            said = ""
        titles = _fail_titles(said)
        if standing:    # each failed label's own line, `SKIP` too: a skip fails this gate
            labels = sorted(_live_failed(check))
            heads = [(line, line[6:].split(":", 1)[0]) for line in said.splitlines()
                     if line.startswith(("FAIL  ", "SKIP  "))]
            # A whole label first: check 3's own line, not `3 acme`'s, which shares its first token
            # that acceptance.sh records each `/`-joined label of.
            titles = [next((line for whole in (True, False) for line, head in heads
                            if head == label or not whole and label in head.split(" ", 1)[0].split("/")),
                           f"{label}: no failure line recorded")
                      for label in labels]
        stopped = "" if code is not None else ", stopped before it finished"
        log(f"WARN tests/live.sh has standing faults at {commit[:12]}:" if standing else
            f"WARN agentkit stays as it is: tests/live.sh failed at {commit[:12]}:")
        for line in [*titles, *([f"[{stopped[2:]}]"] if stopped else [])]:
            log(f"  {line}")
        where = f"Output: {config.tilde(output)}."
        record = dict(line=_fitted(f"tests/live.sh has standing faults on agentkit's main at "
                                   f"{commit[:12]}, also failed on the running install{stopped}",
                                   titles, f"{where} Fix the standing faults.")
                      if standing else
                      _fitted(f"tests/live.sh failed on agentkit's main at {commit[:12]}{stopped}, "
                              "so this host stays on the agentkit it runs", titles,
                              f"{where} Fix main: your next agentkit run goes first in line until "
                              "the install moves, so make it the fix."),
                      typed=None, told=False, standing=standing)
        _put(check / "handed", json.dumps(record))
    if hand and _gate_hand_back(check, record, log, first=not record.get("standing")):
        log(f"handed agentkit's failed tests/live.sh at {commit[:12]} back to fix")


def _gate_hand_back(check, record, log, first=False):
    """Deliver a gate's saved line with the same composer receipt across ticks; with `first`,
    the seat told and when are recorded with it."""
    from . import deliver, watch  # here, not at the top: both import this module

    def keep(**change):
        record.update(change)
        _put(check / "handed", json.dumps(record))

    if record["told"]:
        return False
    key = deliver.remote_key(_git("remote", "get-url", "origin")[1])
    seat = watch.after_merge_deliver(None, {}, key, record["line"], log, typed=record["typed"],
                                     receipt=lambda mark: keep(typed=mark))
    if seat:
        keep(told=True, **({"seat": seat, "at": time.time()} if first else {}))
        return True
    return False


def first_place(state):
    """Whether that run goes first as the fix of a red that holds the install (`live_hand_back`).

    While the install lacks a held commit, the seat told of it owns one place: its earliest
    agentkit run of any kind launched since it was told that has not ended.  Read from the
    runs as they stand, never written at a launch, so no refusal, stop, park or relaunch can
    lose it; a record or session that cannot be read gives no place.
    """
    try:
        seat = transitions.launched_session(state)
        since = min((at for _, commit, check in live_checks()
                     if seat and (at := _told(check, seat)) is not None
                     and _git("merge-base", "--is-ancestor", commit, "HEAD")[0] == 1),
                    default=None)
        if since is None or not _contender(state, seat, since):
            return False
        mine, resolved = (transitions.first_started(state), state.get("run_id") or ""), {}
    except (config.Error, OSError, TypeError):
        return False
    for _, other in run_record.runs():
        try:
            if ((transitions.first_started(other), other.get("run_id") or "") < mine
                    and _contender(other, seat, since, resolved)):
                return False
        except (config.Error, OSError, TypeError):
            continue
    return True


def _told(check, seat):
    """When that check's hand-back told that seat, or None: one whose record or seat's session
    cannot be read told nobody, and takes no other hand-back's place with it."""
    record = _handed(check)
    try:
        if (isinstance(record, dict) and isinstance(record.get("seat"), str)
                and isinstance(record.get("at"), (int, float))
                and config.resolve_session(record["seat"]) == seat):
            return record["at"]
    except (config.Error, OSError):
        pass
    return None


def _contender(state, seat, since, resolved=None):
    """Whether that run is the seat's, on agentkit's repository, launched since then and not
    ended: a review of an agentkit PR, or a task in a clone of agentkit."""
    if (state.get("state") in run_record.ENDED or transitions.first_started(state) < since
            or transitions.launched_session(state, resolved) != seat):
        return False
    found = transitions.PR_PARTS.match(state.get("review_pr") or "")
    where = (f"{found[1]}/{found[2]}" if found else
             gitcall.git(state["repo"], "remote", "get-url", "origin", check=False)
             if state.get("repo") else "")
    return bool(where) and (gitcall.owner_name(where)
                            == gitcall.owner_name(_git("remote", "get-url", "origin")[1]))


def harness_gate_result(plan, passed, gate, log_path, titles=()):
    """A gate pass clears each harness's episode; its second red in a row, a failed `gate` or,
    with none, a failed install, keeps one hand-back naming `titles`: the failed checks the red
    is the harness's for, or what could not be installed.

    The upgrade lock also protects these records while the tick delivers them.  A record that
    cannot be written costs its hand-back, never the upgrade, as a swap mark does.
    """
    for harness in plan:
        check = config.STATE / HARNESS_GATES / harness["name"]
        if passed:
            (check / "handed").unlink(missing_ok=True)
            continue
        record = _handed(check) or {"reds": 0}
        if record["reds"] >= 2:
            continue
        record["reds"] += 1
        if record["reds"] == 2:
            red, fix = ((f"failed its gate twice in a row ({gate})", "harness upgrade gate") if gate
                        else ("could not be installed twice in a row", "harness install"))
            record.update(line=_fitted(f"The {harness['name']} harness upgrade {red}", list(titles),
                                       f"Log: {config.tilde(log_path)}. Fix the {fix}."),
                          typed=None, told=False)
        try:
            check.mkdir(parents=True, exist_ok=True)
            _put(check / "handed", json.dumps(record))
        except OSError:
            pass


def fresh_standing(failed, lines, log_path):
    """Hand back once the checks `failed` the fresh-install gate failed on the release before
    too, naming their `FAIL` `lines`.

    A line not yet told stands as written, its log saying when those checks failed, until the
    tick delivers it under the upgrade lock; once told, no set of checks it has told since the
    last clean pass hands back anything new, until a clean pass clears it (`run_gate`).
    """
    check = config.STATE / FRESH_FAULTS
    record = _handed(check) or {"told": True, "sets": []}
    if not record["told"] or sorted(failed) in record["sets"]:
        return
    check.mkdir(parents=True, exist_ok=True)
    _put(check / "handed", json.dumps(dict(
        sets=[*record["sets"], sorted(failed)], typed=None, told=False, line=_fitted(
            "The fresh-install gate failed checks that fail on the release before too", lines,
            f"Log: {config.tilde(log_path)}. Fix the standing faults."))))


def latest(harness):
    """The release its `[update] latest` command names, or "" where it names none or says none.

    Asked of the network, so bounded like the tick's look at origin: one not back by then,
    or one that names no release, is no newer release.
    """
    if not harness["latest"]:
        return ""
    argv = [config.harness_binary(harness["latest"][0]) or harness["latest"][0],
            *harness["latest"][1:]]
    try:
        proc = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=FETCH_CAP,
                              env={**config.child_env(), **PINS})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return "" if proc.returncode else _release(proc.stdout)


def one_at_a_time():
    """The host-wide upgrade lock, held, or None while another upgrade holds it.

    `ak update` and the tick's background upgrade both take it, so no gate ever verifies a
    box another upgrade is changing under it.
    """
    lock = (config.TMP / "harness-update.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def upgrading():
    """Whether an upgrade holds `one_at_a_time`'s lock now; asking holds it for an instant."""
    held = one_at_a_time()
    if held:
        held.close()
    return held is None


def said_path():
    """What the last background upgrade said: its writer is `background`, its reader the tick."""
    return config.STATE / "harness-update-said.json"


def background(name):
    """`python3 -m agentkit.update <harness>`: the tick's upgrade of one harness; the exit code.

    `upgrade` for that harness alone, whether sessions are working or not: it replaces files,
    never a process, so a seat or run already going keeps working through it.  What it said is
    left for the next tick to write to its log, once.
    """
    config.ensure_dirs()
    held = one_at_a_time()
    if held is None:
        return 0
    out = io.StringIO()
    with held, redirect_stdout(out), redirect_stderr(out):
        try:
            plan = [h for h in harnesses() if h["name"] == name]
            if not plan:
                return 0    # no longer configured, or no longer says how it moves
            code = upgrade(plan, {name: version(plan[0])})
        except Exception as exc:    # detached, this child is heard only through what it said
            say(f"update: {exc!r}")
            code = 1
        said = said_path()
        said.with_suffix(".tmp").write_text(json.dumps(
            {"harness": name, "code": code, "lines": out.getvalue().splitlines()}))
        os.replace(said.with_suffix(".tmp"), said)
    return code


def start(name):
    """`background(name)`, detached: it outlives the tick that starts it, gates and all."""
    subprocess.Popen([sys.executable, "-m", "agentkit.update", name], cwd=config.REPO,
                     env=owner.unmarked(config.child_env()), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def keep_current(log, now=None):
    """The tick's half of keeping every harness on its latest release, in the background.

    Only the checkout this tick runs from does it, as with `go_live`, so a tick from a
    worktree -- a test's above all -- never upgrades this host's harnesses.  A harness this
    host has is asked its `[update] latest` at most once an hour; one behind it is upgraded by
    `background`, one at a time.  A failed gate or install has put the harness back and said
    so; that release is started again once `RETRY_AFTER` has passed since its last start, and a
    newer one at once. Its second red in a row, gate or install, is handed back once until its
    gates pass, and the fresh gate's standing faults once (`fresh_standing`), retrying delivery
    on later ticks while no seat can receive it.  A checkout that is somebody's work
    (`left_as_is`) holds it, unstarted, until an ask finds it main again: its gates test that
    checkout, and refused a half-moved ~/agentkit, a red that reverted a harness for nothing it
    did.  A login its gates would not outlast (`_waits_for_login`) holds it too, with no ask until
    the first tick that one lasts: that tick starts the release it found.
    """
    if agentkit_dir().resolve() != config.REPO:
        return
    said = said_path()
    try:
        result = json.loads(said.read_text())
        said.unlink()
    except (OSError, ValueError):
        result = None
    if isinstance(result, dict):
        name, lines = result.get("harness"), result.get("lines") or []
        log(f"WARN the background upgrade of {name} failed:" if result.get("code")
            else f"the background upgrade of {name}:")
        for line in lines:
            log(f"  {line}")
    held = one_at_a_time()
    if held is None:
        return
    with held:
        for check in sorted((config.STATE / HARNESS_GATES).glob("*")):
            episode = _handed(check)
            if episode and episode["reds"] >= 2:
                if _gate_hand_back(check, episode, log):
                    log(f"handed {check.name}'s failed harness upgrade back to fix")
        faults = config.STATE / FRESH_FAULTS
        if (record := _handed(faults)) and _gate_hand_back(faults, record, log):
            log("handed the fresh-install gate's standing faults back to fix")
    now = time.time() if now is None else now
    record = config.STATE / "harness-latest.json"
    try:
        asked = json.loads(record.read_text())
    except (OSError, ValueError):
        asked = {}
    asked = asked if isinstance(asked, dict) else {}
    for harness in harnesses():
        name = harness["name"]
        entry = asked.get(name) if isinstance(asked.get(name), dict) else {}
        waited = entry.get("waits")
        if (not harness["latest"] or not config.harness_binary(harness["version"][0])
                or not waited and now - entry.get("asked", 0) < ASK_EVERY):
            continue
        installed, newest = version(harness), waited or latest(harness)
        # behind: both name a release, and the installed one is the lower
        go = bool(installed) and _downgrade(newest, installed) and (
            entry.get("tried") != newest or now - entry.get("started", 0) >= RETRY_AFTER)
        held = go and left_as_is()
        waits = go and not held and _waits_for_login(
            "upgrade", f"{name}'s upgrade", margin("live") + margin("fresh"), log, now)
        asked[name] = {**entry, "asked": now, "waits": newest if waits else "",
                       **({"tried": newest, "started": now} if go and not (held or waits) else {})}
        record.write_text(json.dumps(asked))
        if waits:
            return
        if held:
            log(f"{name} {_release(installed)} is behind {newest}: upgraded once "
                f"{agentkit_dir()} is main as origin left it, not {held}: its gates test it")
        elif go:
            log(f"{name} {_release(installed)} is behind {newest}: upgrading it in the background")
            start(name)
            return


def main(argv):
    if command_help.show("update", argv):
        return 0
    dry_run = argv[:1] == ["--dry-run"]
    if argv and not (dry_run and len(argv) == 1):
        raise config.Error(f"usage: ak update [--dry-run]  (got {argv[0]!r})")
    config.ensure_dirs()
    live = live_gate()
    plan = harnesses()
    if not plan:
        # with nothing to move, the gate would spend two hours of real model calls proving that
        # the box still is what it was, which is not an update and not a verification either
        raise config.Error("no configured harness says how it is upgraded; give one an "
                           "[update] version and upgrade command in its adapters/<name>.toml")
    before = {h["name"]: version(h) for h in plan}
    # A harness this host does not have is a skipped line, never a failed upgrade that holds the
    # others -- or agentkit itself -- back; the dry run still names it with the rest of the plan.
    # A binary whose version check fails is installed and broken, not absent, so it stays on the
    # trouble path.
    absent = [h["name"] for h in plan
              if not before[h["name"]] and not config.harness_binary(h["version"][0])]
    for name in absent:
        say(f"update: {name}: skipped: not installed here")

    if dry_run:
        for harness in plan:
            name = harness["name"]
            note = ("versioned reinstall available" if harness["revert"] else
                    "frozen installed release, not a reproducible versioned install; "
                    "cannot be reverted by its channel installer; "
                    "requires a complete local snapshot for rollback, checked before upgrading"
                    if harness_plugin(name).snapshots() else
                    f"cannot be reverted: {harness['cannot'] or 'it offers no versioned reinstall'}")
            print(f"{name} {before[name] or 'not installed'} ({note}): "
                  f"{shlex.join(harness['upgrade'])}")
        e2e = config.REPO / "tests" / "e2e-fresh.sh"
        print("update: dry run, nothing changed; each gate below says whether it would run")
        print(f"update: gate live: run (`bash {live}`)")
        fresh_why = fresh_unavailable()
        if fresh_why:
            print(f"update: gate fresh: skipped: {fresh_why}")
        else:
            print(f"update: gate fresh: run (`bash {e2e}`)")
        why = self_unavailable()
        if why:
            print(f"update: agentkit: skipped: {why}")
        else:
            print(f"update: agentkit {agentkit_version() or '?'}: "
                  f"would move forward (the next version swapped in + `install.sh`)")
        return 0

    plan = [h for h in plan if h["name"] not in absent]
    before = {h["name"]: before[h["name"]] for h in plan}
    # A client holds no harness: there is nothing to upgrade and nothing the gates could
    # verify, but the checkout below them still moves.  Where the checkout cannot move either,
    # nothing at all happened: that stays the exit-1 it always was, in the same words, and the
    # gate is not run.
    if not plan:
        say("update: no harness installed here; nothing to upgrade")
        why = self_unavailable()
        if why:
            print(f"update: agentkit: skipped: {why}")
            print("update: nothing was upgraded; the gate was not run", file=sys.stderr)
            return 1
        return update_self()
    # A harness upgraded under a working session changes what that session runs on with nobody
    # watching, so while one works no harness moves -- the menu's update item waits the same way,
    # and it is no failure -- and agentkit itself still does.
    working = working_sessions()
    if working:
        say(f"update: harnesses: skipped: {len(working)} sessions are working "
            f"({', '.join(working)}); try when they are done")
        update_self()
        return 0
    held = one_at_a_time()
    if held is None:
        say("update: harnesses: skipped: another upgrade is running; try when it is done")
        update_self()
        return 0
    with held:
        code = upgrade(plan, before)
    return code or update_self()


def live_gate():
    """tests/live.sh, the gate a harness upgrade passes before its fresh install; or the refusal.

    Not tests/smoke.sh: that is the landing suite's offline half, whose fake adapters stand in
    for every harness, and it passed at landing on this commit, so only host load can fail it --
    which twice put back a harness release for nothing it did.
    """
    live = config.REPO / "tests" / "live.sh"
    if not live.is_file():
        raise config.Error(f"no acceptance gate at {live}; an unverified upgrade is not one")
    return live


def upgrade(plan, before):
    """Upgrade `plan` from `before`, and put it back where a gate fails for it; the exit code.

    The one path `ak update` and the tick's background upgrade both take, so the snapshot,
    the gates and the revert are as strong whichever of them starts it.
    """
    # a move of ~/agentkit under way ends before anything here reads it; any later one waits
    # for this upgrade to end (update_agentkit)
    with (config.TMP / MOVING).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    live = live_gate()
    output = tempfile.NamedTemporaryFile(mode="w", prefix=f"update-{datetime.now():%Y%m%d-%H%M%S}-",
                                         suffix=".log", dir=config.TMP, delete=False)
    log_path = Path(output.name)
    upgraded, failed, missing = [], [], []
    with output as fh, retention.artifact(log_path, "update"), ExitStack() as stack:
        snapshot, attempted = None, False
        snapshots = stack.enter_context(ExitStack())    # renewed once a restore uses it up
        # the harness whose rollback is a local snapshot rather than a versioned reinstall
        snapshotted = next((h for h in plan if harness_plugin(h["name"]).snapshots()), None)
        try:
            name = snapshotted["name"] if snapshotted else ""
            if name and (before[name] or config.harness_binary(snapshotted["version"][0])):
                if not before[name]:
                    raise config.Error(f"installed {name} failed its pinned version check")
                snapshot = snapshots.enter_context(
                    harness_plugin(name).snapshot(snapshotted, before[name], version))
                say(f"update: {name} snapshot verified at {snapshot.path}")
                fh.write(f"{name} snapshot: {snapshot.path}\n")
                fh.flush()
        except config.Error as exc:
            print(f"update: {exc}; nothing was upgraded; the gate was not run", file=sys.stderr)
            return 1
        for harness in plan:
            name = harness["name"]
            if not before[name]:
                missing.append(name)
                say(f"update: {name} failed its version check; nothing to upgrade")
                continue
            note = ("" if harness is not snapshotted or snapshot is None
                    else f" (local rollback snapshot: {snapshot.path})")
            say(f"update: upgrading {name} from {before[name]}{note}")
            if harness is snapshotted:
                attempted = True
            with swapping(name):
                ok = step(harness["upgrade"], fh, harness["env"])
            if ok:
                upgraded.append(name)
            else:
                failed.append(name)
                say(f"update: WARN upgrading {name} failed; see {log_path}")
        after = {h["name"]: version(h) for h in plan}
        failed += [n for n in upgraded if not after[n]]
        # A channel that moved backwards is not an upgrade: whatever it installed goes back
        # before the gate sees a downgraded box, and the report keeps what was installed.
        downgraded = {harness["name"]: (_release(before[harness["name"]]),
                                        _release(after[harness["name"]]))
                      for harness in plan
                      if _downgrade(before[harness["name"]], after[harness["name"]])}
        for name, (old, now) in downgraded.items():
            say(f"update: {name}: kept: installed {old} is newer than the channel's {now}")
        if downgraded:
            revert([harness for harness in plan if harness["name"] in downgraded],
                   before, after, fh, say, snapshot, attempted)
            after = {h["name"]: version(h) for h in plan}
            failed += [name for name in downgraded if after[name] != before[name]]
        changed = moved(before, after)
        # Upgrading every one of them is the job.  An upgrade that never ran is not a success,
        # whatever the gate then says about the versions that are still sitting there -- so it
        # is named in the result line and it costs the exit code.
        trouble = {**{n: f"{n} could not be upgraded" for n in failed},
                   **{n: f"{n} failed its version check" for n in missing}}
        if trouble:
            # Nothing here is worth verifying: with one harness left behind, the gate would
            # either bless a box that is half new and half old, or -- when nothing ran at all --
            # spend two hours of real model calls proving that the box still is what it was.
            # So whatever moved goes back first, and the gate is not run.
            landed = revert(plan, before, after, fh, say, snapshot, attempted)
            if not upgraded:
                head = "nothing was upgraded"
            elif changed:
                head = (f"{', '.join(changed)}, and then undone where it could be: "
                        "a part of an upgrade is not one")
            else:
                head = f"{', '.join(upgraded)} did not move"
            print(f"update: {head} ({'; '.join(trouble.values())}); the gate was not run "
                  f"-- see {log_path}", file=sys.stderr)
            report(landed, sys.stderr)
            for harness in plan:    # one that installed fine counts no red: no gate judged it
                if harness["name"] in trouble:
                    harness_gate_result([harness], False, "", log_path, [trouble[harness["name"]]])
            return 1
        say(f"update: {', '.join(changed) if changed else 'no harness moved'}; "
            f"running {live.name}")
        # A red gate runs again on the release before: the checks that fail there too are
        # agentkit's own, never the harness's red, and the release the gate tested goes back in.
        # The hand-back names only the checks the red is the harness's for: never ones failing
        # on the release before too, nor another gate's.
        red, titles, outcome = "", [], {}
        for key in ("live", "fresh"):
            passed, failed, lines, outcome[key] = run_gate(key, fh)
            if passed:
                continue
            why = outcome[key]
            red = "live" if key == "live" else f"the fresh-install gate ({why})"
            landed = revert(plan, before, after, fh, say, snapshot, attempted)
            own = ", ".join(sorted(failed))
            if not failed or any(state == "cannot revert" for state, _ in landed.values()):
                titles = sorted(failed) or lines
                break
            reverted = [h for h in plan if landed[h["name"]][0] == "reverted"]
            if reverted:    # with none, the box it failed on is the release before
                say(f"update: {red} failed {own}; running it on the release before")
                titles = sorted(failed - run_gate(key, fh)[1])
                if titles:
                    break
                say(f"update: {red} failed {own} on the release before too: "
                    "agentkit's own checks; installing the release it tested again")
            outcome[key] = f"failed only agentkit's own checks ({own})"
            if key == "fresh":
                fresh_standing(failed, lines, log_path)
            ok = True
            for harness in reverted:
                name = harness["name"]
                if harness is snapshotted:
                    try:
                        snapshots.close()
                        snapshot = snapshots.enter_context(
                            harness_plugin(name).snapshot(harness, before[name], version))
                    except config.Error as exc:
                        say(f"update: {exc}")
                        snapshot, ok = None, False
                        break
                with swapping(name):
                    ok = step(harness["upgrade"], fh, harness["env"]) and ok
            again = {h["name"]: version(h) for h in plan}
            if not ok or again != after:
                red += (", and its release did not install again: "
                        f"{', '.join(moved(after, again)) or 'the reinstall failed'}")
                titles = []     # every check it failed was agentkit's; the red is the reinstall
                landed = revert(plan, before, again, fh, say, snapshot, attempted)
                break
            red = ""
        if not red:
            done = (f"{', '.join(changed)}, live {outcome['live']}" if changed
                    else f"every harness was already current, live {outcome['live']}")
            print(f"update: {done}, fresh-install gate {outcome['fresh']} ({log_path})")
            landed = kept(before, after)
            for name, (old, now) in downgraded.items():
                if after[name] == before[name]:
                    landed[name] = ("kept", f"installed {old} is newer than "
                                            f"the channel's {now}")
            report(landed, sys.stdout)
            if snapshot:
                snapshot.discard()
            harness_gate_result(plan, True, "", log_path)
            return 0
    print(f"update: {red} FAILED after {', '.join(changed) if changed else 'no change'} "
          f"-- see {log_path}", file=sys.stderr)
    report(landed, sys.stderr)
    harness_gate_result(plan, False, red, log_path, titles)
    return 1


if __name__ == "__main__":
    agentkit = sys.argv[1:] == ["--agentkit"]
    # `start` and the menu's `update_first` start it unmarked: the mark is its own
    owner.mark("agentkit update" if agentkit else "harness update")
    sys.exit(startup() if agentkit else background(sys.argv[1]))
