"""`ak run stop` and `ak run clean`: ending a run deliberately, and what a seat's stop takes.

A stop writes the record first, then ends the loop and everything it started, then takes
the checkout unless kept. `ways_out` names the commands that settle a parked run.
`recorded_ending` decides whether recorded work lets a seat's turn end.
"""

import os
import subprocess
import time
from pathlib import Path

from . import config, handback, leases, orch, run, transitions, watch, worker, worktrees
from . import job as jobs
from . import record as run_record


def _ending_work(name, records):
    """The run census and this seat's records, keeping native reads and supplied reads apart."""
    supplied = records
    if records is None:
        try:
            records = [(directory, run_record.read_state(directory) or {})
                       for directory in run_record.run_dirs()]
        except OSError:
            records = []
    mine = []
    for directory, state in records:
        owner = state.get("launched_session") or state.get("session")
        if supplied is not None or owner != name:
            try:
                owner = transitions.launched_session(state)
            except config.Error:
                continue
        if owner == name:
            mine.append((directory, state))
    return records, mine


def owed(name):
    """Whether the seat owes work: a line in its plan it owes (`plan.owed`), or a plan nothing
    can read, which proves nothing done.  Read without the plan's lock:
    a harness hook never waits on it, and every plan write is a whole-file replace."""
    return owed_line(name) is not None


def owed_line(name):
    """The first line the seat owes, in its plan's own words; "" for a plan nothing can read,
    which proves nothing done either; None where it owes nothing."""
    from . import plan
    try:
        for line in plan.lines(name):
            if plan.owed(name, line):
                found = plan.LINE.match(line.strip())
                return found["what"] if found else plan.BOX.sub("", line, count=1).strip()
    except config.Error:
        return ""
    return None


DONE_ASKING = ("Your plan is done: every line is proven, and the owner has written nothing since, "
               "so a question would hold only their attention. Say it in your last message "
               "instead; they read it when they come back.")


def question_refused(name):
    """Why the seat's question prompt goes nowhere, or None where it may ask: its plan is done
    (`plan.finished`) and the owner has written nothing in its conversation since the plan's
    last write, which ticked its last line, so the question would block nothing but the owner.
    A word from the owner since opens new work to align on, and a run of its own parked
    undecided is the seat's to settle, which the owner may be asked about."""
    from . import notify, plan
    if plan.finished(name) is None:
        return None
    try:
        done_at = plan.path(name).stat().st_mtime
    except (OSError, config.Error):
        return None     # a plan nothing can date proves nothing done
    if any(at > done_at for at in notify.owner_said(name)):
        return None
    if _parked(*_ending_work(name, None)):
        return None
    return DONE_ASKING


def _parked(records, mine):
    """Those of the seat's runs parked undecided: ended unsettled, or stalled."""
    return [(directory, state) for directory, state in mine
            if (not transitions.going(state) or state.get("state") == "stalled")
            and transitions.unfinished(state, records)]


def recorded_ending(name, records=None, *, question=False, since=None):
    """(the turn may end, parked records), from the evidence its caller can see.

    The native hook reads parked work, then the plan, then fresh wait receipts; the tick
    supplies its existing census. A question stands past an unnamed seat's name
    (`config.name_owed`), which holds everything else, and past parked work, which holds a
    plan that owes nothing and every live wait. `since` retains the prompt hook's wait on
    work launched in this turn even after it ends.
    """
    if question:
        return True, []
    if config.name_owed(name):
        return False, []
    supplied = records
    records, mine = _ending_work(name, records)
    parked = _parked(records, mine)
    if parked:
        return False, parked
    if not owed(name):
        return True, []     # nothing is owed: no open line in the plan, so the stop stands
    if supplied is None:
        _, mine = _ending_work(name, None)
    for _, state in mine:
        if transitions.going(state) or watch.awaiting_live(state):
            return True, []
        if since is not None and state.get("state") not in ("error", "waiting"):
            for key in ("started_at", "queued_at"):
                stamp = watch._stamp(state.get(key))
                if stamp is not None and stamp >= since:
                    return True, []
    return bool(jobs.job_waiting(name) or watch.waiting_on(name)), []


def stoppable(state):
    """Whether `ak run stop` takes this run: unfinished work, or an `error`.

    `error` reads ended but the tick retries it hourly: stopping one is its owner's off-switch
    for the ladder, the way stopping a waiting run ends its wait.  So is a run stopped to wait
    on an older run's change (`leases.parked`): stopping it calls off the tick's restart.
    Every other ending sits inert, so there is nothing to stop.
    """
    return (state.get("state") not in run_record.ENDED or state.get("state") == "error"
            or leases.parked(state))


def ways_out(state, run_dir):
    """The commands that settle a parked run, each only where it is taken.

    `ak run status` marks an ending looked at (`mark_looked_at`), `ak run stop` ends what is
    `stoppable`, and `ak run resume` carries on what `resume_run` would: a FAIL at its round
    budget only with the `--rounds` its `continue_line` names, and nothing whose checkout is
    gone.
    """
    run_id = Path(run_dir).name
    ways = [f"ak run status {run_id}"] if state.get("state") in run_record.ENDED else []
    if transitions.failed_at_budget(state):
        onward = transitions.continue_line(state, run_dir)
        ways += [onward.removeprefix("continue: ")] if onward else []
    elif not state.get("worktree") or Path(state["worktree"]).is_dir():
        ways.append(f"ak run resume {run_id}")
    if stoppable(state):
        ways.append(f"ak run stop {run_id}")
    return ways


def cmd_clean(argv):
    if len(argv) != 1:
        raise config.Error("usage: ak run clean <runid>")
    run_dir = config.RUNS / argv[0]
    if not (run_dir / "run.json").exists():
        raise config.Error(f"no such run: {argv[0]} (looked in {config.RUNS})")
    state = run_record.read_state(run_dir)
    if state is None:
        raise config.Error(f"{argv[0]}: cannot read {run_dir / 'run.json'}")
    if state.get("scratch"):
        workspace = state.get("worktree")
        if not isinstance(workspace, str) or not Path(workspace).is_dir():
            print(f"{argv[0]}: its workspace is gone; result.md lists what was there")
            return 0
        print(f"{argv[0]}: ran in the scratch workspace {workspace}; its files are "
              "the deliverable, so nothing is removed")
        return 0
    repo, worktree = state.get("repo"), state.get("worktree")
    if not repo or not worktree:
        raise config.Error(f"{argv[0]}: run.json records no worktree; nothing to remove")
    wt = Path(worktree)
    if wt == Path(repo):
        print(f"{argv[0]}: ran with --no-worktree; nothing to remove")
        return 0
    told = []
    if not worktrees.stop_checkout(state, told.append, keep_branch=True):
        raise config.Error(f"{argv[0]}: " + "; ".join(line.removeprefix("WARN ") for line in told))
    print(f"{argv[0]}: removed worktree {wt}; branch {state.get('branch', '?')} kept")
    return 0


def marker_pids(run_id):
    """Pids still carrying this run's marker, except this process and its ancestors."""
    return worker.marked_pids(worker.run_marker(run_id))


def stop_owned_runs(name):
    """Stop every unfinished run this seat launched, the way `ak run stop` stops one.

    The first half of a seat stop, run before the seat's lock: each run costs up
    to STALL_KILL_WAIT inside kill_tree, and nothing it touches is the seat's
    state. A run that refuses is named and left; the seat still ends.
    """
    try:
        dirs = run_record.run_dirs()
    except OSError:
        return
    for run_dir in dirs:
        try:
            state = run_record.read_state(run_dir)
        except (OSError, ValueError):
            continue
        if not state:
            continue
        try:
            if transitions.launched_session(state) != name:
                continue
        except config.Error:
            continue
        if state.get("state") not in run_record.ENDED or leases.parked(state):
            try:
                cmd_stop([run_dir.name])
            except config.Error as exc:
                print(f"could not stop {run_dir.name}: {exc}")
            except (OSError, ValueError, KeyError, TypeError):
                print(f"could not stop {run_dir.name}")


def release_session(name):
    """Stop every unfinished run this seat launched, and drop every checkout it still owns.

    Run directories stay for their results. Browser tabs the seat or those runs
    opened close here; a tab with no recorded opener is not theirs to close.
    The branches go with the checkouts: ending the seat is the deliberate stop
    that takes everything connected to it.
    """
    from . import browser
    stop_owned_runs(name)
    ids = []
    try:
        dirs = run_record.run_dirs()
    except OSError:
        dirs = []
    for run_dir in dirs:
        try:
            state = run_record.read_state(run_dir)
        except (OSError, ValueError):
            continue
        if not state:
            continue
        try:
            if transitions.launched_session(state) != name:
                continue
        except config.Error:
            continue
        ids.append(run_dir.name)
        if state.get("state") in run_record.ENDED:
            if not worktrees.drop_checkout(state, lambda _message: None, keep_branch=False):
                continue
            # the branch went with the checkout: the status row reads this mark,
            # since only a stop without `--keep` says so on its own
            try:
                with run_record.recovery_lock(run_dir):
                    current = run_record.read_state(run_dir) or state
                    current["branch_removed"] = True
                    run_record.save_state(run_dir, current)
            except (OSError, ValueError, TypeError):
                pass
    try:
        browser.close_owned(session=name, runs=ids)
    except (OSError, ValueError, TypeError):
        pass


def stop_line(run_id, branch, kept):
    """The one line a stop prints: what ended, and -- when kept -- the `from:` line.

    The `from:` line is only advertised while its branch exists to relaunch from;
    a removed branch leaves the run's name on the line and nothing unusable after it.
    """
    if not branch:
        return f"stopped {run_id}"
    if not kept:
        return f"stopped {run_id}: branch {branch} removed"
    return f"stopped {run_id}: branch {branch} kept; relaunch with from: {branch}"


def end(run_dir, *, keep, why, log=None, extra=None, owner_check=False, only_if=None):
    """End that run: its record first (`stopped`, under the lock, `why` its error and `extra`
    on it), then its loop and everything it started, then its checkout unless `keep`.  The
    state as recorded; a run already stopped as it stands; None where the run had ended
    already, or where `only_if` no longer holds of the record read under the lock, so there
    was nothing to stop.  `owner_check` is the command's: only the seat a run belongs to stops
    it by hand, while ak's own stops (`leases.park`) are anybody's."""
    run_id = run_dir.name
    log = log or run.note_in(run_dir / "log.txt")
    with run_record.recovery_lock(run_dir):
        current = run_record.read_state(run_dir) or {}
        if owner_check:
            config.check_stop_owner(current.get("launched_session") or current.get("session"))
        if current.get("state") == "stopped" and not stoppable(current):
            return current
        if not stoppable(current) or (only_if and not only_if(current)):
            return None
        kept = bool(keep or not worktrees.checkout_removable(current))
        current.update(state="stopped", verdict="STOPPED", finished_at=time.time(),
                       error=why, reported=True, stop_kept=kept)
        for key in ("recovery_pending", "recovery_notified", "recovery_acknowledged_at",
                    "lease_wait", "handback_pending", "handback_wait_reason", "handback_note",
                    "notification_pending", "pending_inbox", "quota_dry", "refusal_retry",
                    "waiting_for", "login_resume_at", "login_back_at", "stall_resume_at",
                    "resume_after", "error_retry_at", "error_retries", "waiting_on",
                    "waiting_resume_at", "slot_waiting", "launch_pending", "resume_from"):
            current.pop(key, None)
        current.update(extra or {})
        run_record.save_state(run_dir, current)
        transitions.history_finish(current, log)
        try:
            handback.redress_seat(transitions.launched_session(current))
        except config.Error:
            pass
        try:
            handback.record_result(run_dir, current, log)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        state = current
    # The scope where one exists, else the tree by the run's marker -- in practice both,
    # so a scope that refused to stop still loses its processes, and a plain start loses
    # nothing by the scope attempt missing.  The record already says stopped, so whatever
    # notices the dead children aborts instead of replacing them.
    pid = state.get("pid")
    if orch.user_manager() and pid == os.getpid():
        # this process is the run's loop, parking itself at its commit step (`leases.park`):
        # a waited stop of its own unit would end it here, before its save raises the stop
        orch.stop_scope(f"agentkit-run-{run_id}", log, wait=False)
    elif orch.user_manager():
        unit = f"agentkit-run-{run_id}"
        for suffix in (".scope", ".service"):
            try:
                subprocess.run(["systemctl", "--user", "stop", f"{unit}{suffix}"],
                               capture_output=True, encoding="utf-8", errors="replace",
                               env=orch.bus_env(), timeout=orch.SLICE_WAIT)
            except (OSError, subprocess.SubprocessError):
                pass
    # Only a run of its own is ended by its tree: a task whose pid is still its live
    # scheduler's is ended by its marker below, and a task resumed by hand -- a new
    # pid under an old stamp -- is ended by its tree like any run of its own.
    if not jobs.job_scheduler_owns(run_id, state) and isinstance(pid, int) and pid > 0 \
            and pid != os.getpid() and run_record.process_active(state):
        try:
            watch.kill_tree(pid, log)
        except (OSError, ValueError):
            pass
    for member in marker_pids(run_id):
        try:
            watch.kill_tree(member, log)
        except (OSError, ValueError):
            pass
    if not keep and not worktrees.stop_checkout(state, log):
        # The checkout is still there -- a live loop, or a git that said no --
        # so the branch stays with it, and the record says kept: `from:` carries
        # that committed work into a relaunch the same way `--keep` does. Read
        # back under the lock: the dict above predates the kill by whole seconds.
        state["stop_kept"] = True
        try:
            with run_record.recovery_lock(run_dir):
                current = run_record.read_state(run_dir) or state
                current["stop_kept"] = True
                run_record.save_state(run_dir, current)
        except (OSError, ValueError, TypeError):
            pass
    try:
        from . import browser
        browser.close_owned(run=run_id)
    except (OSError, ValueError, TypeError):
        pass
    log(f"stopped {run_id}")
    return state


def stop_job(job_dir, keep, *, why, owner_check=False, only_if=None, say=print):
    """End a whole job: its launcher, then every task left unfinished recorded stopped and the
    job finished, then each run of it still going as `end` ends one, so status reads it ended
    and gc collects it as any finished job.  `why` and `owner_check` are `end`'s, the check
    made of the job's seat as well; `only_if` is judged of the receipt read under the lock, and
    False says it no longer held, so nothing was stopped.  `say` takes the lines the command prints.

    The launcher is ended under the job's lock, which every write of the receipt takes
    (`jobs.save_job`): it holds the receipt in memory and starts any task still queued, so it
    is gone before the stop is written, and nothing writes the receipt back after.  Its runs
    are `jobs.job_runs`.  A second stop ends whatever the first left going.
    """
    with run_record.recovery_lock(job_dir):
        job = jobs.read_job(job_dir)
        if not job or not isinstance(job.get("tasks"), list):
            raise config.Error(f"{job_dir.name}: cannot read {jobs.receipt_path(job_dir)}")
        if only_if and not only_if(job):
            return False
        if owner_check:
            config.check_stop_owner(job.get("seat"))
        stopped = bool(job.get("finished_at"))
        if stopped and all(task.get("state") != "stopped" for task in job["tasks"]):
            raise config.Error(f"{job_dir.name} is already finished; "
                               "only unfinished work can be stopped")
        log = run.note_in(job_dir / "log.txt")
        orch.stop_scope(job.get("scope"), log)
        try:
            # read after the scope stop, which may have ended the launcher and freed its pid
            launcher_alive = bool(run_record.process_active(job))
        except (TypeError, ValueError, AttributeError, OSError):
            launcher_alive = False  # an old receipt with no pid to check, as a resume reads it
        if launcher_alive:
            watch.kill_tree(job["pid"], log)
        if not stopped:
            for task in job["tasks"]:
                if task.get("state") not in jobs.JOB_TERMINAL:
                    task.update(state="stopped", finished_at=time.time(),
                                verdict_line=f"{task['name']}: stopped")
            job["finished_at"] = time.time()
            jobs.save_job(job_dir, job)
    for run_dir, state in jobs.job_runs(job_dir, job):
        if not state:
            # left as it is, as `cmd_stop` leaves one: a stop written over it loses what it held
            say(f"{run_dir.name}: cannot read {run_dir / 'run.json'}; left as it is")
        elif stoppable(state):
            state = end(run_dir, keep=keep, why=why, owner_check=owner_check)
            if state:
                say(stop_line(run_dir.name, state.get("branch"), state.get("stop_kept", False)))
    say(f"{job_dir.name} is already stopped" if stopped else f"stopped {job_dir.name}")
    return True


def cmd_stop(argv):
    """End a run deliberately: its record first, then its loop and its checkout.

    The record goes first -- `stopped`, committed under the lock -- so a scheduler
    that notices its dead child finds the stop already there and aborts instead of
    replacing it.  Then the loop and everything it started: its systemd scope where
    one exists, else its process tree by the run's pid and its `AK_PARENT_RUN`
    marker.  The run reads `stopped`, a final state that is never resumed, never
    handed back and never cards anyone.  The worktree and the local branch go with
    it unless `--keep` keeps them for a relaunch from the printed `from:` line.
    """
    keep = "--keep" in argv
    args = [arg for arg in argv if arg != "--keep"]
    if len(args) != 1 or Path(args[0]).name != args[0] or args[0] in (".", ".."):
        raise config.Error("usage: ak run stop ID [--keep]")
    run_id = args[0]
    if jobs.receipt_path(config.JOBS / run_id).exists():
        stop_job(config.JOBS / run_id, keep, why="stopped by the user", owner_check=True)
        return 0
    run_dir = config.RUNS / run_id
    if not (run_dir / "run.json").exists():
        raise config.Error(f"no such run: {run_id} (looked in {config.RUNS})")
    state = run_record.read_state(run_dir)
    if state is None:
        raise config.Error(f"{run_id}: cannot read {run_dir / 'run.json'}")
    config.check_stop_owner(state.get("launched_session") or state.get("session"))
    if state.get("state") == "stopped" and not stoppable(state):
        print(stop_line(run_id, state.get("branch"), state.get("stop_kept", False)))
        return 0
    if not stoppable(state):
        raise config.Error(f"{run_id} is already {state.get('state')}; "
                           "only unfinished work can be stopped")
    log = run.note_in(run_dir / "log.txt")
    state = end(run_dir, keep=keep, why="stopped by the user", log=log, owner_check=True)
    if state is None:
        raise config.Error(f"{run_id} is already {(run_record.read_state(run_dir) or {}).get('state')}; "
                           "only unfinished work can be stopped")
    print(stop_line(run_id, state.get("branch"), state.get("stop_kept", False)))
    return 0
