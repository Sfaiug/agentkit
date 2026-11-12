"""Run admission, check commands and the host-wide heavy-suite turn."""

import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, gitcall, handback, helper, history, host, orch, stuck, suite_times
from . import transitions, turns
from . import update
from . import waiter
from . import watch
from . import worker
from . import land as landing
from . import record as run_record

_GATE_HELD = threading.local()     # the gate turn this thread holds now, if any


try:
    SLOT_POLL = float(os.environ.get("AK_SLOT_POLL", "30"))
except ValueError:
    SLOT_POLL = 30
STARTING = 6 * SLOT_POLL    # seconds past launching a worker that a run counts what it may grow by


GATE_POLL = 15      # seconds between a waiting gate's tries for a turn; each rewrites its log line
HEAVY_CPUS = 0.7      # initial measured estimates; a repository's pieces may cost more
HEAVY_MEM_MB = 410
SUITE_BUSY = 75       # sysexits' EX_TEMPFAIL: a heavy suite's own host-wide lock is another copy's
ASKING = "ak-asks-the-suite-helper"    # a suite's late question to it, which nothing joins
OUT_OF_MEMORY = "ran out of memory"   # `run_suite(pieces=)`: no exit tells it (`_SuiteMeasure.starved`)
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
    # A green member only needs delivery before the target moves.
    # Finished work precedes fresh launches without joining the first element's gate bypass:
    # a later round, and an orchestrator's own PR, whose build is done before its first review.
    # A held install's fix (`update.first_place`) is admitted as `--first` is.
    wait = state.get("waiting_on") or {}
    return (not (state.get("first") or "land" in wait or "fix" in wait
                 or update.first_place(state)),
            not landing.green_delivery(wait),
            not (state.get("round_summaries") or state.get("own_pr")),
            transitions.first_queued(state),
            state.get("run_id") or "")


def _slot_seat(state):
    seat = state.get("launched_session") or ""
    # A run launched from no seat must not share a turn with a seat named after that run.
    return (*slot_order(state)[:3], seat, "" if seat else state.get("run_id") or "")


# Memory is what admission guards: CPU is shared, and a check given less of it only runs
# slower, while the heavy-suite turns and the line's CPU weights pace the CPU-heavy work.
MEMORY_PRESSURE_LIMIT = 10   # runs stalled on memory a tenth of the time


def resource_limits(readings):
    """Resolve configured gates against one host-reading snapshot."""
    total = host._reading(readings, "mem_total_mb", "total_mb", "mem_total")
    cpus = host._reading(readings, "cpus", "nproc") or 1
    return config.min_free_mb(total if total is not None else 0), config.max_load(cpus)


def _load(value):
    return "?" if value is None else f"{value:g}"


def _run_readings():
    return host.host_readings(slice_dir=orch.slice_cgroup, cpu_dir=orch.run_slice_cgroup)


def host_status_line():
    """The host-admission header at the top of human ``ak run status`` output.

    Two lines: the admission gates, then the heavy-suite turns in force and whether
    an explicit `max_gates` pins them or the slice's headroom derives them.  A
    positive `max_runs` is a gate like the others, so the first line names it:
    `at most 4 runs at once`.  Only a pinned `max_load` gates CPU, so only it shows the load.
    """
    readings = _run_readings()
    minimum, maximum = resource_limits(readings)
    cpus = host._reading(readings, "cpus", "nproc") or 1
    gates, signal = [], ""
    if minimum:
        gates.append(f"≥ {host._g(minimum)} G free")
    if config.max_load_is_set():
        if maximum:
            gates.append(f"load ≤ {_load(maximum)}")
        signal = f" · load {_load(host._reading(readings, 'load', 'load1'))}"
    admitted = ("a run is admitted while " + " and ".join(gates) if gates else
                "a run is admitted (host memory and load gates off)")
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
        segment = f" · {unit[3]} {host._g(unit[0])} of {host._g(unit[1])} G in use{_in_swap(unit)}"
    ours, name = host._slice_or_unit_memory(readings), orch.slice_cgroup().name
    # From a shell outside it, ak's slice is not the unit above, yet its swap is what a wait names.
    if ours and ours[4] and ours != unit and not (unit and unit[3] == name):
        segment += f" · {name} {host._g(ours[0])} of {host._g(ours[1])} G in use{_in_swap(ours)}"
    first = (f"host: {int(cpus)} cpus{signal} · "
             f"{host._g(host._reading(readings, 'free_mb', 'mem_available_mb'))} G free{segment} · "
             f"{admitted}")
    return f"{first}\n{heavy}"


def slot_place(state):
    """`holding` for a top-level run holding its slot, `waiting` for one waiting for it, a dead
    waiter included, which the tick resumes; else None."""
    if state.get("run_depth", 0):
        return None
    if state.get("state") == "running" and run_record.process_active(state):
        return "holding"
    if state.get("state") == "queued" and state.get("slot_waiting"):
        return "waiting"
    return None


def slot_counts(state, *, remember=False):
    """Live slot owners, top-level receipts ahead of this one (including dead waiters), and
    the other waiters' run ids in queue order. Under slot_lock, `remember` saves the queue."""
    running, waiting = 0, [state]
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if other.get("run_id") == state.get("run_id"):
            continue
        place = slot_place(other)
        if place == "holding":
            running += 1
        elif place == "waiting":
            waiting.append(other)
    previous, batches = slot_queue()[5], {}
    for other in waiting:
        batches.setdefault(_slot_seat(other), []).append(other.get("run_id") or "")
    turns, floor = {}, {}
    for seat, pending in batches.items():
        count, before = previous.get(seat, (0, []))
        if set(pending).intersection(before):
            turns[seat] = (count, pending)
            floor[seat[:3]] = max(count, floor.get(seat[:3], 0))
    # A new batch joins the back of its priority's round, level with the seat served most. From
    # 0, or level with the least, it went ahead of every seat still working down an older batch:
    # one whose backlog outlived the other seats' batches got no slot for four days while they
    # took about 300.
    for seat, pending in batches.items():
        turns.setdefault(seat, (floor.get(seat[:3], 0), pending))
    seats, orders = {seat: turn[0] for seat, turn in turns.items()}, []
    for other in sorted(waiting, key=slot_order):
        order = slot_order(other)
        seat = _slot_seat(other)
        rank = seats.get(seat, 0)
        seats[seat] = rank + 1
        orders.append((*order[:3], rank, *order[3:]))
    queue = [order[-1] for order in sorted(orders)]
    ahead = queue.index(state.get("run_id") or "")
    if remember:
        _save_queue(running, queue, turns=turns)
    return running, ahead, queue[:ahead] + queue[ahead + 1:]


def seat_full(seat, launches):
    """Why that seat may not launch that many more runs, or None: a seat may have as many runs
    waiting for a slot as holding one (`slot_place`), and always one, and each launch waits until
    it holds one.  Seats launched everything at once, so the queue outgrew what the host could
    check and a seat's urgent work sat behind its own; a host admitting more runs lets more wait.
    The reason names the run to `ak wait` for: the one that has held its slot longest, else the
    oldest waiting."""
    holding, waiting = [], []
    records = ((directory, run_record.read_state(directory) or {})
               for directory in run_record.run_dirs())
    for directory, other in transitions.runs_by_seat(records).get(seat, []):
        place = slot_place(other)
        if place == "holding":
            holding.append((other.get("slot_started_at") or 0, directory.name))
        elif place == "waiting":
            waiting.append((transitions.first_queued(other), directory.name))
    room = max(len(holding), 1) - len(waiting)
    if launches <= room:
        return None
    first = min(holding or waiting, default=None)
    return (f"{seat} may have as many runs waiting for a slot as holding one, and always one: "
            f"it has {len(waiting)} waiting and {len(holding)} holding, so room for "
            f"{max(room, 0)} more, not {launches}; "
            + (f"`ak wait {first[1]}`, then launch again" if first else "launch one at a time"))


def _save_queue(running, queue, let_in=None, turns=None):
    """Under slot_lock: the queue as this poll decided it, for the waiters behind its first,
    since when that first has waited there while polled (`first_in_line`), how long the last
    20 firsts waited there before they were let in (`let_in`, the state this poll lets in), kept
    across gaps in the polling, and when the last run went in."""
    path, now = config.RUNS / ".slots.queue", time.time()
    waits, saved = first_in_line(now), slot_queue()
    took = saved[4]
    turns = saved[5] if turns is None else turns
    # Only admissions consume turns, and only while that seat's batch still has waiters.
    if let_in:
        seat = _slot_seat(let_in)
        count, pending = turns.get(seat, (0, []))
        turns[seat] = (count + 1, pending)
    # A stall's wait is no pace: counted, each one let in would raise the next one's bar.
    if waits and let_in and let_in.get("run_id") == waits[0] and not let_in.get("slot_stall"):
        took = [*took, now - waits[1]][-20:]
    since = waits[1] if waits and queue[:1] == [waits[0]] else now
    remaining = set(queue)
    turns = {seat: (count, [run_id for run_id in pending if run_id in remaining])
             for seat, (count, pending) in turns.items()}
    temp = path.with_name(".slots.queue.tmp")
    temp.write_text(json.dumps({"at": now, "running": running, "queue": queue, "since": since,
                                "took": took, "last_in": now if let_in else saved[6],
                                "turns": [[*seat, count, pending]
                                          for seat, (count, pending) in turns.items() if pending]}))
    temp.replace(path)


def slot_queue():
    """(when, live slot owners, waiting run ids first in line first, since when that first has
    waited there, the waits there of the last firsts let in, admitted turns and remaining
    waiters by seat, when the last run went in) as the last poll left them."""
    try:
        saved = json.loads((config.RUNS / ".slots.queue").read_text())
        return (float(saved["at"]), int(saved["running"]),
                [str(run_id) for run_id in saved["queue"]], float(saved.get("since") or 0),
                [float(wait) for wait in saved.get("took") or []],
                {tuple(turn[:-2]): (int(turn[-2]), tuple(turn[-1]))
                 for turn in saved.get("turns", []) if len(turn) == 7},
                float(saved.get("last_in") or 0))
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0, 0, [], 0.0, [], {}, 0.0


def first_in_line(now):
    """(the run first in line for a slot, since when it has waited there, how many wait behind
    it, the waits there of the last firsts let in) while a poll rewrote the queue within three
    of the last in line counting it again (`waiter.stale_after`), for `stuck`; after a gap, a new
    wait.  A poll newer than `now`, one that ran while the caller read, is the same wait."""
    at, _, queue, since, took, *_ = slot_queue()
    if queue and since and now - at < waiter.stale_after(len(queue) - 1, SLOT_POLL) + 3 * SLOT_POLL:
        return queue[0], since, len(queue) - 1, took
    return None


def behind_first(run_id):
    """Whether the queue still has this run waiting behind its first (`waiter.behind_first`).

    Such a run skips its poll: it reads no record and takes no lock.
    """
    return waiter.behind_first(config.RUNS / ".slots.queue", run_id, time.time(), SLOT_POLL)


def _holders(state):
    """The records of the other runs holding a slot (`slot_place`)."""
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if other.get("run_id") != state.get("run_id") and slot_place(other) == "holding":
            yield other


def frozen_runs(state):
    """Admitted runs the host has frozen: slot owners whose process is held.

    A frozen run adds no load, so the load gate keeps refilling behind it and the
    thaw lands every run at once. The same owners slot_counts counts, asked of the
    process itself, so a dead run and a reused pid count nothing.
    """
    return sum(1 for other in _holders(state) if host.frozen_cgroup(other.get("pid")))


def _shows_nothing_yet(run):
    """Has `run` launched no worker since it went in, or its last under `STARTING` ago?  Peaks
    settled within 110 s on 2 Nov 2026; then the readings show what it holds.  A turn on a rented
    machine holds 43 MiB here: counted to a median of 763 for life, 9 such held 22 runs in line."""
    try:
        at = (config.RUNS / str(run.get("run_id")) / worker.LAUNCHED).stat().st_mtime
    except OSError:
        return True
    return at < (run.get("slot_started_at") or 0) or time.time() - at < STARTING


def _starting(state, peak):
    """(MB, runs): what the runs holding a slot that show nothing yet may still grow by, a recent
    run's median `peak` less each one's own peak so far, never below 0, and how many may still."""
    holders = [other.get("run_id") for other in _holders(state) if _shows_nothing_yet(other)]
    so_far = history.peaks_so_far(holders)
    growth = [peak - (so_far.get(run_id) or 0) for run_id in holders]
    return sum(mb for mb in growth if mb > 0), sum(mb > 0 for mb in growth)


def _still(starting):
    """`, N starting runs may take M G more` while some may, else ""."""
    mb, runs = starting
    return (f", {runs} starting run{'s' if runs != 1 else ''} may take {host._g(mb)} G more"
            if runs else "")


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


def _in_swap(memory):
    """` · N G in swap` for a (used, high, raw, name, swap) reading holding swap, else ""."""
    return f" · {host._g(memory[4])} G in swap" if memory and memory[4] else ""


def _free_reason(readings, minimum, starting=(0, 0)):
    free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
    if minimum and free is not None and free - starting[0] < minimum:
        return (f"waiting for memory · {host._g(free)} G free{_still(starting)}, "
                f"needs {host._g(minimum)} G", "memory")
    return None, None


def _memory_pressure_reason(readings):
    pressure = host._reading(readings, "slice_memory_pressure")
    if pressure is not None and pressure > MEMORY_PRESSURE_LIMIT:
        return (f"waiting for ak's memory · pressure {pressure:g}%, limit {MEMORY_PRESSURE_LIMIT}%"
                f"{_in_swap(host._slice_or_unit_memory(readings))}", "unit memory")
    return None, None


def _strain(readings, minimum):
    """(reason, kind) while the host really strains, else (None, None): its available memory or
    the kernel's own stall readings, all that holds a run stalled first in line."""
    for reason, kind in (_free_reason(readings, minimum), _memory_pressure_reason(readings)):
        if reason:
            return reason, kind
    return None, None


def _wait_reason(readings, minimum, maximum, peak=None, frozen=0, starting=(0, 0)):
    # An unreadable gate fails open, as the memory check before it did: a host
    # that cannot answer (no /proc on macOS, no cgroup file in a container)
    # must not queue every run forever.  `starting` is what runs let in may still take
    # (`_starting`), counted against both memory gates.
    reason, kind = _free_reason(readings, minimum, starting)
    if reason:
        return reason, kind
    load = host._reading(readings, "load", "load1", "load_1m")
    if maximum and load is not None and load + frozen > maximum:
        if frozen:
            noun = "run" if frozen == 1 else "runs"
            return (f"waiting for the host to calm · load {_load(load)} + {frozen} "
                    f"frozen {noun}, limit {_load(maximum)}", "load")
        return f"waiting for the host to calm · load {_load(load)}, limit {_load(maximum)}", "load"
    reason, kind = _memory_pressure_reason(readings)
    if reason:
        return reason, kind
    unit = host._slice_or_unit_memory(readings)
    # The runs' swap past the slice's allowance takes room, as runs paging their test pieces
    # ran away (24 Oct 2026); seats' swap is bounded by their own caps and never holds a run.
    runs_swap = host._reading(readings, "runs_memory_swap_mb") or 0.0
    used = unit[0] + max(0.0, runs_swap - host.swap_allowance_mb(unit[1])) if unit else None
    if unit and peak is not None:
        room = unit[1] - used
        if room - starting[0] < peak:
            return (f"waiting for the unit's memory · {host._g(room)} G left{_still(starting)}, "
                    f"a run needs {host._g(peak)} G{_in_swap(unit)}", "unit memory")
    elif unit and used > unit[1] * .75:
        raw = unit[2]
        if raw is not None:
            return (f"waiting for the unit's memory · {host._g(used)} of {host._g(unit[1])} G "
                    f"in use ({host._g(raw)} with cache){_in_swap(unit)}", "unit memory")
        return (f"waiting for the unit's memory · {host._g(used)} of {host._g(unit[1])} G"
                f"{_in_swap(unit)}", "unit memory")
    return None, None


def _host_admits(state, readings, is_first):
    """The host gates (`_gates_admit`): False, the wait written on `state`, while one holds.

    A run stalled first in line (`stuck.slot_stall`) goes past every gate but the host's strain
    (`_strain`), `slot_stall` naming the one it went past: the gates derived from those readings
    were retuned again and again, and one held every run for 22 hours of a calm host."""
    readings = _run_readings() if readings is None else readings
    # Judged when this poll saved the queue, under the same lock (`claim_slot`): a pause since
    # is no gap in its polling, and judged later it read as one.
    if stuck.slot_stall(slot_queue()[0]) != state.get("run_id"):
        return _gates_admit(state, readings, is_first)
    reason, kind = _strain(readings, resource_limits(readings)[0])
    if reason:
        return _held(state, reason, kind)
    if not _gates_admit(state, readings, is_first):
        state["slot_stall"] = f"went in on a stall, past: {state['slot_wait_reason']}"
    return True


def _held(state, reason, kind):
    state["slot_waited"] = True
    state["slot_wait_reason"], state["slot_wait_kind"] = reason, kind
    return False


def _gates_admit(state, readings, is_first):
    """The host gates, with what runs let in may still take counted against memory: readings
    lag what a run just let in will use (30 Oct 2026: 43 at once hit the process limit).  With
    nothing measured to count, a run waits a poll after the last let in instead."""
    minimum, maximum = resource_limits(readings)
    if is_first:
        maximum = 0
    peak = history.recent_peak_rss_mb()
    starting = (0, 0) if peak is None else _starting(state, peak)
    pinned = config.max_load_is_set()
    if pinned:
        frozen = 0
        load = host._reading(readings, "load", "load1", "load_1m")
        if maximum and load is not None and load <= maximum:
            # A frozen run adds no load, so the gate reads low behind it; each one
            # counts 1 against the limit. Counted only while the load alone passes:
            # past the limit the wait says so already, and no cgroup is read.
            frozen = frozen_runs(state)
        reason, kind = _wait_reason(readings, minimum, maximum, peak, frozen, starting)
    else:
        reason, kind = _wait_reason(readings, minimum, 0, peak, starting=starting)
    if reason:
        return _held(state, reason, kind)
    if peak is None and 0 <= time.time() - slot_queue()[6] < SLOT_POLL:
        # Named with the readings behind it, rather than the count sentence nothing waits on.
        # The kind stays whatever gate (if any) actually delayed this wait.
        free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
        state["slot_wait_reason"] = f"waiting for steady readings · {host._g(free)} G free"
        if pinned:
            load = host._reading(readings, "load", "load1", "load_1m")
            state["slot_wait_reason"] += f", load {_load(load)}"
        return False
    return True


def claim_slot(state, limit, readings=None, launch=False):
    """Called under slot_lock: count, seat turns and the host gates decide admission.  A gated
    `launch` only records why it waits: its waiter owns the start."""
    # AK_MAX_RUNS=0 is the test-suite escape hatch: it disables count and host gates together.
    ungated = os.environ.get("AK_MAX_RUNS") == "0"
    running, ahead, others = slot_counts(state, remember=not (state.get("run_depth", 0) or ungated))
    if state.get("run_depth", 0) or ungated:
        state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                     **run_record.process_owner())
        state.pop("resume_from", None)
        return True
    is_first = not slot_order(state)[0]
    # A green delivery only merges a tree its line already checked: it spends no headroom a
    # gate guards, every member behind it in the line waits on it, and the queue's one admission
    # a poll has nothing to pace for it: 47 taking turns there held every other run back for half
    # an hour (30 Oct 2026). Who merges next is the line's order (`deliver.merge_lock`).
    green = landing.green_delivery(state.get("waiting_on") or {})
    if (ahead and not green) or (limit and running >= limit and not is_first):
        state["slot_waited"] = True
        state["slot_wait_reason"] = slot_line(running, ahead, limit, is_first)
        state["slot_wait_kind"] = "count"
        return False
    state.pop("slot_stall", None)
    if (not green and not _host_admits(state, readings, is_first)) or launch:
        return False
    _save_queue(running + 1, others, let_in=state)
    state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                 **run_record.process_owner())
    for key in ("resume_from", "reservation_pending",
                "slot_wait_reason", "slot_wait_kind"):
        state.pop(key, None)
    return True


def count_wait(run_id, wait, counted, *, kind=""):
    """Add what this process waited since `counted` to its run's history; returns it moved to now.

    `counted` is the wait's start on the wall clock, which keys its one phase row, and the
    monotonic time it is counted up to.  The waiting process counts its own wait as it polls,
    so one that dies loses at most a poll, and no recovery can count time no process spent
    waiting -- nor a clock correction.
    `kind` comes from the last poll's record, so counting opens no run.json behind the first.
    """
    began, since = counted
    now = time.monotonic()
    history.add_wait(run_id, wait, now - since, began=began, kind=kind)
    return began, now


def wait_for_slot(run_dir, between=None):
    """Reserve a slot in run.json before work starts; no process-local semaphore can do this.

    `between` runs after each poll's wait, while the wait holds nothing, with the wait counted
    so far where this run waits behind the first: it may replace this process with the same
    launch on newer code, or with a waiter that execs that launch back (`run.pickup_while_queued`),
    which counts as it waits and hands the count back (`waiter.SLOT_WAIT_ENV`)."""
    first_poll = True
    handed = os.environ.pop(waiter.SLOT_WAIT_ENV, "").split()
    # back from the waiter: it waited behind the first, uncounted since `counted`
    behind = len(handed) == 2
    # and it announced this wait before it went there, so its log and its seat's bar say it
    # already: every waiter comes back when the install moves, and a bar job is a whole ak
    announced = behind
    wait_kind = None
    counted = tuple(map(float, handed)) if behind else None
    if behind and between is not None and behind_first(run_dir.name):
        # back only as the install moved: back to the waiter, or every waiter polls under the lock
        between(counted)
    while True:
        if not first_poll:
            counted = counted or (time.time(), time.monotonic())
            time.sleep(SLOT_POLL)
            counted = count_wait(run_dir.name, "slot", counted, kind="count" if behind else wait_kind or "")
            waiting_behind = behind_first(run_dir.name)
            if between is not None:
                between(counted if waiting_behind else None)
            if waiting_behind:
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
                # The polls it skipped were count waits.
                state.update(slot_waited=True, slot_wait_kind="count")
                wait_kind = "count"
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
        count_wait(run_dir.name, "slot", counted, kind=wait_kind or "")
    if state.get("slot_waited"):
        minutes = max(0, int((time.time() - state["queued_at"]) / 60))
        kind = wait_kind or "count"
        stall = f" · {state['slot_stall']}" if state.get("slot_stall") else ""
        line = f"waited {minutes} min for a slot ({kind}){stall}\n"
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


def _heavy_held():
    """What one piece of each held turn's holder costs (`_held_cost`), including high slots left
    by a larger limit.

    Slot files persist after their suites finish; only a lock still held counts.
    Probe existing files without creating any, so status never grows the pool.
    """
    held = []
    with _place_costs():
        for index in range(_heavy_max_existing() + 1):
            path = gate_lock(None, index)
            try:
                with path.open("r") as slot:
                    try:
                        fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        held.append(_held_cost(path))
            except OSError:
                pass
    return held


@contextmanager
def _place_costs():
    """Held host-wide while a check reads what held turns cost, or takes turns and says what they
    cost (`_say_cost`): a turn taken but not yet said would read as one on older code, at the
    reader's cost, and a check reading it admitted 11 places on 8 cores beside 4 at 2 cores."""
    config.RUNS.mkdir(parents=True, exist_ok=True)
    with (config.RUNS / ".heavy-costs").open("a") as costs:
        fcntl.flock(costs, fcntl.LOCK_EX)
        yield


def _say_cost(slot, cost):
    """Write `cost`, (cpus, mem_mb) of one piece run on the held turn `slot`, into its lock file,
    inside `_place_costs`.

    Each holder writes on taking a turn and only a held turn is read: the lock says whether its
    holder lives, the text what it costs.  A failed write costs the count's accuracy, never the
    check.
    """
    try:
        slot.truncate(0)
        slot.write(json.dumps(dict(zip(("cpus", "mem_mb"), cost))))
        slot.flush()
    except OSError:
        pass


def _held_cost(path):
    """What one piece of the holder of the turn at `path` costs (`_say_cost`), or None where the
    file says nothing: a holder on code from before 11 Nov 2026."""
    said = read_suite_cost(Path(path))
    cost = (said.get("cpus"), said.get("mem_mb"))
    return cost if all(map(_a_cost, cost)) else None


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


def mark_gate_wait(run_dir, of, since=None):
    """Put `waiting for a heavy suite turn` on the record, or take it off (`of` None).

    `of` is the repository the waiter checks, kept on the mark from the
    per-repository turns; the note and the rank are host-wide and ignore it.  With
    this process's pid and the wait's start, so a
    freed turn goes to the round check that has waited longest.  A landing run's mark
    says so, and its wait's file ranks it (`landing_wait`); the start of its first
    landing wait lives beside the record, where
    whole-record saves cannot wipe it (see `_first_landing_wait`): that start is
    what this returns for a lander, the wait's own start otherwise, and None when
    it recorded none.  A suite whose pieces wait for more turns passes the `since` it
    was admitted at, so it keeps its place.
    """
    since = since or time.time()
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
def landing_wait(landing, since=None, run_id=None, line=False, holds=None):
    """While a landing suite waits for a heavy turn it holds a file of its own, and a line's
    check also `.heavy-landing.wait`.

    Its own file says when its wait began, for which run, whether it is a line's own
    check and whether its check `holds` a turn already, so landing waits rank among themselves
    (`_gate_waiter_before`); None says nothing of turns held, as a file from before 12 Nov 2026
    does.  A wait for a first turn holds none and a suite's for more always holds one, so what
    the file says stays true for as long as it lives.  The line's checkers
    mark no member's record.  `.heavy-landing.wait`, shared by every line's check, says one
    waits: round checks stay behind it (`landing_waits`), as they do behind a waiter on code from
    before 29 Oct 2026, which holds it for any landing wait.  The kernel lets go with the
    holder, so a dead waiter holds nobody back.
    """
    if not landing:
        yield
        return
    config.RUNS.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
    draft, path = config.RUNS / f".landing-draft-{token}", config.RUNS / f".landing-wait-{token}"
    with ((config.RUNS / ".heavy-landing.wait").open("a") if line else nullcontext()) as shared, \
            draft.open("w") as fh:
        if line:
            fcntl.flock(shared, fcntl.LOCK_SH)
        # Locked before it takes its name: a file under that name is never an unheld live one.
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps({"since": since, "run_id": run_id or "", "line": line,
                             "holds": holds}))
        fh.flush()
        draft.rename(path)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _still_landing(context):
    """Whether the line still holds the member a checker's wait is for; True without one.

    A stopped or departed member leaves `landing.line`, and a check for it is no longer
    finished work: it must not hold back every round check for its turn.
    """
    line = (context or {}).get("line")
    if not line:
        return True
    return any(directory.name == context.get("run_id")
               for directory, _ in landing.line(config.RUNS / line))


def _landing_waiters():
    """The live landing waits as (not a line's check, whether it holds a turn, since, run id); a
    dead waiter's file goes, unreadable is none, one from before line checks were marked is a
    run's own, and one from before 12 Nov 2026 holds None (`landing_wait`)."""
    found = []
    for path in config.RUNS.glob(".landing-wait-*"):
        try:
            with path.open() as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    wait = json.loads(fh.read())
                    found.append((not wait.get("line"), wait.get("holds"),
                                  float(wait["since"]), str(wait["run_id"])))
                    continue
                path.unlink(missing_ok=True)     # its holder is gone
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return found


def landing_waits():
    """Whether a line's own check waits for a heavy turn now (`landing_wait`); unreadable is no.

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


def _gate_waiter_before(repo, exclude, since, is_landing=False, line=False, holds=None):
    """Whether a live heavy-suite waiter ranks before this gate; `repo` is ignored.

    Turns were per repository and only a waiter of the same main checkout counted.
    They are host-wide now, so every live waiter counts whichever repository it
    checks.  Rank is a line's own check (`line`), then a run's own landing check (a fork's,
    which no line checks), then any round check; within each the longest wait, then the run id,
    but between two waits that do not say whether their checks hold a turn (`holds`), those
    holding none go first and never hold each other back.
    `--first` plays no part, or loop repairs starve every other suite under load.  A
    round check stays behind any line's check (`landing_waits`).  A landing wait -- a
    run's, or the line checker's that marks no record -- ranks by its own file
    (`landing_wait`), whose start is the one its waiter ranks itself by: a lander's counts
    from its first landing wait, not from the lap.
    A record's landing mark ranks only a lander with no live file, one still on code
    from before the files, by the start of its first landing wait; a mark from before
    landers ranked carries no landing and reads as a round check.  A mark
    whose process is gone, or whose pid no longer matches its record -- a kill or
    a resume left it behind -- holds nobody back.
    """
    if not is_landing and landing_waits():
        return True
    # Owner, 29 Oct 2026: a line's own check goes first.  The line is where a repository's
    # changes land one at a time, so its wait delays every change behind it, while a run's
    # check before it joins the line only spares the line a red.
    me = (not is_landing, not line, holds, since, exclude or "")
    filed = _landing_waiters()
    waits = [(False, *wait) for wait in filed if wait[3] != exclude]
    filed = {run_id for *_, run_id in filed}
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
        waits.append((not landing, True, None, waited, directory.name))
    # 10 Nov 2026: a small line's check, its red target's repair, whose suite runs in a minute,
    # held no turn for two hours behind two older lines' checks waiting for first turns that fit
    # neither, then for more turns for their pieces.  So in a rank, one holding none goes before
    # one asking for more, and two holding none never hold each other back: each takes a turn as
    # soon as one fits it.  The longest wait still decides each turn past a check's first; a
    # share by turns held would need a count that its stale copies rank wrong.  A wait that does
    # not say -- a record's mark, a file from before 12 Nov 2026 -- ranks, and is ranked against,
    # by its start alone, as its own waiter reads it.  So such waits cut a rank by start, and turns
    # held order only waits between the same two cuts: across one, a check asking for more yielded
    # to a younger one holding none, that one to the older wait on older code between them, and
    # that one to the first, and nobody took the free turn.
    def place(wait):
        rank, holds, start = wait[:2], wait[2], wait[3:]
        cuts = sum(other[:2] == rank and other[2] is None and other[3:] < start
                   for other in (me, *waits))
        return (*rank, cuts, 0) if holds is False else (*rank, cuts, 1 if holds else 2, *start)
    return any(place(wait) < place(me) for wait in waits)


class _Pieces:
    """A sharded suite's pieces not yet run, by index, each taken by the next place to free, a
    turn here or a VM on a machine; one a machine had no room to start (`helper.FULL`) waits for
    the next place, one it lost (`helper.GONE`) for the next but the VMs of the suite there that
    lost it."""

    def __init__(self, which):
        self.waiting, self.lost, self.out, self.there = list(which), {}, 0, 0
        self.cond, self.hold = threading.Condition(), None

    def mine(self, there):
        return [index for index in self.waiting if there not in self.lost.get(index, ())]

    def next(self, ended, there):
        """(the next piece, its turn here or True), or None once none may come for this place."""
        while True:
            with self.cond:
                while not there and not self.waiting and self.out and not ended():
                    self.cond.wait(GATE_POLL)
                if ended() or not self.mine(there):
                    self.there -= bool(there)
                    return None
            turn = self.hold.take(lambda: ended() or not self.waiting) if (
                not there and self.hold) else True
            with self.cond:
                mine = turn is not None and self.mine(there)
                if mine:
                    self.waiting.remove(mine[0])
                    self.out += 1
            if mine:
                self.spare()    # it may have been the last to start
                return mine[0], turn
            self.give(turn)

    def give(self, turn):
        """`turn` back to the hold, where the suite's next piece takes it."""
        if turn is not True:
            self.hold.give(turn)
        self.spare()

    def spare(self):
        """Once every piece has started none is left to take a turn: the host has those no
        piece runs on, but the one the suite keeps until it ends (`_GateHold.shed`)."""
        if self.hold and not self.waiting:
            self.hold.shed()

    def done(self, index, back, turn, there):
        """`back`, the exit of a piece `there` gave back, ends that place there."""
        self.give(turn)
        with self.cond:
            self.out -= 1
            if back:
                self.waiting.insert(0, index)
                if back in helper.GONE:    # lost, not turned away before its VM started
                    self.lost.setdefault(index, []).append(there)
                self.there -= 1
            self.cond.notify_all()


class _GateHold:
    """Held turns: the open slot files and those this thread locked.

    The hold owns its files rather than the frame that waited for them, so a fixer
    or a reviewer lets it go from inside the frame that took it.  Releasing unlocks
    the slot and closes the files, as leaving the frame would have.
    A sharded suite has `pieces` places here, the derived limit it was admitted at by `cost`,
    one piece's; each takes a turn of its own (`take`), and turns the host frees join the hold
    (`more`).  A later suite of its check is admitted here by its own (`suite`).
    """

    def __init__(self, files, slots, context=None, pieces=None, more=None, queued=None,
                 cost=None):
        self.files, self.slots, self.context = files, slots, context
        self.pieces, self.more, self.queued, self.cost = pieces or len(slots), more, queued, cost
        self.idle, self.waiting, self.waited, self.shown = list(slots), 0, False, False
        # A turn a piece gives back wakes a waiting sibling at once, not at the next poll.
        self.lock, self.growing, self.queue = threading.Condition(), threading.Lock(), ExitStack()

    def suite(self, cost):
        """A suite's pieces start here, and its red ones going again whole.  One the hold was not
        admitted for, a later suite of its check or a hold kept `alone`, is admitted now as the
        first was: its own piece's `cost` decides its places and its turns, which say it
        (`_say_cost`), and those free now join the hold.  A hold taken for no pieces has no way
        to ask for them (`more`) and stays one place."""
        if self.more and cost != self.cost:
            self.cost = cost
            with _place_costs():
                for slot in self.slots:
                    _say_cost(slot, cost)
            freed, self.pieces = self.more(self.slots, len(self.idle), cost)
            self.slots += freed
            self.idle += freed

    def take(self, stopped):
        """A held turn no other piece runs on, or None once `stopped()`; `give` it back.

        While any piece waits, the suite is one waiter holding turns, at the place it was
        admitted at (`queued`), and one piece at a time asks the host for the turns freed
        since (`more`).
        """
        slot = None
        with self.lock:
            self.waiting += 1
        try:
            while not stopped():
                with self.lock:
                    if self.idle:
                        slot = self.idle.pop()
                        break
                    self.waited = True
                    if self.queued and not self.shown:
                        self.queue.enter_context(self.queued())
                        self.shown = True
                if self.cost and self.growing.acquire(blocking=False):
                    try:
                        freed = self.more(self.slots, len(self.idle), self.cost)[0]
                        # Joined before the next grower asks: its `more` must count them as its own.
                        with self.lock:
                            self.slots += freed
                            self.idle += freed
                            self.lock.notify_all()    # a sibling waiting meanwhile takes one
                    finally:
                        self.growing.release()
                    if freed:
                        continue
                with self.lock:
                    if not self.idle:
                        self.lock.wait(GATE_POLL)
        finally:
            with self.lock:
                self.waiting -= 1
                if not self.waiting:
                    self.queue.close()
                    self.shown = False
        return slot

    def give(self, slot):
        if slot is not None:
            with self.lock:
                self.idle.append(slot)
                self.lock.notify_all()    # a place waiting for a turn sees the list end

    def shed(self):
        """Unlock each turn no piece runs on, so the first waiter in rank takes it, but the one
        the suite keeps until it ends, for its reruns."""
        with self.lock:
            while self.idle and len(self.slots) > 1:
                slot = self.idle.pop()
                self.slots.remove(slot)
                fcntl.flock(slot, fcntl.LOCK_UN)

    def alone(self):
        """One turn kept once a suite's pieces end, and no other taken until a suite starts
        here (`suite`): what runs on it meanwhile runs alone."""
        self.cost = None
        self.shed()

    def release(self):
        try:
            self.queue.close()
            for slot in self.slots:
                fcntl.flock(slot, fcntl.LOCK_UN)
        finally:
            self.slots = []
            self.files.close()


def derived_heavy_limit(readings=None, running=None, job_cpus=HEAVY_CPUS,
                        job_mem_mb=HEAVY_MEM_MB, *, unit=False, others=()):
    """Running suites plus how many more the live headroom fits; at least one.

    The runs slice's idle cores over one suite's 0.7, and free memory over 0.4 GB,
    whichever fits fewer.  Headroom already excludes running suites, so add
    them once; a saturated slice starts one only when none run.  Both come
    from the runs' CPU room and the parent slice's shared memory headroom,
    which a shell beside the slice reads like a worker inside it; the host's CPU
    use outside the slice takes from the cores the slice may use.  Where
    no slice answers, the host's idle cores and free memory stand in.  An
    unreadable gate fails open to the other resource, and to one suite where
    neither answers.  `job_cpus` and `job_mem_mb` are one job's cost, such as a suite
    piece's as measured (`suite_cost`). With `unit`, pieces also fit the caller's soft
    limit and the remaining room under every enclosing hard memory cap.
    Running and new never pass what the slice's cores and memory fit with nothing running:
    a held piece's use dips while it waits, and room read in a dip piled 60 turns on 8 cores.
    Of the `running` turns, those `others` hold take what their holders say a piece costs
    (`_held_cost`), and the rest -- the caller's own and those saying nothing -- the caller's:
    two lines whose pieces cost 2.0 and 0.7 counted each other's at their own and put 25.9
    cores' worth on 18 (11 Nov 2026).  With no `running` given, every held turn is another's.
    """
    if running is None:
        others = _heavy_held()
        running = len(others)
    if readings is None:
        readings = _run_readings()
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
        cpu_whole = cpu_quota
    else:
        load = host._reading(readings, "load", "load1", "load_1m")
        if cpus is not None and load is not None:
            cpu_free = cpus - load
        elif cpus is not None:
            cpu_free = float(cpus)
        else:
            cpu_free = None
        cpu_whole = cpus
    memory = host._slice_or_unit_memory(readings)
    if memory is not None:
        mem_free = memory[1] - memory[0]
        mem_whole = memory[1]
    else:
        mem_free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
        mem_whole = host._reading(readings, "mem_total_mb")
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
        candidates.append(_fits(cpu_free, job_cpus))
    if mem_free is not None:
        candidates.append(_fits(mem_free, job_mem_mb))
    if not candidates:
        return 1
    said = [cost for cost in others if cost]
    candidates += [_fits(total - sum(cost[part] for cost in said), job) - (running - len(said))
                   for part, (total, job) in enumerate(((cpu_whole, job_cpus),
                                                        (mem_whole, job_mem_mb)))
                   if total is not None]
    return max(1, running + max(0, min(candidates)))


def _fits(room, cost):
    """How many of `cost` fit in `room`.  Costs taken from a whole leave float dust, and dust
    must not cost a place: 4 cores less two at 0.8 over 0.8 is 2.9999999999999996."""
    return int(round(room / cost, 9))


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


def _acquire_gate_turn(run_dir, log_path, log, command=None, cwd=None, *, context=None,
                       elsewhere=None):
    """Hold host-wide heavy-suite turns.

    While it waits it asks `elsewhere()` each poll, before it looks for a turn here; once that
    answers, it stops waiting and holds none.
    """
    record = context if context is not None else (run_record.read_state(run_dir) or {}
                                                if run_dir else {})
    repo = record.get("repo")
    is_landing = bool(record.get("landing"))
    # the line's checker marks no member's record: a check with only a context is the line's own
    line = is_landing and not run_dir
    landing_since = _first_landing_wait(run_dir) if run_dir else record.get("since")
    self_id = run_dir.name if run_dir else record.get("run_id")
    if not repo or os.environ.get("AK_MAX_RUNS") == "0":
        return None
    pieces = names_shard(command or "")
    cost = suite_cost(command, cwd or repo, run_dir)[1:] if pieces else (
        HEAVY_CPUS, HEAVY_MEM_MB)
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
        waiting.enter_context(landing_wait(is_landing, me_since, self_id, line, False))
        slots = []
        def admit(mine=(), idle=0, cost=cost):
            """`idle` of `mine` run no piece: they are of those the headroom fits, not running."""
            try:
                pinned = None if pieces else config.max_gates()
            except config.Error as exc:
                if log is not None and not said_bad:
                    said_bad.append(True)
                    log(f"done-when: {exc} · the heavy suite takes a derived turn")
                pinned = None
            # CPU sampling sleeps; locking free slots across it would count them as running.
            readings = _run_readings() if pinned is None else None
            # At the top CPU weight (the line's checker) the use lower-weighted runs hold is its own.
            kept = host.kept_cpu(orch.run_slice_cgroup()) if pinned is None else None
            if kept is not None:
                readings = {**readings, "slice_cpu_used": kept}
            with _place_costs():
                total = max(1, _heavy_max_existing() + 1, len(slots))
                while len(slots) < total:
                    slots.append(files.enter_context(gate_lock(repo, len(slots)).open("a")))
                temp, held, others = [], 0, []
                for fh in slots:
                    if fh in mine:
                        held += 1     # this suite's own turn: its own lock would take it again
                        continue
                    try:
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        held += 1
                        others.append(_held_cost(fh.name))
                        continue
                    temp.append(fh)
                new_limit = pinned if pinned is not None else derived_heavy_limit(
                    readings, held - idle, *cost, unit=pieces, others=others)
                while len(slots) < new_limit:
                    slots.append(files.enter_context(gate_lock(repo, len(slots)).open("a")))
                candidates = []
                if held < new_limit:
                    wanted = new_limit - held if pieces else 1
                    for fh in slots[:new_limit]:
                        if fh not in mine and take_slot([fh]) is not None:
                            candidates.append(fh)
                        if len(candidates) == wanted:
                            break
                for fh in temp:
                    if fh not in candidates:
                        fcntl.flock(fh, fcntl.LOCK_UN)
                for fh in candidates:
                    _say_cost(fh, cost)
                return candidates, new_limit, held
        place = me_since
        slot, limit, held = admit()
        if not limit:
            files.close()
            return None
        if not slot or _gate_waiter_before(repo, self_id, me_since, is_landing, line, False):
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
            turnless = False
            try:
                while True:
                    log_path.write_text(said + "\n")
                    run_record.stop_check(run_dir)
                    time.sleep(GATE_POLL)
                    if is_landing and not _still_landing(context):
                        # Its members left the line: this check waits as a round check now.
                        is_landing, line, waited_since = False, False, time.time()
                        waiting.close()
                    # a checker's wait is its member's, kept beside that member's line time
                    if run_dir or is_landing:
                        counted = count_wait(self_id, "suite" if run_dir else "lander", counted)
                    # Rank and a line's own check waiting decide this host's turns, never who
                    # asks the helper (owner, 30 Oct 2026: nothing waits for compute), as the
                    # first may not ask for long: it waits here to rerun what a machine failed,
                    # or sets up a new machine, and a suite on one takes nothing from a wait here.
                    if elsewhere and elsewhere():
                        turnless = True
                        break
                    slot, limit, held = admit()
                    if not limit:
                        turnless = True
                        break
                    said = f"waiting for a heavy suite turn · {held} running · {max(0, limit - held)} more fit"
                    if slot and not _gate_waiter_before(repo, self_id, waited_since,
                                                        is_landing, line, False):
                        break
                    for fh in slot:
                        fcntl.flock(fh, fcntl.LOCK_UN)
                    slot = []
            finally:
                if run_dir:
                    mark_gate_wait(run_dir, None)
                if run_dir or is_landing:
                    count_wait(self_id, "suite" if run_dir else "lander", counted)
            place = waited_since
            if run_dir:
                history.open_step(run_dir.name, step)
            if turnless:
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
    if not pieces:
        return _GateHold(files, slot, context)

    def beyond(freed):
        """Of `freed`, turns past this check's first, those it ranks first for as it holds one."""
        if freed and _gate_waiter_before(repo, self_id, place, is_landing, line, True):
            for fh in freed:
                fcntl.flock(fh, fcntl.LOCK_UN)
            return []
        return freed

    def more(mine, idle, cost):
        freed, limit, _ = admit(mine, idle, cost)
        return beyond(freed), limit

    @contextmanager
    def queued():
        counted = (time.time(), time.monotonic())
        with landing_wait(is_landing, place, self_id, line, True):
            if run_dir:
                mark_gate_wait(run_dir, repo, place)
            try:
                yield
            finally:
                if run_dir:
                    mark_gate_wait(run_dir, None)
                if run_dir or is_landing:
                    count_wait(self_id, "suite" if run_dir else "lander", counted)
    return _GateHold(files, slot[:1] + beyond(slot[1:]), context, limit, more, queued, cost)


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
    changed headroom reaches runs already queued.  A freed turn goes to the first waiter
    in rank (`_gate_waiter_before`), whether
    `--first` or not: a suite takes a free turn only when no waiter
    ranks before it, and a lander's wait counts from the start of its first landing
    wait.
    A home config this cannot read -- it is read here, mid-run, so one hand-edit
    typo would fail the next suite of every running run -- means a derived count,
    and a log line naming the problem.
    A check running while this thread already holds a turn takes no second one.
    A command naming AK_SHARD gets as many places as the derived limit fits, using its
    repository's measured cost when available: it takes one turn free now, then the others free
    now and those freed later while it ranks first, each running one piece at a time, and once
    its last piece has started gives back each one a piece ends on, but one (`_GateHold`,
    `_Pieces.spare`, `run_suite`).
    A suite the helper has room for (`helper.start`) takes no turn here; one that waits asks it
    again each poll, and goes there once it has room.
    """
    if (getattr(_GATE_HELD, "hold", None) is not None or getattr(_GATE_HELD, "away", None)
            or getattr(_GATE_HELD, "here", None)):
        yield
        return
    _GATE_HELD.away, _GATE_HELD.here, elsewhere = None, None, None
    if command and cwd and names_shard(command):
        cost = suite_cost(command, cwd, run_dir)[1:]
        def ask(say):
            _GATE_HELD.away, _GATE_HELD.here = helper.start(
                *cost, cwd, say, pinned(command, suite_times.handed(cwd)))
            return _GATE_HELD.away
        if not ask(log or (lambda line: None)):
            def elsewhere():
                # Asked each poll: what it says shows once the suite goes, not each look's warning.
                said = []
                if ask(said.append) and log is not None:
                    for line in said:
                        log(line)
                return _GATE_HELD.away
        if _GATE_HELD.here and log is not None:
            log(f"suite runs here: {_GATE_HELD.here}")
    try:
        _GATE_HELD.home = lambda elsewhere: _acquire_gate_turn(
            run_dir, log_path, log, command, cwd, context=context, elsewhere=elsewhere)
        # A suite gone to a helper takes no turn here: those are for what cannot leave this host.
        _GATE_HELD.hold = None if _GATE_HELD.away else _acquire_gate_turn(
            run_dir, log_path, log, command, cwd, context=context, elsewhere=elsewhere)
        yield
    finally:
        current, _GATE_HELD.hold = getattr(_GATE_HELD, "hold", None), None
        away = _GATE_HELD.away
        _GATE_HELD.away = _GATE_HELD.home = _GATE_HELD.here = None
        if current is not None:
            current.release()
        if away is not None:
            helper.finish(away)


def suite_env(times=None):
    """A done-when command's environment, `AK_HEAVY_TURN=1` only while this thread holds a turn,
    and `AK_TIMES` holding `times` when given.

    A suite that queues behind a host-wide lock of its own would hold the turn for as long as
    another copy holds that lock; told it holds one, it says busy at once instead, exit
    `SUITE_BUSY`, and `busy_turn` gives the turn back.  Never inherited: a loop started below
    a suite holds none of that suite's turn, nor its share or test lists.
    """
    env = gitcall.run_child_env()
    for key in ("AK_HEAVY_TURN", "AK_SHARD", "AK_ONLY", "AK_FAILED", "AK_RAN", "AK_NOT_THERE",
                "AK_TIMES"):
        env.pop(key, None)
    if getattr(_GATE_HELD, "hold", None) is not None:
        env["AK_HEAVY_TURN"] = "1"
    if times is not None:
        env["AK_TIMES"] = times
    return env


def pinned(command, times, only=None):
    """`command` as a piece runs it on the suite helper, which hands it no environment: AK_TIMES
    holds `times` in the command, and AK_ONLY names a file there listing the tests `only` names,
    for a piece that runs just those (land._probe); the piece's VM or container takes the file
    with it.

    The piece runs in a clone there, which land._check's look at this checkout never sees: it
    checks that clone itself and fails, as land._check does, if it changed, however the command
    exited, dropping the tests it named as not there, which say nothing of the tree it was given.
    """
    tests = "" if only is None else (
        f"export AK_ONLY=\"$(mktemp)\" && printf '%s\\n' {shlex.join(only)}"
        ' >"$AK_ONLY" || exit\n')
    return (f"export AK_TIMES={shlex.quote(times)}\n{tests}"
            f"head=$(git rev-parse HEAD) || exit\nbash -c {shlex.quote(command)}\ncode=$?\n"
            '[ "$(git rev-parse HEAD)" = "$head" ] && git diff --quiet HEAD ||'
            ' { echo "the piece changed the checkout it tests" >&2;'
            ' : >"${AK_NOT_THERE:-/dev/null}"; [ "$code" != 0 ] || code=1; }\n'
            'exit "$code"')


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
        return max(estimate, value) if _a_cost(value) else estimate
    return path, measured("cpus", HEAVY_CPUS), measured("mem_mb", HEAVY_MEM_MB)


def _a_cost(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


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
    the suite has no such pace: `silence` holds, and stops a command for good; a piece still
    goes once more (`run_suite`)."""
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


def inherit_suite_cost(command, source, cwd):
    """`command` takes each part of `source`'s cost on record (`cpus`, `mem_mb`) it has no
    measure of its own for, `source` a suite of the same repository: a part `source` has none of
    stays the initial estimate, and `command`'s first measured pass replaces the rest as any
    measure.  The lander gives a rewritten `tests:` line the target's, as there ak first meets a
    suite nobody measured, beside the one it replaces (`land._landing_checks`)."""
    path = suite_cost(command, cwd, None)[0]
    try:
        with watch.state_lock():
            own, given = read_suite_cost(path), read_suite_cost(suite_cost(source, cwd, None)[0])
            given = {name: given[name] for name in ("cpus", "mem_mb")
                     if _a_cost(given.get(name)) and not _a_cost(own.get(name))}
            if given:
                write_suite_cost(path, given)
    except OSError:
        pass    # a cost not given keeps the initial estimate


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
    """Wall time and the CPU each box needed everywhere, a line's checker included, over the
    seconds it ran; memory, swap included and less the file cache reclaim frees, where a cgroup
    is this run's or holds only this process."""

    def __init__(self, run_dir):
        state = run_record.read_state(run_dir) or {} if run_dir else {}
        self.run_id = state.get("run_id")
        relative = host.process_cgroup() if state.get("scope") else None
        self.group = (host.cgroup_path(relative) if relative and
                      Path(relative).name in turns._scope_units(state["scope"])
                      else host.own_cgroup())
        self.cpu = []     # each box's CPU seconds (`box.cpu_seconds`) and the seconds it ran
        self.quiet = []   # and the longest each go went without output (`worker.limited`)
        self.baseline = host.held_mb(self.group, swap=True) if self.group is not None else None
        self.peak = self.baseline
        # a cap is the whole cgroup's, whoever else it holds
        self.cgroup = host.cgroup_path(relative) if (relative := host.process_cgroup()) else None
        self.ooms = self.oom()
        self.mem_mb = 0   # what `save` recorded
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def oom(self, event="oom"):
        """How often this process's cgroup ran out of memory, or with `oom_kill` how many of
        its processes the kernel killed for it (`host.memory_events`)."""
        return host.memory_events(self.cgroup).get(event, 0) if self.cgroup is not None else 0

    def starved(self, code, kills):
        """Whether `code` is a SIGKILL while the kernel killed in this cgroup for memory more
        than the `kills` it had: a test may exit 137 on its own."""
        return code in (128 + signal.SIGKILL, -signal.SIGKILL) and self.oom("oom_kill") > kills

    def sample(self):
        if self.baseline is not None:
            held = host.held_mb(self.group, swap=True)
            if held is not None:
                with self.lock:
                    self.peak = max(self.peak, held)

    def save(self, path, pieces, places):
        """`pieces` the ones that ran here, each to its end, on `places` at once, or None where
        one waited for a place: a peak of fewer at once is no piece's memory.  A piece's CPU is
        what each needed while its box ran, so a place waited for or left empty counts none."""
        elapsed = time.monotonic() - self.started
        if elapsed <= 0:
            return
        cost = {"wall_seconds": elapsed, "run_id": self.run_id}
        ran = sum(seconds for _, seconds in self.cpu)
        if len(self.cpu) == pieces and ran > 0:
            cost["cpus"] = max(HEAVY_CPUS, sum(spent for spent, _ in self.cpu) / ran)
        if self.baseline is not None and places:
            cost["mem_mb"] = self.mem_mb = max(HEAVY_MEM_MB, (self.peak - self.baseline) / places)
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

    def overflowed(self, path, planned_mb):
        """A suite whose cgroup ran out of memory since this measure began (`host.memory_events`)
        costs at least twice the `planned_mb` it ran at, however its pieces ended: held memory
        stops at the cap, so no peak shows the overflow, and its next pass is cut smaller."""
        if self.oom() <= self.ooms:
            return
        try:
            with watch.state_lock():
                write_suite_cost(path, {"mem_mb": max(2 * planned_mb, self.mem_mb)})
        except OSError:
            pass

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
    """Keep the whole failure, even when its distinguishing lines precede the output cap: the
    record's head, and those lines at most OUT_CAP bytes, for `flaky_text`."""
    with tempfile.NamedTemporaryFile(dir=run_dir or log_path.parent,
                                     prefix=f"{log_path.stem}-failed-",
                                     suffix=".log", delete=False) as saved:
        saved.write(failed)
    lines = [line for line in failed.decode("utf-8", errors="replace").splitlines()
             if line.strip()]
    reran = {flaky_key(line) for line in rerun.decode("utf-8", errors="replace").splitlines()}
    diff = "\n".join([line for line in lines if flaky_key(line) not in reran][:20])
    note = f"flaky: {command} {how}, then passed on its re-run"
    if log is not None:
        log(f"done-when: {note}")
    return (f"{note}\nfailed output: {Path(saved.name).resolve()}",
            diff.encode()[:turns.OUT_CAP])


def flaky_text(record, cap=None):
    """A `flaky_record` as handed on, its distinguishing lines cut at `cap` bytes. No line ends
    blank: a record is what lies between two blank lines."""
    head, diff = record
    return "\n".join(filter(None, [head, diff[:cap].decode(errors="ignore").rstrip()]))


def shares(reds, others):
    """What each of `reds` red pieces, then each of `others` (green pieces and flaky records),
    hands on of the suite's PIECES_CAP, at most OUT_CAP each: the red pieces take theirs first, so
    one red piece keeps its whole OUT_CAP however many ran, and the others share the rest."""
    red = min(turns.OUT_CAP, turns.PIECES_CAP // max(reds, 1))
    return red, min(turns.OUT_CAP, (turns.PIECES_CAP - reds * red) // max(others, 1))


def unnamed(code, only, ran, output):
    """`code`, or 1 for a run of just the tests `only` lists that exited 0 without naming each
    one as run (`AK_RAN`): a runner may skip a name it does not know and exit 0."""
    missing = [test for test in only if test not in ran]
    if code or not missing:
        return code
    output.write(f"[not named as run (AK_RAN): {' '.join(missing)}]\n".encode())
    return 1


def passes_what_it_holds(code, only, ran, failed, absent):
    """Whether a run of just the tests `only` lists, exiting `code`, passed each one its tree
    holds: it named each as run (`AK_RAN`) but those it named as not there (`AK_NOT_THERE`), as
    a test file names a part only a later change adds, and failing, it named one at least as not
    there and none of the others as failed (`AK_FAILED`).  A narrowing step counts that stack as
    passing them (land._check_tests, land._probe); to a person and every other check the run
    exited as it did."""
    there = [test for test in only if test not in absent]
    return all(test in ran for test in there) and (
        code == 0 or code > 0 and len(there) < len(only) and not set(there) & set(failed))


def run_suite(command, limit, *, confirmed=None, flaky=None, checked=None, **kwargs):
    """Run a suite and keep its named reds and flakes beside its check rows."""
    reds = {} if confirmed is not None or checked is not None else None
    flakes = [] if flaky is not None or checked is not None else None
    try:
        return _run_suite(command, limit, confirmed=reds, flaky=flakes, checked=checked, **kwargs)
    finally:
        if confirmed is not None:
            confirmed.update(reds)
        if flaky is not None:
            flaky.extend(flakes)
        history.test_reds(checked, reds, flakes)


def _run_suite(command, limit, *, cwd, activity, output, run_dir=None, log=None,
              on_wait=None, measure=False, shard=None, pieces=None, later=None, only=None,
              confirmed=None, flaky=None, named=None, checked=None, asked=None,
              raw=None, absent=None, used=None, **kwargs):
    """One command, or all its opted-in pieces, with failed pieces retried alone.

    Callers keep one command and one outcome. Each piece has its own silence window;
    all attempts share the command's ceiling, and live output identifies its piece.
    A red piece that named its failed tests (`AK_FAILED`) retries just those first (`AK_ONLY`),
    here for one red on the suite helper too.
    With `shard` (`k/N`) one piece runs alone with that share set, as the lander probes the
    target's tip: on one turn, never split again, measuring nothing, its cost the suite's;
    with `only` too, just those of its tests, as one share, green only where the runner names
    each one as run (`AK_RAN`): a runner may skip a name it does not know and exit 0.
    `pieces`, a dict, gets each piece's exit as the runner saw it, by share -- None for one
    killed at the limit, `OUT_OF_MEMORY` for one the kernel killed for memory -- so a caller
    decides from codes, never from what a piece printed.
    A piece its first go's silence stopped goes again, alone, after its siblings, which run on:
    a hang costs its piece, never the pieces that pass.  `later`, seconds, is set where the
    suite's pace stops its pieces sooner (`quiet_window`): the silence each piece's later goes
    have.  Without it each go has the whole silence: a suite has no pace where its pieces'
    ordinary quiet outgrew a part of it, so a part would stop pieces only slow.
    `confirmed`, a dict, gets by share the tests a red piece named that failed again alone;
    with `shard` and `only`, those of them its run named both as run and as failed (`AK_FAILED`)
    where it ended in a failing exit: one dead by a signal, its exit negative, repeats nothing;
    for a command not split, under `1/1`, those its failing run named as failed.
    `flaky`, a list, gets the tests that failed, then passed on this tree: those a command named
    so (`AK_FLAKY`), here or on the suite helper, and a red piece's named tests that passed run
    alone.  `named`, a list, gets those a failing run of the command as one piece (not split,
    or `shard`) named as failed, confirmed or not.
    `raw` receives each piece's process exits by share, before checking coverage of `only`.
    `absent`, a list, gets with `shard` and `only` the tests the run named as not there where it
    passed what its tree holds (`passes_what_it_holds`), and none otherwise.
    Every piece gets the file times recorded as the suite starts (`suite_times`): a record
    another suite changes meanwhile would cut a later piece's share differently.
    With `checked` (`run_done_when`'s) each go of a piece leaves its row where it runs, its first
    go asked for at `asked`, a later one as the go before it ended: a turn it waits for is wait.
    `used`, a dict, gets what a command run as one piece used (`worker.boxed`).
    """
    def observed(share, code, killed):
        if raw is not None and (code != SUITE_BUSY or killed):
            raw.setdefault(share, []).append(None if killed else code)

    times = suite_times.handed(cwd)
    env = suite_env(times)
    if shard is not None:
        label, share = ((shard, shard) if only is None else
                        (f"{shard}, its failed tests alone", "1/1"))
        if log is not None:
            log(f"AK_SHARD={label} runs here: command is not sent to the suite helper "
                "(pinned piece)")
        output.write(f"--- AK_SHARD={label} ---\n".encode())
        output.flush()
        ran, failed, gone = (None, [], None) if only is None else ([], [], [])
        code, text, killed = worker.boxed(
            ["bash", "-c", command], limit, cwd=str(cwd), activity=activity, output=output,
            env={**env, "AK_SHARD": share}, only=only, ran=ran, failed=failed, absent=gone,
            flaky=flaky, used=used, **kwargs)
        observed(shard, code, killed)
        if confirmed is not None and only is not None:
            confirmed[shard] = [test for test in only if code > 0 and test in ran and test in failed]
        if absent is not None and only is not None:
            # the last go's, as a re-run decides
            absent[:] = ([test for test in only if test in gone]
                         if passes_what_it_holds(code, only, ran, failed, gone) else [])
        if named is not None and code > 0:
            named.extend(failed)
        if ran is not None:
            code = unnamed(code, only, ran, output)
        if pieces is not None:
            pieces[shard] = None if killed else code
        return code, text, killed
    if not names_shard(command):
        if log is not None:
            log("suite runs here: command is not sent to the suite helper (does not name AK_SHARD)")
        path, _, planned = suite_cost(command, cwd, run_dir) if measure else (None,) * 3
        measured = _SuiteMeasure(run_dir) if measure else None
        aborting = kwargs.pop("abort", None)
        def abort():
            if measured:
                measured.sample()
            return aborting() if aborting else False
        failed = []
        result = worker.boxed(["bash", "-c", command], limit, cwd=str(cwd), activity=activity,
                              output=output, env=env, abort=abort,
                              cpu=measured.cpu if measured else None,
                              quiet=measured.quiet if measured else None, failed=failed,
                              flaky=flaky, used=used, **kwargs)
        observed("", result[0], result[2])
        if confirmed is not None:
            confirmed["1/1"] = failed if result[0] > 0 else []
        if named is not None and result[0] > 0:
            named.extend(failed)
        if measured and not result[2] and result[0] != SUITE_BUSY:
            measured.save(path, 1, 1)
            measured.paced(path, 1)
        if measured:
            measured.overflowed(path, planned)
        return result
    with gate_turn(run_dir, activity, log, command, cwd):
        hold = getattr(_GATE_HELD, "hold", None)
        away = getattr(_GATE_HELD, "away", None)
        path, cpu, mem = suite_cost(command, cwd, run_dir)
        if hold:
            hold.suite((cpu, mem))
        there_command = pinned(command, times)
        # Twice the places it starts with, so a faster machine takes more and every place ends
        # near the others; without a turn every piece runs at once.  The helper's count as many
        # as it fits empty: a suite starting on its little room grows into what frees there.
        places = (hold.pieces if hold else 0) + (away.most if away else 0)
        count = 2 * places or derived_heavy_limit(running=0, job_cpus=cpu, job_mem_mb=mem,
                                                  unit=True)
        # the piece threads do not inherit this thread's held turn
        env = suite_env(times)
        deadline = time.monotonic() + limit
        cancel, writing = threading.Event(), threading.Lock()
        last_shard = None
        measure = _SuiteMeasure(run_dir)
        timeout = kwargs.pop("on_timeout", None)
        silence = kwargs.pop("silence", None)
        silenced = set()    # the pieces whose first go silence stopped, each to go again
        starved = set()     # those whose last go here the kernel killed for memory
        asked_at = {}       # by piece, when its last go ended: its next one is owed from then
        home_reason = getattr(_GATE_HELD, "here", None) or (
            "no place is left on the suite helper" if away else
            "command is not sent to the suite helper (suite already holds a local turn)")
        home_reasons = {}

        with ExitStack() as files:
            results = []
            def over():
                return run_record.stop_check(run_dir) or cancel.is_set() or (
                    time.monotonic() >= deadline)

            def attempt(shard, only=None, first=False, there=None, turn=None):
                """The piece of `shard`, or with `only` just those of its tests, as one share,
                on the helper's `there` or on this host's `turn` (one taken when None);
                a `first` go stopped for silence goes again."""
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
                    if why == "silence" and first:
                        silenced.add(shard)     # its siblings run on; it goes again after them
                    elif why != "abort":
                        cancel.set()
                        if timeout is not None:
                            timeout(why, pid)

                def abort():
                    measure.sample()
                    return cancel.is_set()

                local = None if there or turn else hold
                turn = turn or (local.take(over) if local else True)
                # The watchdog reads this piece's file, so a chatty sibling cannot hide silence.
                left = deadline - time.monotonic()
                if turn is None or left <= 0 or cancel.is_set():
                    if local:
                        local.give(turn)
                    cancel.set()
                    return worker.TIMEOUT, piece, True, []
                if log is not None:
                    reason = home_reasons.get(shard) or (home_reason if first else
                        "command is not sent to the suite helper (piece retry)")
                    with writing:
                        log(f"AK_SHARD={label} on {there.alias}" if there else
                            f"AK_SHARD={label} runs here: {reason}")
                stream, tests = Output(), []
                own = {**env, "AK_SHARD": shard if only is None else "1/1"}
                if own.get(worker.RUN_MARKER):
                    # A stop ends this piece's own processes, never a sibling's that runs on.
                    own[worker.RUN_MARKER] += f"/piece-{shard.replace('/', '-')}"
                try:
                    kills = measure.oom("oom_kill")
                    with history.check(checked, f"AK_SHARD={shard} {command}",
                                       asked_at.get(shard, asked), there and there.alias) as ended:
                        here = {} if there else {"cpu": measure.cpu, "quiet": measure.quiet,
                                                 "only": only, "failed": tests, "flaky": flaky,
                                                 "used": ended}
                        code, _, killed = (worker.limited if there else worker.boxed)(
                            helper.piece(there, shard, there_command)
                            if there else ["bash", "-c", command],
                            left, cwd=str(cwd), activity=Path(piece.name), output=stream,
                            env=own, abort=abort,
                            on_timeout=stopped, silence=silence if first else later or silence,
                            **here, **kwargs)
                        ended["exit"] = None if killed else code
                    if not there or code not in (*helper.GONE, helper.FULL):
                        observed(shard, code, killed)
                    if not there and not killed and measure.starved(code, kills):
                        starved.add(shard)
                    else:
                        starved.discard(shard)
                except BaseException:
                    cancel.set()    # its siblings stop rather than wait out the limit for it
                    raise
                finally:
                    stream.finish()
                    asked_at[shard] = time.time()
                    if local:
                        local.give(turn)
                return code, piece, killed, tests

            def attempts(which):
                """Run the whole pieces at `which` on this host's turns as its first pieces ran
                (`_Pieces`): once none waits to start, a turn one ends on goes back to the host."""
                left = _Pieces(which)
                left.hold = hold

                def place():
                    while (taken := left.next(over, None)) is not None:
                        index, turn = taken
                        try:
                            results[index] = attempt(f"{index + 1}/{count}", turn=turn)
                        finally:    # one that raised too, or a sibling waits for it
                            left.done(index, False, turn, None)

                with ThreadPoolExecutor(max_workers=len(which)) as pool:
                    try:
                        for future in [pool.submit(place) for _ in which]:
                            future.result()
                    except BaseException:
                        cancel.set()
                        raise
                for index in left.waiting:    # stopped before it ran
                    results[index] = attempt(f"{index + 1}/{count}")

            def pull(here):
                """`here` places on this host and `away`'s VMs each take the next waiting piece
                as they free; while one waits, the helper is asked again each GATE_POLL, also
                while the suite runs VMs there, which its probe counts, and those it gives take
                the waiting pieces."""
                pieces_left.hold, futures = hold, []

                def place(there=None):    # a VM there ends with the piece it gives back
                    back = False
                    while not back and (taken := pieces_left.next(over, there)) is not None:
                        (index, turn), shard = taken, f"{taken[0] + 1}/{count}"
                        result = attempt(shard, first=True, there=there, turn=turn)
                        code = result[0]
                        back = there and code in (*helper.GONE, helper.FULL) and not result[2]
                        pieces_left.done(index, back and code, turn, there)
                        if there and not back and flaky is not None:
                            flaky.extend(helper.failed(there, shard, "flaky") or [])
                        if there and code and log is not None:
                            home_reasons[shard] = f"helper {there.alias} {helper.failure(code)}"
                        if not back:
                            results[index], where[index] = result, there
                        elif code == helper.SHORT and (least := helper.short(there)) and log:
                            log(f"the suite helper's VMs of {there.memory_mb} MiB ran out of "
                                f"memory: its next VMs get {least} MiB")
                        elif code == helper.LOST and log:
                            # Without this a suite the helper lost reads as one it ran.
                            log(f"the suite helper {there.alias} lost AK_SHARD={shard}; it runs "
                                "again on the first machine with room, this one included")

                def ended():    # no piece waits or runs, or no place is left to take one
                    return over() or not (pieces_left.waiting or pieces_left.out) or not (
                        here or pieces_left.there)

                def ask():
                    asked = time.monotonic()    # as the suite went
                    while True:
                        with pieces_left.cond:
                            if ended():
                                return
                            # A place ending wakes this, yet it asks once a poll at most.
                            left = asked + GATE_POLL - time.monotonic()
                            pieces_left.cond.wait(left if left > 0 else GATE_POLL)
                            if ended() or not pieces_left.waiting or (
                                    time.monotonic() < asked + GATE_POLL):
                                continue
                        asked = time.monotonic()
                        said, answer = [], []
                        # The suite never waits on an answer (a probe, a copy sent) past its
                        # last piece: one that comes later finishes the helper it joined.
                        threading.Thread(target=start, args=(said, answer), daemon=True,
                                         name=ASKING).start()
                        with pieces_left.cond:
                            while not answer and not ended():
                                pieces_left.cond.wait(GATE_POLL)
                            answer.append(None)
                        if joined := answer[0]:
                            files.callback(helper.finish, joined)
                            for line in said if log else ():
                                log(line)
                            run_there(joined)

                def start(said, answer):
                    joined = helper.start(cpu, mem, cwd, said.append, there_command)[0]
                    with pieces_left.cond:
                        answer.append(joined)
                        pieces_left.cond.notify_all()
                    if joined and answer[0] is None:
                        helper.finish(joined)

                def run_there(there):
                    with pieces_left.cond:
                        vms = min(there.count, len(pieces_left.mine(there)))
                        pieces_left.there += vms
                    futures.extend(pool.submit(place, there) for _ in range(vms))

                with ThreadPoolExecutor(max_workers=here + count + 1) as pool:
                    futures.extend(pool.submit(place) for _ in range(here))
                    if away:
                        run_there(away)
                    futures.append(pool.submit(ask))
                    try:
                        for future in futures:
                            future.result()
                    except BaseException:
                        cancel.set()
                        raise

            results, where, pieces_left = [None] * count, [None] * count, _Pieces(range(count))
            pull(hold.pieces if hold else 0 if away else count)
            # Those on the helper held none of this host's memory, nor needed its CPU.
            ran = [result for result, there in zip(results, where) if result and not there]
            if ran and not any(
                    result[2] or result[0] == SUITE_BUSY for result in results if result):
                measure.save(path, len(ran), None if hold and hold.waited else
                             min(len(ran), hold.pieces if hold else count))
            named = {}    # by index, a piece red on a machine: what it printed there, its tests
            if any(where) and log is not None and not pieces_left.lost and all(
                    result and not result[0] and not result[2] for result in results):
                log(f"every piece passed on the suite helper {next(filter(None, where)).alias}"
                    f"{' and this host' if not all(where) else ''}")
            again, joined, retried = [], [None], set()
            settled = False

            def elsewhere():    # asked while waiting for a turn here
                said = []
                if pieces_left.waiting:
                    joined[0] = helper.start(cpu, mem, cwd, said.append, there_command)[0]
                if joined[0]:
                    files.callback(helper.finish, joined[0])
                    for line in said if log else ():
                        log(line)
                return joined[0]

            def turn_here():    # as busy_turn's: no ceiling is charged with the wait
                nonlocal hold, deadline, env
                joined[0] = None
                began = time.monotonic()
                hold = _GATE_HELD.hold = _GATE_HELD.home(elsewhere)
                queued = time.monotonic() - began
                deadline += queued
                if on_wait is not None:
                    on_wait(queued)
                env = suite_env(times)

            def wait_busy():
                nonlocal hold, deadline, env
                queued = busy_turn(run_dir, activity, log, command, cwd)
                deadline += queued
                if on_wait is not None:
                    on_wait(queued)
                hold = getattr(_GATE_HELD, "hold", None)
                if hold is not None:
                    hold.alone()
                env = suite_env(times)

            # What a machine failed or stopped runs again here, a stopped piece alone, below; what
            # it lost or had no room for, on the first machine with room, this one included. The
            # tests a red piece named go first, at once, one piece at a time, taking no turn: they
            # cost what a model's own test does, which takes none, where a turn was over an hour
            # away (30 Oct 2026). One repeat failure settles the suite; later named reds keep
            # their helper output. Whatever then runs whole here waits for this host's turns.
            while not cancel.is_set():
                fresh = []
                for index, there in enumerate(where):
                    if index in again or not there or not results[index][0] or results[index][2]:
                        continue
                    again.append(index)
                    if log is not None:
                        # its go here takes its place in the suite's output: a copy keeps this one
                        handle, kept = tempfile.mkstemp(dir=run_dir or activity.parent,
                                                        prefix=f"{activity.stem}-helper-failed-",
                                                        suffix=".log")
                        os.close(handle)
                        shutil.copyfile(results[index][1].name, kept)
                        log(f"WARN AK_SHARD={index + 1}/{count} failed on the suite helper; "
                            f"what it printed there: {kept}")
                    if tests := helper.failed(there, f"{index + 1}/{count}"):
                        named[index] = results[index][1], tests
                        fresh.append(index)
                for index in fresh:
                    if settled:
                        break
                    retried.add(index)
                    shard = f"{index + 1}/{count}"
                    while True:
                        results[index] = attempt(shard, named[index][1])
                        code, _, killed, tests = results[index]
                        if code != SUITE_BUSY or killed or cancel.is_set():
                            break
                        wait_busy()
                    if (code > 0 and code != SUITE_BUSY and not killed and tests
                            and shard not in starved):
                        settled = True
                if hold is not None or not (
                        set(again) - set(named) or pieces_left.waiting) or over():
                    break
                turn_here()
                if not joined[0]:
                    break
                away = joined[0]
                pull(hold.pieces if hold else 0)
            if not cancel.is_set():
                if pieces_left.waiting:
                    pull(hold.pieces if hold else len(pieces_left.waiting))
                if whole := [index for index in again if index not in named]:
                    attempts(whole)
            for index in pieces_left.waiting:    # stopped before it ran
                results[index] = attempt(f"{index + 1}/{count}")
            hold = getattr(_GATE_HELD, "hold", None)
            if hold is not None:
                hold.alone()
            chunks, red, flakes, alones = [], [], [], {}

            def goes(index):
                """Piece `index`'s goes after its first, as `go_again` runs them: it yields what
                each runs, its named tests or None for the whole piece, and is sent its end."""
                code, piece, killed, tests = results[index]
                shard = f"{index + 1}/{count}"
                failed = only = alone = None
                how = "failed"
                if shard in silenced and not cancel.is_set():
                    # stopped at its suite's pace: once more alone, with the rest of the limit
                    piece.seek(0)
                    failed, how = piece.read(), f"was stopped after {silence / 60:g} min of silence"
                    code, piece, killed, tests = yield None
                elif shard in starved and not cancel.is_set():
                    code, piece, killed, tests = yield None
                if index in named:    # its tests the helper named, run alone here
                    there, only = named[index]
                    there.seek(0)
                    failed = there.read()
                    how = f"failed on the suite helper {where[index].alias}"
                while not killed and not cancel.is_set():
                    if code == SUITE_BUSY:
                        wait_busy()
                    elif shard in starved:
                        break   # the host's red, never a test's (`land.red_part`)
                    elif only is not None:
                        # Failing again alone, the tests the piece named confirm it red in a
                        # fraction of its time; passing, the whole piece decides, as a failure
                        # can need the tests that ran before it, and a runner that stops at its
                        # first failure names none of those it never reached.
                        alone = ("its failed tests failed again, run alone" if code else
                                 "its failed tests passed run alone: the failure needs the "
                                 "tests that ran before them")
                        if code:
                            if confirmed is not None:
                                confirmed[shard] = tests
                            break
                        # passing alone, they failed, then passed, whatever the piece does next
                        piece.seek(0)
                        flakes.append(flaky_record(f"{command} (AK_SHARD={shard})", failed,
                                                   piece.read(), activity, run_dir, log, how))
                        if flaky is not None:
                            flaky.extend(only)
                        only = None
                    elif not code:
                        break
                    elif failed is None:
                        piece.seek(0)
                        failed = piece.read()
                        only = tests or None
                    else:
                        break
                    code, piece, killed, tests = yield only
                if failed is not None and code == 0 and alone is None:
                    piece.seek(0)
                    flakes.append(flaky_record(f"{command} (AK_SHARD={shard})", failed,
                                               piece.read(), activity, run_dir, log, how))
                results[index] = code, piece, killed, tests
                alones[shard] = alone

            def go_again(which):
                """The goes the pieces at `which` ask for (`goes`), until none asks another: named
                tests one piece at a time, then the whole pieces at once, on turns here taken as
                their first ones were (`_GateHold.suite`, `attempts`): a turn kept for each from
                its first go would sit idle while most are settled by their named tests."""
                going, asked = {index: goes(index) for index in which}, {}

                def answer(index, ended=None):
                    try:
                        asked[index] = going[index].send(ended)
                    except StopIteration:
                        del going[index]

                for index in which:
                    answer(index)
                while going:
                    for index in sorted(going):
                        while index in going and asked[index] is not None:
                            answer(index, attempt(f"{index + 1}/{count}", asked[index]))
                    if not going:
                        break
                    if hold is None and not over():
                        turn_here()
                    if hold is not None:
                        hold.suite((cpu, mem))
                    whole = sorted(going)
                    attempts(whole)
                    if hold is not None:
                        hold.alone()
                    for index in whole:
                        answer(index, results[index])

            # Later named reds keep their helper output.
            alones.update((f"{index + 1}/{count}", None) for index in named if index not in retried)
            ours = [index for index in range(count) if index not in named or index in retried]
            # Stopped for silence or killed for memory beside its siblings, a piece goes again
            # alone, after them: its first go may have lacked what they used.
            last = [index for index in ours if f"{index + 1}/{count}" in silenced | starved]
            go_again([index for index in ours if index not in last])
            for index in last:
                go_again([index])
            # The shares rest on how many ended red, known only now, reruns included.
            reds = sum(1 for code, _, _, _ in results if code)
            red_share, share = shares(reds, count - reds + len(flakes))
            flakes = [flaky_text(record, share) for record in flakes]
            for index, (code, piece, killed, _) in enumerate(results, 1):
                shard = f"{index}/{count}"
                text = turns.cut_file(piece, 0, run_dir or activity.parent,
                                      f"{activity.stem}-AK_SHARD-{shard.replace('/', '-of-')}",
                                      red_share if code else share)
                if code and not killed and alones[shard]:
                    text = f"{alones[shard]}\n{text}"
                ended = ("killed at the limit" if killed else OUT_OF_MEMORY
                         if shard in starved else f"exit {code}")
                # Existing failure diagnostics read the last output; leave a red piece last.
                (red if code else chunks).append(f"--- AK_SHARD={shard} ---\n"
                    f"[{ended}]\n{text}".rstrip())
            if not any(where) and not any(killed for _, _, killed, _ in results):
                measure.paced(path, count)
            measure.overflowed(path, mem)
            text = "\n\n".join(chunks + red + flakes)
            output.write(("\n" + text + "\n").encode())
            output.flush()
            if pieces is not None:
                for index, (code, _, killed, _) in enumerate(results, 1):
                    share = f"{index}/{count}"
                    pieces[share] = None if killed else OUT_OF_MEMORY if share in starved else code
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
                  confirmed=None, flaky=None, checked=None, exits=None, timings=None,
                  absent=None):
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
    never the text, which a command can print anything into. `exits` keeps each piece's attempt
    exits as a list (None for a kill), before coverage validation, so names cannot hide a flake.
    `pieces`, a dict, gets the same
    for each sharded command's pieces, by command then share (`run_suite`); `shard` runs
    every command as that one piece alone, a command like any other, its re-run included,
    and with `only` just those of its tests.  `confirmed`, a dict, gets by command what
    `run_suite` confirms: the tests a red piece named that failed again alone, and `flaky`, a
    list, the tests it found failing, then passing, those a command run whole named failed
    before its re-run passed among them.  `checked`, a check's `(run directory, round, kind,
    tree)`, has each run of a command, or of a piece of one, leave its row in history
    (`history.check`), a re-run one of its own.
    The test files' times the commands printed are kept (`suite_times`) before the log, whole
    until then, takes `text`, its capped form. `timings`, a dict, gets each passing command's
    ({file: seconds}, piece count) from this pass alone, before that cap.  `absent` is
    `run_suite`'s, for one command.
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
    asked = time.time()     # the first command's wait holds the heavy-suite turn's; a later
                            # one is asked for as the one before it ends
    with (gate_turn(run_dir, log_path, log, suite, cwd)
          if heavy or suite else nullcontext()):
        deadline = time.monotonic() + limit
        def waited(seconds):
            nonlocal deadline
            deadline += seconds
        log_path.write_text("")
        for cmd in cmds:
            first_span = None   # the gate log's byte span of a first run that failed, while its
                                # re-run decides: the flaky diff reads whole runs
            named = []          # the tests this command's run named failed
            reds = {} if confirmed is not None or checked is not None else None
            flakes = [] if flaky is not None or checked is not None else None
            busy = False
            # stopped sooner at its suite's pace on its first go; a second has the rest
            window = quiet_window(cmd, cwd, run_dir, silence) if heavy else None
            rest = silence - (window or 0)
            how = "failed"
            raw = {} if exits is not None or timings is not None else None
            while True:
                run_record.stop_check(run_dir)
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                # a suite split into pieces leaves a row for each piece (`run_suite`)
                with log_path.open("ab") as progress, history.check(
                        None if split(cmd) else checked, cmd, asked) as ended:
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
                        only=only, confirmed=reds, flaky=flakes, named=named,
                        # Whole commands retry here; their named outcomes must wait for that.
                        checked=checked if split(cmd) else None, asked=asked, raw=raw,
                        absent=absent, used=ended)
                    ended["exit"] = None if killed else code
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
                asked = time.time()
                if code == 0 or first_span is not None or split(cmd):
                    break
                if killed:
                    if not window or reason[-1:] != ["silence"]:
                        break
                    how = f"was stopped after {window / 60:g} min of silence"
                    del reason[:], running[:]     # a stop of its second go is the one to name
                first_span, first, named = (offset, end), named, []
            if exits is not None:
                exits.extend(raw.values())
            if left <= 0 and first_span is None:
                # the list is out of time: starting this command would give it a limit of its own
                spent, killed, kept = cmd, False, ""
                chunks.append(f"$ {cmd}\n[not run: the done-when limit was already spent]")
                if marks is not None:
                    marks.append(None)
                break
            ok &= code == 0
            if timings is not None and code == 0 and not killed:
                timings[cmd] = suite_times.measured(log_path, offset), max(1, len(raw))
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
                chunks.append(flaky_text(flaky_record(cmd, failed, rerun, log_path, run_dir, log,
                                                      how)))
                if flakes is not None:
                    flakes.extend(first)
            if confirmed is not None:
                confirmed.setdefault(cmd, {}).update(reds)
            if flaky is not None:
                flaky.extend(flakes)
            if not split(cmd):
                history.test_reds(checked, reds, flakes)
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
    suite_times.keep(cwd, log_path)
    log_path.write_text(text)
    # The gate is over and its children are not the round's: a command that exited 0 may
    # still have left processes behind, and they die with the gate, however detached.
    worker.kill_marked(gitcall.run_child_env().get(worker.RUN_MARKER), log=log)
    artifacts.update(set(gitcall.dirty_paths(cwd)) - before)
    return ok, text


def run_round(cmds, cwd, log_path, artifacts, limit, log, silence, run_dir, checked=None):
    """A round's done-when list, on the suite helper first: one piece of the tree at HEAD, so a
    command reads what an earlier one left untracked, at the size of a piece of the repository's
    `tests:` suite, taking no heavy turn here.  Green there is the whole answer.  Anything else
    -- no helper, no recipe, no room, a red, the helper failing -- runs the list here at once
    (`run_done_when`), and that decides, below what the piece printed there.  A list naming
    AK_SHARD runs here, as a suite has its own way there (`run_suite`).  `checked` is as
    `run_done_when` takes it: the list on the helper leaves one row."""
    say, there, asked = log or (lambda line: None), "", time.time()
    if cmds and not any(map(names_shard, cmds)):
        cost = suite_cost(gitcall.declared(cwd, "tests") or "", cwd, run_dir)[1:]
        # Each command's header is no record (`$ cmd`, then its exit): those are counted.
        script = "\n".join(f"printf '%s\\n' {shlex.quote(f'--- $ {cmd} ---')} && "
                           f"bash -c {shlex.quote(cmd)} || exit" for cmd in cmds)
        there_command = pinned(script, suite_times.handed(cwd))
        away, why = helper.start(*cost, cwd, lambda line: None, there_command)
        if away:
            say(f"done-when on the suite helper {away.alias}, as one piece")
            try:
                run_record.stop_check(run_dir)    # a stop marked while it prepared starts none
                with log_path.open("wb") as progress, history.check(
                        checked, "\n".join(cmds), asked, away.alias) as ended:
                    code, _, killed = worker.limited(
                        helper.piece(away, "1/1", there_command),
                        limit, cwd=str(cwd), activity=log_path, output=progress,
                        env=suite_env(), silence=silence, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL)
                    ended["exit"] = None if killed else code
            except OSError as exc:
                # It never started (a list longer than one ssh argument may be): the shell's 126.
                log_path.write_text(f"{exc}\n")
                code, killed = 126, False
            finally:
                helper.finish(away)
            run_record.stop_check(run_dir)
            suite_times.keep(cwd, log_path)
            with log_path.open("rb") as progress:
                out = turns.cut_file(progress, 0, run_dir or log_path.parent, log_path.stem)
            there = (f"On the suite helper {away.alias}, as one piece: "
                     f"[{'killed at the limit' if killed else f'exit {code}'}]\n{out}").rstrip()
            # A command that needs this host (its network, a file only it holds) is only
            # slower: red in the helper's offline VM, it runs here, which decides.
            if not code:
                text = "\n\n".join([there, *(f"$ {cmd}\n[exit 0]" for cmd in cmds)])
                log_path.write_text(text)
                return True, text
            why = f"helper {away.alias} " + ("stopped it at its limit" if killed else
                                              helper.failure(code))
        say(f"done-when runs here: {why}")
    ok, text = run_done_when(cmds, cwd, log_path, artifacts, limit, log, silence=silence,
                             run_dir=run_dir, checked=checked)
    if there:
        text = f"{there}\n\n{text}"
        log_path.write_text(text)
    return ok, text


def release_turn():
    """Let this thread's turn go so the next check takes a fresh one."""
    hold, _GATE_HELD.hold = getattr(_GATE_HELD, "hold", None), None
    if hold is not None:
        hold.release()
