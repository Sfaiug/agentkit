"""One model turn: how it ends, where a round keeps it, what it answered, and the memory its scope ran under.

A turn ends in one of a few ways a harness hands back -- Exhausted, Dead, Killed, Blocked,
NotNeeded, RanDry, CannotRun, TransientHandover -- each a class here.  The turn directories
of a round -- the executor's, the fixer's, the reviewer's, each attempt of each -- and the
answer file a turn leaves are read here, as is the memory cap a turn's scope ran under and
the stop of a run's process tree.  The call itself and its retries follow here from run.py.
"""

import os
import re
import threading
import time
from pathlib import Path

from . import hand_in, host, orch, record as run_record, worker


class Exhausted(Exception):
    pass


class QuotaDry(Exhausted):
    """Out of budget on every eligible provider: wait for a window, then resume."""


class Dead(Exception):
    """The executor outlived its retries: not a FAIL, because nothing was ever judged.

    Kept for the merge pipeline's older receipts; a transient answer never raises it now --
    the same session is resumed indefinitely instead, so there is nothing left to outlive.
    """


class Killed(Exception):
    """A worker turn killed by signal twice within a minute: a person must look.

    Not a death on the provider and not a FAIL -- nothing was executed and nothing was
    judged -- so the run parks as an interruption, resumable, reading `needs you` with the
    signal for a reason.  The session the killed turn left behind travels with it, so the
    resume continues it rather than opening a new one.
    """

    def __init__(self, message, session=None):
        super().__init__(message)
        self.session = session


class NotNeeded(Exception):
    """A follow-up's executor found no work left, before any checks or review."""


class Blocked(Exception):
    """The task cannot be done as written, so the run ends here and says why.

    Not a FAIL: a FAIL is a verdict on work, and there is no work to judge -- either a worker
    ended its turn saying the task contradicts itself, or two fixer rounds left the same
    checks failing the same way, which is the checks being wrong rather than the code.  There
    is nothing for another round or a reviewer to add, and nothing a resume could spend, so
    the orchestrator that wrote the task hears the sentence and writes a new one.  `section`
    is the `## Blocked` section result.md carries.
    """

    def __init__(self, reason, section):
        super().__init__(reason)
        self.section = section


class CannotRun(Blocked):
    """The harness never ran the turn, and its stderr line says why: see `cannot_run`.

    Not a provider fault, so never one of the transient waits -- no wait installs a harness,
    teaches it a flag or logs it in -- and not a FAIL, since nothing was judged.  The work
    goes to another provider first, the way a spent window's does; with nobody left to take
    it, the run is blocked on that line, which is what this is wherever nobody catches it.
    """

    def __init__(self, name, line):
        self.detail = f"cannot run: {line}"
        super().__init__(f"{name} {self.detail}", f"## Blocked\n\n{name} {self.detail}")


class RanDry(Exception):
    """This worker's provider refused it.

    Not a death and not a FAIL -- nothing was executed and nothing was judged -- so the work
    goes to another provider rather than being retried where it cannot run.  The refusal and
    the dead session travel with it, so the post-mortem still has both.
    """

    def __init__(self, name, mark, code, text, session, until, message, quota):
        super().__init__(f"{name} refused: {message}")
        self.name, self.mark, self.code, self.text = name, mark, code, text
        self.session, self.until = session, until
        self.message, self.quota = message, quota
        # and what a role parks with when no one else can take it: a window waits for its refill
        self.why, self.ending = ("ran dry", QuotaDry) if quota else ("refused", Exhausted)
        self.detail = f"refused: {message}"

    def remember(self, state):
        """Remember a short refusal retry, or clear one when a quota window is parked."""
        if self.quota:
            state.pop("refusal_retry", None)
        else:
            state["refusal_retry"] = {"model": self.name, "at": self.until}


class TransientHandover(Exception):
    """This worker failed on the provider twice in a row and another took the role.

    Not a death and not a FAIL -- nothing was executed and nothing was judged -- so the
    turn goes to the next worker the way a spent window's does, and the failed provider
    joins only that round's refused set.  The handover itself already happened inside
    `call_retrying`'s `handover` callback; this only unwinds to the turn loop so it can
    restart the role with the new worker, a fresh session and a fresh out dir.
    """

    def __init__(self, before, new, session, detail):
        super().__init__(f"{before} failed on the provider twice; handed to {new}: {detail}")
        self.before, self.new, self.session, self.detail = before, new, session, detail


def free_dir(lp, name):
    """`round-N/<name>`, or the next `-attempt<n>` beside it: no attempt overwrites another.

    A resumed round, a reviewer falling back, an executor handed over mid-round -- each writes
    where the one before it did, and the diagnostics of a call that failed are exactly what the
    post-mortem needs.
    """
    out, attempt = lp.dir(name), 1
    while out.exists():
        attempt += 1
        out = lp.dir(f"{name}-attempt{attempt}")
    return out


def role_base(dirname):
    """The role directory name without an `-attemptN` suffix."""
    match = re.fullmatch(r"(.+)-attempt(\d+)", dirname)
    return match.group(1) if match else dirname


def attempt_dirs(round_dir, name):
    """Out dirs for one role, the first attempt first."""
    found = []
    base = Path(round_dir) / name
    if base.is_dir():
        found.append((1, base))
    for path in Path(round_dir).glob(f"{name}-attempt*"):
        if not path.is_dir():
            continue
        suffix = path.name[len(name) + len("-attempt"):]
        if suffix.isdigit():
            found.append((int(suffix), path))
    found.sort()
    return [path for _, path in found]


def session_of(directory):
    """A conversation id recorded for this turn, from the file or the event stream."""
    directory = Path(directory)
    try:
        text = (directory / "session_id").read_text(errors="replace").strip()
    except OSError:
        text = ""
    if text:
        return text
    return worker.recovered_session(directory) or None


def latest_turn(round_dir, name):
    """The last call, including retries a host interruption may have left unfinished."""
    dirs = attempt_dirs(round_dir, name)
    if not dirs:
        return None
    out = dirs[-1]
    return max([out, *out.parent.glob(f"{out.name}-retry*")],
               key=lambda path: (path.stat().st_mtime_ns, path.name))


def open_turn(round_dir, name):
    """`(resume|fresh, session)` when this role's latest attempt never finished.

    A missing `final.md` is a turn the host cut off. An executor answer without a
    closing still needs its one extra ask. A recorded session is resumed; without one
    a fresh turn is needed. A finished attempt is `(None, None)`.
    """
    latest = latest_turn(round_dir, name)
    if latest is None:
        return None, None
    if (latest / "final.md").exists():
        submitted = hand_in.read(latest / hand_in.FILE)
        if (name.startswith("reviewer") or submitted is not None and submitted.closing
                or "-retry-hand-in" in latest.name or "-retry-foreground" in latest.name):
            return None, None
    sid = session_of(latest)
    if sid:
        return "resume", sid
    return "fresh", None


def finished_answer(round_dir, name):
    """The latest attempt's `final.md`, or None when that file was never written."""
    dirs = attempt_dirs(round_dir, name)
    if not dirs:
        return None
    return read_answer(dirs[-1] / "final.md")


def host_ended_prompt(state):
    """The one sentence a resumed harness session is handed.

    The conversation already holds the task. This says the checkout was not tidied
    and the turn is the same one, so the model does not start the work over.
    """
    when = None
    deaths = state.get("deaths") or []
    if deaths and isinstance(deaths[-1], dict):
        when = deaths[-1].get("at")
    if not isinstance(when, (int, float)) or isinstance(when, bool):
        when = state.get("interrupted_at")
    if not isinstance(when, (int, float)) or isinstance(when, bool):
        when = time.time()
    clock = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
    return (f"Your process was ended by the host at {clock}, not by you; "
            "the worktree is exactly as you left it. Continue this turn and finish it; "
            "do not start over.")


def latest_worker_turn(round_dir):
    """The latest executor/fixer attempt supersedes earlier attempts, even when it closed."""
    rd = Path(round_dir)
    if not rd.is_dir():
        return None
    turns = [latest_turn(rd, role_base(path.name)) for path in rd.iterdir()
             if path.is_dir() and "-retry" not in path.name
             and not path.name.startswith("reviewer")
             and re.match(r"(?:executor|(?:.+-)?fixer)(?:-|$)", path.name)]
    return max(turns, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)


def open_worker(lp):
    """`(name, kind, session)` of the open executor/fixer attempt, or three Nones."""
    latest = latest_worker_turn(lp.round_dir)
    if latest is None:
        return None, None, None
    name = role_base(latest.name.split("-retry", 1)[0])
    kind, sid = open_turn(lp.round_dir, name)
    return (name, kind, sid) if kind else (None, None, None)


def open_review(round_dir):
    """`(name, kind, session)` of the open reviewer attempt, or three Nones.

    A review that fell back to another model writes under `reviewer-<model>`, so the
    attempt to continue is the newest reviewer directory of any name, not `reviewer`
    alone: a fallback cut off mid-turn would otherwise start its review over. Retries
    belong to that same attempt, including a foreground finish ended by the host.
    """
    rd = Path(round_dir)
    if not rd.is_dir():
        return None, None, None
    best = None
    for path in rd.glob("reviewer*"):
        if not path.is_dir() or "-retry" in path.name or "foreground" in path.name:
            continue
        base = role_base(path.name)
        kind, sid = open_turn(rd, base)
        if not kind:
            continue
        latest = latest_turn(rd, base)
        try:
            mtime = latest.stat().st_mtime
        except OSError:
            mtime = 0
        if best is None or mtime >= best[0]:
            best = (mtime, base, kind, sid)
    return (None, None, None) if best is None else (best[1], best[2], best[3])


def review_turn(round_dir, session, since=""):
    """The round's latest reviewer turn on `session`, unless it is the one named `since`.

    A review is pending until its verdict is saved, not until its reviewer says `done`, and
    its pending record keeps where its session stood when it began.  Parked before the
    verdict (a spent window, an expired login, a stop while its proofs replay), it goes on in
    a conversation that has handed in what it found already: the next turn starts from the
    records of the latest turn since, or its `done` alone would pass the work.  A turn from
    before belongs to a review whose verdict is on the record, and hands on nothing.
    """
    turns = [path for path in Path(round_dir).glob("reviewer*")
             if session and path.is_dir() and session_of(path) == session]
    latest = max(turns, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)
    return None if latest is None or str(latest) == since else latest


def saved_worker_answer(round_dir):
    """The executor or fixer answer file already written for this round."""
    latest = latest_worker_turn(round_dir)
    answer = latest / "final.md" if latest is not None else None
    return answer if answer is not None and answer.is_file() else None


def read_answer(path):
    """One worker answer from disk, or None when it is not there to be read."""
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def scope_is_real(scope):
    """Whether `scope` names a unit systemd actually holds, not a plain start."""
    return (isinstance(scope, str) and bool(scope) and scope != "none"
            and not scope.startswith("none"))


def memory_cap_line(mb):
    """The reason a run that hit `mb` mebibytes records: `killed: memory cap N GB`."""
    gb = mb / 1024
    if abs(gb - round(gb)) < 1e-9:
        shown = str(int(round(gb)))
    else:
        shown = f"{gb:.2f}".rstrip("0").rstrip(".")
    return f"killed: memory cap {shown} GB"


def _scope_units(scope):
    """The unit names a receipt's scope might be, scope first."""
    if not isinstance(scope, str) or not scope:
        return ()
    if scope.endswith(".scope") or scope.endswith(".service"):
        return (scope,)
    return (f"{scope}.scope", f"{scope}.service")


# "<cgroup> <oom_kill count>" this loop has logged.  In the environment, because a loop that
# picks up new code replaces its interpreter (`pickup_new_code`) in the same scope, and must
# not say those kills again; a resume in a new scope is a new process that starts without it.
OOM_LOGGED = "AK_MEMORY_CAP_LOGGED"


_OOM_LOCK = threading.Lock()   # a reviewer and a suite can end on two threads at once


def memory_cap_note(run_dir, log):
    """Log each process the kernel ended at this run's memory cap since the last look.

    Called as each worker turn and each done-when command ends.  That is all it does: the
    turn or command the kill ended goes on or ends the run as any failed command or killed
    worker does.  The count is the cgroup's this loop runs in, and only when that is the
    run's own scope: a run from a seat's shell sits in the seat's, whose kills are not its.
    """
    state = run_record.read_state(Path(run_dir)) or {}
    cap, scope = state.get("memory_cap_mb"), state.get("scope")
    if type(cap) is not int or cap <= 0 or not scope_is_real(scope):
        return
    cgroup = host.process_cgroup()
    if cgroup is None:
        return
    cgroup = cgroup.strip().rstrip("/")
    if cgroup.rsplit("/", 1)[-1] not in _scope_units(scope):
        return
    with _OOM_LOCK:
        where, _, said = os.environ.get(OOM_LOGGED, "").rpartition(" ")
        seen = int(said) if where == cgroup and said.isdigit() else 0
        kills = host._oom_kill_count(cgroup)
        if kills > seen:
            os.environ[OOM_LOGGED] = f"{cgroup} {kills}"
    for _ in range(kills - seen):
        log(f"{memory_cap_line(cap).removeprefix('killed: ')} hit: "
            "the process that grew was ended")


def stop_run_tree(state, log=lambda _: None, wait=False):
    """End everything a run started: its marked processes, then its scope.

    The marker sweep is the backstop that runs everywhere: a plain host has no scope at
    all, and a scope the manager never made answers the stop with nothing stopped. The
    scope stop goes last and, by default, is fire-and-forget -- the loop calling it is
    usually inside that scope and on its way out, so nothing of ours still runs after
    it is asked.  A caller that is already outside the scope, the reaper after a
    memory-cap death, passes `wait` so the stop finishes and the memory is back.
    Never only a process group: a child that left its group is still the run's.
    One sweep ends the run's children too: the marker match covers `<marker>/...`.
    """
    scope = state.get("scope") if isinstance(state, dict) else None
    run_id = state.get("run_id") if isinstance(state, dict) else None
    if run_id:
        worker.kill_marked(worker.run_marker(run_id), log=log)
    orch.stop_scope(scope, log, wait=wait)
