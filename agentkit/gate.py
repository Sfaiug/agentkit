"""Run admission, check commands and the host-wide heavy-suite turn."""

import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, history, host, orch, run, watch, worker
from . import land as landing
from . import record as run_record

_GATE_HELD = threading.local()     # the gate turn this thread holds now, if any


try:
    SLOT_POLL = float(os.environ.get("AK_SLOT_POLL", "30"))
except ValueError:
    SLOT_POLL = 30


GATE_POLL = 15      # seconds between a waiting gate's tries for a turn; each rewrites its log line
HEAVY_CPUS = 0.7      # initial measured estimates; a repository's pieces may cost more
HEAVY_MEM_MB = 410
SUITE_BUSY = 75       # sysexits' EX_TEMPFAIL: a heavy suite's own host-wide lock is another copy's


@contextmanager
def slot_lock():
    """One atomic count-and-claim across seats, processes and job threads."""
    config.RUNS.mkdir(parents=True, exist_ok=True)
    with (config.RUNS / ".slots.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def slot_order(state):
    # A green member only needs delivery before the target moves.
    wait = state.get("waiting_on") or {}
    return (not (state.get("first") or "land" in wait or "fix" in wait),
            not landing.green_delivery(wait),
            state.get("queued_at") or state.get("started_at") or 0,
            state.get("run_id") or "")


CPU_PRESSURE_LIMIT = 40   # ak's own processes are stalled on CPU nearly half the time


def resource_limits(readings):
    """Resolve configured gates against one host-reading snapshot."""
    total = host._reading(readings, "mem_total_mb", "total_mb", "mem_total")
    cpus = host._reading(readings, "cpus", "nproc") or 1
    return config.min_free_mb(total if total is not None else 0), config.max_load(cpus)


def _load(value):
    return "?" if value is None else f"{value:g}"


def _pct(value):
    return "?" if value is None else f"{value:g}%"


def host_status_line():
    """The host-admission header at the top of human ``ak run status`` output.

    Two lines: the admission gates, then the heavy-suite turns in force and whether
    an explicit `max_gates` pins them or the slice's headroom derives them.  A
    positive `max_runs` is a gate like the other two, so the first line names it:
    `at most 4 runs at once`.  A pinned `max_load` keeps the old load wording;
    otherwise the CPU gate is the slice's own pressure.
    """
    readings = host.host_readings(slice_dir=orch.slice_cgroup)
    minimum, maximum = resource_limits(readings)
    cpus = host._reading(readings, "cpus", "nproc") or 1
    gates = []
    if minimum:
        gates.append(f"≥ {host._g(minimum)} G free")
    if config.max_load_is_set():
        if maximum:
            gates.append(f"load ≤ {_load(maximum)}")
        admitted = ("a run is admitted while " + " and ".join(gates) if gates else
                    "a run is admitted (host memory and load gates off)")
        signal = f"load {_load(host._reading(readings, 'load', 'load1'))}"
    else:
        gates.append(f"ak cpu ≤ {CPU_PRESSURE_LIMIT}%")
        admitted = "a run is admitted while " + " and ".join(gates)
        signal = f"ak cpu {_pct(host._reading(readings, 'slice_cpu_pressure'))}"
    try:
        limit = config.max_runs()
    except config.Error:
        limit = 0
    if limit:
        admitted += f" · at most {limit} run{'s' if limit != 1 else ''} at once"
    try:
        pinned = config.max_gates()
    except config.Error:
        pinned = None
    if pinned is not None:
        heavy = ("heavy suites: no cap (pinned)" if not pinned else
                 f"heavy suites: {pinned} at once (pinned)")
    else:
        heavy = f"heavy suites: {derived_heavy_limit(readings)} at once (derived)"
    segment = ""
    unit = host._unit_memory(readings)
    if unit and len(unit) > 3 and unit[3]:
        segment = f" · {unit[3]} {host._g(unit[0])} of {host._g(unit[1])} G in use"
    first = (f"host: {int(cpus)} cpus · {signal} · "
             f"{host._g(host._reading(readings, 'free_mb', 'mem_available_mb'))} G free{segment} · "
             f"{admitted}")
    return f"{first}\n{heavy}"


def slot_counts(state):
    """Live slot owners, and top-level receipts ahead of this one (including dead waiters)."""
    running, ahead = 0, 0
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if other.get("run_id") == state.get("run_id") or other.get("run_depth", 0):
            continue
        if other.get("state") == "running" and run_record.process_active(other):
            running += 1
        elif (other.get("state") == "queued" and other.get("slot_waiting") and
              slot_order(other) < slot_order(state)):
            ahead += 1
    return running, ahead


def frozen_runs(state):
    """Admitted runs the host has frozen: slot owners whose process is held.

    A frozen run adds no load, so the load gate keeps refilling behind it and the
    thaw lands every run at once. The same owners slot_counts counts, asked of the
    process itself, so a dead run and a reused pid count nothing.
    """
    frozen = 0
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if other.get("run_id") == state.get("run_id") or other.get("run_depth", 0):
            continue
        if (other.get("state") == "running" and run_record.process_active(other)
                and host.frozen_cgroup(other.get("pid"))):
            frozen += 1
    return frozen


def slot_line(running, ahead, limit, first=False):
    """The count wait's sentence: "ahead" is only the runs queued before this one.

    Running runs are no queue, so a full limit says so by itself; a `first` run
    skips the count cap and waits only on the queue.
    """
    if limit and running >= limit and not first:
        return f"waiting for a slot · limit full ({running} running) · {ahead} ahead"
    return f"waiting for a slot · {ahead} ahead"


def slot_note(state):
    return state.get("slot_wait_reason") or slot_line(
        *slot_counts(state), config.max_runs(), not slot_order(state)[0])


def _slice_cpu_reason(readings):
    """(reason, kind) while ak's own slice is CPU-saturated, else (None, None).

    Unreadable fails open with the rest: a host that cannot answer must not
    queue every run forever.
    """
    pressure = host._reading(readings, "slice_cpu_pressure")
    if pressure is not None and pressure > CPU_PRESSURE_LIMIT:
        return (f"waiting for ak's CPU · pressure {pressure:g}%, "
                f"limit {CPU_PRESSURE_LIMIT}%", "cpu")
    return None, None


def _wait_reason(readings, minimum, maximum, frozen=0):
    # An unreadable gate fails open, as the memory check before it did: a host
    # that cannot answer (no /proc on macOS, no cgroup file in a container)
    # must not queue every run forever.
    free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
    if minimum and free is not None and free < minimum:
        return f"waiting for memory · {host._g(free)} G free, needs {host._g(minimum)} G", "memory"
    load = host._reading(readings, "load", "load1", "load_1m")
    if maximum and load is not None and load + frozen > maximum:
        if frozen:
            noun = "run" if frozen == 1 else "runs"
            return (f"waiting for the host to calm · load {_load(load)} + {frozen} "
                    f"frozen {noun}, limit {_load(maximum)}", "load")
        return f"waiting for the host to calm · load {_load(load)}, limit {_load(maximum)}", "load"
    unit = host._unit_memory(readings)
    if unit and unit[0] > unit[1] * .75:
        raw = unit[2] if len(unit) > 2 else None
        if raw is not None:
            return (f"waiting for the unit's memory · {host._g(unit[0])} of {host._g(unit[1])} G "
                    f"in use ({host._g(raw)} with cache)", "unit memory")
        return (f"waiting for the unit's memory · {host._g(unit[0])} of {host._g(unit[1])} G",
                "unit memory")
    return None, None


def claim_slot(state, limit, readings=None):
    """Called under slot_lock: count, FIFO and two steady host polls decide admission."""
    running, ahead = slot_counts(state)
    # AK_MAX_RUNS=0 is the test-suite escape hatch: it disables count and host gates together.
    ungated = os.environ.get("AK_MAX_RUNS") == "0"
    if state.get("run_depth", 0) or ungated:
        state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                     **run_record.process_owner())
        state.pop("resume_from", None)
        return True
    is_first = not slot_order(state)[0]
    if ahead or (limit and running >= limit and not is_first):
        state["slot_waited"] = True
        state["slot_wait_reason"] = slot_line(running, ahead, limit, is_first)
        state["slot_wait_kind"] = "count"
        state["slot_healthy_polls"] = 0
        return False
    readings = host.host_readings(slice_dir=orch.slice_cgroup) if readings is None else readings
    minimum, maximum = resource_limits(readings)
    if is_first:
        maximum = 0
    pinned = config.max_load_is_set()
    if pinned:
        frozen = 0
        load = host._reading(readings, "load", "load1", "load_1m")
        if maximum and load is not None and load <= maximum:
            # A frozen run adds no load, so the gate reads low behind it; each one
            # counts 1 against the limit. Counted only while the load alone passes:
            # past the limit the wait says so already, and no cgroup is read.
            frozen = frozen_runs(state)
        reason, kind = _wait_reason(readings, minimum, maximum, frozen)
    else:
        # The slice's own pressure gates now; the host load goes unread.
        reason, kind = _wait_reason(readings, minimum, 0)
        if reason is None and not is_first:
            reason, kind = _slice_cpu_reason(readings)
    if reason:
        state["slot_waited"] = True
        state["slot_wait_reason"], state["slot_wait_kind"] = reason, kind
        state["slot_healthy_polls"] = 0
        return False
    polls = state.get("slot_healthy_polls", 0) + 1
    if polls < 2:
        state["slot_healthy_polls"] = polls
        # The gates pass but steadiness is still owed: say that, with the
        # readings behind it, rather than the count sentence nothing waits on.
        # The kind stays whatever gate (if any) actually delayed this wait.
        free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
        if pinned:
            load = host._reading(readings, "load", "load1", "load_1m")
            state["slot_wait_reason"] = (
                f"waiting for steady readings · {host._g(free)} G free, load {_load(load)}")
        else:
            pressure = host._reading(readings, "slice_cpu_pressure")
            state["slot_wait_reason"] = (
                f"waiting for steady readings · {host._g(free)} G free, "
                f"ak cpu pressure {_pct(pressure)}")
        return False
    state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                 **run_record.process_owner())
    for key in ("resume_from", "slot_healthy_polls", "reservation_pending",
                "slot_wait_reason", "slot_wait_kind"):
        state.pop(key, None)
    return True


def reserve_slot(state, limit):
    claim_slot(state, limit)
    # Steadiness is counted by the waiter's own polls, not banked here: the
    # launch check only records an early reason, and admission still needs
    # two consecutive healthy polls from the waiter itself.
    state.pop("slot_healthy_polls", None)


def wait_for_slot(run_dir):
    """Reserve a slot in run.json before work starts; no process-local semaphore can do this."""
    announced = False
    first_poll = True
    wait_kind = None
    while True:
        limit = config.max_runs()
        with slot_lock(), run_record.recovery_lock(run_dir):
            state = run_record.read_state(run_dir) or {}
            if state.get("state") == "running" and state.get("pid") == os.getpid():
                return state
            if first_poll and state.get("state") != "queued" and not run_record.process_active(state):
                # drive also accepts a saved receipt directly (the job/recovery API).
                state.update(run_id=run_dir.name, state="queued", slot_waiting=True,
                             queued_at=time.time(), **run_record.process_owner())
                state.setdefault("run_depth", run.run_depth())
                # A new queue episode starts with no memory of the last one's wait.
                for key in ("slot_waited", "slot_wait_reason", "slot_wait_kind"):
                    state.pop(key, None)
                run_record.save_state(run_dir, state)
            if state.get("state") != "queued" or state.get("pid") != os.getpid():
                raise config.Error(f"{run_dir.name}: another process owns this launch")
            first_poll = False
            if claim_slot(state, limit):
                run_record.save_state(run_dir, state)
                break
            # Admission clears the kind, so the receipt below reads this copy.
            wait_kind = state.get("slot_wait_kind") or wait_kind
            run_record.save_state(run_dir, state)
        if not announced:
            print(slot_note(state), flush=True)
            run.redress_seat(state.get("launched_session"))
            announced = True
        time.sleep(SLOT_POLL)
    if state.get("slot_waited"):
        minutes = max(0, int((time.time() - state["queued_at"]) / 60))
        kind = wait_kind or "count"
        line = f"waited {minutes} min for a slot ({kind})\n"
        # Preflight and a detached waiter's stdout already live here. Keep the waiting
        # receipt first, without replacing the inode the background child's stdout owns.
        path = run_dir / "log.txt"
        with path.open("r+", encoding="utf-8") as fh:
            content = fh.read()
            fh.seek(0)
            fh.write(line + content)
        print(line.rstrip(), flush=True)
    run.redress_seat(state.get("launched_session"))
    return state


def gate_lock(repo, slot):
    """The lock file of one host-wide heavy-suite turn; `repo` is ignored.

    Turns were per repository, one set of slot files per main checkout.  Only the
    heavy suite takes one now, counted host-wide, so every suite meets on the same
    files whichever repository it checks.  The argument stays so old callers still
    pass it.
    """
    return config.RUNS / f".heavy-{slot}.lock"


def take_slot(slots):
    """The first of the open slot files this call locks, or None while a gate holds each."""
    for slot in slots:
        try:
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            continue
        return slot
    return None


def _heavy_max_existing():
    """Highest heavy-slot index with a lock file on disk, or -1 when none do.

    Slot files persist once opened, so a limit that shrinks leaves its higher
    files behind -- and the suites still holding them.  A waiter that only opens
    its new prefix would never see those holders and would admit over them.
    """
    try:
        best = -1
        for path in config.RUNS.glob(".heavy-*.lock"):
            try:
                idx = int(path.name[len(".heavy-"):-len(".lock")])
            except ValueError:
                continue
            if idx > best:
                best = idx
        return best
    except OSError:
        return -1


def _heavy_running():
    """Count held turns, including high slots left by a larger limit.

    Slot files persist after their suites finish; only a lock still held counts.
    Probe existing files without creating any, so status never grows the pool.
    """
    held = 0
    for index in range(_heavy_max_existing() + 1):
        try:
            with gate_lock(None, index).open("r") as slot:
                try:
                    fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held += 1
        except OSError:
            pass
    return held


def _first_landing_wait(run_dir):
    """This run's first landing wait, or None when it never waited to land.

    The start lives beside the record, not in it: a whole-record save of the loop's
    own state would wipe it from run.json between two laps, and the next lap would
    count from itself instead.  `land` clears it for a fresh landing and when the
    landing ends.
    """
    try:
        return float((Path(run_dir) / "landing_since").read_text().strip())
    except (OSError, ValueError):
        return None


def clear_landing_wait(run_dir):
    """A fresh or finished landing counts from its own first wait."""
    try:
        (Path(run_dir) / "landing_since").unlink(missing_ok=True)
    except OSError:
        pass


def mark_gate_wait(run_dir, of):
    """Put `waiting for a heavy suite turn` on the record, or take it off (`of` None).

    `of` is the repository the waiter checks, kept on the mark from the
    per-repository turns; the note and the rank are host-wide and ignore it.  With
    this process's pid and the wait's start, so a
    freed turn goes to the waiter that has waited longest.  A landing run's mark
    says so; the start of its first landing wait lives beside the record, where
    whole-record saves cannot wipe it (see `_first_landing_wait`): that start is
    what this returns for a lander, the wait's own start otherwise, and None when
    it recorded none.
    """
    since = time.time()
    try:
        with run_record.record(run_dir) as state:
            if state and state.get("state") == "running":
                if of:
                    if state.get("landing"):
                        first = _first_landing_wait(run_dir)
                        if first is None:
                            first = since
                            try:
                                (Path(run_dir) / "landing_since").write_text(repr(since))
                            except OSError:
                                pass    # without the marker this wait still ranks as landing
                        state["gate_turn"] = {"pid": os.getpid(), "of": str(of),
                                              "since": since, "landing": True}
                        return first
                    state["gate_turn"] = {"pid": os.getpid(), "of": str(of), "since": since}
                else:
                    state.pop("gate_turn", None)
                    since = None
                return since
    except OSError:
        pass            # an unmarked record costs a status line, never the turn
    return None


def gate_turn_note(state):
    """`waiting for a heavy suite turn` while a run waits in `gate_turn`, else ""."""
    turn = state.get("gate_turn")
    if (state.get("state") != "running" or not isinstance(turn, dict)
            or turn.get("pid") != state.get("pid")):
        return ""
    return "waiting for a heavy suite turn"


def _gate_waiter_before(repo, exclude, since, is_landing=False):
    """Whether a live heavy-suite waiter ranks before this gate; `repo` is ignored.

    Turns were per repository and only a waiter of the same main checkout counted.
    They are host-wide now, so every live waiter counts whichever repository it
    checks.  Rank is a landing run before any round check, then the longest wait,
    then the run id, so a freed turn finishes a run ready to land before starting
    another round's check; `--first` plays no part, or loop repairs starve every
    other suite under load.  A lander's wait
    counts from the start of its first landing wait, not from the lap; a mark from
    before landers ranked carries no landing and reads as a round check.  A mark
    whose process is gone, or whose pid no longer matches its record -- a kill or
    a resume left it behind -- holds nobody back.
    """
    me = (not is_landing, since, exclude or "")
    for directory in run_record.run_dirs():
        if directory.name == exclude:
            continue
        other = run_record.read_state(directory) or {}
        if other.get("state") != "running":
            continue
        turn = other.get("gate_turn")
        if not isinstance(turn, dict) or turn.get("pid") != other.get("pid"):
            continue
        if not run_record.process_active(other):
            continue
        landing = bool(turn.get("landing"))
        waited = _first_landing_wait(directory) if landing else turn.get("since")
        if not isinstance(waited, (int, float)) or isinstance(waited, bool):
            waited = turn.get("since") if landing else 0
            if not isinstance(waited, (int, float)) or isinstance(waited, bool):
                waited = 0
        if (not landing, waited, directory.name) < me:
            return True
    return False


class _GateHold:
    """Held turns: the open slot files and those this thread locked.

    The hold owns its files rather than the frame that waited for them, so a fixer
    or a reviewer lets it go from inside the frame that took it.  Releasing unlocks
    the slot and closes the files, as leaving the frame would have.
    """

    def __init__(self, files, slots, context=None):
        self.files, self.slots, self.context = files, slots, context

    def alone(self):
        for slot in self.slots[1:]:
            fcntl.flock(slot, fcntl.LOCK_UN)
        self.slots = self.slots[:1]

    def release(self):
        try:
            for slot in self.slots:
                fcntl.flock(slot, fcntl.LOCK_UN)
        finally:
            self.slots = []
            held = getattr(_GATE_HELD, "count", 0)
            if held:
                _GATE_HELD.count = held - 1
            self.files.close()


def derived_heavy_limit(readings=None, running=None, job_cpus=HEAVY_CPUS,
                        job_mem_mb=HEAVY_MEM_MB, *, unit=False):
    """Running suites plus how many more the live headroom fits; at least one.

    The slice's idle cores over one suite's 0.7, and its free memory over 0.4 GB,
    whichever fits fewer.  Headroom already excludes running suites, so add
    them once; a saturated slice starts one only when none run.  Both come
    off the slice's own cgroup -- its CPU room and the slice's memory headroom --
    which a shell beside the slice reads like a worker inside it; where
    no slice answers, the host's idle cores and free memory stand in.  An
    unreadable gate fails open to the other resource, and to one suite where
    neither answers.  `job_cpus` and `job_mem_mb` are one job's cost, for jobs
    other than a heavy suite. With `unit`, pieces also fit the caller's soft
    limit and the remaining room under every enclosing hard memory cap.
    """
    if running is None:
        running = _heavy_running()
    if readings is None:
        readings = host.host_readings(slice_dir=orch.slice_cgroup)
    cpu_quota = host._reading(readings, "slice_cpu_quota")
    if cpu_quota is not None:
        used = host._reading(readings, "slice_cpu_used")
        cpu_free = cpu_quota - used if used is not None else float(cpu_quota)
    else:
        cpus = host._reading(readings, "cpus", "nproc")
        load = host._reading(readings, "load", "load1", "load_1m")
        if cpus is not None and load is not None:
            cpu_free = cpus - load
        elif cpus is not None:
            cpu_free = float(cpus)
        else:
            cpu_free = None
    slice_used = host._reading(readings, "slice_memory_used_mb")
    slice_high = host._reading(readings, "slice_memory_high_mb")
    if slice_used is not None and slice_high is not None:
        mem_free = slice_high - slice_used
    else:
        own = host._unit_memory(readings)
        if own is not None:
            mem_free = own[1] - own[0]
        else:
            mem_free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
    if unit:
        own = host._unit_memory(readings)
        if own is not None:
            room = own[1] - own[0]
            mem_free = min(mem_free, room) if mem_free is not None else room
        room = host._reading(readings, "unit_memory_max_headroom_mb")
        if room is not None:
            mem_free = min(mem_free, room) if mem_free is not None else room
    candidates = []
    if cpu_free is not None:
        candidates.append(int(cpu_free / job_cpus))
    if mem_free is not None:
        candidates.append(int(mem_free / job_mem_mb))
    if not candidates:
        return 1
    return max(1, running + max(0, min(candidates)))


def whole_checks_that_fit(command=None):
    """How many checks running `command` fit side by side, as `gate_turn` hands out turns.

    A sharded suite takes every free turn, so one fits; any other takes one turn of the
    pinned count, or of the derived one when nothing pins it or the pin means no cap.
    """
    if names_shard(command or ""):
        return 1
    try:
        pinned = config.max_gates()
    except config.Error:
        pinned = None
    return pinned or derived_heavy_limit()


def _acquire_gate_turn(run_dir, log_path, log, command=None, cwd=None, *, context=None):
    """Wait for and hold one host-wide heavy-suite turn; None when no turn is taken."""
    record = context if context is not None else (run_record.read_state(run_dir) or {}
                                                if run_dir else {})
    repo = record.get("repo")
    is_landing = bool(record.get("landing"))
    landing_since = _first_landing_wait(run_dir) if run_dir else record.get("since")
    self_id = run_dir.name if run_dir else record.get("run_id")
    if not repo or os.environ.get("AK_MAX_RUNS") == "0":
        return None
    pieces = names_shard(command or "")
    _, job_cpus, job_mem_mb = suite_cost(command, cwd or repo, run_dir) if pieces else (
        None, HEAVY_CPUS, HEAVY_MEM_MB)
    said_bad = []
    config.RUNS.mkdir(parents=True, exist_ok=True)
    files = ExitStack()
    try:
        slots = []
        def admit():
            try:
                pinned = None if pieces else config.max_gates()
            except config.Error as exc:
                if log is not None and not said_bad:
                    said_bad.append(True)
                    log(f"done-when: {exc} · the heavy suite takes a derived turn")
                pinned = None
            # CPU sampling sleeps; locking free slots across it would count them as running.
            readings = host.host_readings(slice_dir=orch.slice_cgroup) if pinned is None else None
            total = max(1, _heavy_max_existing() + 1, len(slots))
            while len(slots) < total:
                slots.append(files.enter_context(gate_lock(repo, len(slots)).open("a")))
            temp, held = [], 0
            for fh in slots:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    held += 1
                    continue
                temp.append(fh)
            new_limit = pinned if pinned is not None else derived_heavy_limit(
                readings, held, job_cpus, job_mem_mb, unit=pieces)
            while len(slots) < new_limit:
                slots.append(files.enter_context(gate_lock(repo, len(slots)).open("a")))
            candidates = []
            if held < new_limit:
                wanted = new_limit - held if pieces else 1
                for fh in slots[:new_limit]:
                    if take_slot([fh]) is not None:
                        candidates.append(fh)
                    if len(candidates) == wanted:
                        break
            for fh in temp:
                if fh not in candidates:
                    fcntl.flock(fh, fcntl.LOCK_UN)
            return candidates, new_limit, held
        slot, limit, held = admit()
        if not limit:
            files.close()
            return None
        me_since = landing_since if is_landing and landing_since is not None else time.time()
        if not slot or _gate_waiter_before(repo, self_id, me_since, is_landing):
            for fh in slot:
                fcntl.flock(fh, fcntl.LOCK_UN)
            slot = []
            began = time.monotonic()
            said = f"waiting for a heavy suite turn · {held} running · {max(0, limit - held)} more fit"
            if log is not None:
                log(f"done-when: {said}")
            waited_since = mark_gate_wait(run_dir, repo) if run_dir else None
            if waited_since is None:
                waited_since = me_since if is_landing else time.time()
            step = history.close_step(run_dir.name) if run_dir else None
            uncapped = False
            try:
                while True:
                    log_path.write_text(said + "\n")
                    run_record.stop_check(run_dir)
                    time.sleep(GATE_POLL)
                    slot, limit, held = admit()
                    if not limit:
                        uncapped = True
                        break
                    said = f"waiting for a heavy suite turn · {held} running · {max(0, limit - held)} more fit"
                    if not slot:
                        continue
                    if _gate_waiter_before(repo, self_id, waited_since, is_landing):
                        for fh in slot:
                            fcntl.flock(fh, fcntl.LOCK_UN)
                        slot = []
                        continue
                    break
            finally:
                if run_dir:
                    mark_gate_wait(run_dir, None)
            if run_dir:
                history.open_step(run_dir.name, step)
            if uncapped:
                files.close()
                return None
            if log is not None:
                log(f"done-when: took a heavy suite turn after "
                    f"{orch.span(time.monotonic() - began)}")
    except BaseException:
        files.close()
        raise
    held = getattr(_GATE_HELD, "count", 0)
    _GATE_HELD.count = held + 1
    return _GateHold(files, slot, context)


@contextmanager
def gate_turn(run_dir, log_path, log, command=None, cwd=None, *, context=None):
    """One host-wide heavy-suite turn, held for as long as the list runs.

    Only the heavy suite -- the `# once` line, the repository's `tests:` suite --
    takes one at landing; every other done-when command
    runs without.  A
    suite builds its own Postgres, port and temp dir at ~0.7 core and ~0.4 GB, so
    a suite starts when the slice's live headroom fits one more, or none run,
    counting running suites once; an explicit
    `max_gates` pins the count instead.  A turn is a flock on one of the host's
    slot files, which the kernel lets go of when its holder dies, so a killed
    suite never blocks the next.  With no `run_dir`, a read-only `context` lets a checker
    take a turn without marking or changing any member's record or history.
    A waiting suite rewrites its own log every poll,
    so the stall ladder reads the wait as life, and says so on its record for `ak
    run status`; the ceiling starts once the turn is its own, and a stop lands
    while it waits as it does mid-list.  A run without a repository, a direct
    caller with no record or context and the test suites' `AK_MAX_RUNS=0` take no turn;
    `max_gates = 0` also leaves ordinary suites uncapped. The limit is re-read on every poll,
    so a changed pin or a
    changed headroom reaches runs already queued.  A freed turn goes to the waiter
    that has waited longest among the highest rank, a landing run before any round
    check, whether `--first` or not: a suite takes a free turn only when no waiter
    ranks before it, and a lander's wait counts from the start of its first landing
    wait.
    A home config this cannot read -- it is read here, mid-run, so one hand-edit
    typo would fail the next suite of every running run -- means a derived count,
    and a log line naming the problem.
    A check running while this thread already holds a turn takes no second one.
    A command naming AK_SHARD reserves all the pieces live headroom fits, each a turn,
    using its repository's measured cost when available; this count is always derived.
    """
    if getattr(_GATE_HELD, "hold", None) is not None:
        yield
        return
    hold = _acquire_gate_turn(run_dir, log_path, log, command, cwd, context=context)
    if hold is None:
        yield
        return
    _GATE_HELD.hold = hold
    try:
        yield
    finally:
        current, _GATE_HELD.hold = _GATE_HELD.hold, None
        if current is not None:
            current.release()


def suite_env():
    """A done-when command's environment, `AK_HEAVY_TURN=1` only while this thread holds a turn.

    A suite that queues behind a host-wide lock of its own would hold the turn for as long as
    another copy holds that lock; told it holds one, it says busy at once instead, exit
    `SUITE_BUSY`, and `busy_turn` gives the turn back.  Never inherited: a loop started below
    a suite holds none of that suite's turn.
    """
    env = run.run_child_env()
    env.pop("AK_HEAVY_TURN", None)
    env.pop("AK_SHARD", None)
    if getattr(_GATE_HELD, "hold", None) is not None:
        env["AK_HEAVY_TURN"] = "1"
    return env


def busy_turn(run_dir, log_path, log, command=None, cwd=None):
    """A heavy suite said busy: give its turn back for a poll, then queue for one again.

    Its own lock is another copy's, and every other suite on the host can use the turn
    meanwhile.  The poll holds no turn and no waiting mark, so no waiter ranks behind it;
    after it the suite queues as a new waiter, and its log reads as it did once it has a
    turn.  Returns the seconds that queueing took, which no ceiling is charged with; the
    poll is, so a suite that only ever says busy still ends.
    """
    hold, _GATE_HELD.hold = getattr(_GATE_HELD, "hold", None), None
    if hold is not None:
        hold.release()
    run_record.stop_check(run_dir)
    time.sleep(GATE_POLL)
    if hold is None:
        return 0.0
    kept = log_path.read_bytes()
    began = time.monotonic()
    _GATE_HELD.hold = _acquire_gate_turn(run_dir, log_path, log, command, cwd,
                                      context=hold.context)
    log_path.write_bytes(kept)
    return time.monotonic() - began


def flaky_key(line):
    """Ignore varying values without depending on a suite's failure words.

    Absolute paths can have a different temporary root on each run; relative test names stay.
    """
    return re.sub(r"(?<![\w.])/[^\s'\"`<>]+|"
                  r"\b(?:0x[0-9a-f]+|[0-9a-f]{8,}(?:-[0-9a-f]+)*)\b|"
                  r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", "<varying>", line, flags=re.I)


def names_shard(command):
    return re.search(r"\bAK_SHARD\b", command) is not None


def suite_cost(command, cwd, run_dir):
    """A repository and suite's measured scheduling cost, or the initial estimate."""
    state = run_record.read_state(run_dir) or {} if run_dir else {}
    repo = Path(state.get("repo") or run.main_checkout(cwd)).resolve()
    key = hashlib.sha256(f"{repo}\n{command}".encode()).hexdigest()
    path = config.STATE / f"suite-{key}.json"
    try:
        cost = read_suite_cost(path)
        cpu, mem = cost["cpus"], cost["mem_mb"]
        if all(type(value) in (int, float) and math.isfinite(value) and value > 0
               for value in (cpu, mem)):
            return path, max(HEAVY_CPUS, cpu), max(HEAVY_MEM_MB, mem)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return path, HEAVY_CPUS, HEAVY_MEM_MB


def read_suite_cost(path):
    try:
        cost = json.loads(path.read_text())
        return cost if isinstance(cost, dict) else {}
    except (OSError, ValueError):
        return {}


def write_suite_cost(path, updates):
    """Called under the lifecycle lock so measurements keep the split-run receipt."""
    cost = read_suite_cost(path)
    cost.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as saved:
        json.dump(cost, saved)
    Path(saved.name).replace(path)


def check_suite_pieces():
    """The split run checks its branch's declaration, never the target's fallback."""
    command = run.declared(Path.cwd(), "tests")
    if not command or not names_shard(command):
        raise SystemExit("The branch's tests: line must name AK_SHARD")
    env = suite_env()
    pieces = [subprocess.Popen(["bash", "-c", command],
                              env={**env, "AK_SHARD": f"{index}/3"})
              for index in range(1, 4)]
    codes = [piece.wait() for piece in pieces]
    raise SystemExit(int(any(codes)))


def split_suite_run(lp, command):
    """Only a whole suite measured by this run can start its repository's split run."""
    if not command or names_shard(command):
        return
    path, _, _ = suite_cost(command, lp.wt, lp.run_dir)
    cost = read_suite_cost(path)
    seconds = cost.get("wall_seconds", 0)
    if (cost.get("run_id") != lp.state.get("run_id")
            or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 120):
        return
    check = "python3 -c " + shlex.quote(
        f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); "
        "from agentkit.gate import check_suite_pieces; check_suite_pieces()")
    text = (f"The repository's `tests:` suite ran whole for {seconds:g} seconds:\n"
            f"```bash\n{command}\n```\n\n"
            "Make the `tests:` line run only its `AK_SHARD=k/N` share (1-based), and "
            "everything when unset. Use the test runner's own sharding where it has one: "
            "jest, vitest and playwright take `--shard=k/N`; pytest can select by a "
            "conftest option. Otherwise split the test file list by position. Pieces share "
            "no temp dir, port, database or other file; together they run every test exactly "
            "once. Keep the check below: it reads this branch's own `tests:` line and runs "
            "pieces 1/3, 2/3 and 3/3 at the same time.\n")
    try:
        run.start_followups(lp.state, lp.run_dir, lp.log, lp.cfg,
                            split={"command": command, "text": text, "check": check,
                                   "cost": str(path)})
    except (config.Error, OSError, run_record.StopRequested) as exc:
        lp.log(f"WARN could not start the suite split: {exc}")


class _SuiteMeasure:
    """Wall time works everywhere; only this run's cgroup can attribute CPU and memory."""

    def __init__(self, run_dir):
        state = run_record.read_state(run_dir) or {} if run_dir else {}
        self.run_id = state.get("run_id")
        relative = host.process_cgroup() if state.get("scope") else None
        self.group = (host.cgroup_path(relative) if relative and
                      Path(relative).name in run._scope_units(state["scope"]) else None)
        self.cpu = host._slice_cpu_stat(self.group) or {}
        reading = host._scope_readings(self.group) if self.group is not None else None
        self.baseline = reading[1] if reading else None
        self.peak = self.baseline
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def sample(self):
        if self.baseline is not None:
            reading = host._scope_readings(self.group)
            if reading:
                with self.lock:
                    self.peak = max(self.peak, reading[1])

    def save(self, path, pieces):
        cpu = (host._slice_cpu_stat(self.group) or {}).get("usage_usec")
        first = self.cpu.get("usage_usec")
        elapsed = time.monotonic() - self.started
        if elapsed <= 0:
            return
        cost = {"wall_seconds": elapsed, "run_id": self.run_id}
        if cpu is not None and first is not None and self.baseline is not None:
            cost.update(cpus=max(HEAVY_CPUS, (cpu - first) / (elapsed * 1e6 * pieces)),
                        mem_mb=max(HEAVY_MEM_MB, (self.peak - self.baseline) / (1024**2 * pieces)))
        try:
            with watch.state_lock():
                previous = read_suite_cost(path)
                # A fast retry must not erase the slow whole attempt that earned a split.
                seconds = previous.get("wall_seconds", 0)
                if (previous.get("run_id") == self.run_id and type(seconds) in (int, float)
                        and math.isfinite(seconds)):
                    cost["wall_seconds"] = max(elapsed, seconds)
                write_suite_cost(path, cost)
        except OSError:
            pass    # a missing measurement keeps the initial estimate


def flaky_record(command, failed, rerun, log_path, run_dir, log):
    """Keep the whole failure, even when its distinguishing lines precede the output cap."""
    with tempfile.NamedTemporaryFile(dir=run_dir or log_path.parent,
                                     prefix=f"{log_path.stem}-failed-",
                                     suffix=".log", delete=False) as saved:
        saved.write(failed)
    lines = [line for line in failed.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    reran = {flaky_key(line) for line in rerun.decode("utf-8", errors="replace").splitlines()}
    diff = [line for line in lines if flaky_key(line) not in reran][:20]
    note = f"flaky: {command} failed, then passed on its re-run"
    if log is not None:
        log(f"done-when: {note}")
    return "\n".join([note, f"failed output: {Path(saved.name).resolve()}", *diff])


def run_suite(command, limit, *, cwd, activity, output, run_dir=None, log=None,
              on_wait=None, measure=False, **kwargs):
    """One command, or all its opted-in pieces, with failed pieces retried alone.

    Callers keep one command and one outcome. Each piece has its own silence window;
    all attempts share the command's ceiling, and live output identifies its piece.
    """
    env = suite_env()
    if not names_shard(command):
        path = suite_cost(command, cwd, run_dir)[0] if measure else None
        measured = _SuiteMeasure(run_dir) if measure else None
        aborting = kwargs.pop("abort", None)
        def abort():
            if measured:
                measured.sample()
            return aborting() if aborting else False
        result = worker.limited(["bash", "-c", command], limit, cwd=str(cwd),
                                activity=activity, output=output, env=env, abort=abort, **kwargs)
        if measured and not result[2] and result[0] != SUITE_BUSY:
            measured.save(path, 1)
        return result
    with gate_turn(run_dir, activity, log, command, cwd):
        hold = getattr(_GATE_HELD, "hold", None)
        path, cpu, mem = suite_cost(command, cwd, run_dir)
        count = len(hold.slots) if hold else derived_heavy_limit(
            running=0, job_cpus=cpu, job_mem_mb=mem, unit=True)
        env = suite_env()    # the piece threads do not inherit this thread's held turn
        deadline = time.monotonic() + limit
        cancel, writing = threading.Event(), threading.Lock()
        last_shard = None
        measure = _SuiteMeasure(run_dir)
        timeout = kwargs.pop("on_timeout", None)

        with ExitStack() as files:
            results = []
            def attempt(shard):
                run_record.stop_check(run_dir)
                piece = files.enter_context(tempfile.NamedTemporaryFile(
                    dir=activity.parent, prefix=f"{activity.stem}-piece-", suffix=".log"))
                header = f"--- AK_SHARD={shard} ---\n".encode()

                class Output:
                    def __init__(self):
                        self.pending = b""

                    def emit(self, data):
                        nonlocal last_shard
                        output.write((header if last_shard != shard else b"") + data)
                        output.flush()
                        last_shard = shard

                    def write(self, data):
                        with writing:
                            piece.write(data)
                            piece.flush()
                            # A sibling can take the live log only between whole lines.
                            self.pending += data
                            lines, newline, self.pending = self.pending.rpartition(b"\n")
                            if newline:
                                self.emit(lines + newline)

                    def flush(self):
                        piece.flush()

                    def finish(self):
                        with writing:
                            if self.pending:
                                self.emit(self.pending + b"\n")
                                self.pending = b""

                def stopped(why, pid):
                    if why != "abort":
                        cancel.set()
                        if timeout is not None:
                            timeout(why, pid)

                def abort():
                    measure.sample()
                    return cancel.is_set()

                # The watchdog reads this piece's file, so a chatty sibling cannot hide silence.
                left = deadline - time.monotonic()
                if left <= 0:
                    cancel.set()
                    return worker.TIMEOUT, piece, True
                stream = Output()
                try:
                    code, _, killed = worker.limited(
                        ["bash", "-c", command], left,
                        cwd=str(cwd), activity=Path(piece.name),
                        output=stream, env={**env, "AK_SHARD": shard}, abort=abort,
                        on_timeout=stopped, **kwargs)
                finally:
                    stream.finish()
                return code, piece, killed

            with ThreadPoolExecutor(max_workers=count) as pool:
                try:
                    futures = [pool.submit(attempt, f"{index}/{count}")
                               for index in range(1, count + 1)]
                    results = [future.result() for future in futures]
                except BaseException:
                    cancel.set()
                    raise
            if not any(killed or code == SUITE_BUSY for code, _, killed in results):
                measure.save(path, count)
            hold = getattr(_GATE_HELD, "hold", None)
            if hold is not None:
                hold.alone()
            chunks, red, flakes = [], [], []
            for index, (code, piece, killed) in enumerate(results, 1):
                shard = f"{index}/{count}"
                failed = None
                while code and not killed and not cancel.is_set():
                    if code == SUITE_BUSY:
                        queued = busy_turn(run_dir, activity, log, command, cwd)
                        deadline += queued
                        if on_wait is not None:
                            on_wait(queued)
                        hold = getattr(_GATE_HELD, "hold", None)
                        if hold is not None:
                            hold.alone()
                        env = suite_env()
                    elif failed is None:
                        piece.seek(0)
                        failed = piece.read()
                    else:
                        break
                    code, piece, killed = attempt(shard)
                if failed is not None and code == 0:
                    piece.seek(0)
                    flakes.append(flaky_record(f"{command} (AK_SHARD={shard})", failed,
                                               piece.read(), activity, run_dir, log))
                results[index - 1] = code, piece, killed
                piece.seek(0, os.SEEK_END)
                size = piece.tell()
                piece.seek(max(0, size - run.OUT_CAP))
                text = piece.read().decode("utf-8", errors="replace").rstrip()
                # Existing failure diagnostics read the last output; leave a red piece last.
                (red if code else chunks).append(f"--- AK_SHARD={shard} ---\n"
                    f"[{'killed at the limit' if killed else f'exit {code}'}]\n{text}".rstrip())
            text = "\n\n".join(chunks + red + flakes)
            output.write(("\n" + text + "\n").encode())
            output.flush()
            return next((code for code, _, _ in results if code), 0), text, any(
                killed for _, _, killed in results)


def _running_commands(pid):
    """The live leaves of a command, before its group is ended."""
    table = watch._proc_table()
    found = {pid}
    # A shell can exit while its background child still holds the output pipe.
    # Its group keeps that child with the command after reparenting.
    for child in table:
        try:
            if os.getpgid(child) == pid:
                found.add(child)
        except OSError:
            pass
    while True:
        children = {child for child, (parent, _, _) in table.items()
                    if parent in found} - found
        if not children:
            break
        found.update(children)
    live = {child: row for child, row in table.items()
            if child in found and row[1] not in ("Z", "X")}
    parents = {row[0] for row in live.values()}
    running = []
    for child, (_, _, args) in live.items():
        if child in parents or not args:
            continue
        birth = host.process_identity(child)
        if birth is None:
            continue
        command = " ".join(" ".join(args).split())
        if len(command) > 160:
            command = command[:159] + "…"
        elapsed = max(0, int(time.time() - birth["started_at"]))
        running.append(f"{command} ({elapsed}s)")
    return running


def run_done_when(cmds, cwd, log_path, artifacts, limit=None, log=None, silence=None,
                  run_dir=None, heavy=False):
    """Run commands while they produce output, with a ceiling on the whole list.

    Each command gets its own silence window. The list's ceiling never resets,
    so a command that prints forever still fails the round. Output goes straight
    to the gate log so the external stall ladder sees the same activity.

    A stopped gate is a failed gate, never a stopped run: the fixer round runs as it does
    for any other failure.  Whatever the commands newly dirty -- __pycache__, build output
    -- goes into `artifacts`: that is the loop's own droppings, not the executor's work,
    and commit_leftovers must never hand it to the reviewer.

    The commands run seatless, as the workers do: an `ak run` or a smoke suite a done-when
    starts is launched from no seat, so it is nobody's to report and in no seat's tally.

    No command starts on a stopped run: each one asks first, so a stop that lands
    mid-list aborts the gate instead of running commands no record wants anymore.

    A command that exits non-zero runs once more at once, within the same ceiling, and the
    re-run decides it: under load a timing test fails by chance far more often than a change
    breaks it.  A pass that took the re-run is said, not hidden -- a `flaky:` record after
    the command's keeps the lines the failed run printed that its passing re-run did not,
    comparing without numbers, hex ids or absolute paths, in their order, at most 20.
    It names a file in the run directory holding the whole failed output for the run's
    follow-ups. A killed
    command is not re-run: it spent the silence window or ceiling, which a second go would
    only spend again.

    When `heavy` the list runs on one host-wide heavy-suite turn (`gate_turn`),
    taken before its first command and let go however the list ends; the ceiling
    counts from the turn, not the wait.  Otherwise it runs without one.  A heavy
    command that exits `SUITE_BUSY` never ran: it is no failure and no re-run, it gives
    its turn back for a poll (`busy_turn`) and runs again.
    """
    limit = 3600 * run_record.CEILING_HOURS if limit is None else limit
    silence = 60 * run_record.SILENCE_MINUTES if silence is None else silence
    before = set(run.dirty_paths(cwd))
    chunks, ok = [], True
    spent, killed, kept = None, False, ""   # the command the limit ran out on, whether it had
                                            # begun, and the output it had produced by then
    reason, running = [], []

    def stopped(why, pid):
        reason.append(why)
        running.extend(_running_commands(pid))

    suite = next((cmd for cmd in cmds if names_shard(cmd)), None)
    with gate_turn(run_dir, log_path, log, suite, cwd) if heavy or suite else nullcontext():
        deadline = time.monotonic() + limit
        def waited(seconds):
            nonlocal deadline
            deadline += seconds
        log_path.write_text("")
        for cmd in cmds:
            first = None        # the output of a first run that failed, while its re-run decides
            first_span = None   # its byte span in the gate log: the flaky diff reads whole runs
            busy = False
            while True:
                run_record.stop_check(run_dir)
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                with log_path.open("ab") as progress:
                    progress.write(f"$ {cmd}\n".encode())
                    progress.flush()
                    offset = progress.tell()
                    code, piece_text, killed = run_suite(
                        cmd, left, silence=silence, activity=log_path,
                        on_timeout=stopped, cwd=str(cwd), output=progress,
                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                        run_dir=run_dir, log=log, on_wait=waited, measure=heavy)
                    end = progress.tell()
                if log is not None and run_dir is not None:
                    run.memory_cap_note(run_dir, log)
                with log_path.open("rb") as progress:
                    progress.seek(max(offset, log_path.stat().st_size - run.OUT_CAP))
                    out = progress.read().decode("utf-8", errors="replace")
                if names_shard(cmd):
                    out = piece_text
                if heavy and code == SUITE_BUSY and not killed:
                    if log is not None and not busy:
                        log(f"done-when: busy: {cmd} exited {SUITE_BUSY}; it runs again "
                            "each poll, its heavy suite turn given back meanwhile")
                    busy = True
                    deadline += busy_turn(run_dir, log_path, log)
                    continue
                if code == 0 or killed or first is not None or names_shard(cmd):
                    break
                first = out
                first_span = (offset, end)
            if left <= 0 and first is None:
                # the list is out of time: starting this command would give it a limit of its own
                spent, killed, kept = cmd, False, ""
                chunks.append(f"$ {cmd}\n[not run: the done-when limit was already spent]")
                break
            ok &= code == 0
            chunks.append(f"$ {cmd}\n[{'killed at the limit' if killed else f'exit {code}'}]\n"
                          f"{out if names_shard(cmd) else out[-run.OUT_CAP:]}".rstrip())
            if first is not None and code == 0:
                # blank lines dropped: a record is what lies between two, and these are one
                # both runs read whole from the gate log: the capped `out` starts mid-output
                # on a chatty suite, which hides a failure above the cap and frames shared
                # lines the re-run's own window dropped as lines it never printed
                with log_path.open("rb") as progress:
                    progress.seek(first_span[0])
                    failed = progress.read(first_span[1] - first_span[0])
                    progress.seek(offset)
                    rerun = progress.read(end - offset)
                chunks.append(flaky_record(cmd, failed, rerun, log_path, run_dir, log))
            if killed:
                spent, kept = cmd, out
                break
    if spent is not None:
        ok = False
        if killed:
            tail = kept.strip().splitlines()
            last = tail[-1] if tail else "(no output)"
            if len(last) > 160:
                last = last[:159] + "…"
            cause = (f"{silence / 60:g} min of silence" if reason and reason[0] == "silence" else
                     f"{limit / 3600:g}h ceiling")
            stopped_line = f"done-when: stopped after {cause}: {spent} (last output: {last})"
            stopped_line += "".join(f"; still running: {command}" for command in running)
        else:
            stopped_line = (f"done-when: stopped after {limit / 3600:g}h ceiling: {spent} "
                            f"(the limit was spent before it could start)")
        chunks.append(stopped_line + ", and the commands after it, if any, were not run.")
        if log is not None:
            log(stopped_line)
    text = "\n\n".join(chunks)
    log_path.write_text(text)
    # The gate is over and its children are not the round's: a command that exited 0 may
    # still have left processes behind, and they die with the gate, however detached.
    worker.kill_marked(run.run_child_env().get(worker.RUN_MARKER), log=log)
    artifacts.update(set(run.dirty_paths(cwd)) - before)
    return ok, text


def turn_held():
    """Whether this thread holds a heavy-suite turn, including a directly acquired hold."""
    return bool(getattr(_GATE_HELD, "count", 0))


def release_turn():
    """Let this thread's turn go so the next check takes a fresh one."""
    hold, _GATE_HELD.hold = getattr(_GATE_HELD, "hold", None), None
    if hold is not None:
        hold.release()
