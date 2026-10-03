"""Check commands and the host-wide heavy-suite turn."""

import fcntl
import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path

from . import config, history, host, orch, run, watch, worker
from . import record as run_record

_GATE_HELD = threading.local()     # the gate turn this thread holds now, if any


GATE_POLL = 15      # seconds between a waiting gate's tries for a turn; each rewrites its log line
HEAVY_CPUS = 0.7      # one heavy suite's measured cost: ~0.7 core and ~0.4 GB, its own
HEAVY_MEM_MB = 410    # Postgres, port and temp dir, so twice the headroom fits twice the suites
SUITE_BUSY = 75       # sysexits' EX_TEMPFAIL: a heavy suite's own host-wide lock is another copy's


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
    this process's pid, as the merge turn's mark is, and the wait's start, so a
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
    """One held gate turn: the open slot files and the one this thread locked.

    The hold owns its files rather than the frame that waited for them, so a fixer
    or a reviewer lets it go from inside the frame that took it.  Releasing unlocks
    the slot and closes the files, as leaving the frame would have.
    """

    def __init__(self, files, slot):
        self.files, self.slot = files, slot

    def release(self):
        try:
            if self.slot is not None:
                fcntl.flock(self.slot, fcntl.LOCK_UN)
        finally:
            self.slot = None
            held = getattr(_GATE_HELD, "count", 0)
            if held:
                _GATE_HELD.count = held - 1
            self.files.close()


def derived_heavy_limit(readings=None, running=None):
    """Running suites plus how many more the live headroom fits; at least one.

    The slice's idle cores over one suite's 0.7, and its free memory over 0.4 GB,
    whichever fits fewer.  Headroom already excludes running suites, so add
    them once; a saturated slice starts one only when none run.  Both come
    off the slice's own cgroup -- its CPU room and the slice's memory headroom --
    which a shell beside the slice reads like a worker inside it; where
    no slice answers, the host's idle cores and free memory stand in.  An
    unreadable gate fails open to the other resource, and to one suite where
    neither answers.
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
        unit = host._unit_memory(readings)
        if unit is not None:
            mem_free = unit[1] - unit[0]
        else:
            mem_free = host._reading(readings, "free_mb", "mem_available_mb", "mem_available")
    candidates = []
    if cpu_free is not None:
        candidates.append(int(cpu_free / HEAVY_CPUS))
    if mem_free is not None:
        candidates.append(int(mem_free / HEAVY_MEM_MB))
    if not candidates:
        return 1
    return max(1, running + max(0, min(candidates)))


def _acquire_gate_turn(run_dir, log_path, log):
    """Wait for and hold one host-wide heavy-suite turn; None when no turn is taken."""
    record = run_record.read_state(run_dir) or {} if run_dir else {}
    repo = record.get("repo")
    is_landing = bool(record.get("landing"))
    landing_since = _first_landing_wait(run_dir) if run_dir else None
    self_id = run_dir.name if run_dir else None
    if not repo or os.environ.get("AK_MAX_RUNS") == "0":
        return None
    said_bad = []
    config.RUNS.mkdir(parents=True, exist_ok=True)
    files = ExitStack()
    try:
        slots = []
        def admit():
            try:
                pinned = config.max_gates()
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
            new_limit = pinned if pinned is not None else derived_heavy_limit(readings, held)
            while len(slots) < new_limit:
                slots.append(files.enter_context(gate_lock(repo, len(slots)).open("a")))
            candidate = take_slot(slots[:new_limit]) if held < new_limit else None
            for fh in temp:
                if fh is not candidate:
                    fcntl.flock(fh, fcntl.LOCK_UN)
            return candidate, new_limit, held
        slot, limit, held = admit()
        if not limit:
            files.close()
            return None
        me_since = landing_since if is_landing and landing_since is not None else time.time()
        if slot is None or _gate_waiter_before(repo, self_id, me_since, is_landing):
            if slot is not None:
                fcntl.flock(slot, fcntl.LOCK_UN)
                slot = None
            began = time.monotonic()
            said = f"waiting for a heavy suite turn · {held} running · {max(0, limit - held)} more fit"
            if log is not None:
                log(f"done-when: {said}")
            waited_since = mark_gate_wait(run_dir, repo)
            if waited_since is None:
                waited_since = me_since if is_landing else time.time()
            step = history.close_step(run_dir.name)     # the wait is no step's work
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
                    if slot is None:
                        continue
                    if _gate_waiter_before(repo, self_id, waited_since, is_landing):
                        fcntl.flock(slot, fcntl.LOCK_UN)
                        slot = None
                        continue
                    break
            finally:
                mark_gate_wait(run_dir, None)
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
    return _GateHold(files, slot)


@contextmanager
def gate_turn(run_dir, log_path, log):
    """One host-wide heavy-suite turn, held for as long as the list runs.

    Only the heavy suite -- the `# once` line, the repository's `tests:` suite --
    takes one at landing; every other done-when command
    runs without.  A
    suite builds its own Postgres, port and temp dir at ~0.7 core and ~0.4 GB, so
    a suite starts when the slice's live headroom fits one more, or none run,
    counting running suites once; an explicit
    `max_gates` pins the count instead.  A turn is a flock on one of the host's
    slot files, which the kernel lets go of when its holder dies, so a killed
    suite never blocks the next.  A waiting suite rewrites its own log every poll,
    so the stall ladder reads the wait as life, and says so on its record for `ak
    run status`; the ceiling starts once the turn is its own, and a stop lands
    while it waits as it does mid-list.  A run without a repository, a direct
    caller with no record, the test suites' `AK_MAX_RUNS=0` and `max_gates = 0`
    all take no turn.  The limit is re-read on every poll, so a changed pin or a
    changed headroom reaches runs already queued.  A freed turn goes to the waiter
    that has waited longest among the highest rank, a landing run before any round
    check, whether `--first` or not: a suite takes a free turn only when no waiter
    ranks before it, and a lander's wait counts from the start of its first landing
    wait.
    A home config this cannot read -- it is read here, mid-run, so one hand-edit
    typo would fail the next suite of every running run -- means a derived count,
    and a log line naming the problem.
    A check running while this thread already holds a turn takes no second one.
    """
    if getattr(_GATE_HELD, "hold", None) is not None:
        yield
        return
    hold = _acquire_gate_turn(run_dir, log_path, log)
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
    if getattr(_GATE_HELD, "hold", None) is not None:
        env["AK_HEAVY_TURN"] = "1"
    return env


def busy_turn(run_dir, log_path, log):
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
    _GATE_HELD.hold = _acquire_gate_turn(run_dir, log_path, log)
    log_path.write_bytes(kept)
    return time.monotonic() - began


def flaky_key(line):
    """Ignore varying values without depending on a suite's failure words.

    Absolute paths can have a different temporary root on each run; relative test names stay.
    """
    return re.sub(r"(?<![\w.])/[^\s'\"`<>]+|"
                  r"\b(?:0x[0-9a-f]+|[0-9a-f]{8,}(?:-[0-9a-f]+)*)\b|"
                  r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", "<varying>", line, flags=re.I)


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

    with gate_turn(run_dir, log_path, log) if heavy else nullcontext():
        deadline = time.monotonic() + limit
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
                    code, _, killed = worker.limited(
                        ["bash", "-c", cmd], left, silence=silence, activity=log_path,
                        on_timeout=stopped, cwd=str(cwd), output=progress,
                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=suite_env())
                    end = progress.tell()
                if log is not None and run_dir is not None:
                    run.memory_cap_note(run_dir, log)
                with log_path.open("rb") as progress:
                    progress.seek(max(offset, log_path.stat().st_size - run.OUT_CAP))
                    out = progress.read().decode("utf-8", errors="replace")
                if heavy and code == SUITE_BUSY and not killed:
                    if log is not None and not busy:
                        log(f"done-when: busy: {cmd} exited {SUITE_BUSY}; it runs again "
                            "each poll, its heavy suite turn given back meanwhile")
                    busy = True
                    deadline += busy_turn(run_dir, log_path, log)
                    continue
                if code == 0 or killed or first is not None:
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
                          f"{out[-run.OUT_CAP:]}".rstrip())
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
                # The gate log is replaced below and can be reused by later checks;
                # each flake needs a file of its own that a follow-up can still read.
                with tempfile.NamedTemporaryFile(dir=run_dir or log_path.parent,
                                                 prefix=f"{log_path.stem}-failed-",
                                                 suffix=".log", delete=False) as saved:
                    saved.write(failed)
                failed_path = Path(saved.name).resolve()
                lines = [line for line in failed.decode("utf-8", errors="replace").splitlines()
                         if line.strip()]
                # the failure is what the failed run said that its passing re-run did not:
                # a tally and a passing tail both repeat, so the last lines alone name neither
                reran = {flaky_key(line) for line in
                         rerun.decode("utf-8", errors="replace").splitlines()}
                diff = [line for line in lines if flaky_key(line) not in reran][:20]
                chunks.append("\n".join([f"flaky: {cmd} failed, then passed on its re-run",
                                         f"failed output: {failed_path}", *diff]))
                if log is not None:
                    log(f"done-when: flaky: {cmd} failed, then passed on its re-run")
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
            cause = (f"{silence / 60:g} min of silence" if reason == ["silence"] else
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
