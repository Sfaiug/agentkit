"""Run records: reads, stop-safe writes, recovery locks and process ownership."""

import copy
import fcntl
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config, host

SILENCE_MINUTES = 20            # no command output or harness event for this long is a death
CEILING_HOURS = 6               # the whole done-when list, even if it keeps printing
_RECOVERY_HELD = threading.local()   # the recovery locks this thread is already inside
_RUN_TEMP = "run.tmp"
DELIVERY_TEMP = "delivery.tmp"
RECOVERY_LOCK = "recovery.lock"


class StopRequested(Exception):
    """A stop landed while this attempt still ran: the disk already says `stopped`.

    Raised by `save_state` when it would overwrite a deliberate end, so a job thread
    whose children were just killed aborts instead of saving `running` back over it.
    Never user-facing: `drive` catches it and keeps the record as the stop left it.
    """


def record_limits(state):
    """Migrate old receipts without reviving task-specific time budgets."""
    for key in ("done_when_minutes", "turn_hours", "stall_minutes"):
        state.pop(key, None)
    state.setdefault("silence_minutes", SILENCE_MINUTES)
    state.setdefault("ceiling_hours", CEILING_HOURS)


def read_state(run_dir):
    try:
        state = json.loads((run_dir / "run.json").read_text())
        return state if isinstance(state, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


def run_dirs():
    return sorted(d for d in config.RUNS.iterdir() if d.is_dir()) if config.RUNS.exists() else []


def process_owner(pid=None):
    pid = os.getpid() if pid is None else pid
    return {"pid": pid, "process_identity": host.process_identity(pid)}


def process_active(state):
    pid = state.get("pid")
    if not host.alive(pid):
        return False
    current = host.process_identity(pid)
    if current is None:
        # A zombie still answers kill(0). An unreadable /proc, however, is not proof of death.
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
        except (OSError, IndexError):
            return True
    saved = state.get("process_identity")
    if saved:
        return all(saved.get(key) == current[key] for key in ("boot", "ticks"))
    # Old records lack the fingerprint: check birth time and the actual run command. A
    # recycled PID starts after the old receipt, or belongs to a different kind of process.
    if state.get("started_at") and current["started_at"] > state["started_at"] + 1:
        return False
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return True
    return any(Path(arg).name == "ak" and args[i + 1:i + 2] == ["run"]
               for i, arg in enumerate(args))


@contextmanager
def recovery_lock(run_dir):
    """Serialize reaping, acknowledgment and launch handoff; never hold across model work.

    Reentrant within a thread, and counted here because flock is not: `save_state`
    takes it for every write it makes, and `reap`, `cmd_stop` and the launch handoff
    hold it across the read-decide-write the save is the end of.
    """
    held = getattr(_RECOVERY_HELD, "paths", None)
    if held is None:
        held = _RECOVERY_HELD.paths = set()
    mine = str(run_dir)
    if mine in held:
        yield
        return
    held.add(mine)
    try:
        with (Path(run_dir) / RECOVERY_LOCK).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    finally:
        held.discard(mine)


def _write_state(run_dir, state, temp=_RUN_TEMP):
    """The bare record write every save ends in; the guard and the lock live in `save_state`.

    One temporary file per lock a writer holds: `mark_delivery` writes under another lock
    than a save, and two writers filling one temporary file would put a torn record in place.
    """
    previous = read_state(run_dir) or {}
    record_limits(state)
    tmp = run_dir / temp
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(run_dir / "run.json")
    waits = [wait if isinstance(wait := saved.get("waiting_on"), dict) else {}
             for saved in (previous, state)]
    if (any(waits[0].get(key) != waits[1].get(key) for key in ("line", "joined", "land", "fix"))
            or (previous.get("state") != state.get("state")
                and state.get("state") not in ("running", "queued"))):
        from . import land
        # A wake's bookkeeping must not put another suite ahead of its delivery.
        for name in {wait["line"] for wait in waits if isinstance(wait.get("line"), str)}:
            land.start_line(config.RUNS / name)


def save_state(run_dir, state):
    """Write the record, unless a stop landed first -- the check and the write are atomic.

    The guard reads under `recovery_lock`, the same lock a stop marks under, so a
    writer that read `running` can never replace the `stopped` receipt afterward: it
    either lands first and the stop re-reads it, or it raises `StopRequested` and the
    deliberate end stands.  `mark_delivery` alone writes past this, through
    `_write_state`: it holds `delivery_lock`, marks endings a stop always refuses, and
    taking this lock there would invert `reap`'s lock order into a deadlock.

    A first write skips the lock: a stop refuses a run with no receipt, so none can
    be racing it -- and no lock file is left behind for a record written once.
    """
    if not (run_dir / "run.json").exists():
        return _write_state(run_dir, state)
    with recovery_lock(run_dir):
        if state.get("state") != "stopped":
            try:
                existing = json.loads((run_dir / "run.json").read_text())
            except (OSError, ValueError):
                existing = None
            if isinstance(existing, dict) and existing.get("state") == "stopped":
                raise StopRequested(f"{run_dir.name} was stopped")
        _write_state(run_dir, state)


class Record(dict):
    """A run's record as `record` read it; changed as a dict, written by `record` or `flush`."""

    def __init__(self, run_dir, loaded):
        super().__init__(loaded)
        self.run_dir, self.stopped = run_dir, loaded.get("state") == "stopped"
        self.written = copy.deepcopy(loaded)

    def flush(self):
        """Write now what changed since the read or the last flush, and only if something did.

        For a caller whose next step reads this write's time.  The guard is `save_state`'s: a
        record that says `stopped` never goes back to anything else.
        """
        if self == self.written:
            return
        if self.stopped and self.get("state") != "stopped":
            raise StopRequested(f"{self.run_dir.name} was stopped")
        _write_state(self.run_dir, self)
        self.written = copy.deepcopy(dict(self))


class Unreadable(OSError):
    """`record` found no run.json it could read, and wrote nothing: the caller skips the run."""


@contextmanager
def record(run_dir):
    """The one way to change a record that exists: read, change and write it under one lock.

    Yields the record as it stands under `recovery_lock`, the lock every save and a stop hold;
    the caller changes keys (a key popped is removed) and a clean exit writes once, if anything
    changed.  An exception writes nothing.  A run.json that is missing or cannot be read raises
    `Unreadable` before the block runs: nobody can tell what it held, so nothing is written
    over it -- not a copy read before the lock, and not a record of only the changed keys.
    One block per run at a time: a second one inside would read the record without the first
    one's changes, and write over them.
    """
    run_dir = Path(run_dir)
    with recovery_lock(run_dir):
        loaded = read_state(run_dir)
        if loaded is None:
            raise Unreadable("run.json cannot be read")
        current = Record(run_dir, loaded)
        yield current
        current.flush()


def stop_check(run_dir):
    """Raise `StopRequested` if the run was stopped: every spawn boundary asks first.

    Read under `recovery_lock`, the lock a stop marks under, so the read itself
    cannot straddle the commit: a checker queued behind the stop sees the stopped
    record and never starts work the sweep already passed.  A missing run, or a
    receipt that cannot be read, is not a stop -- direct unit-test callers and a
    record removed underfoot carry on as before.
    """
    if run_dir is None:
        return
    try:
        with recovery_lock(run_dir):
            try:
                stopped = (json.loads((Path(run_dir) / "run.json").read_text())
                           .get("state") == "stopped")
            except (OSError, ValueError):
                return
    except OSError:
        return
    if stopped:
        raise StopRequested(f"{Path(run_dir).name} was stopped")


def writing(run_dir):
    """A pending write, including a dangling link the collector must leave alone."""
    return any(os.path.lexists(Path(run_dir) / name) for name in (_RUN_TEMP, DELIVERY_TEMP))
