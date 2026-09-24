"""Upgrade the harnesses with acceptance gates and a restorable local snapshot.

Which harnesses, and how each one moves, is `[update]` in `adapters/<harness>.toml` -- the
version command, the upgrade, the versioned reinstall that puts it back, the environment it
needs and the directory to snapshot where it has no such reinstall.  A harness whose manifest
names no version and upgrade command is not one `ak update` moves.

Claude and Codex offer versioned reinstalls. Muse's channel installer deletes old builds,
so its local launcher, build, metadata and launch links must be saved before any upgrade.
Failures attempt rollback and verify the resulting identities; a failed restore is reported
explicitly, with its snapshot retained. Ordinary launches and version checks remain frozen.

A gate that cannot run on this host is a skipped line, never a refusal: the upgrade runs
against the gates that are available, and the report says which ran.  Only the harnesses
this host has are upgraded, and none while a session is working.  Agentkit itself moves
after the harnesses either way, and the three-minute tick moves it on its own.
"""

from contextlib import ExitStack, redirect_stdout
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from datetime import datetime

from . import command_help, config, retention
from .harness import load as harness_plugin

VERSION = re.compile(r"\d+\.\d+\.\d+[^\s()]*")
PINS = {"DISABLE_AUTOUPDATER": "1", "MUSE_NO_AUTO_UPDATE": "1", "MUSE_LAUNCHER_INSTALL": "0"}
STEP_CAP = 30 * 60          # an upgrade that is not done in half an hour is not going to be
SMOKE_CAP = 2 * 60 * 60     # the gate makes real model calls and waits out two retry backoffs
E2E_CAP = 90 * 60           # a fresh account, three harness installs and one real merged run
FETCH_CAP = 60              # the tick's look at origin; one not back by then is offline

VERSION_KEY = "{version}"   # `[update] revert`: where the version to reinstall goes


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
                       "env": {str(key): str(value) for key, value in env.items()},
                       "cannot": str(facts.get("cannot") or ""),
                       "snapshot_dir": str(facts.get("snapshot_dir") or "")}
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


def step(cmd, fh, env=None, timeout=STEP_CAP):
    """Run one command into the log; True when it exited 0."""
    cmd = [config.harness_binary(cmd[0]) or cmd[0], *cmd[1:]]
    fh.write(f"\n$ {shlex.join(cmd)}\n")
    fh.flush()
    try:
        with subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True,
                              env={**config.child_env(), **PINS, **(env or {})}) as proc:
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                fh.write(f"[timed out after {timeout}s]\n")
                code = "timeout"
            finally:
                # A timed-out Muse launcher can leave its installer subshell writing.
                # Signal only while the child is still ours: wait()/poll() may already have
                # reaped an exited launcher, after which its PID/PGID could be reused.
                if proc.returncode is None and proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
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


def muse_install_lock(directory, *, remove_stale=False):
    """Refuse live/unknown writers; reclaim only a lock with a demonstrably dead PID."""
    lock = directory / ".muse-update-lock"
    try:
        info = lock.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise config.Error(f"unsafe Muse installer lock at {lock}; inspect it before retrying")
    pidfile = lock / "pid"
    try:
        pidinfo = pidfile.lstat()
        if (not stat.S_ISREG(pidinfo.st_mode) or pidinfo.st_uid != os.geteuid()
                or pidinfo.st_nlink != 1):
            raise ValueError("unsafe pid file")
        text = pidfile.read_text().strip()
        if not text.isascii() or not text.isdecimal() or not 0 < int(text) < 2**31:
            raise ValueError("invalid pid")
        pid = int(text)
    except (OSError, ValueError) as exc:
        raise config.Error(f"cannot identify the writer of Muse installer lock {lock}: {exc}; "
                           "inspect the lock and remove it only if no installer is running") from exc
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise config.Error(f"cannot inspect pid {pid} holding Muse installer lock {lock}") from exc
    else:
        raise config.Error(f"Muse installer lock {lock} is held by running pid {pid}; retry after it exits")
    if remove_stale:
        # Do not traverse or recursively delete an unexpected replacement lock.
        def identity(value):
            return value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        if (identity(lock.lstat()) != identity(info) or identity(pidfile.lstat()) != identity(pidinfo)
                or pidfile.read_text().strip() != text or set(lock.iterdir()) != {pidfile}):
            raise config.Error(f"Muse installer lock {lock} changed during its stale-lock check")
        pidfile.unlink()
        lock.rmdir()
        say(f"update: removed stale Muse installer lock {lock} (dead pid {pid})")


class MuseSnapshot:
    """A local rollback for the launcher's adjacent muse-bin-<build> layout.

    Taken for the harness whose manifest says `[update] snapshot_dir = "launcher"` and for no
    other: it is what a channel installer that deletes the build it replaces needs, and the only
    rollback strategy there is here.  Unknown layouts fail closed. Copies are verified and restore files are staged on each
    destination filesystem before any harness upgrades. Only failed-restore copies stay
    protected from automatic retention; a verified rollback releases its snapshot immediately.
    """

    metadata = (".muse-version", ".muse-release-info.json", ".muse-update-checked-at",
                ".muse-update-notice")

    def __init__(self, harness, identity):
        self.harness, self.identity = harness, identity
        self.path = None
        self.staged, self.parents, self.stage_ids = {}, {}, {}
        self.lock = None

    @staticmethod
    def describe(path):
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid != os.geteuid():
            raise config.Error(f"Muse file is not owned by this account: {path}")
        if stat.S_ISLNK(info.st_mode):
            return {"link": os.readlink(path), "mode": mode}
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise config.Error(f"Muse snapshot needs a regular file or symlink: {path}")
        with path.open("rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        return {"sha256": digest, "mode": mode}

    @staticmethod
    def parent_identity(parent):
        # Do not follow a replaced parent during restore, even if the final file is a link.
        info = parent.stat()
        if (parent.resolve(strict=True) != parent or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o300 != 0o300
                or not os.access(parent, os.W_OK | os.X_OK)):
            raise config.Error(f"Muse restore needs an owned, writable directory without symlink parents: {parent}")
        return info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode)

    def launch_paths(self, path, *, in_install=False):
        paths = []
        while True:
            if path in paths or (in_install and path.parent != self.directory):
                raise config.Error(f"Muse has a cyclic or external build link: {path}")
            self.parent_identity(path.parent)
            paths.append(path)
            if not path.is_symlink():
                self.describe(path)
                return paths
            path = Path(os.path.abspath(path.parent / os.readlink(path)))

    def managed_paths(self):
        paths = {self.directory / name for name in self.metadata}
        paths.add(self.directory / "muse-bin")
        paths.update(self.directory.glob("muse-bin-*"))
        return {p for p in paths if p.exists() or p.is_symlink()}

    @staticmethod
    def copy(source, target):
        shutil.copy2(source, target, follow_symlinks=False)
        if not target.is_symlink():
            with target.open("rb") as fh:
                os.fsync(fh.fileno())

    def __enter__(self):
        try:
            self.lock = (config.TMP / "muse-update.lock").open("a")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            command = config.harness_binary(self.harness["version"][0])
            if not command:
                raise config.Error("Muse launcher is not installed here")
            self.entry = Path(os.path.abspath(command))
            paths = set(self.launch_paths(self.entry))
            self.launcher = self.entry.resolve(strict=True)
            self.directory = self.launcher.parent
            muse_install_lock(self.directory)
            build = (self.directory / ".muse-version").read_text().strip()
            if not re.fullmatch(r"\d+\.\d+\.\d+-R\d+(?:\.\d+)?", build):
                raise config.Error("Muse has an unsupported installed build layout")
            binary = self.directory / f"muse-bin-{build}"
            if not os.access(binary, os.X_OK) or not os.access(self.launcher, os.X_OK):
                raise config.Error("Muse's launcher or active binary is not executable")
            release = json.loads((self.directory / ".muse-release-info.json").read_text())
            if not isinstance(release, dict) or release.get("version") != build:
                raise config.Error("Muse release metadata does not identify the installed build")
            managed = self.managed_paths()
            for path in managed:
                paths.update(self.launch_paths(path, in_install=True))
            self.entries = {p: self.describe(p) for p in sorted(paths)}
            self.path = Path(tempfile.mkdtemp(prefix="muse-snapshot-", dir=config.TMP))
            self.saved = {}
            for i, (path, entry) in enumerate(self.entries.items()):
                parent = path.parent
                if parent not in self.parents:
                    self.parents[parent] = self.parent_identity(parent)
                    self.staged[parent] = Path(tempfile.mkdtemp(prefix=".ak-muse-restore-", dir=parent))
                    self.stage_ids[parent] = self.parent_identity(self.staged[parent])
                saved = self.path / str(i)
                self.copy(path, saved)
                self.copy(saved, self.staged[parent] / path.name)
                self.saved[path] = saved
                if self.describe(saved) != entry:
                    raise config.Error(f"Muse snapshot copy could not be verified: {path}")
            manifest = {"identity": self.identity, "launcher": str(self.launcher),
                        "entry": str(self.entry), "files": [
                            {"path": str(p), "saved": self.saved[p].name, **entry}
                            for p, entry in self.entries.items()]}
            with (self.path / "manifest.json").open("w") as fh:
                json.dump(manifest, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            self.check_restore()
            if version(self.harness) != self.identity:
                raise config.Error("Muse's installed identity changed during snapshot preflight")
            if (self.managed_paths() != managed
                    or any(self.describe(p) != entry for p, entry in self.entries.items())):
                raise config.Error("Muse changed while its snapshot was being taken")
            muse_install_lock(self.directory, remove_stale=True)
            return self
        except (OSError, RuntimeError, ValueError, config.Error) as exc:
            self.__exit__(None, None, None)
            if self.path:
                shutil.rmtree(self.path, ignore_errors=True)
            raise config.Error(f"cannot assure a complete Muse snapshot and safe restore: {exc}") from exc

    def check_restore(self):
        for parent, identity in self.parents.items():
            if self.parent_identity(parent) != identity:
                raise config.Error(f"Muse restore directory changed: {parent}")
            if self.parent_identity(self.staged[parent]) != self.stage_ids[parent]:
                raise config.Error(f"Muse staged restore directory changed: {self.staged[parent]}")
        muse_install_lock(self.directory)
        for path, entry in self.entries.items():
            if (self.describe(self.saved[path]) != entry
                    or self.describe(self.staged[path.parent] / path.name) != entry):
                raise config.Error(f"Muse restore copy changed: {path}")

    def restore(self):
        self.check_restore()
        muse_install_lock(self.directory, remove_stale=True)
        extras = self.managed_paths() - self.entries.keys()
        # Destination ownership/link count describe the failed installation, not the saved
        # build. Replace those entries without opening their contents or following links.
        # A directory cannot be overwritten by a file: move it aside on the same filesystem
        # first, and let staging cleanup remove it after the restored version is verified.
        for path in set(self.entries) | extras:
            try:
                directory = stat.S_ISDIR(path.lstat().st_mode)
            except FileNotFoundError:
                continue
            if directory:
                displaced = Path(tempfile.mkdtemp(prefix=".displaced-", dir=self.staged[path.parent]))
                os.replace(path, displaced / "entry")
        # Restore the binaries/metadata before publishing the launcher and its launch links.
        launch = set(self.launch_paths_from_snapshot())
        for path in sorted(self.entries, key=lambda p: p in launch):
            os.replace(self.staged[path.parent] / path.name, path)
        for path in extras:
            path.unlink(missing_ok=True)
        if any(self.describe(p) != entry for p, entry in self.entries.items()):
            raise config.Error("Muse restore bytes, links or modes did not match the snapshot")
        if version(self.harness) != self.identity:
            raise config.Error("restored Muse failed its pinned version check")
        self.discard()

    def discard(self):
        """Only verified/unused backups may be deleted or handed to routine retention."""
        try:
            shutil.rmtree(self.path)
        except OSError as exc:
            # A cleanup error must neither misreport a verified restore nor strand another
            # permanent binary copy. Failed restores never reach this registration path.
            retention.begin(self.path, "update")
            retention.finish(self.path)
            say(f"update: snapshot cleanup failed at {self.path}: {exc}")

    def launch_paths_from_snapshot(self):
        path = self.entry
        while True:
            yield path
            entry = self.entries[path]
            if "link" not in entry:
                break
            path = Path(os.path.abspath(path.parent / entry["link"]))

    def __exit__(self, *exc):
        for directory in self.staged.values():
            # A changed install parent must not redirect even cleanup outside its old home.
            try:
                if self.parent_identity(directory.parent) == self.parents[directory.parent]:
                    shutil.rmtree(directory)
            except (OSError, RuntimeError, config.Error) as cleanup_error:
                say(f"update: restore staging cleanup failed at {directory}: {cleanup_error}")
        if self.lock:
            self.lock.close()


def moved(before, after):
    """The harnesses whose version actually changed, as `name old->new`."""
    return [f"{n} {before[n] or '?'}->{after[n] or '?'}" for n in before if before[n] != after[n]]


RELEASE = re.compile(r"\d+\.\d+\.\d+")


def _release(text):
    """The first X.Y.Z a version identity names, or "" when it names none."""
    match = RELEASE.search(text or "")
    return match.group(0) if match else ""


def _downgrade(old, new):
    """True when both identities name a release and the new one is the lower."""
    old_release, new_release = _release(old), _release(new)
    return (bool(old_release and new_release)
            and [int(part) for part in new_release.split(".")]
            < [int(part) for part in old_release.split(".")])


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
    failure, however it ended.  Only what this gate appended is read back: the smoke
    gate that passed first wrote its own acceptance line to the same log.
    """
    why = fresh_unavailable()
    if why:
        return False, f"skipped: {why}"
    e2e = config.REPO / "tests" / "e2e-fresh.sh"
    log(f"update: running {e2e.name}, the fresh-install gate")
    try:
        mark = os.fstat(fh.fileno()).st_size
    except OSError:
        mark = 0
    if step(["bash", str(e2e)], fh, {"AGENTKIT_ACCEPTANCE_REQUIRED": "1"}, timeout=E2E_CAP):
        return True, "passed (throwaway HOME with borrowed logins; clean host and interactive logins not exercised)"
    try:
        with open(fh.name, "rb") as gate_log:
            gate_log.seek(mark)
            text = gate_log.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    if "acceptance:" not in text and "[exit 2]" in text:
        reason = ""
        for line in text.splitlines():
            if "e2e-fresh.sh:" in line:
                reason = line.split("e2e-fresh.sh:", 1)[1].strip()
        return False, f"skipped: {reason or 'the fresh-install gate could not run on this host'}"
    return False, "failed"


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
            word = watch.session_state(session["name"], session=session, cfg=cfg)["word"]
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            continue     # what cannot be read cannot prove anything is working
        if word == "working":
            working.append(session["name"])
    return working


def agentkit_dir():
    """The checkout the menu updates: ~/agentkit, whatever checkout this runs from."""
    return Path.home() / "agentkit"


def agentkit_version():
    """That checkout's short commit, or "" when it is no checkout at all."""
    try:
        proc = subprocess.run(["git", "-C", str(agentkit_dir()), "rev-parse", "--short", "HEAD"],
                              capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                              env={**config.child_env(), **PINS})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def agentkit_newer():
    """origin/main's short commit when that checkout lacks it, else "": as the tick last fetched
    it, so asking costs no network."""
    code, newer = _git("rev-parse", "--short", "origin/main")
    if code or not newer or not _git("merge-base", "--is-ancestor", "origin/main", "HEAD")[0]:
        return ""
    return newer


def _git(*args, timeout=60):
    """One git command in that checkout: its exit code and output, 1 when it could not run."""
    try:
        proc = subprocess.run(["git", "-C", str(agentkit_dir()), *args], capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env={**config.child_env(), **PINS})
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def update_agentkit():
    """Fast-forward ~/agentkit and reinstall from it; the exit code.

    A fast-forward of main only, never a merge: a checkout with its own commits, changes of
    its own or another branch out is somebody's work, and is left as it is, saying so.
    Everything both commands print is said out loud, because the menu shows the last lines
    of it; stdout is a pipe, so install.sh sees no tty and asks no questions.
    """
    directory = agentkit_dir()
    _, branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    code, changes = _git("status", "--porcelain", "--untracked-files=normal")
    why = (f"on {branch or 'a detached HEAD'}, not main" if branch != "main"
           else "dirty" if code or changes else "")
    if why:
        say(f"update: agentkit: left as it is: {directory} is {why}")
        return 1
    commands = ([["git", "-C", str(directory), "pull", "--ff-only"],
                 [str(directory / "install.sh")]])
    for cmd in commands:
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


def update_once(where):
    """`update_agentkit`, and what it said, a failure only the first time: the exit code and lines.

    A checkout left as it is, and a pull or install.sh that failed, is said once per origin
    commit -- by `ak update` and in the tick's log alike, each keeping its own record -- so
    a checkout somebody is working in is not the same lines every three minutes.
    """
    said = io.StringIO()
    with redirect_stdout(said):
        code = update_agentkit()
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


def go_live(log):
    """The tick's half of `update_self`: agentkit live within one tick of origin/main moving.

    Only the checkout this tick runs from moves -- the cron line runs ~/agentkit/bin/ak --
    so a tick from a worktree, a test's above all, never touches the live one.  A fetch that
    fails is offline, silent, and the next tick fetches again.
    """
    if agentkit_dir().resolve() != config.REPO:
        return
    if _git("fetch", "--quiet", "origin", "main", timeout=FETCH_CAP)[0]:
        return
    code, head = _git("rev-parse", "origin/main")
    if code or not _git("merge-base", "--is-ancestor", "origin/main", "HEAD")[0]:
        return
    failed, lines = update_once("watch")
    if not failed:
        log(f"agentkit is live at {head[:12]}")
    elif lines:
        log(f"WARN agentkit did not go live at {head[:12]}:")
        for line in lines:
            log(f"  {line}")


def main(argv):
    if command_help.show("update", argv):
        return 0
    dry_run = argv[:1] == ["--dry-run"]
    if argv and not (dry_run and len(argv) == 1):
        raise config.Error(f"usage: ak update [--dry-run]  (got {argv[0]!r})")
    config.ensure_dirs()
    smoke = config.REPO / "tests" / "smoke.sh"
    if not smoke.is_file():
        raise config.Error(f"no acceptance gate at {smoke}; an unverified upgrade is not one")
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
                    if harness["snapshot_dir"] else
                    f"cannot be reverted: {harness['cannot'] or 'it offers no versioned reinstall'}")
            print(f"{name} {before[name] or 'not installed'} ({note}): "
                  f"{shlex.join(harness['upgrade'])}")
        e2e = config.REPO / "tests" / "e2e-fresh.sh"
        print("update: dry run, nothing changed; each gate below says whether it would run")
        print(f"update: gate smoke: run (`bash {smoke}`)")
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
                  f"would fast-forward (`git pull --ff-only` + `install.sh`)")
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

    output = tempfile.NamedTemporaryFile(mode="w", prefix=f"update-{datetime.now():%Y%m%d-%H%M%S}-",
                                         suffix=".log", dir=config.TMP, delete=False)
    log_path = Path(output.name)
    upgraded, failed, missing = [], [], []
    with output as fh, retention.artifact(log_path, "update"), ExitStack() as stack:
        snapshot, attempted = None, False
        # the harness whose rollback is a local snapshot rather than a versioned reinstall
        snapshotted = next((h for h in plan if h["snapshot_dir"]), None)
        try:
            name = snapshotted["name"] if snapshotted else ""
            if name and (before[name] or config.harness_binary(snapshotted["version"][0])):
                if not before[name]:
                    raise config.Error(f"installed {name} failed its pinned version check")
                snapshot = stack.enter_context(MuseSnapshot(snapshotted, before[name]))
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
            if step(harness["upgrade"], fh, harness["env"]):
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
        trouble = [f"{n} could not be upgraded" for n in failed]
        trouble += [f"{n} failed its version check" for n in missing]
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
            print(f"update: {head} ({'; '.join(trouble)}); the gate was not run "
                  f"-- see {log_path}", file=sys.stderr)
            report(landed, sys.stderr)
            return 1
        say(f"update: {', '.join(changed) if changed else 'no harness moved'}; "
            f"running {smoke.name}")
        gate = "smoke"
        if step(["bash", str(smoke)], fh, {"AGENTKIT_ACCEPTANCE_REQUIRED": "1"}, timeout=SMOKE_CAP):
            fresh_ok, fresh_why = fresh_gate(fh, say)
            if fresh_ok or fresh_why.startswith("skipped:"):
                done = (f"{', '.join(changed)}, smoke passed" if changed
                        else "every harness was already current, smoke passed")
                print(f"update: {done}, fresh-install gate {fresh_why} ({log_path})")
                landed = kept(before, after)
                for name, (old, now) in downgraded.items():
                    if after[name] == before[name]:
                        landed[name] = ("kept", f"installed {old} is newer than "
                                                f"the channel's {now}")
                report(landed, sys.stdout)
                if snapshot:
                    snapshot.discard()
                return update_self()
            gate = f"the fresh-install gate ({fresh_why})"
        landed = revert(plan, before, after, fh, say, snapshot, attempted)
    print(f"update: {gate} FAILED after {', '.join(changed) if changed else 'no change'} "
          f"-- see {log_path}", file=sys.stderr)
    report(landed, sys.stderr)
    return 1
