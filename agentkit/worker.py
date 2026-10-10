"""One headless model call: role preamble + task text -> adapter -> final.md."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import box, command_help, config, hand_in, host, record
from .harness import load as harness_plugin

# A worker session is not a seat: `ak notify` is suppressed there, and a finding names a class
# the fixer has to finish, not a line to patch, so that a later round only confirms fixes.
NO_NOTIFY = ("[checked by ak: tests/test_notify_rule.py] ak suppresses `ak notify` in worker sessions.\n"
             "[worker judgement] Anything you would report or ask goes into your `## Summary`.")
EVERY_INSTANCE = ('[worker judgement] You may dispute a finding instead of changing code: use '
                  '`ak hand-in dispute path:line "why it is wrong" --run COMMAND` or `--quote LINES`.\n'
                  "[checked by ak: tests/test_dispute_hand_in.py] ak refuses disputes outside the "
                  "handed blocking findings, commands that do not exit 0 and absent quotes.\n"
                  "[worker judgement] For every "
                  "undisputed finding, fix every instance of that pattern in {work}, not only "
                  "the cited line, and list the sites you changed in your summary.")
ONE_PASS = ("[worker judgement] Report every finding you can establish in this one pass, grouped by "
            "pattern with every site listed.\n"
            "[checked by ak: tests/test_dispute_hand_in.py] ak supplies each dispute beside its finding "
            "with ak's proof output; findings handed in again are weighed normally, others are dropped.\n"
            "[worker judgement] Uphold a disputed finding by handing it in again with "
            "`ak hand-in finding`. Drop it by not handing it in "
            "again. Then say which earlier findings are fixed and which are not, then anything new.")
# A task that cannot be done as written is the task's defect, not the worker's: handing it in ends
# the run there, and the orchestrator that wrote the task gets the sentence back instead of a
# reviewer's verdict on work nobody could do.
BLOCKED = ('[worker judgement] Close every turn with `ak hand-in done`, or `ak hand-in blocked "<why>"` if the task '
           'cannot be completed as written, or `ak hand-in not-needed "<why>"` if a fix run\'s '
           "first turn finds the defect gone or already being fixed.\n"
           "[worker judgement] `blocked` is only for a task that cannot be completed as written; never for a "
           "transient provider failure, a capacity refusal, or a check the loop runs later such "
           "as the `# once` suite.\n"
           "[checked by ak: tests/test_hand_in.py] ak refuses malformed or wrong-role closings "
           "and records after a closing.\n"
           "[checked by ak: tests/test_executor_text_ignored.py] ak asks once for a missing closing, "
           "then sends the work to checks and review.")
# The reviewer supplies evidence; the loop weighs it outside the reviewer's editable copy.
GATE = ("[worker judgement] Hand in a **blocking** finding only for a correctness defect in "
        "the task's outcome, a safety or data-loss risk, a check the executor weakened or "
        "skipped, a scope violation (work the task did not ask for, or asked-for work "
        "missing), or complexity the diff adds: a second home for a piece of knowledge, a special "
        "case inside general code, work pushed onto callers that the module could do, or a "
        "function that only forwards to another. Quote the added lines and name the other home "
        "or the caller in why it matters; complexity already on main is neither blocking nor a "
        "follow-up. Moving what the change needs into its one home, or deleting what it makes "
        "dead, is no scope violation. Use "
        "`ak hand-in finding path:line \"what\" \"why it matters\" --run 'command'` "
        "or `--quote 'lines from that file'` for blocking findings only; use only files on the branch.\n"
        "[checked by ak: tests/test_hand_in.py] ak refuses malformed or evidence-free findings, "
        "missing files, invalid lines, absent quotes, finding commands that exit 0, "
        "follow-ups without `--before` that quote or whose command exits 0, and follow-up commands "
        "of more than one line, with backticks or naming this checkout's path.\n"
        "[checked by ak: tests/test_proof_weighed.py] ak replays finding commands on a clean "
        "checkout of the commit and on the base with changed tests overlaid (scratch: workspace only). "
        "Passing or unfinished proofs and exits 126/127 become notes; proven changed-line defects or regressions "
        "that pass on base block; pre-existing defects elsewhere become follow-ups only if the proof runs and fails on base.\n"
        "[worker judgement] **Follow-ups** never block and are fixed after the merge, by a run of "
        "their own where one takes them: a defect of a kind that would fail a round, with that same "
        "evidence, that existed before this task (prove that with `--before 'base or "
        "ancestor commit, or verbatim lines from the named file at base'`), or a smaller defect of "
        "this change that need not hold it (no `--before`; its command must fail now). Hand them in with "
        "`ak hand-in follow-up path:line \"what\" \"why it matters\" --run 'command'` (the command "
        "becomes the check of a line in the owning session's plan and the done-when of the run that "
        "fixes it). Omit everything else everywhere.\n"
        "[checked by ak: tests/test_followup_runs.py] ak re-runs the command on base and checks --before there; "
        "a proof that cannot run or does not fail, or a --before absent from base, drops the follow-up into Notes.\n"
        "[checked by ak: tests/test_followups_never_block.py] ak re-runs a follow-up without --before "
        "on this commit, where it must fail, and on base, where failing makes it one from before the task.\n"
        "[checked by ak: tests/test_followup_rule.py] ak keeps every round's follow-ups, a failed round's included.\n"
        "[checked by ak: tests/test_followup_lines.py] after the merge a follow-up's line in the owning "
        "session's plan holds back no done of the session's where a run takes it.\n"
        "[checked by ak: tests/test_followup_runs.py] ak starts a fix run for each follow-up after the "
        "merge where the session marks an executor, its command the run's check, and defers the line only "
        "once a run has it; a line no run takes is the session's own and holds its done.\n"
        "[worker judgement] Finish with `ak hand-in done`.\n"
        "[checked by ak: tests/test_hand_in.py] ak derives FAIL from any finding that stays blocking, "
        "otherwise PASS, however long the follow-ups list is; follow-ups are never a reason to fail.")
# A repository whose AGENTS.md says `users: real` ships a new feature hidden until the owner
# turns it on for everyone, so its reviewer holds one more finding blocking.
REAL_USERS = ("[worker judgement] This repository has real users: new user-visible behaviour (something a user can "
              "do that they could not before; an improvement to an existing feature is not) that "
              "is not behind the project's feature switch, or is on for anyone but the owner by "
              "default, is also a blocking finding.")
# The owner's own words for how much to build and how, in every executor and fixer.
LEAST = ("[worker judgement] Minimum change that solves the task completely; the best part is no part. Less is "
         "more: brutal elimination, the least possible steps. Make it as if the system had been "
         "designed for it: each piece of knowledge in one home, no special case inside general "
         "code, nothing callers must do that a module could, and what the change makes dead deleted.")
COMMITS = ("[checked by ak: tests/test_leftover_junk.py] ak commits uncommitted work before checks and review.")
PROCESSES = ("[checked by ak: tests/test_turn_leftover_processes.py] ak stops processes left running "
             "when your turn ends and asks once to finish in the foreground.")
CHECKS = ("[checked by ak: tests/test_reviewer_judges_the_diff.py] ak runs per-round done-when "
          "commands even when the worker skips them.")
REVIEW_COPY = ("[checked by ak: tests/test_reviewer_edits_never_land.py] ak reviews in an isolated copy, "
               "archives and undoes edits; they never reach the branch.")
TIMEOUT = 124       # what a turn killed for running past its limit exits with, as `timeout(1)` does
KILL_GRACE = 5      # how long a killed process group is given to go quietly before SIGKILL
RUN_MARKER = "AGENTKIT_RUN"   # every process of a run carries its directory path
MARK_KILL_GRACE = 10   # how long marked processes get to go quietly after TERM before KILL
ACTIVITY_POLL = 1   # file-backed harness output has no portable readiness notification
AUTH_CAP = 20       # the `auth` verb reads a file; one still silent after this is not answering
AUTH_GRACE = 60     # a turn that was over this fast and said nothing never reached the model
STDERR_CHUNK = 64 * 1024   # how much of a turn's diagnostics is held in memory while scanning


def run_marker(run_id):
    """The run directory keeps equal ids in different ak homes distinct on one host."""
    return str(config.RUNS / run_id) if run_id else None


class LoginExpired(Exception):
    """This harness cannot authenticate: the turn never ran, or never reached the model.

    Not a transport death and not a refusal.  Nothing can be retried until somebody logs in
    again, so this travels up instead of spending the twenty-minute silence window and the
    three attempts an outage is owed, and the loop parks the run where the tick picks it up
    the moment that harness's `auth` verb passes.  The conversation the parked turn left
    behind travels with it, so the resume continues it rather than opening a new one.
    """

    def __init__(self, harness, why, session=None):
        super().__init__(f"{harness} login expired: {why}")
        self.harness, self.why, self.session = harness, why, session


def auth_ok(harness, seat=False, run_id=None, account=None):
    """Whether that harness can authenticate right now, and the one line it said about it.

    `run_id` marks the probe as that run's own, so detached descendants die with the run
    like any other child; a probe with no run to name runs unmarked, as before.  `account`
    asks about that one of its provider's logins (`config.account_env`), never another's.

    `seat` asks about the interactive login instead of a headless turn's.  They are two
    logins wherever a harness has a worker credential of its own, and they expire apart: a
    box whose workers are fine on a long-lived token can still have a seat showing
    `Please run /login`, and answering the seat with the worker's token would hide exactly
    the thing this is here to catch.  A harness with one login answers both the same.

    Three answers, not two.  `adapters/<h>.sh auth` answers in one line: exit 0 and where
    the token is, which is True, or exit 1 and why there is none, which is False.  Anything
    else did not answer at all and is None -- an adapter that declares no `auth` verb exits
    2 on it, one that cannot be run says nothing, one that fell over says a page, one that
    exited 0 in silence said nothing about a token.  The line is required on both codes and
    not only on one: a crashing adapter exits 1, and parking every run of the night on a
    traceback would be a worse failure than the one this is here to stop -- but a malformed
    adapter exits 0 just as easily, and a `yes` nobody said is what lifts a card the owner
    still has to act on and restarts work nothing has authenticated.

    None is not a yes.  A turn is launched on it, because that is exactly what happened
    before this verb existed -- but nothing an answer earned is undone by one: a card stays
    up, a parked run stays parked, and a login episode ends only on a `yes`.  An adapter
    that is briefly unrunnable is not somebody logging back in.
    """
    try:
        adapter = config.adapter(harness)
    except config.Error:
        return None, ""
    env = config.child_env()
    if run_id:
        env[RUN_MARKER] = run_marker(run_id)
    else:
        # no run to name means unmarked, even inside a run whose marker the child
        # would otherwise inherit -- a login probe is nobody's to sweep.
        env.pop(RUN_MARKER, None)
    if account is not None:
        env.update(config.account_env(account))
    try:
        # `input` rather than DEVNULL: the adapter gets a stdin that is closed at once, and
        # asking it a question opens no file of its own on a machine watching for that.
        done = subprocess.run([str(adapter), "auth"] + (["seat"] if seat else []), input="",
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=AUTH_CAP, env=env)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    # Both streams together, never one or the other: an adapter that answered on stdout and
    # also said something on stderr has said two things, and two things is not one line.
    said = [line.strip() for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    if len(said) == 1 and done.returncode in (0, 1):
        return done.returncode == 0, said[0]
    return None, said[-1] if said else ""


def auth_scanner(harness):
    """A resumable scan of one turn's diagnostics for that harness's own logout words.

    Answers the `[auth] signatures` the babysitter reads off a seat's screen, in the one
    place a headless turn can put them.  A turn that said this never reached the model,
    whatever its exit code was and however long it took to say so.

    The whole log, not its tail: a harness that said it was logged out and then printed a
    page of its own unwinding would hide the one line that explains the turn.  And only what
    has been appended since the last look, keeping the longest signature of overlap so a
    match across two reads is still one -- because the watchdog calls this about once a
    second while the turn is still running, which is what lets a harness that said it was
    logged out and then hung end at once instead of spending the whole silence window.
    """
    from . import watch     # here, not at the top: the babysitter imports this module
    marks = [(mark, mark.lower()) for mark in watch.auth_expiry(harness)[2]
             if isinstance(mark, str) and mark]
    keep = max((len(mark) for mark, _ in marks), default=1) - 1
    read, carry = 0, ""

    def seen(out_dir):
        """The signature this turn has written by now, or None.  Resumes where it left off.

        The offset and the overlap only move together, and only once a read has reached the
        end: a look that failed part way leaves both where the last whole one put them, so
        the next look reads the same bytes again rather than joining two that never met.
        """
        nonlocal read, carry
        if not marks:
            return None
        try:
            with (Path(out_dir) / "stderr.log").open(encoding="utf-8", errors="replace") as fh:
                fh.seek(read)
                said, chunk = carry, fh.read(STDERR_CHUNK)
                while chunk:
                    said = (said + chunk).lower()
                    found = next((mark for mark, low in marks if low in said), None)
                    if found:
                        return found
                    said = said[-keep:] if keep else ""
                    chunk = fh.read(STDERR_CHUNK)
                read, carry = fh.tell(), said
        except (OSError, ValueError):
            return None
        return None

    return seen


def said_nothing(out_dir):
    """Whether the harness streamed no event at all: an empty or absent event log."""
    try:
        return not (Path(out_dir) / "events.jsonl").read_text(errors="replace").strip()
    except OSError:
        return True


PREAMBLES = {
    "executor": (
        "You are the executor.\n"
        "[worker judgement] Work only inside {workspace} on the current branch; never push.\n"
        f"{COMMITS}\n{CHECKS}\n{PROCESSES}\n{LEAST}\n"
        "[worker judgement] Finish with a `## Summary` section: what changed, how you verified it, open issues.\n"
        f"{NO_NOTIFY}\n{BLOCKED}"),
    "reviewer": (
        f"You are the reviewer.\n{REVIEW_COPY}\n{PROCESSES}\n"
        "[checked by ak: tests/test_reviewer_judges_the_diff.py] ak ran every done-when "
        "command on exactly the commit under review; the complete output is below under "
        "`## Done-when output`, except the commands marked deferred, which run once "
        "at landing on the commit to be merged.\n"
        "[worker judgement] Run whatever is needed to prove or dismiss a finding, except "
        "done-when commands, the repository's `tests:` suite, and checks marked deferred; probes "
        "must leave nothing behind outside a temporary directory.\n"
        "[worker judgement] Judge the diff against the task and its done-when criteria. "
        "A check the executor weakened, skipped or deleted is a FAIL unless the task asked for "
        "exactly that.\n"
        "[checked by ak: tests/test_suite_in_round.py] ak runs the full `tests:` suite once at landing.\n"
        "[worker judgement] A task whose done-when leaves the suite out has weakened no check. "
        "The deferred checks' absence from your input is by design and is never a finding.\n"
        f"{GATE}\n{ONE_PASS}"),
    "fixer": (
        "You are the executor, continuing.\n"
        f"{EVERY_INSTANCE.format(work='the diff')}\n{COMMITS}\n{CHECKS}\n{PROCESSES}\n{LEAST}\n"
        "[worker judgement] Finish with `## Summary`: what changed, how you verified it, open issues.\n"
        f"{NO_NOTIFY}\n{BLOCKED}"),
    # somebody else's PR: no executor ran, so the diff is judged against the repository itself
    "reviewer-pr": (
        f"You are the reviewer of a pull request by another author.\n{REVIEW_COPY}\n{PROCESSES}\n"
        "[worker judgement] Run tests/commands as needed; probes must leave nothing behind "
        "outside a temporary directory. Judge the diff against what the repository itself says "
        "-- its AGENTS.md, README, tests and conventions -- and against the intent the PR states. "
        f"\n{GATE}\n{ONE_PASS}"),
    # the same three roles for a run with no repository: nothing to commit, and the reviewer is
    # given the workspace rather than a diff
    "executor-scratch": (
        "You are the executor.\n"
        "[worker judgement] Work only inside {workspace}. It is a scratch workspace, not a git "
        "repository: there is nothing to commit and nothing to push, and every deliverable is a "
        f"file you leave there.\n{CHECKS}\n{PROCESSES}\n{LEAST}\n"
        "[worker judgement] Finish with a `## Summary` section: what you produced, "
        f"how you verified it, open issues.\n{NO_NOTIFY}\n{BLOCKED}"),
    "fixer-scratch": (
        "You are the executor, continuing.\n"
        "[worker judgement] Work only inside {workspace}; its files are the deliverable.\n"
        f"{EVERY_INSTANCE.format(work='the workspace')}\n{CHECKS}\n{PROCESSES}\n{LEAST}\n"
        "[worker judgement] Finish with `## Summary`: what changed, how you verified it, open issues.\n"
        f"{NO_NOTIFY}\n{BLOCKED}"),
    "reviewer-scratch": (
        f"You are the reviewer.\n{PROCESSES}\n"
        "[worker judgement] Read-only: do not edit files under review.\n"
        "[checked by ak: tests/test_reviewer_judges_the_diff.py] ak ran every done-when "
        "command on exactly the workspace under review; the complete output is below under "
        "`## Done-when output`.\n"
        "[worker judgement] Run whatever is needed to prove or dismiss a finding, except "
        "done-when commands; probes "
        "must leave nothing behind outside a temporary directory.\n"
        "[worker judgement] Judge the contents of {workspace} against the task and its done-when criteria.\n"
        f"{GATE}\n{ONE_PASS}"),
}


def _lineage():
    """This process and every ancestor, walked by ppid from /proc.

    A sweep names a run by the marker its processes carry, and the process asking for
    the sweep is inside that run as often as not: it and everything above it carry the
    same marker.  They are not what the sweep is for.  Signalling them ends the run
    that asked.  The walk stops at an unreadable row, pid 0, or a cycle.
    """
    lineage, pid = set(), os.getpid()
    while pid and pid not in lineage:
        lineage.add(pid)
        stat = host.proc_stat(pid)
        if stat is None or stat.ppid <= 0:
            break
        pid = stat.ppid
    return lineage


def marked_pids(run_id, exact=False):
    """Every pid carrying the given marker or below it, except this process and its ancestors.

    Found by scanning /proc/*/environ, so a child that left its process group -- setsid,
    a double fork, a harness that starts each shell command as its own session leader --
    is still one of the run's.  The caller and its ancestors are never among them,
    whatever marker they carry and whatever marker was asked for: a kill from inside a run
    must not take the run that asked for it.  Entries are matched whole, so one run marker
    is never a prefix of another's -- except below a slash: `<marker>/suite` is the run's
    own suite, so a sweep of the run ends it too, while a sweep of the suite ends only
    the suite.  `exact` matches only the marker itself: a failed turn's cleanup ends
    the turn's own leftovers while the suite running beside it keeps going.
    Unreadable rows -- a process that just exited,
    another user's -- are skipped, never fatal.
    """
    if not run_id:
        return []
    skip = _lineage()
    want = f"{RUN_MARKER}={run_id}".encode()
    prefix = want + b"/"
    try:
        entries = [entry for entry in os.listdir("/proc") if entry.isdigit()]
    except OSError:
        return []
    found = []
    for entry in entries:
        pid = int(entry)
        if pid in skip:
            continue
        try:
            with open(f"/proc/{pid}/environ", "rb") as fh:
                env = fh.read()
        except OSError:
            continue
        for part in env.split(b"\0"):
            if part == want or (not exact and part.startswith(prefix)):
                found.append(pid)
                break
    return found


def kill_marked(run_id, grace=MARK_KILL_GRACE, log=None, exact=False):
    """End every process carrying the run's marker: TERM to all of it, then KILL after `grace`.

    The scope's backstop, and the plain host's only net: what a run started is found by its
    environment, not by its parent or its group, so nothing detached outlives the run.  The
    caller and its ancestors are not part of that, whatever marker was given -- `marked_pids`
    leaves them out -- so the loop's own end-of-run sweep still ends every process the run
    started.  One sweep ends the run's sub-marked processes too (`<marker>/suite`), so no sweep
    of a run can miss its suite; `exact` sweeps only the marker itself, for a failed turn's
    cleanup while the suite beside it keeps running.  Polls for the exits and returns
    early; True when nothing marked is left.  Never raises: a cleanup that fails leaves
    the next one to act.
    """
    if not run_id:
        return True
    marked = marked_pids(run_id, exact=exact)
    if not marked:
        return True
    for pid in marked:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        marked = marked_pids(run_id, exact=exact)
        if not marked:
            return True
        time.sleep(0.2)
    for pid in marked:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        marked = marked_pids(run_id, exact=exact)
        if not marked:
            return True
        time.sleep(0.2)
    if log is not None:
        log(f"WARN {run_id}: still alive after KILL: {marked[:5]}; the next cleanup acts again")
    return False


def kill_group(proc, run_id=None):
    """Take down the whole process group -- and, where the run is named, its marker.

    SIGTERM first, so a harness can still close its session file, then SIGKILL for whatever
    ignored it -- the test runner, the compiler, the git it left behind.  The group is named
    before any wait: reaping the leader takes its pid, and the group's name with it.  The
    group is never the whole of it: a child that left the group is still the run's, so where
    the child's marker names the run, every process carrying exactly it is ended too, except
    this process and its ancestors -- a killed turn's cleanup, never the suite beside it.
    """
    try:
        group = os.getpgid(proc.pid)
    except OSError:
        return
    if group == os.getpgid(0):
        # Popen has returned but the child has not reached setsid yet: the id still names our
        # own group, and TERM/KILL to it would take down this run instead of the child.
        return
    try:
        os.killpg(group, signal.SIGTERM)
    except OSError:
        return
    try:
        proc.wait(timeout=KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        pass
    if run_id:
        kill_marked(run_id, exact=True)


def limited(cmd, limit, *, silence=None, activity=None, output=None, on_timeout=None,
            abort=None, stop=None, **kwargs):
    """Run a process group until it exits, goes silent, reaches an optional ceiling, or
    says something that means it will never finish.

    Returns (exit code, captured output, killed). `activity` is the output file the
    command or harness writes directly, so even output without a newline counts and
    the watcher can see progress while communicate waits. A killed group keeps its
    partial output and reads TIMEOUT, distinct from a command that exits 124 itself.

    Adapters write regular files, whose readiness cannot tell us when more output
    arrives. A one-second stat poll resets the silence window without rearming a
    timer for every event; it is cheap enough to share with the ceiling check.
    The external ladder allows this observation delay and TERM cleanup to finish
    before intervening, so this watchdog can preserve the reason for the stop.
    `on_timeout(reason, pid)` runs before any signal, while the command's children
    can still be read for the stop diagnostic.

    `abort` is asked on the same poll and outranks both windows: a harness that has already
    said it cannot authenticate is not going to finish, and waiting out the silence window
    for one that keeps emitting events -- or never emits another -- is the whole of what
    this is here to stop.  It must be cheap and must not raise.

    `stop(process, grace)` can own TERM/KILL cleanup when a wrapper encloses the command.

    Where the child was given an environment that carries AGENTKIT_RUN, a kill ends every
    process carrying exactly it, however detached -- never only the child's own process
    group, never the suite beside it, and never this process or its ancestors.
    A plain inherited environment names no run, and
    neither does a copy of this process's own marker: both are the run this process is
    inside, and the kill stays with the child's session.
    """
    def written():
        try:
            stat = Path(activity).stat()
            return stat.st_size, stat.st_mtime_ns
        except (OSError, TypeError):
            return None

    previous = written()
    started = time.monotonic()
    # Only an environment this call handed the child names a run to clean up.  Nothing
    # passed, or a dict that still carries this process's own marker, means the child
    # is inside the caller's run, and ending that run would take the caller with it.
    child_env = kwargs.get("env")
    run_id = child_env.get(RUN_MARKER) if isinstance(child_env, dict) else None
    # A dict that merely copies this process's environment still carries the run
    # this process is inside.  That marker was not handed to the child as its own
    # run, and sweeping it would take the siblings of this process with it.
    if run_id and run_id == os.environ.get(RUN_MARKER):
        run_id = None
    if output is not None:
        kwargs["stdout"] = subprocess.PIPE
    proc = subprocess.Popen(cmd, start_new_session=True, **kwargs)
    expired, finished = threading.Event(), threading.Event()

    def end():
        if stop is None:
            kill_group(proc, run_id)
        else:
            stop(proc, KILL_GRACE)

    def watch_output():
        last, seen = started, previous
        while not finished.is_set():
            now = time.monotonic()
            current = written()
            if current != seen:
                last, seen = now, current
            reason = ("abort" if abort is not None and abort() else
                      "ceiling" if limit is not None and now - started >= limit else
                      "silence" if silence is not None and now - last >= silence else None)
            if reason:
                expired.set()
                try:
                    if on_timeout is not None:
                        on_timeout(reason, proc.pid)
                finally:
                    end()
                return
            remaining = [ACTIVITY_POLL]
            if limit is not None:
                remaining.append(limit - (now - started))
            if silence is not None:
                remaining.append(silence - (now - last))
            finished.wait(min(remaining))

    monitor = None
    if limit is not None or silence is not None or abort is not None:
        monitor = threading.Thread(target=watch_output)
        monitor.start()
    try:
        if output is None:
            out, _ = proc.communicate()
        else:
            # Keep the pipe open until descendants close it too. Redirecting directly
            # to the file would let a shell that backgrounds its child pass at once.
            with proc.stdout:
                for chunk in iter(lambda: proc.stdout.read1(64 * 1024), b""):
                    output.write(chunk)
                    output.flush()
            proc.wait()
            out = ""
    except BaseException:
        # The group has its own session, so an interrupted caller must stop it too.
        end()
        try:
            proc.communicate(timeout=KILL_GRACE)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        raise
    finally:
        finished.set()
        if monitor is not None:
            monitor.join()
    killed = expired.is_set()
    return (TIMEOUT if killed else proc.returncode), out or "", killed


def boxed(cmd, limit, *, env, cwd, **kwargs):
    """The check watchdog and status, with worker walls and throwaway HOME writes."""
    with tempfile.TemporaryDirectory(dir=Path(kwargs["activity"]).parent) as out_dir, \
            box.command(cmd, env, out_dir, cwd=cwd,
                        home_overlay=True, drain=True) as (cmd, env, spawn):
        code, text, killed = limited(cmd, limit, env=env, cwd=cwd, **spawn, **kwargs)
        if not killed:
            # Bubblewrap exits 1 when it cannot build the box. Without the supervisor's
            # report that is no exit of the command: it never started, the shell's 126.
            code = box.returncode(out_dir, 126 if code == 1 else code)
            if code == 126 and not (Path(out_dir) / box.PROCESSES).exists():
                message = box.launch_error(out_dir, env)
                if kwargs.get("output") is not None:
                    kwargs["output"].write(message.encode())
                    kwargs["output"].flush()
                else:
                    text += message
    return code, text, killed


def recovered_session(out_dir):
    """The conversation id a killed turn never wrote down, read back out of its own stream.

    Every adapter writes `session_id` after its CLI exits, by pulling the id out of the events
    the CLI streamed -- so a turn that was killed has the events and no file.  Without this the
    retry would open a fresh conversation and the killed turn's work would be gone.  The three
    shapes are Claude's `session_id`, Codex's `thread_id` and Muse's `stream.id`, besides a
    capitalized `sessionID` and a `conversation_id` other CLIs stream; the last one seen wins,
    as in claude.sh, and an id does not change within a turn anyway.
    """
    found = None
    try:
        with (Path(out_dir) / "events.jsonl").open(errors="replace") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                stream = event.get("stream")
                value = (event.get("session_id") or event.get("sessionID")
                         or event.get("thread_id") or event.get("conversation_id")
                         or (stream.get("id") if isinstance(stream, dict) else None))
                if isinstance(value, str) and value.strip():
                    found = value.strip()
    except OSError:
        return None
    return found


def shell_timeout_ms():
    """Let the harness accept long calls without promising an uninterrupted turn.

    This is the shell maximum, not a silence exemption: a foreground tool whose
    harness emits no events can still lose its turn to the silence watchdog.
    """
    return str(int(record.CEILING_HOURS * 3600 * 1000))


def call(cfg, model_name, body, workspace, out_dir, role="executor", session=None, env=None,
         limit=None, places=()):
    """Run one turn.  Returns (exit_code, final_text, session_id, killed); out_dir holds the
    artifacts.

    The turn is given config.seatless_env(): a worker is nobody's seat, so nothing it starts --
    a nested `ak run`, a smoke suite -- is launched from the seat the loop was launched from.

    A Claude turn is also given BASH_DEFAULT_TIMEOUT_MS and BASH_MAX_TIMEOUT_MS at the
    done-when ceiling so the harness default need not force a command into the background.
    This does not bypass the event-silence watchdog during a foreground tool call. Codex
    and Muse expose no equivalent knob (their shell timeout is per tool call, chosen by the model),
    so their environment is unchanged; see docs/guide.md.

    A turn whose event stream stays silent for `limit` seconds is killed with everything
    it spawned and comes back as TIMEOUT with `killed`. There is no total turn limit.

    A turn that cannot authenticate never becomes one of those silences.  The harness's `auth`
    verb is asked before the launch, and again where a turn was over within AUTH_GRACE having
    streamed nothing.  Its own logout words in the turn's diagnostics say it too, whatever the
    turn's exit code -- and they are watched for while the turn is still running, so a harness
    that said it and then hung, or that said it and kept emitting events, is stopped on the
    line it already wrote rather than on a window that never closes.  Either way `LoginExpired`
    is raised at once: waiting out twenty minutes and spending three retries on a wall is how
    one expired token turned into three dead runs and an hour apiece.

    The gate carries REAL_USERS when the workspace's AGENTS.md says `users: real`, read by the
    loop's own reader on every turn that has the gate: a reviewer's first turn, its retries, and
    a follow-up that starts a new conversation all hold it.  No other preamble has the gate.

    `places` are directories the turn may write beside its workspace, out dir and harness state.
    """
    entry = config.model(cfg, model_name)
    adapter = config.adapter(entry["harness"])
    extra = {}
    if entry["harness"] == "claude":
        cap = shell_timeout_ms()
        extra = {"BASH_DEFAULT_TIMEOUT_MS": cap, "BASH_MAX_TIMEOUT_MS": cap}
    turn_env = {**config.seatless_env(), **extra, **(env or {})}
    ok, why = auth_ok(entry["harness"], run_id=turn_env.get(RUN_MARKER),
                      account=turn_env.get(config.ACCOUNT_ENV))
    if ok is False:
        raise LoginExpired(entry["harness"], why)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    turn_env[hand_in.ENV] = hand_in.start(out_dir, workspace, turn_env.pop(hand_in.CONTINUE, None),
                                       role=role, findings=turn_env.pop(hand_in.FINDINGS_ENV, None))
    preamble = PREAMBLES[role].format(workspace=workspace)
    if GATE in preamble:
        from . import run as loop
        if loop.users_declared(workspace) == "real":
            preamble = preamble.replace(GATE, f"{GATE}\n{REAL_USERS}")
    prompt = out_dir / "prompt.md"
    prompt.write_text(f"{preamble}\n\n{body}")
    cmd = [str(adapter), "run", entry["model"], entry["effort"], str(workspace), str(prompt), str(out_dir)]
    if session:
        cmd.append(session)
    began = time.monotonic()
    # the same scan the turn is judged by afterwards, handed to the watchdog so a harness
    # that says it is logged out and then hangs -- or keeps emitting events, which resets
    # the silence window for ever -- is stopped on the line it already wrote
    watching = auth_scanner(entry["harness"])
    # The adapter's own stderr, which is not the harness's: a line it prints before it hands
    # the harness `2>"$out/stderr.log"` -- `opencode.sh: opencode is not installed` -- went to
    # the loop's stderr and never reached the turn's diagnostics.  It is kept apart while the
    # harness writes that file, and added to the end of it once the turn is over.
    own = out_dir / "adapter-stderr.log"
    paths = config.manifest(entry["harness"]).get("worker", {})
    with box.command(cmd, turn_env, out_dir, cwd=workspace,
                     state=paths.get("state", ()), places=places,
                     logins=paths.get("logins", ())) as (cmd, turn_env, spawn), \
            own.open("wb") as err:
        code, _, killed = limited(cmd, None, silence=limit, activity=out_dir / "events.jsonl",
                                  abort=lambda: watching(out_dir),
                                  env=turn_env, stderr=err, **spawn)
    if not killed:
        code = box.returncode(out_dir, code)
    harness_plugin(entry["harness"]).record_turn(out_dir, config.STATE,
                                                turn_env.get(config.ACCOUNT_ENV, ""))
    try:
        said = own.read_bytes()
        own.unlink()
        if said:
            with (out_dir / "stderr.log").open("ab") as fh:
                fh.write(said)
    except OSError:
        pass
    final = out_dir / "final.md"
    text = final.read_text(errors="replace") if final.exists() else ""
    sid_file = out_dir / "session_id"
    sid = sid_file.read_text(errors="replace").strip() if sid_file.exists() else ""
    session = sid or recovered_session(out_dir)
    mark = watching(out_dir)
    if not mark and not killed and said_nothing(out_dir) \
            and time.monotonic() - began < AUTH_GRACE:
        # nothing streamed and it was over in a minute: this turn never reached the model, so
        # ask why before treating a silence as one -- the verb, not a guess at the stderr
        authed, said = auth_ok(entry["harness"], run_id=turn_env.get(RUN_MARKER),
                               account=turn_env.get(config.ACCOUNT_ENV))
        mark = said if authed is False else None
    if mark:
        raise LoginExpired(entry["harness"], mark, session)
    return code, text, session, killed


def turn(cfg, model_name, body, workspace, out_dir, role="executor", session=None, env=None,
         limit=None, log=None, places=()):
    """One call and its cleanup; the fifth result says whether it left processes running."""
    # Let call apply harness defaults over inheritance; pass only explicit overrides.
    env = dict(env or {})
    # A turn ends independently of the suite and the loop's helpers, even on a plain host.
    marker = env.get(RUN_MARKER) or os.environ.get(RUN_MARKER) or run_marker("worker")
    marker = f"{marker}/turn-{uuid.uuid4().hex}"
    env[RUN_MARKER] = marker
    log = log or (lambda message: print(message, file=sys.stderr))
    try:
        result = call(cfg, model_name, body, workspace, out_dir, role, session, env=env,
                      limit=limit, places=places)
    finally:
        left = box.leftovers(out_dir)
        for pid, command in left:
            log(f"{role} {model_name} left process {pid}: {command}; stopping it")
        # Auth probes are helpers outside the turn's box; the marker still guards them.
        probes = marked_pids(marker, exact=True)
        for pid in probes:
            try:
                command = (Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
                           .replace("\0", " ").strip())
            except OSError:
                command = "command unavailable"
            log(f"{role} {model_name} left process {pid}: {command}; stopping it")
        if probes:
            kill_marked(marker, log=log, exact=True)
    return (*result, bool(left or probes))


def main(argv):
    if command_help.show("worker", argv):
        return 0
    opts = {"--workspace": None, "--out": None, "--session": None, "--role": "executor"}
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in opts:
            if i + 1 >= len(argv):
                raise config.Error(f"{arg} needs a value")
            opts[arg], i = argv[i + 1], i + 2
        elif arg.startswith("-"):
            raise config.Error(f"unknown flag {arg!r}; {command_help.WORKER_USAGE}")
        else:
            positional.append(arg)
            i += 1
    if len(positional) != 2:
        raise config.Error(command_help.WORKER_USAGE)
    model_name, task_path = positional
    if opts["--role"] not in PREAMBLES:
        raise config.Error(f"--role must be one of {', '.join(PREAMBLES)} (got {opts['--role']!r})")
    task = Path(task_path).expanduser()
    if not task.is_file():
        raise config.Error(f"no such task file: {task}")
    workspace = Path(opts["--workspace"] or ".").expanduser().resolve()
    if not workspace.is_dir():
        raise config.Error(f"no such workspace: {workspace}")
    config.ensure_dirs()
    out = Path(opts["--out"]).expanduser() if opts["--out"] else config.TMP / f"worker-{model_name}-{task.stem}"
    cfg = config.load()
    try:
        code, _, _, _, _ = turn(cfg, model_name, task.read_text(), workspace, out, opts["--role"],
                                opts["--session"])
    except LoginExpired as expired:
        # one turn on its own has no run to park: say what is wrong and what fixes it
        raise config.Error(str(expired)) from None
    print(Path(out) / "final.md")
    if code != 0:
        print(f"ak worker: {model_name} exited {code}; see {Path(out) / 'stderr.log'}", file=sys.stderr)
    return code
