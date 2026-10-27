"""Muse Code: a channel installer beside its launcher, and a usage probe of its own.

Its screen, its stall words and its `[update]`/`[usage]` facts are data -- adapters/muse.toml.
What needs Python is what reads a file: the build its launcher installed, the snapshot an
upgrade is put back from (its channel installer deletes the build it replaces), the probe
response muse_usage.py beside it cached, the quota a refused run recorded, whether a config.toml
entry is that probe's to run, the session store a turn's tokens are written to, and which
session a seat owns.

Its TUI rejects `--session-id`, so a seat's session is learned rather than issued, as OpenCode's
is: every launch gets a receipt, a directory named in its environment, and the SessionStart hook
that launch's line carries (`adapters/muse.sh hook`) links into it the id Muse reported and the
processes the hook runs under, each with its birth.  The first of each stands: a link never
replaces one, a stale launch writes only into its own receipt, and a receipt this launch replaced
is gone.  The receipt's token is kept in the seat's record, so no other seat -- not one in the
same directory -- reads or writes it.  Muse's `/new` fires no hook, but its own registry moves
the launch's process to the new session, and the receipt follows it there.

No title hooks: 1.4.0-R4302.1 refuses /rename before and after a completed turn and
mid-turn ("naming is unavailable"), and rejects --name at launch. See the title fixtures;
a cleared composer is no receipt, and a command.invoked record is no custom name.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import uuid

from .. import config, host

RECEIPT_ENV = "AGENTKIT_MUSE_RECEIPT"
SESSION = re.compile(r"[\w-]+")     # a session's folder name, never a path


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


snapshot = Snapshot


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


def sessions():
    """~/.local/share/muse/sessions, or $XDG_DATA_HOME's: every session's folder, under
    YYYY/MM/DD/<session>/, and the views Muse caches of them, under .msp-view-*/<session>/."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "muse/sessions"


def session_logs(session):
    """Where Muse logs that session: its session.jsonl, in its folder."""
    return sorted(sessions().glob(f"*/*/*/{session}/session.jsonl"))


def conversation_stores():
    """Each session's folder: Muse ends none (in 1.4.11 a `session_retention_days` of 1 left a
    session five days old, and no command removes one)."""
    return [{"root": sessions(), "pattern": "[0-9]*/[0-9]*/[0-9]*/*/"}]


def end_conversation(path, ends):
    """The session's row in session-index.db, then the views cached of it, then its folder:
    a pass cut short finds the folder again, and nothing of it is left once that goes.  Asked
    once Muse's writers wait on the index, as a session resumed meanwhile has written or cached."""
    folder = Path(path)
    root = folder.parents[3]
    index = (root.parent / "session-index.db").as_uri() + "?mode=rw"
    try:
        with contextlib.closing(sqlite3.connect(index, uri=True, timeout=30)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            views = sorted(root.glob(f".msp-view-*/{folder.name}"))
            if not ends(*views):
                return
            db.execute("DELETE FROM sessions WHERE session_dir = ?", (str(folder),))
    except sqlite3.Error as exc:
        raise OSError(f"Muse's session index: {exc}") from exc
    for view in views:
        shutil.rmtree(view)
    shutil.rmtree(folder)


def path_for(record):
    token = record.get("muse_launch")
    if isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token):
        return config.STATE / f"muse-launch-{token}"
    return None


def conversation(record, cwd=None):
    """The session this seat's launch reported, or None where it reported none yet; the one
    Muse's registry has since moved that launch's process to, once the registry says so, kept
    in the receipt for the seat to reopen on after that process is gone."""
    path = path_for(record)
    try:
        sid = (path / "session").read_text(encoding="utf-8") if path else ""
    except OSError:
        return None
    if not SESSION.fullmatch(sid):
        return None
    now = followed(path)
    if now and now != sid:
        with contextlib.suppress(OSError):
            _write(path, "session", now, os.replace)
        return now
    return sid


def registered():
    """Each (session, process) Muse's registry of live sessions lists, under its data home: one
    `<session>.json` each, `{"session_id": ..., "process_generation_hint": "pid=<pid>", ...}`
    (1.4.12).  A crashed Muse leaves its entries behind, under a pid another process may hold."""
    for entry in (sessions().parent / "runtime/muse/sessions").glob("*.json"):
        try:
            data = json.loads(entry.read_text())
            sid, hint = data["session_id"], data["process_generation_hint"]
        except (OSError, ValueError, TypeError, KeyError):
            continue
        if sid == entry.stem and SESSION.fullmatch(sid) and isinstance(hint, str):
            yield sid, hint


def followed(path):
    """The one session the registry has given a process of that receipt's lineage since its
    hook, while that process lives as it was then, or None: no evidence, or more than one,
    picks nothing."""
    try:
        launch = json.loads((path / "lineage").read_text())
        processes = {f"pid={pid}": (pid, birth) for pid, birth in launch["processes"]}
        earlier = set(launch["earlier"])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    found = {sid for sid, hint in registered() if hint in processes and sid not in earlier
             and host.process_identity(processes[hint][0]) == processes[hint][1]}
    return found.pop() if len(found) == 1 else None


def started(receipt, event):
    """A SessionStart into that launch's receipt: the session Muse reported, and its lineage --
    the processes this hook runs under, the Muse that fired it among them, each with its birth,
    so a recycled pid is none of them -- with every other session the registry already lists.
    That Muse was born before its hook ran, so an entry an earlier holder of its pid left is
    among those, and any listed later under its pid is its own.  Each is linked, so the first
    stands; a receipt gone takes nothing."""
    sid = event.get("session_id") if isinstance(event, dict) else None
    if not isinstance(sid, str) or not SESSION.fullmatch(sid):
        return
    processes, pid = [], os.getppid()
    while pid > 1 and (stat := host.proc_stat(pid)) and (birth := host.process_identity(pid)):
        processes.append([pid, birth])
        pid = stat.ppid
    earlier = sorted({session for session, _ in registered()} - {sid})
    lineage = json.dumps({"processes": processes, "earlier": earlier})
    for name, text in (("session", sid), ("lineage", lineage)):
        with contextlib.suppress(OSError):
            _write(Path(receipt), name, text, os.link)


def _write(receipt, name, text, place):
    """`text` as the receipt's file `name`, put there whole by `place`: a link, or a replace."""
    fd, tmp = tempfile.mkstemp(dir=receipt, prefix=f".{name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        place(tmp, receipt / name)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def resumable(record, cwd, conversation):
    """The receipt is the whole answer: the launcher never issues a Muse id."""
    return bool(conversation)


def forget(record):
    """Remove that launch's receipt, moved aside first: a hook writing into it then finds no
    directory to land in."""
    path = path_for(record)
    if path:
        gone = path.with_name(f"{path.name}.gone")
        try:
            path.rename(gone)
        except OSError:
            return
        shutil.rmtree(gone, ignore_errors=True)


retire = forget   # the receipt is all a seat's launch keeps


def launched(name, cwd, conversation):
    """A receipt of this launch's own; a resumed session is in it from the start."""
    token = uuid.uuid4().hex
    path = path_for({"muse_launch": token})
    path.mkdir(mode=0o700)
    if conversation:
        (path / "session").write_text(conversation, encoding="utf-8")
    config.update_session(name, muse_launch=token)
    return {RECEIPT_ENV: str(path)}


def seat_token_sources(record):
    session = conversation(record)
    if not session:
        return []
    return [source for path in session_logs(session)
            for source in (path, *(path.parent / "subagent").rglob("session.jsonl"))]


def seat_token_usage(entry, cursor):
    tokens = provider_tokens(run_event(entry, "goal_usage_attribution").get("record") or {})
    if tokens is not None:
        return entry["recorded_at"] / 1_000_000, entry.get("id"), tokens


def provider_tokens(record):
    quantity = record.get("quantity") or {}
    if record.get("usage_family") != "provider" or quantity.get("reported") is False:
        return None
    counts = [quantity.get(key) for key in ("input_tokens", "output_tokens")]
    counts = [value for value in counts if type(value) is int and value >= 0]
    if counts:
        return sum(counts)


def said(record, cwd, conversation):
    """Each run of the session starts with the prompt it was given and commits every answer it
    showed as an event of its own; its reasoning, tool batches and reminders are other events,
    and a child session is a log of its own.  Its chat shows a run's first final answer, one
    with no `phase`, to its prompt or a steer, and none after it: Muse 1.4.12 logs a later one
    its own end-of-turn reminder asked for that no screen of it ever displays."""
    from . import turns
    answered = set()        # runs whose prompt or latest steer a shown final answered

    def run(entry):
        named = entry["payload"].get("run_id")
        return named if isinstance(named, str) else None

    def asked(entry):
        text = typed(entry)
        if text:
            answered.discard(run(entry))
        return text

    def shown(entry):
        event = run_event(entry, "assistant_message_committed")
        final = run(entry) if event and not event.get("phase") else None
        if final in answered:
            return None
        if final:
            answered.add(final)
        return event.get("text")
    return turns(session_log(conversation), asked, shown)


def user_messages(record, cwd, conversation):
    """What `typed` reads, dated when Muse recorded it, in microseconds as `seat_token_usage`
    reads them; a line dated otherwise is nobody's answer."""
    from . import entries, user_message
    for entry in entries(session_log(conversation)):
        at = entry.get("recorded_at")
        kept = type(at) is int and user_message(at / 1_000_000, typed(entry))
        if kept:
            yield kept


def card(record, cwd, conversation):
    """Muse's own question card in that session, as the fact its hooks write for it (adapters/
    muse.toml), dated when Muse recorded it; or None where it asked none.  Muse logs each card
    going up and its settling -- answered, or Esc's `interrupted` -- as run events naming its
    prompt and tool call, hooks or none (`/new` leaves a launch's behind): the newest card is
    up until a settling of that same card follows it, and then down from that moment."""
    from . import last_entry
    settled, prompted = {}, []

    def named(event):
        return event.get("prompt_id"), event.get("tool_call_id")

    def asked(entry):
        if run_event(entry, "started"):     # read newest first: a prompt after what follows
            prompted.append(entry)
        done = run_event(entry, "user_input_prompt_settled")
        if done:
            settled.setdefault(named(done), (entry.get("recorded_at"), done.get("outcome"),
                                             bool(prompted)))
        return bool(run_event(entry, "user_input_prompt_requested"))
    path = session_log(conversation)
    entry = last_entry(path, asked) if path else None
    event = run_event(entry or {}, "user_input_prompt_requested")
    if not isinstance(event.get("prompt_id"), str):
        return None
    at, outcome, since = settled.get(named(event), (entry.get("recorded_at"), None, False))
    if type(at) is not int:
        return None
    if outcome == "answered":
        return {"event": "PostToolBatch", "kind": "request_user_input", "text": "", "at": at / 1e6}
    if outcome:
        # An Esc ends the turn, resting the seat until its next prompt, which Muse reports by no
        # hook: from that prompt on, the turn the Esc ended is just over.
        return {"event": "Stop" if since else "Interrupt", "kind": "", "text": "", "at": at / 1e6}
    first = next(iter(event.get("questions") or ()), None)
    text = first.get("question") if isinstance(first, dict) else None
    return {"event": "Notification", "kind": "question_prompt",
            "text": text if isinstance(text, str) else "", "at": at / 1e6}


def session_log(conversation):
    """That session's log, or None where it has none or no such name."""
    if not isinstance(conversation, str) or not SESSION.fullmatch(conversation):
        return None
    logs = session_logs(conversation)
    return logs[0] if logs else None


BACKGROUND = {"tool.bash": "shell", "workflow.agent.native": "subagent",
              "workflow.run.native": "workflow"}     # a task's kind in Claude's terms (1.4.12)


def background(session):
    """The work that session's log has running in the background, as Claude's Stop hands it
    over (`background_tasks`), or None where there is no log to read.  1.4.12 links a terminal,
    a sub-agent or a workflow `background` as it starts and logs its end: the task's own, or a
    sub-agent's result.  The agents a workflow starts are its own work, not the seat's."""
    from . import entries
    log = session_log(session)
    if log is None:
        return None
    linked, kinds, gone = [], {}, set()
    try:
        for entry in entries(log):
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            event = payload.get("event") or payload.get("record")
            if not isinstance(event, dict):
                continue
            ref = event.get("attempt_ref")
            task = ref.get("task_id") if isinstance(ref, dict) else event.get("task_id")
            if not isinstance(task, str):
                continue
            said = event.get("kind")
            if said == "task_stream_linked" and event.get("execution_mode") == "background":
                linked.append(task)
            elif said == "proposed":
                kinds[task] = event.get("task_kind")
            elif said in ("completed", "failed", "cancelled", "rejected", "result_ready",
                          "workflow_child_lifecycle"):
                gone.add(task)
    except OSError:
        return None
    return [{"id": task, "type": BACKGROUND[kinds[task]]} for task in dict.fromkeys(linked)
            if task not in gone and kinds.get(task) in BACKGROUND]


def typed(entry):
    """What the user side typed that one session.jsonl line holds: a run's prompt, or a line
    steered into a running turn as the run drains it.  A steer that opens a run of its own is
    that run's prompt; background tasks' notices are drained from another source."""
    steer = run_event(entry, "inbox_item_drained").get("delivery_snapshot")
    if not isinstance(steer, dict) or steer.get("source") != {"source": "user_steer"}:
        steer = {}
    text = run_event(entry, "started").get("prompt") or steer.get("body")
    return text if isinstance(text, str) else None


def run_event(entry, kind):
    """One session.jsonl line's run event of that kind, or {}."""
    payload = entry.get("payload")
    run = isinstance(payload, dict) and payload.get("kind") == "run"
    event = payload.get("event") if run else None
    return event if isinstance(event, dict) and event.get("kind") == kind else {}


def tokens(out):
    """What the turn in `out` spent, read from Muse's own session store, or None.

    `muse exec --json` streams no usage at all.  The stream names the session and the run the
    turn opened; the session's log (`session_logs`) records a provider usage for every model
    request, owned by that run -- earlier turns of a resumed session are other runs.  Input
    tokens already include the cached prefix.
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
    if not isinstance(session, str) or not SESSION.fullmatch(session) or not runs:
        return None
    total, seen = 0, False
    for path in session_logs(session):
        try:
            with path.open(errors="replace") as source:
                for line in source:
                    if "goal_usage_attribution" not in line:
                        continue
                    try:
                        payload = json.loads(line).get("payload") or {}
                        record = payload["event"]["record"]
                        if record["owner"].get("run_id") not in runs:
                            continue
                        spent = provider_tokens(record)
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue
                    if spent is not None:
                        total, seen = total + spent, True
        except OSError:
            continue
    return total if seen else None
