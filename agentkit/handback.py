"""What a run hands back and to whom.

The words of a hand-back and its verdict, the seat a run speaks for and the
notice it gets, the delivery lock that keeps one ending from being told twice,
the project a run files under, and the follow-ups a merged run opens.  The
result a run writes, announcing its ending, and the recovery after a kill or a
memory cap still follow from `run.py`.
"""

import fcntl
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import config, gitcall, hand_in, host, notify, orch, plan, prompts, record as run_record, task as taskfile, transitions, turns


NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten")   # the hand-back spells the spent budget out


QUEUED_GRACE = 30               # old launchers did not record the background child's identity


_DELIVERY_HELD = threading.local()   # the delivery locks this thread is already inside


STALL_RESUME_GRACE = 600        # the tick stopped this loop and its resume is on the way; reap


def followup_place(text):
    """The review's site, independent of its wording or Markdown decoration."""
    site = re.search(r"([^\s`*]+):(\d+)\b", text)
    if site:
        return f"{site[1].removeprefix('./')}:{int(site[2])}"
    return text.splitlines()[0].strip()


def followup_open(state):
    """Whether this fix run is still on its way: running, about to, or resuming itself --
    stopped to wait on an older run's change too, which the tick starts again (`leases.parked`),
    and a FAIL on a conflict with main, which the tick parks and resumes (`parkable_conflict`)."""
    return (state.get("state") == "running"
            or (state.get("state") == "queued"
                and (run_record.process_active(state) or state.get("slot_waiting")))
            or (state.get("state") in ("waiting", "waiting_login", "exhausted", "error", "stopped")
                and transitions.going(state))
            or (state.get("state") == "interrupted" and state.get("deaths")
                and transitions.tick_resumes(state))
            or (state.get("state") == "fail"
                and transitions.parkable_conflict(state, config.RUNS / str(state.get("run_id")))))


def repair_open(state, tip):
    """Whether this repair run holds its command on the target at `tip`.

    The one answer to both "does this red get a repair" and "do its waiters retry": one
    repair per command per tip.  On its way it does, on any tip.  Ended, it holds the tip
    its launch recorded from the probe that found it failing (`repair_tip`) -- never one
    read off its branch later, which a rebase or an aborted integration moves -- unless it
    merged, which moved the target, or found the command passing there (`not needed`).
    Failed, passed unmerged or blocked, another run of it on that tip would only repeat it;
    a target that moved past it is a new red.
    """
    return followup_open(state) or (
        state.get("state") in run_record.ENDED and not transitions.delivered(state)
        and state.get("repair_tip") == tip)


def open_followup(state, text, repair=None, tip=None, split=None, check=None, held=None):
    """The open run already fixing `text`, or None.

    A review follow-up is the same `check` in the same repository from the same seat: a run
    whose done-when is that command fixes it, whatever its words; any other follow-up is the
    same site.  With `held`, the time its deferred line was written, a run that ended
    delivering it since counts too: the line's work is that run's, never a done's
    (`plan.outcomes`); one that delivered before had only an earlier line.  A `repair` is the
    same repository, target and command from any seat, open at the target's `tip`: the
    target is everybody's.  A suite split holds its line forever, and its repository while
    open.
    """
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if split:
            if (other.get("repo") == state.get("repo") and other.get("split_suite")
                    and (other["split_suite"] == split or followup_open(other))):
                return directory.name
            continue
        if (other.get("run_id") != state.get("run_id") and other.get("followup")
                and other.get("repo") == state.get("repo")
                and other.get("repair") == repair
                and (repair_open(other, tip) if repair else
                     transitions.launched_session(other) == transitions.launched_session(state)
                     and ((other["followup"].get("check") or "").strip() == check.strip() if check
                          else other["followup"]["place"] == followup_place(text))
                     and (followup_open(other) or held is not None and transitions.delivered(other)
                          and (other.get("finished_at") or 0) >= held))):
            return directory.name
    return None


def started_by(run_dir, item):
    """The fix run this ending already started for `item`, whatever became of it, or None: a
    handoff cut off before its receipt starts no item twice, not even one stopped since."""
    for directory in run_record.run_dirs():
        followup = (run_record.read_state(directory) or {}).get("followup") or {}
        if followup.get("run") == run_dir.name and followup.get("text") == item:
            return directory.name
    return None


def followups_handed(run_dir, state, handed):
    """Write the receipt that this ending's list is handed on: onto the record as it stands,
    so nothing written there meanwhile -- a stop, a delivery's mark -- is put back.  Read and
    written under `delivery_lock` too, taken inside the recovery lock as `reap` takes it: a
    delivery's mark lands before the read or after the write, never between them.  Then into
    the result, the one place that names them: a merge's ending, typed or only recorded
    (`routine_ending`), does not."""
    state.update(handed)
    with run_record.recovery_lock(run_dir), delivery_lock(run_dir), \
            run_record.record(run_dir) as current:
        current.update(handed)
    save_result(run_dir, notices=(followup_report(state),))


def plan_followup(session, repo, item, check, proven, log, deferred=True):
    """Write one review follow-up into the seat's plan, unless an open line already holds its
    check in this project; the entry the run's ending names it by, or why the plan refused it.
    `proven` is the commit the check failed on, which the line names; the line is `deferred`
    where a fix run has it.  The entry says how the plan holds the line: an open line that
    already held the check is kept, deferred or the seat's own as this merge finds it."""
    outcome = "Fix " + item.splitlines()[0].replace("·", "-")
    try:
        line = plan.add(session, outcome, check, repo, proven=proven, deferred=deferred)
        entry = {"outcome": outcome, "deferred": plan.deferred(line)}
    except (config.Error, OSError) as exc:
        entry = {"outcome": outcome, "refused": str(exc)}
    log(f"follow-up for {session}: {outcome}" + (f" (not planned: {entry['refused']})"
                                                if "refused" in entry else " (in its plan)"))
    return entry


def retry_command(state):
    """The one command that finishes a PASS whose delivery failed, or None.

    A run that reviewed its work and then could not push it is not over and not a new run's
    job: `ak run merge` picks up exactly where the delivery stopped.
    """
    if (state.get("state") != "pass" or not state.get("merge_failed") or state.get("scratch")
            or state.get("review_pr") or not state.get("repo")):
        return None
    return f"ak run merge {state['run_id']}"


def final_check_line(state, cmds):
    """The run's `final check:` result.md line: what the once-commands came to, and where."""
    record = state.get("final_check") or {}
    if record.get("outcome") in ("passed", "failed") and (
            record.get("sha") or record.get("where") in ("round", "landing")):
        sha = f" on {record['sha']}" if record.get("sha") else ""
        where = record.get("where")
        if where == "round":
            rnd = record.get("round")
            loc = f"in round {rnd}" if rnd else "in round"
            return f"final check: {record['outcome']} {loc}{sha}"
        if where == "landing":
            if record.get("tested") and record["tested"] != record.get("tree_sha"):
                return f"final check: {record['outcome']} at landing on tree {record['tested']}"
            return f"final check: {record['outcome']} at landing{sha}"
        if record.get("sha"):
            return f"final check: {record['outcome']} on {record['sha']}"
    if not taskfile.group_commands(cmds)[1]:
        return "final check: none (no once-commands)"
    return "final check: not run"


def result_done_when(cmds, state=None):
    """Commands as result.md shows them, including where each once-command ran."""
    record = (state.get("final_check") or {}) if isinstance(state, dict) else {}
    where = record.get("where") or ("landing" if record.get("outcome") else None)
    rnd = record.get("round")
    if where == "round":
        suffix = f"(once, in round {rnd})" if rnd else "(once, in round)"
    elif where == "landing":
        suffix = "(once, at landing)"
    else:
        suffix = "(once)"
    marked = []
    for cmd in cmds:
        bare, once = taskfile.split_once(cmd)
        if once and "(once" not in bare:
            cmd = f"{bare} {suffix}"
        marked.append(cmd)
    return marked


def save_result(run_dir, text=None, *, notices=()):
    """Publish a report or save its full notices without a rebuild losing them.

    Build the report before taking the delivery lock: while git reads its diff, the tick
    can deliver a notice. Read its saved section only at publication, under the same lock.
    """
    with delivery_lock(run_dir):
        result = run_dir / "result.md"
        try:
            saved = result.read_text()
        except FileNotFoundError:
            saved = ""
        heading = "\n## Seat notice\n\n"
        _, boundary, kept = saved.partition(heading)
        if text is None:
            missing = [part for part in notices if part and part not in kept]
            if missing:
                with result.open("a") as output:
                    output.write(heading + "\n\n".join(missing) + "\n")
        else:
            result.write_text(text + boundary + kept)


def write_result(run_dir, state, cmds, log=None, cfg=None):
    """The full result.md.  `log` carries a stop observed while reporting, if any.

    The state and exit code stay the delivery's -- a merged run is merged -- but nothing
    about a stop is silent: the diff-stat fallback names it, and its remedy is logged.
    """
    wt = Path(state["worktree"])
    # A blocked run heads its report with the word for it: nothing was delivered and nothing
    # was judged, so the delivery outcome would call FAIL on work that was never reviewed.
    outcome = ("BLOCKED" if state.get("state") == "blocked"
               else transitions.delivery(state, transitions.report_config(cfg)))
    parts = [f"# {outcome} — {state['title']}", "",
             f"VERDICT: {state['verdict']}",
             f"rounds: {len(state['round_summaries'])} of {state['rounds']}"]
    if state.get("scratch"):
        # no branch, no PR, no merge: the files are where this run's work went
        parts += [f"workspace: {wt}",
                  f"executor: {state['executor']}   reviewer: {state['reviewer']}",
                  "", "## Deliverables", gitcall.links(wt)]
    else:
        try:
            stat = gitcall.git(wt, "diff", "--stat", f"{state['base_sha']}...HEAD", check=False) or "(no changes)"
        except gitcall.Stopped as exc:
            # the report never depends on git working -- and a stop is recorded, not swallowed:
            # the diff-stat section names it, and the remedy goes to the log with everything else
            stat = f"(cannot read the diff: {exc})"
            if log is not None:
                log(f"ERROR {exc}")
        except config.Error as exc:
            stat = f"(cannot read the diff: {exc})"   # the report never depends on git working
        parts += [f"branch: {state['branch']}",
                  f"pr: {state.get('pr') or '(none)'}",
                  f"merged: {'yes' if state.get('merged') else 'no'}"]
        if state.get("merge_note"):
            parts.append(f"merge: {state['merge_note']}")
        retry = retry_command(state)
        if retry:
            parts.append(f"retry delivery: {retry}")
        parts += [f"worktree: {state['worktree']}",
                  f"executor: {state['executor'] or '-'}   reviewer: {state['reviewer']}",
                  "", "## Diff stat", "```", stat, "```"]
    if state.get("blocked"):
        parts += ["", state["blocked"], ""]
    parts += ["", "## Done-when", "```", "\n".join(result_done_when(cmds, state)), "```", ""]
    parts += [final_check_line(state, cmds), ""]
    if prompts.base_proof_line(state):
        parts += [prompts.base_proof_line(state), ""]
    # A model's summary need not repeat a stop; a fix started from this result
    # still needs the diagnostic the gate recorded before ending the children.
    try:
        with (run_dir / "log.txt").open(errors="replace") as progress:
            stopped = [line.rstrip().split("] ", 1)[1] for line in progress
                       if re.match(r"^\[\d\d:\d\d:\d\d\] done-when: stopped ", line)]
    except OSError:
        stopped = []
    if stopped:
        parts += ["## gitcall.Stopped checks", "", "```", *stopped, "```", ""]
    for entry in state["round_summaries"]:
        dw = {True: "done-when passed", False: "done-when failed"}.get(
            entry["done_when"], "done-when not run")
        parts += [f"## Round {entry['round']} ({entry['verdict']}, {dw})", "",
                  entry["summary"], ""]
    if state.get("error"):
        parts += ["## Why this run stopped", "", state["error"], ""]
    if state["verdict"] != "PASS" and prompts.overridden_section(state):
        parts += [prompts.overridden_section(state)]
    if state["verdict"] != "PASS" and state["findings"]:
        parts += ["## Reviewer findings", "", prompts.without_followups(state["findings"]), ""]
    if followup_report(state):
        parts += [followup_report(state), ""]
    if state.get("notes"):
        parts += ["## Notes", "", *("- " + item.replace("\n", "\n  ") for item in state["notes"]), ""]
    if state.get("disputes"):
        parts += ["## Disputes", "", *("- " + item.replace("\n", "\n  ") for item in state["disputes"]), ""]
    onward = transitions.continue_line(state, run_dir)
    if onward:
        parts += [onward, ""]
    save_result(run_dir, "\n".join(parts))


def run_project(state):
    """The checkout a run's work belongs to, or None when it belongs to none.

    A run belongs to the checkout its task's `repo:` names, else to its task folder's
    (`task_project`), never to one it merely inherits from where it was launched.  `project`
    is that answer, settled once by the process that launched the run (`preflight`), where a
    relative `repo:` still means something; so the run votes the same while it waits for a slot
    and once it works, whoever reads it from wherever.  A run launched before the field existed
    is read from its task: an absolute `repo:` is that checkout; a relative one is the checkout
    its record says it works in, once it has started, and no vote before, nobody else knowing
    what `.` meant; no `repo:` is its task folder's.  One with no task to read belongs to the
    repository it works on.
    """
    if "project" in state:
        return orch.checkout_of(state["project"])
    try:
        path = config.RUNS / state["run_id"] / "task.md"
        meta = taskfile.parse_task(path)[0]
    except (KeyError, TypeError, OSError, ValueError, config.Error):
        return task_project(state.get("repo"), state.get("task_file"))
    try:
        named = gitcall.repo_line(meta, path)
    except config.Error:
        # a launch refuses such a line, so only a receipt from before that has one, and it
        # never got as far as a project: it has none rather than breaking everyone who reads it
        return None
    if named and not named.is_absolute():
        return orch.checkout_of(state.get("repo"))
    return task_project(named, state.get("task_file"))


def task_project(repo, task_file):
    """The checkout a task belongs to: the repository it works in, else its task folder's.

    A task with no repository belongs to the checkout its task file's folder is named for: an
    orchestrator files a project's tasks under ~/.agentkit/tasks/<project>/, whatever the task
    works in.
    """
    if repo:
        return orch.checkout_of(repo)
    if not isinstance(task_file, str) or not task_file:
        return None
    try:
        parts = Path(task_file).resolve().relative_to((config.HOME / "tasks").resolve()).parts
    except (OSError, ValueError):
        return None
    if len(parts) < 2:
        return None
    return next((checkout for checkout in orch.checkouts()
                 if checkout.name.lower() == parts[0].lower()), None)


def join_session_project(session, runs=None):
    """File a session under the project most of its runs belong to, again at each launch.

    A session filed by hand (`ak orch project`) keeps that project: its job can be one project
    while most of its runs land in another.  Any other session's launched runs vote, each for
    its `run_project` from the moment it is queued; a run belonging to no checkout has no vote
    (`session_vote`).  A tie or no votes keeps the filing.  Returns the project the session
    has after the count.

    `runs` are run records a draw or a tick has already read, and from them only a session
    that still has no project when its turn at the lock comes is filed: a launch's own count,
    taken from disk, is never overwritten by one read before that launch's run was there.
    """
    if not session:
        return None
    try:
        session = config.resolve_session(session)
    except config.Error:
        return None
    # One count at a time per session: a count taken before a later launch's run was on
    # disk must not be written after that launch's, or the minority wins until the next.
    with notify.session_lock(session) as session:
        record = config.session_records().get(session)
        if record is None:
            return None
        repo = record.get("repo")
        if not record.get("filed") and (runs is None or not repo):
            repo = session_vote(session, (run_record.read_state(directory) or {} for directory in run_record.run_dirs())
                                if runs is None else runs, repo)
            if repo != record.get("repo"):
                config.update_session(session, repo=repo)
        return repo


def session_vote(session, states, repo=None):
    """The project most of the runs `session` launched, among `states`, belong to.

    `repo` is the project the session has: a tie keeps it, else goes to the first by name,
    and a session none of whose runs votes keeps it too.
    """
    votes = Counter()
    for state in states:
        try:
            if transitions.launched_session(state) != session:
                continue
        except config.Error:
            continue
        checkout = run_project(state)
        if checkout is not None:
            votes[str(checkout)] += 1
    if not votes:
        return repo
    most = max(votes.values())
    if votes.get(repo) == most:
        return repo
    return min((voted for voted, count in votes.items() if count == most),
               key=lambda voted: (Path(voted).name, voted))


def stamp_origin(state):
    """Stamp this launch's test origin on a run state going to disk, if it has one.

    A run launched while the sink marker is set records the marker's value in
    run.json, so everything that later speaks for the run obeys the record --
    the launching seat may be long gone and the reaping process unmarked.
    A run.json without the record is the owner's run and behaves as today: an
    empty stamp writes nothing.
    """
    marker = (os.environ.get(notify.SINK_ENV) or "").strip()
    if marker:
        state.setdefault("notify_sink", marker)
    return state


@contextmanager
def speaking_for(state):
    """The destination anything said for this run goes to: its launch record.

    A run launched under the sink marker sends its notices to that sink or
    nowhere, never to the owner's webhook -- even when `ak watch` reaps it
    hours later with no marker in its own environment.  A run.json without the
    record leaves the environment alone, which is today's behaviour exactly.
    """
    marker = state.get("notify_sink") if isinstance(state, dict) else None
    if not marker:
        yield
        return
    previous = os.environ.get(notify.SINK_ENV)
    os.environ[notify.SINK_ENV] = marker
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(notify.SINK_ENV, None)
        else:
            os.environ[notify.SINK_ENV] = previous


def redress_seat(session):
    """Rewrite the bar of the seat that launched a run now, not at the next tick or draw.

    A run's step, round and ending are what the bar names, so each one is published the moment
    it happens, through the one writer the tick uses and from the facts already on record: no
    look at the seat's screen.  The writer waits on the seat's lock and on tmux, so the run
    hands it to a `run-shell -b` job on the seats' own server (`publish_seat`) and waits on
    neither.  The handoff times out after a second; the next tick or step repairs a missed
    update.  The job is the server's, not the run's: the run's exit, the stop of its scope and
    its marker sweep leave it be.  A seat tmux has lost, and a legacy one on the user's own
    server, is no target there, so nothing runs for it; nothing here ever raises into the run.

    Every open menu hears of it first, whatever tmux holds: the run touches the one file they
    watch (`config.runs_moved_path`), which takes no lock, so the seat's row moves with its bar
    though the seat's word stays as it was -- a legacy seat's and a gone seat's rows included.
    """
    if not session:
        return
    try:
        config.runs_moved_path().touch()
    except OSError:
        pass   # the next draw's own read, or the menu's timer, catches up
    publish = shlex.join([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                          "from agentkit import handback; handback.publish_seat(sys.argv[2])",
                          str(config.REPO), session])
    try:
        # silent and always 0: tmux shows a job's output, or its failure, in the seat's pane
        orch.tmux_out("run-shell", "-b", "-t", f"={session}:",
                      orch.tmux_text(f"{publish} >/dev/null 2>&1; true"),
                      socket=orch.socket_name(), timeout=1)
    except Exception:  # noqa: BLE001 - the bar is dressing; the run beneath it is what matters
        pass


def publish_seat(session):
    """`redress_seat`'s job: that seat's bar, if tmux still holds it on agentkit's own server."""
    from . import watch  # here, not at the top: it reaches run
    seat = orch.find(session)
    if seat is not None and orch.on_own_server(seat):
        watch.announce_state(seat)


def seat_tallies(records, now=None):
    """What the runs each seat launched add up to: {seat: (running, needing him, merged)}.

    `running` is the runs still going of their own accord -- `going`, the same test the
    seat row's own reason counts, so `1 running` on the row and `1 running` in this tally can
    never disagree about a run parked on a window; the second figure is the endings still his
    -- menu.v5o_needs_look, again the test the row's reason reads; `merged` the merges of the
    last gc.GC_AGE.  From records already
    read, so the menu draws its rows and lists its runs from one pass over run.json, and
    read-only: nothing here reaps or writes.  A seat that launched nothing is not in the answer
    at all, and a record whose seat cannot be resolved counts for nobody.
    """
    from . import gc  # here, not at the top: it reaches run
    from . import menu
    now = time.time() if now is None else now
    states = list(records)
    index = transitions.supersession_index(states)
    found = {}
    for state in states:
        try:
            seat = transitions.launched_session(state)
        except config.Error:
            continue
        if not seat:
            continue
        counts = found.setdefault(seat, [0, 0, 0])
        if transitions.going(state):
            counts[0] += 1
        elif menu.v5o_needs_look(state, None, index, now):
            counts[1] += 1
        elif state.get("merged"):
            finished = state.get("finished_at") or state.get("started_at")
            if isinstance(finished, (int, float)) and now - gc.GC_AGE <= finished <= now:
                counts[2] += 1
    return {seat: tuple(counts) for seat, counts in found.items()}


def notice_title(state):
    """The run's title for the notice, with every path token dropped.

    A word carrying `/` or `~` is a path, and a path on this line is the worst of both: long
    enough to push the rest off it, and useless on the phone that reads it.  result.md has the
    paths, and `ak run status` names result.md.
    """
    words = (state.get("title") or state.get("run_id") or "agentkit run").split()
    return " ".join(word for word in words if "/" not in word and "~" not in word)


@contextmanager
def launcher_world(session):
    """Look for that seat in either world that may hold it, and act in the one that found it.

    Yields whether anybody is in it.  Finding the seat and typing into it have to happen in
    the same environment: a lookup that only succeeded with the suite's redirect lifted would
    otherwise be followed by a send that puts the redirect back and aims at the wrong server.
    See `launcher_watched` for why the inherited lookup always goes first.  Read-only either
    way: no seat is made, killed or attached, and the environment is always put back.
    """
    if orch.watching(session):
        yield True
        return
    dropped = {}
    for key in (orch.SOCKET_ENV, "TMUX_TMPDIR"):
        if key in os.environ:
            dropped[key] = os.environ.pop(key)
    try:
        yield orch.watching(session)
    finally:
        os.environ.update(dropped)


def launcher_watched(session):
    """Whether the seat that launched this run is still up, in either world that may hold it.

    The run inherits its launcher's environment, and a suite running inside a live seat
    points the seat lookup at servers of the suite's own ($AGENTKIT_TMUX_SOCKET and
    $TMUX_TMPDIR, the isolation check 0 of tests/smoke.sh requires): asking only there
    mistakes a live launcher seat for a gone one, and a run nobody orphaned reports an
    orphan.  But $TMUX_TMPDIR is also legitimately set (orch.job_env keeps it precisely
    so a child reaches the same servers), so the inherited lookup -- which keeps it --
    always goes first and its answer stands: the redirect is lifted for a second lookup
    only when the first already missed, which is exactly the suite's shape.  Read-only
    either way: no seat is made, killed or attached.
    """
    with launcher_world(session) as live:
        return live


def handback_verdict(state, cfg=None):
    """The words a hand-back line may carry about how a run ended.

    `PASS merged`, `PASS not merged`, `DONE`, `FAIL`, `BLOCKED`, `ERROR` -- the delivery outcome, not
    the review verdict, because what the orchestrator decides next turns on where the work
    went and not on what the reviewer thought of it.
    """
    if state.get("state") == "not_needed":
        return "DONE"
    if state.get("state") == "blocked":
        return "BLOCKED"
    if state.get("state") == "error":
        return "ERROR"
    if not transitions.delivery(state, transitions.report_config(cfg)).startswith("PASS"):
        return "FAIL"
    return "PASS merged" if state.get("merged") else "PASS not merged"


def handback_reason(state, cfg=None):
    """The one line after the verdict: why it ended that way, in the run's own words."""
    if state.get("state") == "not_needed":
        return " ".join(transitions.delivery(state, cfg).split())
    if state.get("state") in ("blocked", "error", "waiting"):
        return " ".join((state.get("error") or "no reason was recorded").split())[:300]
    # A memory-cap death is the whole news: rounds and findings say nothing about a
    # run the kernel stopped before it could finish a turn.
    cap_line = " ".join((state.get("error") or "").split())
    if cap_line.startswith("killed: memory cap"):
        return cap_line[:300]
    if state.get("state") not in run_record.ENDED and transitions.needs_recovery(state):
        # an interruption, or a stop no window will lift: what stopped it is the whole news,
        # and rounds and findings say nothing about a run that never reached its verdict.  A
        # resumed attempt that did reach one is an ending, `recovery_pending` or not, and says
        # what every other ending says.  Its own full stop goes: the line puts one after it.
        return " ".join(transitions.recovery_reason(state).split()).rstrip(".")[:300]
    word = transitions.delivery(state, transitions.report_config(cfg))
    if word.startswith("PASS, not merged: "):
        reason = word[len("PASS, not merged: "):]
        retry = retry_command(state)
        return f"{reason}; retry delivery: {retry}" if retry else reason
    if word.startswith("PASS"):
        return state.get("pr") or word[len("PASS, "):]
    # a FAIL hands back what the next step turns on: the rounds it spent and why they did
    # not pass -- the findings themselves, or the check still failing
    spent = len(state.get("round_summaries") or [])
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    if review_failed(state):
        rows = hand_in.Review(state["review_records"]).findings
        said = " ".join("\n".join("- " + hand_in.item_text(row) for row in rows).split())
        if len(said) <= 600:
            return f"after {spent} rounds, open findings: {said}".rstrip(".")
        # a line cut short must not read as the whole list: a fix of what it shows alone
        # spends the next round on the rest, so it names the reviewer's whole report
        count = f"{len(rows)} open findings" if len(rows) != 1 else "1 open finding"
        where = state.get("findings_file")
        whole = f" (every one in full: {where})" if where else ""
        return f"after {spent} rounds, {count}, cut short here{whole}: {said[:600]}".rstrip(".")
    # else a PASS the loop overrode says why it did, and a check still failing names its line
    why = "; ".join(filter(None, (review.get("overridden"), failed_check(state))))
    if why:
        return f"after {spent} rounds, {why}".rstrip(".")
    return " ".join((state.get("merge_note") or state.get("error")
                     or "no reason was recorded").split())[:300].rstrip(".")


def review_failed(state):
    """Blocking records distinguish a reviewer FAIL from a PASS the loop overrode."""
    return hand_in.Review(state.get("review_records") or []).verdict == "FAIL"


def failed_check(state):
    """The check a FAIL whose review passed still has failing, as the hand-back says it.

    The final check first, by the line `first_failure` read off it, else by the one its gate
    recorded; then the round's own done-when.  None when no check is failing.
    """
    history = state.get("done_when_failure")
    history = history if isinstance(history, dict) else {}

    def first(gate):
        for cmd, said in history.get(gate) or []:
            return f"`{cmd}` \u2014 {said}" if said else f"`{cmd}`"
        return None

    record = state.get("final_check") if isinstance(state.get("final_check"), dict) else {}
    if record.get("outcome") == "failed":
        where = record.get("where")
        if where == "round":
            rnd = record.get("round")
            loc = f"in round {rnd}" if rnd else "in round"
            log = f"see round-{rnd}/once.log" if rnd else "see once.log"
            return (f"the final check failed {loc}: "
                    + (record.get("line") or first("once") or log))
        if where == "landing":
            return ("the final check failed at landing: "
                    + (record.get("line") or first("once") or "see final-check.log"))
        return ("the final check failed: "
                + (record.get("line") or first("once") or "see final-check.log"))
    if first("every"):
        return f"the done-when failed: {first('every')}"
    return None


def planned_followups(state):
    """The review follow-ups a merge handed to its seat, as the ending's sentence about them:
    the lines a fix run took (deferred, holding no done), the lines that are the seat's own
    to build, and the lines its plan refused."""
    entries = state.get("followup_plan") or []
    planned = [entry for entry in entries if "refused" not in entry]
    deferred = [entry["outcome"] for entry in planned if entry.get("deferred")]
    owed = [entry["outcome"] for entry in planned if not entry.get("deferred")]
    refused = [f"{entry['outcome']} ({entry['refused']})" for entry in entries
               if "refused" in entry]
    checked = ("checked by the reviewer's probe until its fix is on the default branch or "
               "`ak plan check N` puts your own test in its place")
    return ((f"Review follow-ups now deferred in your plan: {'; '.join(deferred)}, each fixed "
             f"by a run of its own and {checked} and makes the line yours. " if deferred else "")
            + (f"Review follow-ups now in your plan, yours to build: {'; '.join(owed)}, each "
               f"{checked}. " if owed else "")
            + (f"Review follow-ups your plan refused, yours to judge: {'; '.join(refused)}. "
               if refused else ""))


def followup_report(state):
    """Keep everything a compact seat notice refers to in the run's result."""
    parts = []
    if state.get("followups"):
        parts += ["## Follow-ups", "",
                  *("- " + item.replace("\n", "\n  ") for item in state["followups"]), ""]
    if state.get("followup_plan"):
        parts += ["## Follow-up plan", "", planned_followups(state).strip(), ""]
    if state.get("followup_runs"):
        parts += ["## Fix runs", "", *("- " + name for name in state["followup_runs"]), ""]
    return "\n".join(parts)


def seat_notice(line, state, run_dir, brief, action="Decide the next step."):
    """A run line that fits stays unchanged; otherwise its files carry the whole news.

    Use the bound of a typed line (`watch.too_long`), including its byte limit, after every addition to the
    line. Never type even the compact form unless that bound accepts it and its full notice
    and follow-ups have been saved in result.md, including for an older pending ending.
    """
    from . import watch  # here, not at the top: it reaches run
    if not watch.too_long(line):
        return line

    def shown(path):
        try:
            return f"~/{path.relative_to(Path.home())}"
        except ValueError:
            return str(path)

    result = run_dir / "result.md"
    where = shown(result)
    report = result.name
    parts = [brief, f"Result: {where}."]
    count = len(state.get("followups") or [])
    if count:
        parts.append(f"{count} review follow-ups in full in {report}.")
    parts.append(action)
    if line.endswith(watch.FRESH_NOTE):
        parts.append(watch.FRESH_NOTE.lstrip("; "))
    compact = " ".join(parts)
    refusal = watch.too_long(compact)
    if refusal:
        raise config.Error(refusal)
    save_result(run_dir, notices=(line, followup_report(state)))
    return compact


def already_handed_back(state):
    """Whether this ending -- and not an earlier attempt's -- has already been handed back.

    `handed_back` is when the line was typed.  A run that reached its ending after that was a
    later attempt, whose own ending nobody has heard, whatever mark a resume failed to clear
    left behind: `clear_delivery` drops it on every new attempt, and this is the belt under
    that.  An undated mark from an older record is taken at its word.
    """
    said, ended = state.get("handed_back"), (state.get("finished_at")
                                             or state.get("interrupted_at"))
    if not isinstance(said, (int, float)) or isinstance(said, bool):
        return bool(said)
    if isinstance(ended, (int, float)) and not isinstance(ended, bool):
        return said >= ended
    return True


def owes_ending(state):
    """Whether this ending still has to be said, and nothing has said it.

    `handed_back` is the orchestrator having been told and `reported` is the ending having
    been given to the owner instead -- an orphan notice that landed, or the runs list handing
    a gone seat's ending over when he opened it.  An ending with neither has been heard by
    nobody -- a resumed attempt that ended carries no pending flag at all, because `reap`
    leaves an ending to `announce` -- so the tick keeps offering it until one of them is true.
    Which is why no pending flag is consulted here: one is how a delivery says it has not
    happened yet, and having happened is the only thing that stops the offer.

    An acknowledgement is not one of those.  Opening a run in `r` or naming it to `ak run
    status` marks it looked at, which settles it for the menu and for him -- but the owner is
    never the fallback for a run that did not work out, so him having glanced at it cannot be
    what the orchestrator was owed.  The hand-back still goes.

    A `stopped` run owes nothing at all: the stop was deliberate, so there is no ending
    to hand back and no card to send.

    An error the tick will retry owes nothing either: the retry is the next step, and
    saying "decide the next step" every hour for a run that resumes itself is the
    person being needed when they are not.  The stamp going away -- the worktree
    gone, the task unparsable -- is what starts the telling again.
    """
    if state.get("state") == "stopped":
        return False
    if transitions.going(state) and state.get("state") == "error":
        return False
    return (state.get("state") in run_record.ENDED and not already_handed_back(state)
            and not state.get("reported"))


def clear_delivery(state):
    """Forget what the last attempt's ending said: this one owes an ending of its own.

    A resume and a delivery retry both carry the old record forward, and its delivery marks
    with it.  Left there, a `handed_back` from the attempt before would make every later tick
    skip the new ending as already said; a `recovery_notified` would make the next
    interruption keep quiet because an earlier one had already spoken; and `reported` would
    fold the new ending out of the menu.  Every one of them is the last attempt's word.
    """
    for key in ("handed_back", "handback_pending", "handback_typed", "handback_note",
                "handback_wait_reason", "notification_pending", "recovery_notified"):
        state.pop(key, None)
    state["reported"] = False
    return state


@contextmanager
def delivery_lock(run_dir):
    """The one delivery an ending gets, held from deciding to say it until it is said.

    The loop that finished a run and the `ak watch` tick that found it unheard can both be
    holding a snapshot of the same ending.  Without this they both type the line and then
    write their own snapshot back, one of them over the other's marks, and the seat reads the
    ending twice.  Its own file, apart from the recovery lock: `reap` already holds that one while it
    calls down to here.

    Reentrant within a thread, and counted here because flock is not: `mark_delivery` takes it
    for every write it makes, and `hand_back` holds it across the whole decision the write is
    the end of.
    """
    held = getattr(_DELIVERY_HELD, "paths", None)
    if held is None:
        held = _DELIVERY_HELD.paths = set()
    mine = str(run_dir)
    if mine in held:
        yield
        return
    held.add(mine)
    try:
        with (Path(run_dir) / "delivery.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    finally:
        held.discard(mine)


def same_attempt(state, record):
    """Whether these two are the same attempt of a run, and not one either side of a resume.

    A resume keeps the directory and the id and carries the record forward: a new process owns
    it, and the ending it had is cleared.  A snapshot from before that is about an attempt
    nobody is waiting on any more, so nothing it decided may be written to the one running now
    -- an old `handed_back` would silence the new ending for good, and an old `pending_inbox`
    clear would lose the new question.  Whose process it is and when it ended are what tell
    them apart; a record with neither, as an old receipt or a fixture has, is its own attempt.
    """
    return all(state.get(key) == record.get(key)
               for key in ("pid", "finished_at", "interrupted_at"))


def mark_delivery(run_dir, state, **marks):
    """Write what a run still owes somebody onto the record as it stands, and nothing else.

    Never the caller's whole snapshot: two processes can be holding one each, and a whole
    save would put the older one back over the newer's marks -- including the `handed_back`
    that is the only thing stopping a second line.  The read and the write are one stretch
    under `delivery_lock`, so nothing can land between them either, and the record has to
    still be the attempt the caller decided about -- see `same_attempt` -- or nothing is
    written at all.  A mark given as None is removed; `pending_inbox`, the merge question a
    run still owes the inbox, is written the same way and for the same reason.  The caller's
    own copy is updated too, so what it does next reads what the record says.  False when the
    record had moved on and the marks were dropped.
    """
    with delivery_lock(run_dir):
        current = run_record.read_state(run_dir)
        if current is None:
            current = dict(state)
        elif not same_attempt(state, current):
            return False
        for key, value in marks.items():
            if value is None:
                current.pop(key, None)
                state.pop(key, None)
            else:
                current[key] = state[key] = value
        # Past `save_state`'s guard on purpose: these are endings a stop always
        # refuses, so no stop can race them, and this lock plus that one in this
        # order would invert the order `reap` takes them in.  See `save_state`.
        run_record._write_state(run_dir, current, run_record.DELIVERY_TEMP)
        return True


ROUTINE_NOTE = "routine ending: recorded, not typed"


def seat_owes_nothing(state):
    """Whether the seat that launched the run owes no work (`stop.owed`): then no turn of its
    waits on the run or on its change going live, and either is recorded, never typed.  A
    seat that owes work may have ended its turn on that very wait (`stop.recorded_ending`),
    so for it the ending, or the change going live (`watch.after_merge_health`), is the end
    of the wait and goes to it like any other."""
    from . import stop  # here, not at the top: they reach run
    session = transitions.launched_session(state)
    return not (session and stop.owed(session))


def routine_ending(state):
    """An ending nothing is the seat's to decide about: a merge, or a `not needed`, while the
    seat that launched it owes no work (`seat_owes_nothing`).  What it started (fix runs,
    plan lines) is in its result and the seat's plan, and `ak run status` names it.  A red
    target's repair's merge is routine whatever its seat owes: the runs parked on it retry by
    themselves, and their own endings end the seat's wait -- its going live is not, as the
    hook counts that wait.  A fix run's delivery has settled its line as it ended
    (`settle_delivered_line`): ticked where its fix is on the default branch, the seat's own
    where its check still fails, and then the ending goes to it.  Read only: it runs nothing."""
    if not transitions.delivered(state):
        return False
    return bool(state.get("repair")) or seat_owes_nothing(state)


def settle_delivered_line(state, log):
    """A fix run that delivered -- merged, or found its fix not needed -- runs its line's check
    in its seat's plan once, as it ends, and nothing else of that plan (`plan.delivery`): the
    line ticks where its fix is on the default branch, and is the seat's own where its check
    still fails or could not run."""
    check, session = (state.get("followup") or {}).get("check"), transitions.launched_session(state)
    if not (check and session and transitions.delivered(state)):
        return
    try:
        plan.delivery(session, check)
    except (config.Error, OSError) as exc:
        log(f"WARN could not check its line in {session}'s plan: {exc}")


def finish_typed(session, mark, log, cfg=None):
    """Whether nothing ak typed is left unsent in that seat's composer.

    A routine ending types nothing, but a line an earlier pass typed and never saw sent
    (`mark`, the receipt `watch.type_at_prompt` hands back) gets its Enter as that pass's
    would: left there, it would hold every later line back as the owner's draft.  A seat
    gone, down or reopened since holds no such line.
    """
    from . import watch  # here, not at the top: it reaches run
    if not (isinstance(mark, dict) and mark.get("line")):
        return True
    with launcher_world(session) as live:
        seat = orch.find(session) if live else None
        if not (watch.after_merge_live(seat) and seat.get("created") == mark.get("seat")):
            return True
        return watch.type_at_prompt(seat, mark["line"], log, cfg=cfg, typed=mark)


def _systemctl_fields(unit):
    """(Result, ControlGroup, OOMPolicy) for `unit`, or (None, "", "") when the manager
    cannot be asked.

    A unit it does not have is an empty Result, not a failure to ask: the caller
    tries the other suffix.  The labelled properties are parsed by name because
    `--value` does not promise the order they were requested in.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ControlGroup",
             "-p", "LoadState", "-p", "OOMPolicy"],
            capture_output=True, encoding="utf-8", errors="replace",
            env=orch.bus_env(), timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None, "", ""
    if proc.returncode != 0:
        return None, "", ""
    fields = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    if fields.get("LoadState") == "not-found":
        return "", "", ""
    return fields.get("Result", ""), fields.get("ControlGroup", ""), fields.get("OOMPolicy", "")


def _scope_oom_probe(state):
    """(systemd Result, oom_kill count) for the run's scope.  Either witness is enough.

    A scope that goes on past a kill (OOMPolicy=continue) counts none: the kill ended one
    process, and a loop dead in it later died of something else.
    """
    result, kills = "", 0
    for unit in turns._scope_units(state.get("scope")):
        shown, cgroup, policy = _systemctl_fields(unit)
        if shown is None:
            continue
        if policy != "continue":
            kills = max(kills, host._oom_kill_count(cgroup))
        if shown:
            result = shown
        if result == "oom-kill" or kills:
            return result, kills
    return result, kills


def memory_cap_reason(state, probe=None):
    """The memory-cap line when this scope was ended by its own cap, else None.

    A run that was not given a cap cannot have been killed by one, and a plain
    start has no scope to ask.  `probe` returns the unit Result and the oom_kill
    count so a test never asks the real manager.  Anything unreadable is not a
    memory kill: a dead loop with no witness stays the interruption it always was.
    """
    cap = state.get("memory_cap_mb")
    if type(cap) is not int or cap <= 0 or not turns.scope_is_real(state.get("scope")):
        return None
    probe = _scope_oom_probe if probe is None else probe
    try:
        result, kills = probe(state)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return None
    if result == "oom-kill" or (type(kills) is int and kills > 0):
        return turns.memory_cap_line(cap)
    return None


def free_run_dir(slug):
    """The run directory this minute's stamp and `slug` name, `-2`, `-3` on where it is taken."""
    name = f"{datetime.now():%Y%m%d-%H%M}-{slug}"
    directory = config.RUNS / name
    number = 1
    while directory.exists():
        number += 1
        directory = config.RUNS / f"{name}-{number}"
    return directory


def launch_line(run_id, title, executor, reviewer, *, self_review=None):
    """The one line a launch from a seat puts on the seat's terminal.

    A review-only run has no executor, so it names its reviewer instead of a pair;
    every other launch names both models.  One builder, every launch path.
    A round reviewed by the executor's own model says `self-reviewed`: the pair says
    it by name, except a review-only run of the seat's own PR, whose caller passes it.
    Callers that know the config pass identity, so an alias marks too.
    """
    if self_review is None:
        self_review = bool(executor and executor == reviewer)
    models = f"{executor}/{reviewer}" if executor else f"{reviewer} review"
    if self_review:
        models += ", self-reviewed"
    return (f"run {run_id} launched: {title} ({models}); "
            "it counts on this bar and in the menu; you will be told when it ends")
