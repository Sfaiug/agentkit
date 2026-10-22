"""Run admission, check commands and the host-wide heavy-suite turn."""

import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, gitcall, handback, helper, history, host, orch, transitions, turns, watch
from . import worker
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
# A piece on the suite helper runs in a clone there, which land._check's look at this checkout
# never sees: the piece checks that clone itself and fails, as land._check does, if it changed.
PINNED_PIECE = ('head=$(git rev-parse HEAD) && bash -c {} || exit\n'
                '[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||'
                ' {{ echo "the piece changed the checkout it tests" >&2; exit 1; }}')
QUIET_RUNS = 20       # a suite's pace: the longest any of its last runs went without output;
QUIET_TIMES = 3       # three times that stops it, room for a slower host than those runs had,
QUIET_FLOOR = 5 * 60  # and never under five minutes, however chatty the suite


@contextmanager
def slot_lock():
    """One atomic count-and-claim across seats, processes and job threads."""
    config.RUNS.mkdir(parents=True, exist_ok=True)
    with (config.RUNS / ".slots.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def slot_order(state):
    # A green member only needs delivery before the target moves.  A run started again after a
    # park (`leases.restart`) waits from where its first attempt queued, not behind the queue.
    # Finished rounds precede fresh launches without joining the first element's gate bypass.
    wait = state.get("waiting_on") or {}
    return (not (state.get("first") or "land" in wait or "fix" in wait),
            not landing.green_delivery(wait),
            not (state.get("round_summaries") or (state.get("own_pr") and state.get("own_pr_wait"))),
            transitions.first_queued(state),
            state.get("run_id") or "")


CPU_PRESSURE_LIMIT = 40   # ak's own processes are stalled on CPU nearly half the time
MEMORY_PRESSURE_LIMIT = 10   # ... on memory a tenth of it: pages back from swap stall far less


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
    """Live slot owners, top-level receipts ahead of this one (including dead waiters), and
    the other waiters' run ids in queue order."""
    running, waiting = 0, []
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if other.get("run_id") == state.get("run_id") or other.get("run_depth", 0):
            continue
        if other.get("state") == "running" and run_record.process_active(other):
            running += 1
        elif other.get("state") == "queued" and other.get("slot_waiting"):
            waiting.append(slot_order(other))
    waiting.sort()
    mine = slot_order(state)
    return running, sum(order < mine for order in waiting), [order[-1] for order in waiting]


def _save_queue(running, queue, let_in=None):
    """Under slot_lock: the queue as this poll decided it, for the waiters behind its first,
    since when that first has waited there while polled (`first_in_line`), and how long the last
    20 firsts waited there before they were let in (`let_in`, the run this poll lets in), kept
    across gaps in the polling."""
    path, now = config.RUNS / ".slots.queue", time.time()
    waits, took = first_in_line(now), slot_queue()[4]
    if waits and let_in == waits[0]:
        took = [*took, now - waits[1]][-20:]
    since = waits[1] if waits and queue[:1] == [waits[0]] else now
    temp = path.with_name(".slots.queue.tmp")
    temp.write_text(json.dumps({"at": now, "running": running, "queue": queue, "since": since,
                                "took": took}))
    temp.replace(path)


def slot_queue():
    """(when, live slot owners, waiting run ids first in line first, since when that first has
    waited there, the waits there of the last firsts let in) as the last poll left them."""
    try:
        saved = json.loads((config.RUNS / ".slots.queue").read_text())
        return (float(saved["at"]), int(saved["running"]),
                [str(run_id) for run_id in saved["queue"]], float(saved.get("since") or 0),
                [float(wait) for wait in saved.get("took") or []])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0, 0, [], 0.0, []


def first_in_line(now):
    """(the run first in line for a slot, since when it has waited there, how many wait behind
    it, the waits there of the last firsts let in) while a poll within four rewrote the queue,
    for `stuck`: its first polls every one, and once it is gone a waiter behind it within three
    (`behind_first`); after a gap, a new wait.  A poll newer than `now`, one that ran while the
    caller read, is the same wait."""
    at, _, queue, since, took = slot_queue()
    if queue and since and now - at < 4 * SLOT_POLL:
        return queue[0], since, len(queue) - 1, took
    return None


def behind_first(run_id):
    """Whether the queue still has this run waiting behind its first, who alone can be admitted.

    Such a run skips its poll: it reads no record and takes no lock. A queue no poll rewrote
    for two polls -- its first stopped or died -- is counted again by whoever polls next.
    """
    at, _, queue, *_ = slot_queue()
    return 0 <= time.time() - at < 2 * SLOT_POLL and run_id in queue[1:]


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
    # A run behind the first polls nothing that refreshes its own reason: its place is the queue's.
    _, running, queue, *_ = slot_queue()
    if state.get("run_id") in queue[1:]:
        counts = running, queue.index(state["run_id"])
    elif state.get("slot_wait_reason"):
        return state["slot_wait_reason"]
    else:
        counts = slot_counts(state)[:2]
    return slot_line(*counts, config.max_runs(), not slot_order(state)[0])


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
    pressure = host._reading(readings, "slice_memory_pressure")
    if pressure is not None and pressure > MEMORY_PRESSURE_LIMIT:
        return (f"waiting for ak's memory · pressure {pressure:g}%, "
                f"limit {MEMORY_PRESSURE_LIMIT}%", "unit memory")
    unit = host._slice_or_unit_memory(readings)
    peak = history.recent_peak_rss_mb() if unit else None
    if unit and peak is not None:
        room = unit[1] - unit[0]
        if room < peak:
            return (f"waiting for the unit's memory · {host._g(room)} G left, "
                    f"a run needs {host._g(peak)} G", "unit memory")
    elif unit and unit[0] > unit[1] * .75:
        raw = unit[2]
        if raw is not None:
            return (f"waiting for the unit's memory · {host._g(unit[0])} of {host._g(unit[1])} G "
                    f"in use ({host._g(raw)} with cache)", "unit memory")
        return (f"waiting for the unit's memory · {host._g(unit[0])} of {host._g(unit[1])} G",
                "unit memory")
    return None, None


def _host_admits(state, readings, is_first):
    """The host gates and two steady polls: False, the wait written on `state`, while one holds."""
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
    if reason is None and not is_first and landing_waits():
        # Finished work goes first: the headroom a new run would take is the suite's.
        reason, kind = "waiting for a landing suite's turn · finished work goes first", "landing"
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
    return True


def claim_slot(state, limit, readings=None):
    """Called under slot_lock: count, FIFO and two steady host polls decide admission."""
    running, ahead, others = slot_counts(state)
    # AK_MAX_RUNS=0 is the test-suite escape hatch: it disables count and host gates together.
    ungated = os.environ.get("AK_MAX_RUNS") == "0"
    if state.get("run_depth", 0) or ungated:
        state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                     **run_record.process_owner())
        state.pop("resume_from", None)
        return True
    _save_queue(running, others[:ahead] + [state.get("run_id")] + others[ahead:])
    is_first = not slot_order(state)[0]
    if ahead or (limit and running >= limit and not is_first):
        state["slot_waited"] = True
        state["slot_wait_reason"] = slot_line(running, ahead, limit, is_first)
        state["slot_wait_kind"] = "count"
        state["slot_healthy_polls"] = 0
        return False
    # A green delivery only merges a tree its line already checked: it spends no headroom a
    # gate guards, and every member behind it in the line waits on it.
    if not landing.green_delivery(state.get("waiting_on") or {}) and not _host_admits(
            state, readings, is_first):
        return False
    _save_queue(running + 1, others, let_in=state.get("run_id"))
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


def count_wait(run_id, wait, counted):
    """Add what this process waited since `counted` to its run's history; returns it moved to now.

    `counted` is the wait's start on the wall clock, which keys its one phase row, and the
    monotonic time it is counted up to.  The waiting process counts its own wait as it polls,
    so one that dies loses at most a poll, and no recovery can count time no process spent
    waiting -- nor a clock correction.
    """
    began, since = counted
    now = time.monotonic()
    history.add_wait(run_id, wait, now - since, began=began)
    return began, now


def wait_for_slot(run_dir, between=None):
    """Reserve a slot in run.json before work starts; no process-local semaphore can do this.

    `between` runs after each poll's wait, while the wait holds nothing: it may replace this
    process with the same launch on newer code (`run.pickup_while_queued`)."""
    announced = False
    first_poll = True
    behind = False
    wait_kind = None
    counted = None
    while True:
        if not first_poll:
            counted = counted or (time.time(), time.monotonic())
            time.sleep(SLOT_POLL)
            counted = count_wait(run_dir.name, "slot", counted)
            if between is not None:
                between()
            if behind_first(run_dir.name):
                behind = True
                continue
        limit = config.max_runs()
        with slot_lock(), run_record.recovery_lock(run_dir):
            state = run_record.read_state(run_dir) or {}
            if state.get("state") == "running" and state.get("pid") == os.getpid():
                return state
            if first_poll and state.get("state") != "queued" and not run_record.process_active(state):
                # drive also accepts a saved receipt directly (the job/recovery API).
                state.update(run_id=run_dir.name, state="queued", slot_waiting=True,
                             queued_at=time.time(), **run_record.process_owner())
                state.setdefault("run_depth", gitcall.run_depth())
                # A new queue episode starts with no memory of the last one's wait.
                for key in ("slot_waited", "slot_wait_reason", "slot_wait_kind"):
                    state.pop(key, None)
                run_record.save_state(run_dir, state)
            if state.get("state") != "queued" or state.get("pid") != os.getpid():
                raise config.Error(f"{run_dir.name}: another process owns this launch")
            if first_poll:
                # what held the launch before this process took it up: its launcher, a pickup
                wait_kind = state.get("slot_wait_kind")
            if behind:
                # The polls it skipped were count waits, and steadiness starts over after one.
                state.update(slot_waited=True, slot_wait_kind="count", slot_healthy_polls=0)
                behind = False
            first_poll = False
            if claim_slot(state, limit):
                run_record.save_state(run_dir, state)
                break
            # Admission clears the kind, so the receipt below reads this copy.
            wait_kind = state.get("slot_wait_kind") or wait_kind
            run_record.save_state(run_dir, state)
        if not announced:
            print(slot_note(state), flush=True)
            handback.redress_seat(state.get("launched_session"))
            announced = True
    if counted:
        count_wait(run_dir.name, "slot", counted)
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
    handback.redress_seat(state.get("launched_session"))
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
    """This run's first landing wait, or None when it never looked for a landing turn.

    The start lives beside the record, not in it: a whole-record save of the loop's
    own state would wipe it from run.json between two laps, and the next lap would
    count from itself instead.  `land` clears it for a fresh landing and when the
    landing ends.
    """
    try:
        return float((Path(run_dir) / "landing_since").read_text().strip())
    except (OSError, ValueError):
        return None


def _seed_landing_wait(run_dir, since):
    """Start this run's first landing wait at `since`; without the marker it still ranks."""
    try:
        (Path(run_dir) / "landing_since").write_text(repr(since))
    except OSError:
        pass


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
    freed turn goes to the round check that has waited longest.  A landing run's mark
    says so, and its wait's file ranks it (`landing_wait`); the start of its first
    landing wait lives beside the record, where
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
                            _seed_landing_wait(run_dir, since)
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


@contextmanager
def landing_wait(landing, since=None, run_id=None):
    """While a landing suite waits for a heavy turn it holds two files.

    `.heavy-landing.wait`, shared by every landing wait, says one waits: round checks and
    new runs stay behind it (`landing_waits`), whatever code each waiter runs.  A file of
    its own says when its wait began and for which run, so landing waits rank among
    themselves (`_landing_waiters`); the line's checkers mark no member's record.  The
    kernel lets go with the holder, so a dead waiter holds nobody back.
    """
    if not landing:
        yield
        return
    config.RUNS.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
    draft, path = config.RUNS / f".landing-draft-{token}", config.RUNS / f".landing-wait-{token}"
    with (config.RUNS / ".heavy-landing.wait").open("a") as shared, draft.open("w") as fh:
        fcntl.flock(shared, fcntl.LOCK_SH)
        # Locked before it takes its name: a file under that name is never an unheld live one.
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps({"since": since, "run_id": run_id or ""}))
        fh.flush()
        draft.rename(path)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _still_landing(context):
    """Whether the line still holds the member a checker's wait is for; True without one.

    A stopped or departed member leaves `landing.line`, and a check for it is no longer
    finished work: it must not hold back every build and round check for its turn.
    """
    line = (context or {}).get("line")
    if not line:
        return True
    return any(directory.name == context.get("run_id")
               for directory, _ in landing.line(config.RUNS / line))


def _landing_waiters():
    """The live landing waits as (since, run id); a dead waiter's file goes, unreadable is none."""
    found = []
    for path in config.RUNS.glob(".landing-wait-*"):
        try:
            with path.open() as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    wait = json.loads(fh.read())
                    found.append((float(wait["since"]), str(wait["run_id"])))
                    continue
                path.unlink(missing_ok=True)     # its holder is gone
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return found


def landing_waits():
    """Whether a landing suite waits for a heavy turn now; unreadable is no.

    Probes take turns on their own file, so one probe never reads another as a waiter.
    """
    try:
        with (config.RUNS / ".heavy-landing.probe").open("a") as turn, \
                (config.RUNS / ".heavy-landing.wait").open("a") as probe:
            fcntl.flock(turn, fcntl.LOCK_EX)
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        pass
    return False


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
    other suite under load.  A round check stays behind any landing wait
    (`landing_waits`).  A landing wait -- a run's, or the line checker's that marks no
    record -- ranks by its own file (`landing_wait`), whose start is the one its waiter
    ranks itself by: a lander's counts from its first landing wait, not from the lap.
    A record's landing mark ranks only a lander with no live file, one still on code
    from before the files, by the start of its first landing wait; a mark from before
    landers ranked carries no landing and reads as a round check.  A mark
    whose process is gone, or whose pid no longer matches its record -- a kill or
    a resume left it behind -- holds nobody back.
    """
    if not is_landing and landing_waits():
        return True
    me = (not is_landing, since, exclude or "")
    filed = _landing_waiters()
    if any((False, *wait) < me for wait in filed if wait[1] != exclude):
        return True
    filed = {run_id for _, run_id in filed}
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
        if landing and directory.name in filed:
            continue
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
    which a shell beside the slice reads like a worker inside it; the host's CPU
    use outside the slice takes from the cores the slice may use.  Where
    no slice answers, the host's idle cores and free memory stand in.  An
    unreadable gate fails open to the other resource, and to one suite where
    neither answers.  `job_cpus` and `job_mem_mb` are one job's cost, such as a suite
    piece's as measured (`suite_cost`). With `unit`, pieces also fit the caller's soft
    limit and the remaining room under every enclosing hard memory cap.
    """
    if running is None:
        running = _heavy_running()
    if readings is None:
        readings = host.host_readings(slice_dir=orch.slice_cgroup)
    cpu_quota = host._reading(readings, "slice_cpu_quota")
    cpus = host._reading(readings, "cpus", "nproc")
    used = host._reading(readings, "slice_cpu_used")
    if cpu_quota is not None or (cpus is not None and used is not None):
        if cpu_quota is None:
            cpu_quota = cpus
        outside = host._reading(readings, "outside_cpu_used")
        if outside is not None and cpus is not None:
            cpu_quota = min(cpu_quota, cpus - outside)
        cpu_free = cpu_quota - used if used is not None else float(cpu_quota)
    else:
        load = host._reading(readings, "load", "load1", "load_1m")
        if cpus is not None and load is not None:
            cpu_free = cpus - load
        elif cpus is not None:
            cpu_free = float(cpus)
        else:
            cpu_free = None
    memory = host._slice_or_unit_memory(readings)
    if memory is not None:
        mem_free = memory[1] - memory[0]
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
    # A landing suite is seen waiting from its first look at the turns until it holds them.
    waiting = ExitStack()
    try:
        # A lander's wait counts from the start of its first landing wait, not from the lap.
        me_since = landing_since if is_landing and landing_since is not None else time.time()
        if is_landing and run_dir and landing_since is None:
            # Its first landing wait starts here, as its file says: a waiter on older code
            # ranks it by this marker, and must rank it by the same start.
            _seed_landing_wait(run_dir, me_since)
        waiting.enter_context(landing_wait(is_landing, me_since, self_id))
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
            # At the top CPU weight (the line's checker) the use lower-weighted runs hold is its own.
            kept = host.kept_cpu(orch.slice_cgroup()) if pinned is None else None
            if kept is not None:
                readings = {**readings, "slice_cpu_used": kept}
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
        if not slot or _gate_waiter_before(repo, self_id, me_since, is_landing):
            for fh in slot:
                fcntl.flock(fh, fcntl.LOCK_UN)
            slot = []
            began = time.monotonic()
            counted = (time.time(), began)
            said = f"waiting for a heavy suite turn · {held} running · {max(0, limit - held)} more fit"
            if log is not None:
                log(f"done-when: {said}")
            marked = mark_gate_wait(run_dir, repo) if run_dir else None
            waited_since = me_since if is_landing else marked or time.time()
            step = history.close_step(run_dir.name) if run_dir else None
            uncapped = False
            try:
                while True:
                    log_path.write_text(said + "\n")
                    run_record.stop_check(run_dir)
                    time.sleep(GATE_POLL)
                    if is_landing and not _still_landing(context):
                        # Its members left the line: this check waits as a round check now.
                        is_landing, waited_since = False, time.time()
                        waiting.close()
                    # a checker's wait is its member's, kept beside that member's line time
                    if run_dir or is_landing:
                        counted = count_wait(self_id, "suite" if run_dir else "lander", counted)
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
                if run_dir or is_landing:
                    count_wait(self_id, "suite" if run_dir else "lander", counted)
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
    finally:
        waiting.close()
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
    take a turn without marking or changing any member's record; the member's history
    row keeps how long the checker waited.
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
    A suite the helper has room for (`helper.start`) takes a turn only for pieces it hands back.
    """
    if getattr(_GATE_HELD, "hold", None) is not None or getattr(_GATE_HELD, "away", None):
        yield
        return
    away = None
    if command and cwd and names_shard(command):
        away = helper.start(*suite_cost(command, cwd, run_dir)[1:], cwd, log or (lambda line: None))
    if away is not None:
        _GATE_HELD.away = away
        _GATE_HELD.home = lambda: _acquire_gate_turn(run_dir, log_path, log, command, cwd,
                                                     context=context)
        try:
            yield
        finally:
            current, _GATE_HELD.hold = getattr(_GATE_HELD, "hold", None), None
            _GATE_HELD.away = _GATE_HELD.home = None
            if current is not None:
                current.release()
            helper.finish(away)
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
    a suite holds none of that suite's turn, nor its share or test lists.
    """
    env = gitcall.run_child_env()
    for key in ("AK_HEAVY_TURN", "AK_SHARD", "AK_ONLY", "AK_FAILED", "AK_RAN"):
        env.pop(key, None)
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
    """A repository and suite's measured scheduling cost, each part the initial estimate
    until a finished suite measured it."""
    state = run_record.read_state(run_dir) or {} if run_dir else {}
    repo = Path(state.get("repo") or gitcall.main_checkout(cwd)).resolve()
    key = hashlib.sha256(f"{repo}\n{command}".encode()).hexdigest()
    path = config.STATE / f"suite-{key}.json"
    cost = read_suite_cost(path)
    def measured(name, estimate):
        value = cost.get(name)
        if type(value) in (int, float) and math.isfinite(value) and value > 0:
            return max(estimate, value)
        return estimate
    return path, measured("cpus", HEAVY_CPUS), measured("mem_mb", HEAVY_MEM_MB)


def read_suite_cost(path):
    try:
        cost = json.loads(path.read_text())
        return cost if isinstance(cost, dict) else {}
    except (OSError, ValueError):
        return {}


def quiet_runs(cost):
    """The longest each of a suite's last measured runs went without output, oldest first."""
    quiet = cost.get("quiet")
    return [seconds for seconds in quiet if type(seconds) in (int, float)
            and math.isfinite(seconds) and seconds >= 0] if isinstance(quiet, list) else []


def quiet_window(command, cwd, run_dir, silence):
    """The silence that stops `command` sooner than `silence`, at its suite's pace: three times
    the longest any of its last 20 measured runs went without output, five minutes at least,
    where that fits in `silence` twice.  A command or piece it stops goes once more, alone,
    with the rest of `silence` (`run_suite`, `run_done_when`): a hang waits no longer than one
    window did, and a quiet stretch the suite never had passes on that second go.  None where
    the suite has no such pace: `silence` holds, and its stop is final."""
    quiet = quiet_runs(read_suite_cost(suite_cost(command, cwd, run_dir)[0]))
    window = max(QUIET_FLOOR, QUIET_TIMES * max(quiet, default=0))
    return window if len(quiet) >= QUIET_RUNS and 2 * window <= silence else None


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
    command = gitcall.declared(Path.cwd(), "tests")
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
        handback.start_followups(lp.state, lp.run_dir, lp.log, lp.cfg,
                            split={"command": command, "text": text, "check": check,
                                   "cost": str(path)})
    except (config.Error, OSError, run_record.StopRequested) as exc:
        lp.log(f"WARN could not start the suite split: {exc}")


class _SuiteMeasure:
    """Wall time and each box's CPU work everywhere, a line's checker included; memory, less
    the file cache reclaim frees, where a cgroup is this run's or holds only this process."""

    def __init__(self, run_dir):
        state = run_record.read_state(run_dir) or {} if run_dir else {}
        self.run_id = state.get("run_id")
        relative = host.process_cgroup() if state.get("scope") else None
        self.group = (host.cgroup_path(relative) if relative and
                      Path(relative).name in turns._scope_units(state["scope"])
                      else host.own_cgroup())
        self.cpu = []     # each box's CPU seconds (`worker.boxed`)
        self.quiet = []   # and the longest each go went without output (`worker.limited`)
        self.baseline = host.held_mb(self.group) if self.group is not None else None
        self.peak = self.baseline
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def sample(self):
        if self.baseline is not None:
            held = host.held_mb(self.group)
            if held is not None:
                with self.lock:
                    self.peak = max(self.peak, held)

    def save(self, path, pieces):
        elapsed = time.monotonic() - self.started
        if elapsed <= 0:
            return
        cost = {"wall_seconds": elapsed, "run_id": self.run_id}
        if len(self.cpu) == pieces:
            cost["cpus"] = max(HEAVY_CPUS, sum(self.cpu) / (elapsed * pieces))
        if self.baseline is not None:
            cost["mem_mb"] = max(HEAVY_MEM_MB, (self.peak - self.baseline) / pieces)
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

    def paced(self, path, pieces):
        """Once each of a run's `pieces` ran to its end, the longest any of its goes went
        without output joins the suite's pace, a retry's too: a pace it outgrew retires."""
        if len(self.quiet) < pieces:
            return
        try:
            with watch.state_lock():
                quiet = quiet_runs(read_suite_cost(path)) + [max(self.quiet)]
                write_suite_cost(path, {"quiet": quiet[-QUIET_RUNS:]})
        except OSError:
            pass


def flaky_record(command, failed, rerun, log_path, run_dir, log, how="failed"):
    """Keep the whole failure, even when its distinguishing lines precede the output cap."""
    with tempfile.NamedTemporaryFile(dir=run_dir or log_path.parent,
                                     prefix=f"{log_path.stem}-failed-",
                                     suffix=".log", delete=False) as saved:
        saved.write(failed)
    lines = [line for line in failed.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    reran = {flaky_key(line) for line in rerun.decode("utf-8", errors="replace").splitlines()}
    diff = [line for line in lines if flaky_key(line) not in reran][:20]
    note = f"flaky: {command} {how}, then passed on its re-run"
    if log is not None:
        log(f"done-when: {note}")
    return "\n".join([note, f"failed output: {Path(saved.name).resolve()}", *diff])


def run_suite(command, limit, *, cwd, activity, output, run_dir=None, log=None,
              on_wait=None, measure=False, shard=None, pieces=None, later=None, only=None,
              confirmed=None, **kwargs):
    """One command, or all its opted-in pieces, with failed pieces retried alone.

    Callers keep one command and one outcome. Each piece has its own silence window;
    all attempts share the command's ceiling, and live output identifies its piece.
    A red piece that named its failed tests (`AK_FAILED`) retries just those first (`AK_ONLY`).
    With `shard` (`k/N`) one piece runs alone with that share set, as the lander probes the
    target's tip: on one turn, never split again, measuring nothing, its cost the suite's;
    with `only` too, just those of its tests, as one share, green only where the runner names
    each one as run (`AK_RAN`): a runner may skip a name it does not know and exit 0.
    `pieces`, a dict, gets each piece's exit as the runner saw it, by share -- None for one
    killed at the limit -- so a caller decides from codes, never from what a piece printed.
    `later`, seconds, is set where the suite's pace stops its pieces sooner (`quiet_window`):
    the silence each piece's later goes have; a piece its first go's silence stopped goes
    again, alone, after its siblings, which run on.
    `confirmed`, a dict, gets by share the tests a red piece named that failed again alone;
    with `shard` and `only`, those of them its run named both as run and as failed (`AK_FAILED`)
    where it ended in a failing exit: one dead by a signal, its exit negative, repeats nothing.
    """
    env = suite_env()
    if shard is not None:
        label, share = ((shard, shard) if only is None else
                        (f"{shard}, its failed tests alone", "1/1"))
        output.write(f"--- AK_SHARD={label} ---\n".encode())
        output.flush()
        ran, failed = (None, None) if only is None else ([], [])
        code, text, killed = worker.boxed(
            ["bash", "-c", command], limit, cwd=str(cwd), activity=activity, output=output,
            env={**env, "AK_SHARD": share}, only=only, ran=ran, failed=failed, **kwargs)
        if confirmed is not None and only is not None:
            confirmed[shard] = [test for test in only if code > 0 and test in ran and test in failed]
        if not code and ran is not None and (missing := [test for test in only if test not in ran]):
            output.write(f"[not named as run (AK_RAN): {' '.join(missing)}]\n".encode())
            code = 1
        if pieces is not None:
            pieces[shard] = None if killed else code
        return code, text, killed
    if not names_shard(command):
        path = suite_cost(command, cwd, run_dir)[0] if measure else None
        measured = _SuiteMeasure(run_dir) if measure else None
        aborting = kwargs.pop("abort", None)
        def abort():
            if measured:
                measured.sample()
            return aborting() if aborting else False
        result = worker.boxed(["bash", "-c", command], limit, cwd=str(cwd), activity=activity,
                              output=output, env=env, abort=abort,
                              cpu=measured.cpu if measured else None,
                              quiet=measured.quiet if measured else None, **kwargs)
        if measured and not result[2] and result[0] != SUITE_BUSY:
            measured.save(path, 1)
            measured.paced(path, 1)
        return result
    with gate_turn(run_dir, activity, log, command, cwd):
        hold = getattr(_GATE_HELD, "hold", None)
        away = getattr(_GATE_HELD, "away", None)
        path, cpu, mem = suite_cost(command, cwd, run_dir)
        count = away.count if away else len(hold.slots) if hold else derived_heavy_limit(
            running=0, job_cpus=cpu, job_mem_mb=mem, unit=True)
        env = suite_env()    # the piece threads do not inherit this thread's held turn
        deadline = time.monotonic() + limit
        cancel, writing = threading.Event(), threading.Lock()
        last_shard = None
        measure = _SuiteMeasure(run_dir)
        timeout = kwargs.pop("on_timeout", None)
        silence = kwargs.pop("silence", None)
        silenced = set()    # the pieces whose first go silence stopped, each to go again

        with ExitStack() as files:
            results = []
            def attempt(shard, only=None, first=False):
                """The piece of `shard`, or with `only` just those of its tests, as one share;
                a `first` go stopped for silence goes again where the suite has a pace."""
                run_record.stop_check(run_dir)
                piece = files.enter_context(tempfile.NamedTemporaryFile(
                    dir=activity.parent, prefix=f"{activity.stem}-piece-", suffix=".log"))
                label = shard if only is None else f"{shard}, its failed tests alone"
                header = f"--- AK_SHARD={label} ---\n".encode()

                class Output:
                    def __init__(self):
                        self.pending = b""

                    def emit(self, data):
                        nonlocal last_shard
                        output.write((header if last_shard != label else b"") + data)
                        output.flush()
                        last_shard = label

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
                    if why == "silence" and first and later:
                        silenced.add(shard)     # its siblings run on; it goes again after them
                    elif why != "abort":
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
                    return worker.TIMEOUT, piece, True, []
                stream, tests = Output(), []
                own = {**env, "AK_SHARD": shard if only is None else "1/1"}
                if own.get(worker.RUN_MARKER):
                    # A stop ends this piece's own processes, never a sibling's that runs on.
                    own[worker.RUN_MARKER] += f"/piece-{shard.replace('/', '-')}"
                try:
                    here = {} if away else {"cpu": measure.cpu, "quiet": measure.quiet,
                                            "only": only, "failed": tests}
                    code, _, killed = (worker.limited if away else worker.boxed)(
                        helper.piece(away, shard, PINNED_PIECE.format(shlex.quote(command)))
                        if away else ["bash", "-c", command],
                        left, cwd=str(cwd), activity=Path(piece.name), output=stream,
                        env=own, abort=abort,
                        on_timeout=stopped, silence=silence if first else later or silence,
                        **here, **kwargs)
                finally:
                    stream.finish()
                return code, piece, killed, tests

            def attempts(which, width, first=False):
                with ThreadPoolExecutor(max_workers=width) as pool:
                    try:
                        futures = [pool.submit(attempt, f"{index + 1}/{count}", first=first)
                                   for index in which]
                        for index, future in zip(which, futures):
                            results[index] = future.result()
                    except BaseException:
                        cancel.set()
                        raise

            results = [None] * count
            attempts(range(count), count, first=True)
            if not away and not any(killed or code == SUITE_BUSY for code, _, killed, _ in results):
                measure.save(path, count)
            again = [index for index, (code, _, killed, _) in enumerate(results)
                     if away and code and not killed and not cancel.is_set()]
            helped, away = away, None
            if helped and any(code == helper.SHORT for code, *_ in results):
                least = helper.short(helped)
                if log is not None:
                    log(f"the suite helper's VMs of {helped.memory_mb} MiB ran out of memory: "
                        f"its next VMs get {least} MiB")
            if helped and log is not None:
                # Without these a suite the helper lost reads as one it ran.
                for index in again:
                    if results[index][0] == helper.LOST:
                        log(f"the suite helper lost AK_SHARD={index + 1}/{count}; it runs here")
                if not any(code or killed for code, _, killed, _ in results):
                    log(f"every piece passed on the suite helper {helped.alias}")
            if again or helped and silenced and not cancel.is_set():
                # What the helper lost, failed, ran out of memory for or stopped runs again
                # here, on this host's own turns; a stopped piece alone, below.
                for index in (index for index in again
                              if results[index][0] not in (helper.LOST, helper.SHORT)):
                    if log is not None:
                        # its go here takes its place in the suite's output: a copy keeps this one
                        handle, kept = tempfile.mkstemp(dir=run_dir or activity.parent,
                                                        prefix=f"{activity.stem}-helper-failed-",
                                                        suffix=".log")
                        os.close(handle)
                        shutil.copyfile(results[index][1].name, kept)
                        log(f"WARN AK_SHARD={index + 1}/{count} failed on the suite helper; "
                            f"what it printed there: {kept}")
                began = time.monotonic()
                hold = _GATE_HELD.hold = _GATE_HELD.home()
                queued = time.monotonic() - began    # as busy_turn's: no ceiling is charged
                deadline += queued
                if on_wait is not None:
                    on_wait(queued)
                env = suite_env()
                if again:
                    attempts(again, len(hold.slots) if hold else len(again))
            hold = getattr(_GATE_HELD, "hold", None)
            if hold is not None:
                hold.alone()
            chunks, red, flakes = [], [], []
            for index, (code, piece, killed, tests) in enumerate(results, 1):
                shard = f"{index}/{count}"
                failed = only = alone = None
                how = "failed"
                if shard in silenced and not cancel.is_set():
                    # stopped at its suite's pace: once more alone, with the rest of the limit
                    piece.seek(0)
                    failed, how = piece.read(), f"was stopped after {silence / 60:g} min of silence"
                    code, piece, killed, tests = attempt(shard)
                while not killed and not cancel.is_set():
                    if code == SUITE_BUSY:
                        queued = busy_turn(run_dir, activity, log, command, cwd)
                        deadline += queued
                        if on_wait is not None:
                            on_wait(queued)
                        hold = getattr(_GATE_HELD, "hold", None)
                        if hold is not None:
                            hold.alone()
                        env = suite_env()
                    elif only is not None:
                        # Failing again alone, the tests the piece named confirm it red in a
                        # fraction of its time; passing, the whole piece decides, as a failure
                        # can need the tests that ran before it.
                        alone = ("its failed tests failed again, run alone" if code else
                                 "its failed tests passed run alone: the failure needs the "
                                 "tests that ran before them")
                        if code:
                            if confirmed is not None:
                                confirmed[shard] = tests
                            break
                        only = None
                    elif not code:
                        break
                    elif failed is None:
                        piece.seek(0)
                        failed = piece.read()
                        only = tests or None
                    else:
                        break
                    code, piece, killed, tests = attempt(shard, only)
                if failed is not None and code == 0:
                    piece.seek(0)
                    flakes.append(flaky_record(f"{command} (AK_SHARD={shard})", failed,
                                               piece.read(), activity, run_dir, log, how))
                results[index - 1] = code, piece, killed, tests
                text = turns.cut_file(piece, 0, run_dir or activity.parent,
                                      f"{activity.stem}-AK_SHARD-{shard.replace('/', '-of-')}")
                if code and not killed and alone:
                    text = f"{alone}\n{text}"
                # Existing failure diagnostics read the last output; leave a red piece last.
                (red if code else chunks).append(f"--- AK_SHARD={shard} ---\n"
                    f"[{'killed at the limit' if killed else f'exit {code}'}]\n{text}".rstrip())
            if not helped and not any(killed for _, _, killed, _ in results):
                measure.paced(path, count)
            text = "\n\n".join(chunks + red + flakes)
            output.write(("\n" + text + "\n").encode())
            output.flush()
            if pieces is not None:
                pieces.update({f"{index}/{count}": None if killed else code
                               for index, (code, _, killed, _) in enumerate(results, 1)})
            return next((code for code, _, _, _ in results if code), 0), text, any(
                killed for _, _, killed, _ in results)


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
                  run_dir=None, heavy=False, marks=None, shard=None, pieces=None, only=None,
                  confirmed=None):
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

    `marks`, a list, gets each command's exit as the runner saw it, in order -- None for one
    killed at the limit or never run, and none for those after a kill: what decides a proof,
    never the text, which a command can print anything into.  `pieces`, a dict, gets the same
    for each sharded command's pieces, by command then share (`run_suite`); `shard` runs
    every command as that one piece alone, a command like any other, its re-run included,
    and with `only` just those of its tests.  `confirmed`, a dict, gets by command what
    `run_suite` confirms: the tests a red piece named that failed again alone.
    """
    limit = 3600 * run_record.CEILING_HOURS if limit is None else limit
    silence = 60 * run_record.SILENCE_MINUTES if silence is None else silence
    before = set(gitcall.dirty_paths(cwd))
    chunks, ok = [], True
    spent, killed, kept = None, False, ""   # the command the limit ran out on, whether it had
                                            # begun, and the output it had produced by then
    reason, running = [], []

    def stopped(why, pid):
        reason.append(why)
        running.extend(_running_commands(pid))

    # a command run as one piece is the one command it is: its output read and re-run as any
    split = names_shard if shard is None else lambda _: False
    suite = next((cmd for cmd in cmds if split(cmd)), None)
    with gate_turn(run_dir, log_path, log, suite, cwd) if heavy or suite else nullcontext():
        deadline = time.monotonic() + limit
        def waited(seconds):
            nonlocal deadline
            deadline += seconds
        log_path.write_text("")
        for cmd in cmds:
            first_span = None   # the gate log's byte span of a first run that failed, while its
                                # re-run decides: the flaky diff reads whole runs
            busy = False
            # stopped sooner at its suite's pace on its first go; a second has the rest
            window = quiet_window(cmd, cwd, run_dir, silence) if heavy else None
            rest = silence - (window or 0)
            how = "failed"
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
                        cmd, left, activity=log_path, later=window and rest,
                        silence=rest if first_span is not None else window or silence,
                        on_timeout=stopped, cwd=str(cwd), output=progress,
                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                        run_dir=run_dir, log=log, on_wait=waited, measure=heavy, shard=shard,
                        pieces=None if pieces is None else pieces.setdefault(cmd, {}),
                        only=only,
                        confirmed=None if confirmed is None else confirmed.setdefault(cmd, {}))
                    end = progress.tell()
                if log is not None and run_dir is not None:
                    turns.memory_cap_note(run_dir, log)
                if heavy and code == SUITE_BUSY and not killed:
                    if log is not None and not busy:
                        log(f"done-when: busy: {cmd} exited {SUITE_BUSY}; it runs again "
                            "each poll, its heavy suite turn given back meanwhile")
                    busy = True
                    deadline += busy_turn(run_dir, log_path, log)
                    continue
                if code == 0 or first_span is not None or split(cmd):
                    break
                if killed:
                    if not window or reason[-1:] != ["silence"]:
                        break
                    how = f"was stopped after {window / 60:g} min of silence"
                    del reason[:], running[:]     # a stop of its second go is the one to name
                first_span = (offset, end)
            if left <= 0 and first_span is None:
                # the list is out of time: starting this command would give it a limit of its own
                spent, killed, kept = cmd, False, ""
                chunks.append(f"$ {cmd}\n[not run: the done-when limit was already spent]")
                if marks is not None:
                    marks.append(None)
                break
            ok &= code == 0
            if marks is not None:
                marks.append(None if killed else code)
            if split(cmd):
                out = piece_text
            else:
                with log_path.open("rb") as progress:
                    out = turns.cut_file(progress, offset, run_dir or log_path.parent,
                                         log_path.stem)
            chunks.append(f"$ {cmd}\n[{'killed at the limit' if killed else f'exit {code}'}]\n"
                          f"{out}".rstrip())
            if first_span is not None and code == 0:
                # blank lines dropped: a record is what lies between two, and these are one
                # both runs read whole from the gate log: the capped `out` starts mid-output
                # on a chatty suite, which hides a failure above the cap and frames shared
                # lines the re-run's own window dropped as lines it never printed
                with log_path.open("rb") as progress:
                    progress.seek(first_span[0])
                    failed = progress.read(first_span[1] - first_span[0])
                    progress.seek(offset)
                    rerun = progress.read(end - offset)
                chunks.append(flaky_record(cmd, failed, rerun, log_path, run_dir, log, how))
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
            cause = (f"{limit / 3600:g}h ceiling" if not reason or reason[0] != "silence" else
                     f"{silence / 60:g} min of silence" if not window else
                     f"{rest / 60:g} min of silence on its second go "
                     f"({window / 60:g} on its first, at its suite's pace)")
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
    worker.kill_marked(gitcall.run_child_env().get(worker.RUN_MARKER), log=log)
    artifacts.update(set(gitcall.dirty_paths(cwd)) - before)
    return ok, text


def turn_held():
    """Whether this thread holds a heavy-suite turn, including a directly acquired hold."""
    return bool(getattr(_GATE_HELD, "count", 0))


def release_turn():
    """Let this thread's turn go so the next check takes a fresh one."""
    hold, _GATE_HELD.hold = getattr(_GATE_HELD, "hold", None), None
    if hold is not None:
        hold.release()
