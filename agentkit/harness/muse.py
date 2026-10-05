"""Muse Code: a channel installer beside its launcher, and a usage probe of its own.

Its screen, its stall words and its `[update]`/`[usage]` facts are data -- adapters/muse.toml.
What needs Python is what reads a file: the build its launcher installed, the snapshot an
upgrade is put back from (its channel installer deletes the build it replaces), the probe
response agentkit/muse_usage.py cached, the quota a refused run recorded, whether a config.toml
entry is that probe's to run, and the session store a turn's tokens are written to.

No title hooks: 1.4.0-R4302.1 refuses /rename before and after a completed turn and
mid-turn ("naming is unavailable"), and rejects --name at launch. See the title fixtures;
a cleared composer is no receipt, and a command.invoked record is no custom name.
"""

import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import tempfile

from .. import config


def identity(text, argv):
    """Muse's release label plus the build its launcher actually installed.

    The label alone does not identify a build: the launcher records that beside itself, so a
    frozen installed release can still be told from the next one.
    """
    launcher = config.harness_binary(argv[0])
    try:
        build = (Path(launcher).resolve(strict=True).parent / ".muse-version").read_text().strip()
    except (OSError, RuntimeError, TypeError):
        build = ""
    return f"{text} (installed build {build})" if build and build not in text else text


def snapshot(harness, identity, version):
    """The installed launcher, build, metadata and launch links, for `restore()` to put back."""
    return Snapshot(harness, identity, version)


def install_lock(directory, *, remove_stale=False):
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
        print(f"update: removed stale Muse installer lock {lock} (dead pid {pid})", flush=True)


class Snapshot:
    """A local rollback for the launcher's adjacent muse-bin-<build> layout.

    Muse's channel installer deletes the build it replaces and offers no versioned reinstall,
    so this is the only way back from an upgrade.  Unknown layouts fail closed. Copies are verified and restore files are staged on each
    destination filesystem before any harness upgrades. Only failed-restore copies stay
    protected from automatic retention; a verified rollback releases its snapshot immediately.
    """

    metadata = (".muse-version", ".muse-release-info.json", ".muse-update-checked-at",
                ".muse-update-notice")

    def __init__(self, harness, identity, version):
        self.harness, self.identity, self.version = harness, identity, version
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
            install_lock(self.directory)
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
            if self.version(self.harness) != self.identity:
                raise config.Error("Muse's installed identity changed during snapshot preflight")
            if (self.managed_paths() != managed
                    or any(self.describe(p) != entry for p, entry in self.entries.items())):
                raise config.Error("Muse changed while its snapshot was being taken")
            install_lock(self.directory, remove_stale=True)
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
        install_lock(self.directory)
        for path, entry in self.entries.items():
            if (self.describe(self.saved[path]) != entry
                    or self.describe(self.staged[path.parent] / path.name) != entry):
                raise config.Error(f"Muse restore copy changed: {path}")

    def restore(self):
        self.check_restore()
        install_lock(self.directory, remove_stale=True)
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
        if self.version(self.harness) != self.identity:
            raise config.Error("restored Muse failed its pinned version check")
        self.discard()

    def discard(self):
        """Only verified/unused backups may be deleted or handed to routine retention."""
        try:
            shutil.rmtree(self.path)
        except OSError as exc:
            # A cleanup error must neither misreport a verified restore nor strand another
            # permanent binary copy. Failed restores never reach this registration path.
            from .. import retention   # here: the usage probe imports this module without it
            retention.begin(self.path, "update")
            retention.finish(self.path)
            print(f"update: snapshot cleanup failed at {self.path}: {exc}", flush=True)

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
                print(f"update: restore staging cleanup failed at {directory}: {cleanup_error}",
                      flush=True)
        if self.lock:
            self.lock.close()


def _stem(account):
    """What one login's quota record and probe cache are named after: an account's are its own."""
    return f"usage-meta.{account}" if account else "usage-meta"


def record_turn(out, state_dir, account):
    """Keep a refused turn's quota without letting the box write ak's other records."""
    report = out / "quota.json"
    try:
        data = json.loads(report.read_text())
    except (OSError, ValueError):
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{_stem(account)}.json").write_text(json.dumps(data) + "\n")
    # A retry whose box cannot start must not date an earlier refusal as new.
    report.unlink()


def usage_extra(out, data, state_dir):
    """Muse's adapter strips its probe timestamp.

    Match the source before carrying its age into the snapshot; an unidentifiable response must
    not look newly measured.  `out["fetched_at"]` is already None -- `[usage] strips_timestamp`
    -- so a response nothing here recognises stays unmeasured.  An account's response names it,
    and is matched against that account's files alone.
    """
    from .. import usage   # here, not at the top: usage is what calls this
    account = data.get("account")
    stem = _stem(account if isinstance(account, str) else "")
    for filename in (f"{stem}.json", f"{stem}-probe.json"):
        path = state_dir / filename
        try:
            cached = json.loads(path.read_text())
            if (cached.get("meters") == data.get("meters")
                    and cached.get("error") == data.get("error")):
                out["fetched_at"] = (path.stat().st_mtime if filename == f"{stem}.json"
                                     else usage._number(cached.get("fetched_at")))
                break
        except (OSError, ValueError, TypeError, AttributeError):
            pass


def usage_recorded(state_dir, now):
    """The quota imported from a refused turn's adapter report, for as long as it stands.

    Each meter is trusted for at most its own window, as the adapter's `usage` verb trusts it.
    Where `[providers.meta]` lists accounts every login has a record of its own, and nothing
    here says which row is being read: none is applied, and each reaches its own row through
    that account's `usage` verb, which answers with it first.
    """
    try:
        if config.accounts(config.load(), "meta"):
            return []
    except config.Error:
        pass
    path = state_dir / "usage-meta.json"
    try:
        age = now - path.stat().st_mtime
        return [meter for meter in json.loads(path.read_text())["meters"]
                if meter["resets_at"] > now and meter["window_secs"] > age]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def usage_policy(entry, effort):
    """The probe uses a config.toml model key and effort of this harness, with no fallback."""
    return (isinstance(entry.get("model"), str) and bool(entry["model"])
            and isinstance(effort, str) and bool(effort))


def tokens(out):
    """What the turn in `out` spent, read from Muse's own session store, or None.

    `muse exec --json` streams no usage at all.  The stream names the session and the run the
    turn opened; the session's session.jsonl, under ~/.local/share/muse/sessions/YYYY/MM/DD/,
    records a provider usage for every model request, owned by that run -- earlier turns of a
    resumed session are other runs.  Input tokens already include the cached prefix.
    """
    session, runs = None, set()
    try:
        with (out / "events.jsonl").open(errors="replace") as source:
            for line in source:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                stream = event.get("stream") if isinstance(event, dict) else None
                if isinstance(stream, dict) and stream.get("kind") == "session":
                    session = session or stream.get("id")
                payload = event.get("payload") if isinstance(event, dict) else None
                linked = payload.get("run_stream") if isinstance(payload, dict) else None
                if isinstance(linked, dict) and isinstance(linked.get("id"), str):
                    runs.add(linked["id"])
    except OSError:
        return None
    if not isinstance(session, str) or not re.fullmatch(r"[\w-]+", session) or not runs:
        return None
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "muse/sessions"
    total, seen = 0, False
    for path in root.glob(f"*/*/*/{session}/session.jsonl"):
        try:
            with path.open(errors="replace") as source:
                for line in source:
                    if "goal_usage_attribution" not in line:
                        continue
                    try:
                        payload = json.loads(line).get("payload") or {}
                        record = payload["event"]["record"]
                        quantity = record["quantity"]
                        if (record.get("usage_family") != "provider"
                                or record["owner"].get("run_id") not in runs
                                or quantity.get("reported") is False):
                            continue
                        counts = [quantity.get(key) for key in ("input_tokens", "output_tokens")]
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
                    counts = [count for count in counts
                              if isinstance(count, int) and not isinstance(count, bool)
                              and count >= 0]
                    if counts:
                        total, seen = total + sum(counts), True
        except OSError:
            continue
    return total if seen else None
