"""One model turn: how it ends, where a round keeps it, what it answered, and the memory its scope ran under.

A turn ends in one of a few ways a harness hands back -- Exhausted, Dead, Killed, Blocked,
NotNeeded, RanDry, CannotRun, TransientHandover -- each a class here.  The turn directories
of a round -- the executor's, the fixer's, the reviewer's, each attempt of each -- and the
answer file a turn leaves are read here, as is the memory cap a turn's scope ran under and
the stop of a run's process tree.  The call itself, its retries and what its harness said instead of an answer are here too.
"""

import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from . import (config, gitcall, hand_in, history, host, orch, record as run_record, refusals,
               update, worker)
from .harness import FAULT, LIMITED, SPENT, load as harness_plugin, says


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


def latest_worker_turn(round_dir, name=""):
    """The latest executor/fixer attempt supersedes earlier attempts, even when it closed;
    `name` keeps one turn's attempts and handovers alone (`own_pr_fix`)."""
    rd = Path(round_dir)
    if not rd.is_dir():
        return None
    turns = [latest_turn(rd, role_base(path.name)) for path in rd.iterdir()
             if path.is_dir() and "-retry" not in path.name and path.name.startswith(name)
             and not path.name.startswith("reviewer")
             and re.match(r"(?:executor|(?:.+-)?fixer)(?:-|$)", path.name)]
    return max(turns, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)


def open_worker(lp, name=""):
    """`(name, kind, session)` of the open executor/fixer attempt, or three Nones."""
    latest = latest_worker_turn(lp.round_dir, name)
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


OUT_CAP = 20 * 1024


def kept(output, where, name):
    """Save `output`, a binary file from where it stands, whole in a new file under `where`, a
    part at a time: the line that names it heads any part of it a model is handed, so nothing a
    check printed is out of its reach."""
    with tempfile.NamedTemporaryFile(dir=where, prefix=f"{name}-whole-", suffix=".log",
                                     delete=False) as whole:
        shutil.copyfileobj(output, whole)
    return f"[only part of this output is shown; all of it is in {Path(whole.name).resolve()}]"


def cut(text, where, name):
    """`text` as a model is handed it: whole up to OUT_CAP, else its end under `kept`'s line."""
    return (text if len(text) <= OUT_CAP else
            f"{kept(io.BytesIO(text.encode()), where, name)}\n{text[-OUT_CAP:]}")


def cut_file(output, start, where, name):
    """`cut` of a binary file's bytes from `start` to its end, never read whole: a check can
    print more than the run's memory holds."""
    size = output.seek(0, os.SEEK_END)
    output.seek(start)
    line = f"{kept(output, where, name)}\n" if size - start > OUT_CAP else ""
    output.seek(max(start, size - OUT_CAP))
    return line + output.read(OUT_CAP).decode("utf-8", errors="replace")


# A transient answer is what a person answers by typing `continue`: the same worker session
# again, after 1, 5, 15, 30 and 60 minutes, then hourly, indefinitely.  The run stays
# `running` throughout, so its session reads `working`, and never ends in `error` for one.
TRANSIENT_BACKOFF = (60, 300, 900, 1800, 3600)


TRANSIENT_HOURLY = 3600


KILL_WINDOW = 60              # a second signal kill inside this many seconds parks the run


SWAP_POLL = 10                # seconds between looks at a harness swap a failed turn waits out


KILLED = {-15: "SIGTERM", -9: "SIGKILL"}   # worker exits by signal, as `subprocess` reports them


# When a refusal says to come back: Codex prints `Try again at Oct 12th, 2026 11:39 PM` in this
# machine's own timezone, and a 429 body carries the same moment as an ISO timestamp.  A clock
# time with no date is not read: on its own it could be minutes ago or a week off, and the
# meters answer that better than a guess would.
TRY_AGAIN_ISO = re.compile(r"try again (?:at|on)\s+"
                           r"(\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d)?"
                           r"(?:Z|[+-]\d\d:?\d\d)?)", re.I)


TRY_AGAIN_NAMED = re.compile(r"try again (?:at|on)\s+([A-Za-z]{3,9})\.?\s+(\d{1,2})"
                             r"(?:st|nd|rd|th)?,?\s+(\d{4})(?:\s+at)?,?\s+(\d{1,2}):(\d{2})"
                             r"(?::\d{2})?\s*([AaPp])?\.?[Mm]?\.?", re.I)


MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


# The files in a worker's out dir that are the harness talking.  prompt.md is what it was told,
# and session_id is bookkeeping; neither is ever evidence of anything the harness said.
NOT_HARNESS = ("prompt.md", "session_id", hand_in.FILE, hand_in.REPORT, hand_in.FINDINGS_FILE)


ANSWER = "final.md"             # and this one arrives as `text`, already read by worker.call


ECHO = 40                       # a prompt is recognised quoted back by this many of its own
                                # first characters -- the role preamble, which is one line and
                                # which no refusal begins with


REFUSAL_CAP = 1000              # a refusal replaces the answer instead of following it, so it is
                                # short; past this many characters what is there is an answer


# A heading distinguishes an answer from the harness's short refusal.
ANSWERED = re.compile(r"^\s{0,3}#{1,6}\s", re.M)


# A record in a harness's event log is that harness reporting a failure when one of its own kind
# fields says so -- Codex ends a refused turn with `turn.failed`, Claude with a `result` whose
# subtype names an error -- or when it carries an error of its own.  Whatever a command or a tool
# printed is cut out of every record first, at any depth: that text is the work's own output,
# quoted inside the record, and a task that greps for the words a refusal uses is not one.
EVENT_KINDS = ("type", "subtype", "kind", "status", "state", "level")


EVENT_FAILED = re.compile(r"error|fail|abort", re.I)


EVENT_OUTPUT = ("aggregated_output", "output", "stdout", "stderr", "command", "content",
                "arguments", "tool_result", "input")


# A fix run's check, in a folder of its own: the run directory is the loop's, read-only
# to its turns, and the executor writes this one.
REGRESSION = Path("regression", "regression.sh")


def regression_script(run_dir):
    """A fix run's check: in its folder, or beside the run for one started before it had one."""
    legacy = run_dir / REGRESSION.name
    return legacy if legacy.is_file() else run_dir / REGRESSION


def stall_minutes_for(run_dir, state):
    """The shared silence limit, preserving the one recorded when this run launched."""
    return state.get("silence_minutes", run_record.SILENCE_MINUTES)


def killed_word(code):
    """How a worker exit by signal reads: `killed (SIGTERM)`, never an exit code.

    None for any other exit: a worker that exited by code said what the code says.
    """
    if code is None or code >= 0:
        return None
    return f"killed ({KILLED.get(code, f'SIG{-code}')})"


def transient_delay(attempt):
    """How long the attempt-th transient retry waits: 1, 5, 15, 30, 60 minutes, then hourly."""
    if attempt <= len(TRANSIENT_BACKOFF):
        return TRANSIENT_BACKOFF[attempt - 1]
    return TRANSIENT_HOURLY


def transient(code, text):
    """Why this call looks like a provider failure rather than an answer, or None.

    Only a non-zero exit qualifies: a worker that exited 0 said what it meant to say, however
    much of an API error it quotes back while saying it.  A kill is not one either: it reads
    as the signal, through `killed_word`, and takes its own road.  An empty final.md gets
    here only once `cannot_run` has found no harness fault on stderr.  Anything else the
    harness said is for its own words to read (`Harness.failure`), and `call_retrying` asked
    them first; a final.md the model answered in says nothing here.
    """
    if code == 0 or killed_word(code):
        return None
    return f"exited {code} with an empty final.md" if not text.strip() else None


def cannot_run(code, text, stderr, out_dir=None, harness=None):
    """The stderr line saying this harness never ran the turn at all, or None.

    Only for a non-zero exit, not a kill, that left final.md empty: whatever answered is an
    answer, and a kill takes its own road.  The line holds one of the harness's `faults`
    words (`Harness.failure`), and no outage word stands anywhere beside it: that is waited
    out instead.
    `opencode.sh: opencode is not installed` is the case -- it was retried like a 500,
    hourly, for as long as nobody installed it.

    Exit 126 or 127 with an empty event stream never ran either: the shell refused the
    exec -- `Argument list too long` for a prompt over one argument's limit -- and no
    wait starts what cannot start, whatever else stderr says.  The role goes to the next
    worker, as a refused one does.
    """
    if code == 0 or killed_word(code) or text.strip():
        return None
    if code in (126, 127) and out_dir is not None and worker.said_nothing(out_dir):
        line = next((" ".join(line.split()) for line in stderr.splitlines() if line.strip()),
                     "")
        return line or f"exited {code} with an empty event stream"
    outcome, word = harness_plugin(harness).failure(stderr, ran=False)
    if outcome != FAULT:
        return None
    return next((" ".join(line.split()) for line in stderr.splitlines() if says(line, word)),
                None)


def transient_wait(out_dir, delay):
    """Sleep out one transient wait of the turn writing into `out_dir` (`run_wait`)."""
    run_wait(Path(out_dir).parent.parent, delay)


def run_wait(run_dir, delay):
    """Sleep out `delay` seconds the run waits on something outside it, with its record saying
    until when.

    The tick reads a run's silence off its newest write, and a wait writes nothing: the
    30-minute wait read as a 20-minute silence, the tick killed the loop, its resume began the
    waits again at one minute, and the third such stall parked a run whose provider was only
    down.  `transient_wait` on the record, with this loop's pid, is where `watch.stall_clock`
    starts that clock instead.  A turn with no run record above its round (a direct caller's)
    only sleeps.
    """
    if (run_dir / "run.json").is_file():
        try:
            with run_record.recovery_lock(run_dir):
                state = run_record.read_state(run_dir)
                if state and state.get("state") == "running":
                    state["transient_wait"] = {"until": time.time() + delay, "pid": os.getpid()}
                    run_record.save_state(run_dir, state)
        except OSError:
            pass            # an unwritten mark costs a stall rung, never the wait itself
    step = history.close_step(run_dir.name)     # the wait is no step's work
    time.sleep(delay)
    history.open_step(run_dir.name, step)


def shell_foreground_note():
    """Keep long commands attached to the turn that must report their result."""
    return ("Run long commands, tests included, in the foreground and wait for them; "
            "a turn that ends with a command still running in the background is not finished. "
            f"A command that may print nothing for {run_record.SILENCE_MINUTES} minutes starts "
            "with `timeout <seconds>`, or that silence stops it.")


FINISH_IN_FOREGROUND = ("The command you left in the background was stopped when your turn ended. "
                        "Run it in the foreground now, wait for it, and report.")


NO_VERDICT_ASK = ("Your previous turn ended without ak hand-in done. Review the diff now, "
                  "hand in any remaining findings or follow-ups with ak hand-in, then run "
                  "ak hand-in done. Earlier records have been carried into this turn. "
                  "Do not start commands you will not wait for in this turn.")


NO_CLOSING_ASK = ('Your previous turn ended without a closing hand-in. Close it now with '
                  'ak hand-in done, ak hand-in blocked "<why>" or ak hand-in not-needed "<why>" '
                  'as instructed. Earlier records have been carried into this turn. '
                  'Do not start commands you will not wait for in this turn.')


def turn_unfinished(out_dir):
    """Did this turn end with a command still running in the background -- unfinished, then.

    Either the harness says so on stderr (`Background tasks still running`, which Claude
    prints when it stops a turn over background work) or its event log's last
    `background_tasks_changed` event still lists a task -- Claude 2.1.263 streams those as
    `{"type": "system", "subtype": "background_tasks_changed", "tasks": [...]}`, and only the
    last one counts, so a list the turn emptied before ending is finished.  A missing or
    unreadable file is no signal: the turn counts as finished.
    """
    try:
        if "Background tasks still running" in (Path(out_dir) / "stderr.log").read_text(
                errors="replace"):
            return True
    except OSError:
        pass
    try:
        lines = (Path(out_dir) / "events.jsonl").read_text(errors="replace").splitlines()
    except OSError:
        return False
    last = None
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if (event.get("type") == "background_tasks_changed"
                or event.get("subtype") == "background_tasks_changed"):
            last = event
    if last is None:
        return False
    return bool(last.get("tasks", last.get("background_tasks")))


def tail(path, cap=OUT_CAP):
    """The last `cap` bytes of a file, as text; an event log can be far too big to read whole."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - cap))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def answered(text):
    """Did the worker answer here, or did the harness put a refusal where the answer belongs?

    A refusal takes the answer's place rather than following it: it is the whole of what the
    harness managed to say, and it is short. Legacy text answers carry a heading or length
    of their own; closing hand-in records establish an answer separately.
    """
    return len(text) > REFUSAL_CAP or bool(ANSWERED.search(text))


def without_output(node):
    """`node` with every command's and tool's output cut out of it, at any depth."""
    if isinstance(node, dict):
        return {k: without_output(v) for k, v in node.items() if k not in EVENT_OUTPUT}
    if isinstance(node, list):
        return [without_output(item) for item in node]
    return node


# Re-encoded, a control character in a record's text -- a line break, a tab -- reads as an
# escape (`\n`, `\t`, `\u000b`) that runs into the word after it, which then never stands on
# its own; so do characters outside ASCII unless they are written as they are.  With every
# control character and line separator a space and the rest written as is, the only escapes
# left are `\"` and `\\`, which end in neither a letter nor a digit, and a record stays one
# line wherever `str.splitlines` would break it.
ONE_LINE = {code: " " for code in (*range(0x20), *range(0x7f, 0xa0), 0x2028, 0x2029)}


def one_line(node):
    """`node` with every control character and line separator in its text a space, at any
    depth."""
    if isinstance(node, dict):
        return {k: one_line(v) for k, v in node.items()}
    if isinstance(node, list):
        return [one_line(item) for item in node]
    return node.translate(ONE_LINE) if isinstance(node, str) else node


def is_failure(node):
    """Does this record say of itself that it is a failure, at any depth?"""
    if isinstance(node, list):
        return any(is_failure(item) for item in node)
    if not isinstance(node, dict):
        return False
    for key, value in node.items():
        if key in ("error", "is_error") and value not in (None, False, "", [], {}):
            return True
        if key in EVENT_KINDS and isinstance(value, str) and EVENT_FAILED.search(value):
            return True
    return any(is_failure(value) for value in node.values())


def is_terminal(node, terminal):
    """Is this record the run's own terminal report, whatever its kind calls it?

    The kind is the harness's own: `[stall] terminal` in adapters/<harness>.toml names it,
    and it is read at any depth the way `is_failure` reads a failure.
    """
    if not terminal:
        return False
    if isinstance(node, list):
        return any(is_terminal(item, terminal) for item in node)
    if not isinstance(node, dict):
        return False
    for key, value in node.items():
        if key in EVENT_KINDS and value == terminal:
            return True
    return any(is_terminal(value, terminal) for value in node.values())


def record_text(node):
    """Every string a terminal record says, in one place, for the answer-shape test.

    Kind discriminators are not what it says: they name the record, and a long one of those
    must never read as an answer on its own.
    """
    if isinstance(node, dict):
        return "\n".join(record_text(value) for key, value in node.items()
                          if key not in EVENT_KINDS)
    if isinstance(node, list):
        return "\n".join(record_text(item) for item in node)
    return node if isinstance(node, str) else ""


def failures(chunk, terminal, terminal_only=False, handed_in=False):
    """The failure records of an event log, each minus the output of the work it quotes, its
    text's control characters read as spaces and the rest as written.

    The output goes first, so a command that failed while printing the words a refusal uses
    contributes its exit code and nothing else.  The run's terminal record is kept beside
    them, failure or not: with an empty final.md it is the only place a refusal can be, and
    the adapter may never have filled final.md at all.  A record that declares itself a
    failure is the harness speaking, whatever shape its text has; the answer-shape test
    decides only a terminal record that declares none, where an answer-shaped text is the
    worker's answer and never a refusal.  With ``terminal_only`` (the zero-exit path), only a
    terminal record's explicit failure or unanswered text is kept, so an earlier stream warning
    cannot discard an answer. Handed-in records establish an answer without a text-shape test;
    explicit terminal errors still speak. A line that is not a JSON record says nothing here.
    """
    records = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = without_output(json.loads(line))
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if terminal_only:
            terminal_record = is_terminal(record, terminal)
            failure = (terminal_record
                       and (is_failure(record)
                            or (not handed_in and not answered(record_text(record)))))
        else:
            failure = (is_failure(record)
                       or (is_terminal(record, terminal)
                           and not handed_in and not answered(record_text(record))))
        if failure:
            records.append(json.dumps(one_line(record), ensure_ascii=False))
    return records


def harness_said(out_dir, text, harness, failures_only=False):
    """What the harness itself said this attempt, with the work's own output kept out of it.

    Three sources, because a refusal lands in a different one on each harness.  The answer --
    Claude's and Muse's refusals arrive there -- but only where nothing answered, because a
    refusal replaces an answer instead of following one.  `stderr.log`, which is the harness's
    own diagnostics and not anywhere a command's output goes.  And the event log, where
    Codex's refusal arrived while final.md stayed empty: every failure record, and the run's
    terminal record -- `[stall] terminal` in adapters/<harness>.toml names its kind -- whether
    or not that kind names a failure, each stripped of what the work printed: a task that
    greps for the words a refusal uses, or a test that prints them, is the work talking and
    never the provider.  With ``failures_only`` (the exit-zero path), only a terminal refusal
    event or unanswered terminal record is read and stderr is ignored, because a harness may
    log a retried warning before a successful answer.  The prompt is not read at all, nor any
    line quoting it back.
    """
    from . import watch     # here, not at the top: watch reaches run
    out_dir = Path(out_dir)
    try:
        with (out_dir / "prompt.md").open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        first = ""
    # up to the first quote or backslash: past those an event log's own JSON escaping means the
    # prompt is no longer in it character for character, and the marker would never match
    echo = first.split('"')[0].split("\\")[0].strip()
    echo = echo if len(echo) >= ECHO else ""
    submitted = hand_in.read(out_dir / hand_in.FILE)
    # Successful turns with a record file use it even when the model forgot to hand in anything.
    # An unfinished, failed call may still contain a real provider error in its final text.
    handed_in = submitted is not None and (submitted.closing is not None or failures_only)
    if failures_only and not handed_in and answered(text):
        return ""
    terminal = watch.terminal(harness)
    parts = [] if failures_only or handed_in or answered(text) else [text]
    for path in sorted(out_dir.glob("*")):
        if path.name in NOT_HARNESS or path.name == ANSWER or not path.is_file():
            continue
        chunk = tail(path)
        if path.suffix == ".jsonl":
            parts += failures(chunk, terminal, terminal_only=failures_only, handed_in=handed_in)
        elif not failures_only:
            parts.append(chunk[-REFUSAL_CAP:])
    return "\n".join(line for part in parts for line in part.splitlines()
                      if line.strip() and not (echo and echo in line))


def ran_dry(code, said, harness, refusal=False):
    """The harness's own word for a spent provider window in this exit, or None.

    They come from the harness package's shared `[stall] quotas` beside the adapter's own,
    read off a seat's screen the same way, each a whole word (`Harness.failure`);
    a LIMITED one parks a worker's account as a SPENT one does.
    A non-zero exit is as required here as it is for `transient`, because a worker that exited
    0 said what it meant to say.  The scoped terminal refusal path may pass ``refusal`` for an
    exit-zero turn that never answered.
    """
    if code == 0 and not refusal:
        return None
    outcome, word = harness_plugin(harness).failure(said)
    return word if outcome in (SPENT, LIMITED) else None


def try_again_at(said):
    """The moment a refusal named as the one to come back at, as an epoch, or None."""
    match = TRY_AGAIN_ISO.search(said)
    if match:
        try:
            return datetime.fromisoformat(match.group(1).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    match = TRY_AGAIN_NAMED.search(said)
    if not match:
        return None
    month, day, year, hour, minute, half = match.groups()
    if month[:3].lower() not in MONTHS:
        return None
    hour, half = int(hour), (half or "").lower()
    if half == "p":
        hour = hour % 12 + 12
    elif half == "a":
        hour %= 12
    try:
        return datetime(int(year), MONTHS.index(month[:3].lower()) + 1, int(day), hour,
                        int(minute)).timestamp()
    except ValueError:
        return None


def resume_failed(out_dir, killed, text):
    """A resume the harness ended at once, with nothing streamed and nothing answered.

    A silence kill ran and was stopped; this one never started. The Codex session that
    exited before its first byte after a host freeze is the case, and retrying that id
    spends the transport attempts on a conversation that will not come back.
    """
    if killed or (text or "").strip():
        return False
    return worker.said_nothing(out_dir)


def note_turn_meters(cfg, name, out_dir, account, before=()):
    """The meters the turn in `out_dir` reported about the account it ran on are the reading,
    and what it spent beside how far it moved them from `before` is a pair of what a window
    holds in tokens (`usage.record_pairs`).

    Best effort and never the turn's failure: a harness that says nothing leaves the
    endpoint's reading alone.
    """
    from . import usage     # here, not at the top: usage reaches turns
    try:
        entry = config.model(cfg, name)
        plugin = harness_plugin(entry["harness"])
        meters = plugin.turn_meters(out_dir)
        tokens = plugin.tokens(out_dir) if before else None
    except (config.Error, OSError, ValueError, TypeError, AttributeError):
        return
    try:
        if meters:
            usage.record_turn_meters(cfg, entry["provider"], meters, account)
        usage.record_pairs(cfg, name, account, before, tokens, meters)
    except (config.Error, OSError, ValueError, TypeError, AttributeError, KeyError):
        pass


def call_retrying(cfg, name, body, workspace, out_dir, role, session, log, limit=None,
                  fresh_body=None, resume_note=None, handover=None, previous=None, findings=None,
                  base=None):
    """worker.call, retried while the harness keeps dying on the provider instead of the task.

    Returns (code, text, session, dead): `dead` stays False -- a transient answer is resumed
    indefinitely now, so there is nothing left to give up on.  A retry resumes the session
    the dead attempt left behind, if any, and gets its own out dir, so the failed attempt's
    stderr.log survives for the post-mortem.  A resume that exits at once with no output is
    not one of those retries: that id is abandoned after the first such exit, and the role
    continues in a fresh conversation (`fresh_body` when the caller has the original prompt,
    otherwise the same one). The new session id replaces the old.

    A turn killed for emitting no event for `limit` seconds is one of those retries: nothing
    judged it, so it is retried on the same session rather than scored, with the same waits.

    Each turn's box ends its leftovers, without ending the suite or the loop's helpers.
    A turn that left processes or reports background work is unfinished:
    the same session is called once more, with no backoff, to run it in the
    foreground and report -- the same round, and not one of the transient waits.  That
    turn gets artifacts of its own (`<role>-retry-foreground`, beside the transient retries'
    `-retryN`, so `written_answer` still finds whose answer the round recorded): the first
    turn's diagnostics survive it, and only what the second turn itself wrote determines
    completion and retry behavior.  A second turn that ends the same way is carried on from
    with a WARN, as if it had been finished.

    Only an answer that names the account hands the round over.  A provider that lists
    `accounts` runs each call on the one with the most room left, and one that refuses for
    quota is marked spent on its own: the same worker goes again at once on the next account
    with room, on its own session.  A spent window otherwise leaves `RanDry` for the caller,
    whose job is another provider, not another try here: a usage-limit reset held is never
    spent for it, since only the owner spends one.
    An empty exit whose stderr says the harness never ran the turn leaves `CannotRun` the
    same way, at once: another provider, or a run blocked on that line.  Before either, a
    failed exit, not a kill, that an install or revert of its harness overlapped
    (`update.swap_end`) waits for that swap to end and starts again on its session: once per
    swap, since the retry begins after it ended.

    A worker exit by signal is neither: it reads as the signal, resumes once at once, and on
    a second kill inside a minute raises `Killed` for the run to park on.

    `handover`, when the turn loop gives one, is what a second transient failure in a row
    tries before its wait: called with the failure's detail, it moves the role to the next
    worker the way a spent window's moves and returns the new worker, or None when no other
    worker can take it.  A move raises `TransientHandover` at once, with no wait, so the
    loop restarts the role fresh; None waits out the growing waits on the same session, as
    without it, and tries only once -- the waits after that are the run's own.

    An executor or fixer of a fix run may also write the run's regression folder.  `base` is
    the target ref the reviewer's `users:` line is read at (`worker.users_declared`).
    """
    from . import usage     # here, not at the top: usage reaches turns
    limit = 60 * run_record.SILENCE_MINUTES if limit is None else limit
    out_dir = Path(out_dir)
    run_dir = out_dir.parent.parent
    places = [place for place in [run_dir / REGRESSION.parent]
              if role in ("executor", "fixer") and place.is_dir()]
    note = shell_foreground_note()
    if note not in body:
        # the executor and fixer bodies already carry it in the context header; the reviewer
        # body is built from the task text, so it gets it here, said once either way
        body = f"{note}\n\n{body}"
    entry = config.model(cfg, name)
    # Mark only the worker child; the loop's orphaned-orchestrator fallback may still speak.
    # Every role (and retry) lives under <run>/round-N/<role> and inherits this audit log.
    env = {**gitcall.run_child_env(), "AK_RUN_ROLE": "worker",
           "AK_RUN_LOG": str(run_dir / "log.txt")}
    if findings:
        env[hand_in.FINDINGS_ENV] = str(findings)
    if base:
        env[worker.BASE_ENV] = base
    attempt, calls, last_kill, account, span = 1, 0, None, None, None
    handover_tried = False
    last_dir, last_sid = Path(previous) if previous is not None else None, session

    def turn(text, target, session):
        """One call, with a login failure taken aside before it costs a wait.

        No call starts on a stopped run: the stop lands first and the sweep after
        it, so a retry that outlived the sweep would otherwise run a whole turn no
        record wants anymore.
        """
        nonlocal account, span, last_dir, last_sid
        run_record.stop_check(run_dir)
        account = usage.account(cfg, entry["provider"], model=name)[0]
        before = usage.reading(entry["provider"], account)
        began = time.time()
        named = env if account is None else {**env, **config.account_env(account)}
        if session and session == last_sid and last_dir is not None:
            named = {**named, hand_in.CONTINUE: str(last_dir / hand_in.FILE)}
        try:
            with gitcall.reviewer_checkout(workspace, target, log) if role in (
                    "reviewer", "reviewer-pr") else nullcontext(workspace) as cwd:
                result = worker.turn(cfg, name, text.replace(str(Path(workspace).resolve()), str(cwd)), cwd,
                                     target, role, session, env=named, limit=limit, log=log,
                                     places=places)
        except worker.LoginExpired as expired:
            log(f"{role} {name} cannot authenticate: {expired.why}; the run waits for that "
                "login rather than retrying into it")
            expired.session = expired.session or session
            refusals.refused(expired.harness, run_dir)
            raise
        else:
            span = (began, time.time())
        finally:
            memory_cap_note(run_dir, log)     # however the turn ended
        note_turn_meters(cfg, name, target, account, before)
        last_dir, last_sid = target, result[2] or session
        return result

    def swapped(code, killed, session):
        """Whether an install or revert of this harness overlapped the turn that just failed.

        Its command was missing then, which reads as a harness that cannot run, so the swap is
        waited out like a provider fault and the turn starts again on its session: once per
        swap, since that start comes after the swap ended.
        """
        if killed or not code or killed_word(code) or update.swap_end(
                entry["harness"], *span) is None:
            return False
        log(f"WARN {role} {name} exited {code} while {entry['harness']} was being swapped; "
            "starting again once that swap has ended"
            + (f", resuming session {session}" if session else ""))
        while (end := update.swap_end(entry["harness"], *span) or 0) > (now := time.time()):
            transient_wait(out_dir, min(SWAP_POLL, end - now))
        return True

    def next_account(until, message):
        """Park the account this turn ran on alone, and whether another of its provider has
        room: the turn goes there, on its own session, before any other model is asked."""
        usage.mark_exhausted(cfg, entry["provider"], until, account)
        spare, room = usage.account(cfg, entry["provider"], model=name)
        if room and spare != account:
            log(f"{role} {name} ran dry on account {account}: {message}; going on with account "
                f"{spare}" + (f", resuming session {session}" if session else ""))
        return room and spare != account

    while True:
        target = out_dir if not calls else out_dir.with_name(f"{out_dir.name}-retry{calls}")
        # Only the conversation the caller handed in is a resume. An id this ladder's own
        # first attempt left behind is a fresh turn's, and an empty exit on it is the
        # transport failure the three attempts are for, not a session that cannot be opened.
        asked = session if not calls else None
        code, text, sid, killed, unfinished = turn(body, target, session)
        if swapped(code, killed, sid or session):
            session, calls = sid or session, calls + 1
            continue
        if asked and resume_failed(target, killed, text):
            # One empty exit abandons the id. The role continues in a new conversation,
            # and the dead id is not retried and does not spend the transport attempts.
            log(f"resume of {asked} failed; fresh conversation")
            if isinstance(resume_note, dict):
                resume_note["restarted"] = True
                resume_note["at"] = time.time()
            if fresh_body is not None:
                body = fresh_body if note in fresh_body else f"{note}\n\n{fresh_body}"
            session = None
            calls += 1
            target = out_dir.with_name(f"{out_dir.name}-retry{calls}")
            code, text, sid, killed, unfinished = turn(body, target, None)
            session = sid or None
            calls += 1
            if swapped(code, killed, session):
                continue
        else:
            session, calls = sid or session, calls + 1
        # An ask for a missing closing or verdict is the turn's one extra call already.
        if (not killed and (unfinished or turn_unfinished(target))
                and "-retry-hand-in" not in out_dir.name and not body.endswith(NO_VERDICT_ASK)):
            log(f"{role} {name} ended its turn with a command still in the background; asking "
                "it to finish in the foreground")
            finish = target.with_name(f"{target.name}-retry-foreground")
            # Foreground recovery also asks for the closing, so neither role spends another ask.
            finish_body = (f"{FINISH_IN_FOREGROUND} "
                           f"{NO_VERDICT_ASK if role.startswith('reviewer') else NO_CLOSING_ASK}")
            code, text, sid, killed, unfinished = turn(finish_body, finish, session)
            session = sid or session
            if swapped(code, killed, session):
                continue
            if not killed and (unfinished or turn_unfinished(finish)):
                log(f"WARN {role} {name} ended its turn with a command still in the background "
                    "again; carrying on with what it reported")
            target = finish
        elif not killed and (unfinished or turn_unfinished(target)):
            log(f"WARN {role} {name} ended its turn with a command still in the background "
                "again; carrying on with what it reported")
        # A harness that never ran the turn says so on stderr, and that outranks the refusal
        # words below: a 404 for a model it does not have reads `API Error` like a 500, and
        # Codex's missing model suggests `try a different model` like its capacity refusal.
        # Not a wait: the caller hands the work over, or the run is blocked on this line.
        fault = None if killed else cannot_run(
            code, text, tail(target / "stderr.log"), target, entry["harness"])
        if fault:
            log(f"WARN {role} {name} cannot run: {fault}")
            raise CannotRun(name, fault)
        # Some adapters exit zero after streaming turn.failed; that event still refused
        # the turn. On a successful exit only failure events speak, never answer text.
        # A spent window, a refusal or an outage, each in the harness's own whole words.  A
        # kill by signal reads as the signal whatever else was said, unless the window is spent.
        said = harness_said(target, text, entry["harness"], failures_only=code == 0)
        outcome, mark = harness_plugin(entry["harness"]).failure(said)
        sig = killed_word(code) if not killed else None
        if outcome in (SPENT, LIMITED) or (outcome and not sig):
            quota = ran_dry(code, said, entry["harness"],
                            refusal=code == 0 and bool(said))
            lines = [line for line in said.splitlines() if says(line, mark)]
            message = lines[0] if lines else said or mark
            try:
                parsed = record_text(json.loads(message))
                if parsed:
                    message = parsed
            except (TypeError, ValueError):
                pass
            message = " ".join(message.split()) or mark
            if not quota:
                # A fault, not the account: the same session again, after the growing
                # wait, indefinitely -- what a person answers by typing `continue`.
                if handover is not None and attempt == 2 and not handover_tried:
                    handover_tried = True
                    detail = f"transient {mark!r}: {message} (twice in a row)"
                    new = handover(detail)
                    if new is not None:
                        raise TransientHandover(name, new, session, detail)
                    log(f"WARN {role} {name} {detail}; no other worker can take it")
                delay = transient_delay(attempt)
                log(f"WARN {role} {name} transient {mark!r}: {message} "
                    f"(attempt {attempt}); retrying in {delay}s"
                    + (f", resuming session {session}" if session else ""))
                attempt += 1
                transient_wait(out_dir, delay)
                continue
            if account is not None and next_account(try_again_at(said), message):
                continue
            requested = try_again_at(said)
            until = usage.mark_exhausted(cfg, entry["provider"], requested) or requested
            parked = (f"; nothing is picked on {entry['provider']} until "
                      + time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
            log(f"WARN {role} {name} refused: {message}{parked}")
            raise RanDry(name, quota, code, text, session, until, message, True)
        if sig:
            # The worker died by signal, not on the provider and not on the task: it
            # resumes once, at once, on the session it left behind.  A second kill
            # inside the minute is somebody -- or something -- killing it on purpose,
            # and the run parks for a person instead of retrying into it.
            now = time.time()
            if last_kill is not None and now - last_kill < KILL_WINDOW:
                raise Killed(f"{role} {name} {sig} twice within a minute; "
                             f"see {target}*/stderr.log", session)
            last_kill = now
            log(f"WARN {role} {name} {sig}; resuming once"
                + (f", resuming session {session}" if session else ""))
            continue
        why = (f"emitted no event for {orch.span(limit)} and was killed with everything it "
               f"spawned (session {session or 'not recorded'})" if killed else transient(code, text))
        if not why:
            # a quota word left only in the model's answer is the answer talking, not the
            # provider: it parks no account and hands nothing over
            refusals.answered(entry["harness"])
            return code, text, session, False
        if handover is not None and attempt == 2 and not handover_tried:
            handover_tried = True
            detail = f"{why} (twice in a row)"
            new = handover(detail)
            if new is not None:
                raise TransientHandover(name, new, session, detail)
            log(f"WARN {role} {name} {detail}; no other worker can take it")
        delay = transient_delay(attempt)
        log(f"WARN {role} {name} {why} (attempt {attempt}); retrying in {delay}s"
            + (f", resuming session {session}" if session else ""))
        attempt += 1
        transient_wait(out_dir, delay)
