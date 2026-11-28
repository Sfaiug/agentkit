"""Check parked landing-line stacks and wake each run to deliver or fix its own work.

Green evidence names the tested tree, including for stacks it covers. A red stack
after a green one blames its newest member, whose fixer waits until the runs ahead of it in
that stack have left the line, unless the tests it failed fail again on the target's tip with
it alone; later stacks are rebuilt without it.
A red suite piece runs again on the target's tip alone before anyone is blamed: red there
pauses the line on the retry ladder, and red through the ladder is the target's own and
gets one repair, at once where the tests that failed it fail again there alone.  So does a
file whose tests failed, then passed, on two trees (`_flaked`).  The lander never owns a member's
process or delivery.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager, nullcontext
import copy
import fcntl
from fractions import Fraction
import functools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import (config, gitcall, looks_alone, prompts, record, suite_times, transitions, turns,
               update, versions)

KEEP = 24 * 3600    # a recorded tree older than a day lands through its own suite again
CHECKED = 60        # a pass shorter than a minute checked nothing: it says nothing of the pace
FLAKY = 7 * 24 * 3600   # a file's tests failing, then passing, on two trees this close get one
                        # repair, which holds the file as long unless a change editing it merges
# A stack's scratch checkout says so in its own git directory, naming the checker that made it:
# one a killed checker left goes when a checker next starts a pass (`_clear_left`), or with gc a
# day unused, whatever it holds, and no other checkout for it.
SCRATCH_MARK = "ak-lander-scratch"
WAKE = 10           # a blamed run waits at most this long once no run it waits on is in line
BATCH = 2 * 3600    # on a busy host a whole suite waits at most this long for company,
COMPANY = 3         # and at most this many times its last green check (`gate.green_seconds`):
# two hours were sized on suites of some 40 minutes, and one of 94 seconds waited 2 h 02 min.
# Waiting three times its length, a suite holds the host a quarter of the time at most, as two
# hours held those; the owner chose "3x own check" (18 Nov 2026).
IDLE_SPAN = 60      # the seconds a mean of the host's idle processors spans at least: a run's end
                    # leaves its processors idle for about a minute before waiting work takes
                    # them (16 Nov 2026, #3746)


def _trees(turn, kind="trees"):
    path = turn.with_suffix(".green")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return path, {}
    kept = data.get(kind) if isinstance(data, dict) else None
    now = time.time()
    # Red probes do not age out into duplicate repairs; each tick checks the receipt.
    return path, {tree: entry for tree, entry in (kept or {}).items()
                  if isinstance(entry, dict)
                  and (kind == "red" or now - entry.get("at", 0) < KEEP)}


def passed(turn, tree):
    """The suite evidence for `tree` on `turn` -- `leader`, `tested`, `at`, `code` -- or None."""
    return _trees(turn)[1].get(tree)


def _red(turn, tree):
    """The tree whose target red `tree` has, its own or one it landed over (`as`), and that red."""
    reds = _trees(turn, "red")[1]
    root = (reds.get(tree) or {}).get("as", tree)
    red = reds.get(root)
    return root, None if red is None or "as" in red else red


def red_tests(turn, tree):
    """The tests the line holds its target at `tree` red on by name (`_red`)."""
    return (_red(turn, tree)[1] or {}).get("tests", [])


@functools.cache
def _code():
    """The ak commit this lander checks under: what another commit's lander saw holds only once
    both commits passed a check of the line (`_answering`)."""
    from . import run
    try:
        return run.git(config.REPO, "rev-parse", "HEAD")
    except config.Error:
        return None


def _answering(turn, kind):
    """The evidence of `kind` that answers this lander: its own commit's, and another's once
    that commit and this one each passed a check of the line -- an ak update that breaks the
    checks themselves passes none, so nothing seen before it or under it is trusted."""
    passing = ({entry.get("code") for entry in _trees(turn)[1].values()}
               | set(_trees(turn, "passed")[1])) - {None}
    return {tree: entry for tree, entry in _trees(turn, kind)[1].items()
            if entry.get("code") == _code()
            or {entry.get("code"), _code()} <= passing}


def note(turn, trees, leader, *, checks=(), tested=None, at=None, code=None, red=None,
         red_stacks=None):
    """Keep stack evidence, with the `checks` it ran and the lander `code` that ran them,
    separately from target probes awaiting their repair.  A pass a later one of the same tree
    replaces stays on record as its code's (`passed`), as it still proves that code passed the
    line.  Evidence kept again from an earlier pass (`at`) keeps that pass's code."""
    # Runs check beside the lander and each other; only the evidence write is serialized.
    with turn.with_suffix(".green.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path, kept = _trees(turn)
        failed = {} if red_stacks == {} else _trees(turn, "red_stacks")[1]
        repairs = _trees(turn, "red")[1]
        passes = _trees(turn, "passed")[1]
        for old in (kept[tree] for tree in trees if kept.get(tree, {}).get("code")):
            passes[old["code"]] = {"at": max(old["at"], passes.get(old["code"], {}).get("at", 0))}
        checked_at = time.time() if at is None else at
        kept.update({tree: {"at": checked_at, "tested": tested or tree, "leader": leader,
                            "checks": list(checks), "code": _code() if at is None else code}
                     for tree in trees})
        for tree, entry in (red or {}).items():
            if entry is None:
                repairs.pop(tree, None)     # the target's tip passed the piece again
            else:
                repairs[tree] = entry
                kept.pop(tree, None)     # a target found red holds no earlier pass
        failed.update({tree: {"at": time.time(), **fix, "checks": list(checks), "code": _code()}
                       for tree, fix in (red_stacks or {}).items()})
        for tree in trees:
            failed.pop(tree, None)
        fresh = path.with_name(path.name + ".new")
        fresh.write_text(json.dumps({"trees": kept, "red": repairs,
                                    "red_stacks": failed, "passed": passes}))
        fresh.replace(path)


@contextmanager
def _pass(turn):
    """The line's singleton flock, and the time each held pass takes: its start and process
    while it runs, then the last 20 that checked something.  While this process holds it, the
    pass's own: `fruitless`, how many passes before it in a row checked something and moved
    nobody, a pass whose process died mid-check one of them unless its record says it `moved`,
    and `moved`, None until it checks members, then whether it wrote one a verdict, and `waited`,
    whether it ended holding a whole suite off for company (`_waits_for_company`), and `idle`,
    the reading of the host it keeps should it hold one off (`_idle_mean`).  A pass that
    only waited counts for neither, and one that held a suite off neither, nor among the last
    20: a busy host holds one off at every retry, and their time would set the pace `stuck`
    reads."""
    from . import host
    with turn.with_suffix(".lander.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        kept = passes(turn)
        took = kept.get("took") or []
        held = SimpleNamespace(moved=None, fruitless=0 if kept.get("moved") else kept.get(
            "fruitless", 0) + bool(kept.get("started") and not record.process_active(kept)),
            waited=False, idle=host.IdleReading.of(kept.get("idle")))
        counted = {"fruitless": held.fruitless} if held.fruitless else {}
        started = time.time()
        held.start = {"took": took, **counted, "started": started, **record.process_owner()}
        _keep_passes(turn, held.start)
        try:
            yield held
        finally:
            spent = time.time() - started
            checked = spent >= CHECKED and not held.waited
            fruitless = 0 if held.moved else held.fruitless + (held.moved is False and checked)
            _keep_passes(turn, {"took": (took + [spent])[-20:] if checked else took,
                                **({"fruitless": fruitless} if fruitless else {}),
                                **({"idle": held.idle._asdict()} if held.waited and held.idle
                                   else {})})


def passes(turn):
    """The line's passes (`_pass`): `took`, the seconds of its last passes that checked
    something, `fruitless` while the last of those moved nobody, `idle` where the last held a
    suite off, and while one runs its `started`, process and, once it wrote a verdict,
    `moved`."""
    try:
        data = json.loads(turn.with_suffix(".passes").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _keep_passes(turn, data):
    path = turn.with_suffix(".passes")
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(json.dumps(data))
    fresh.replace(path)


def member(state):
    """Whether a record holds a place in its line: parked, or a green delivery that continues
    itself."""
    from . import handback
    wait = state.get("waiting_on")
    return (isinstance(wait, dict) and not state.get("merged")
            and (state.get("state") == "waiting"
                 or (green_delivery(wait)
                     and state.get("state") not in record.ENDED
                     and handback.followup_open(state)
                     and (record.process_active(state) or transitions.tick_resumes(state))))
            and isinstance(wait.get("line"), str)
            and type(wait.get("joined")) in (int, float))


def line(turn):
    """Green deliveries in tested stack order, then the rest in join order, the fixes of what
    holds them all first: a held install's (`update.first_place`) and the target's repair
    (`handback.start_followups`), on whose stack every one behind is checked excused none of
    the target's red (`holding`).  Joined 18th of 20, a repair was in neither of two passes
    that found the target red in more tests and moved nobody, checking 9 then 5 from the front
    (16 Nov 2026).  Their records every reader's (`record.runs`), so only read."""
    members = [(directory, state) for directory, state in record.runs()
               if member(state) and state["waiting_on"]["line"] == turn.name]
    deliveries = {directory.name: state["waiting_on"]["land"] for directory, state in members
                  if green_delivery(state["waiting_on"])}
    # A repaired member keeps its join place behind the deliveries its tree includes.
    # A predecessor's replacement verdict does not stand in for its earlier tested tree.
    return sorted(members, key=lambda member: (
        not green_delivery(member[1]["waiting_on"]),
        sum(deliveries.get(name) == tree
            for name, tree in member[1]["waiting_on"].get("after", {}).items())
        if green_delivery(member[1]["waiting_on"])
        else not (member[1].get("repair") or update.first_place(member[1])),
        member[1]["waiting_on"]["joined"], member[0].name))


def green_delivery(wait):
    """A green delivery stays ahead: the stacks behind it are the ones that can land."""
    return "land" in wait and "fix" not in wait


def red_stack(wait):
    """Whether the lander found `wait`'s member red on top of runs ahead of it, named in its
    `after`.  Its fixer works on the member's branch rebased onto the target, which holds
    none of their changes until they land, so it waits for them to leave the line before
    waking to fix.  A delivery's red required checks keep `land` beside their `fix`: theirs."""
    return "fix" in wait and "land" not in wait and bool(wait.get("after"))


def red_behind(wait, names):
    """Whether a `red_stack` verdict still waits on runs in the line, `names`."""
    return red_stack(wait) and bool(wait["after"].keys() & names)


@contextmanager
def _waking(turn, log):
    """The pass's `wake`: each parked member of the line as it stands with a `fix` that waits
    on no run in it (`red_behind`) is woken, once a pass.  Asked as the pass starts and ends,
    for each verdict it gives, and every WAKE seconds while it runs: the runs ahead leave on
    their own time, and one check holds a pass for hours (a run blamed behind runs that all
    merged at 20:26 waited past 22:40 for the next pass, 5 Nov 2026).  Each wake ends with
    the line's next delivery (`deliver_next`)."""
    from . import watch
    # a resume takes its record a moment after its start, and one refused leaves it parked:
    # that one the next pass wakes again
    woken, launched, done = set(), {}, threading.Event()

    def wake():
        members = line(turn)
        names = {directory.name for directory, _ in members}
        for directory, state in members:
            if (state.get("state") == "waiting" and "fix" in state["waiting_on"]
                    and not red_behind(state["waiting_on"], names)):
                # `woken` under the run's own lock: two threads of the pass wake it once
                with record.recovery_lock(directory):
                    if (directory.name not in woken and record.read_state(directory) == state
                            and not record.process_active(state)):
                        woken.add(directory.name)
                        watch.launch_resume(directory.name, log)
        deliver_next(turn, log, launched, members)

    def watching():
        while not done.wait(WAKE):
            wake()

    wake()
    watcher = threading.Thread(target=watching, daemon=True)
    watcher.start()
    try:
        yield wake
    finally:
        done.set()
        watcher.join()
    wake()


def deliver_next(turn, log=lambda _: None, launched=None, members=None):
    """Wake the line's head, its first green delivery, once it is parked with no process and
    no resume of it is coming up; no other delivery is woken for its place.

    Only the head takes the merge lock (`deliver.members_ahead`): each delivery woken behind
    it only polls for its turn.  On 13 Nov 2026 a green stack of 41 woke 41 runs, the load
    went from 125 to 215 on 18 cores and one merged every ~100 s (7 in 12 min), against 15 to
    25 s uncontended.  Asked by each wake of a pass (`_waking`), the one after each verdict
    too, and by each delivery as it ends (`deliver.land_from_line`), handing on the turn.
    A resume coming up writes the run's log (`watch.resumes`) until it takes the record or
    ends; a terminal's only follows the run it started, as long as the run waits in line.
    `launched` holds the (pid, identity) of each head a pass woke while that process lives:
    one refused or dead is woken again at the pass's next wake."""
    from . import host, watch
    try:
        members = line(turn) if members is None else members
        green = [(directory, state) for directory, state in members
                 if green_delivery(state["waiting_on"])]
        if not green:
            return False
        head, state = green[0]
        # under the run's own lock, as `_waking`'s: two threads of a pass wake it once
        with record.recovery_lock(head):
            pid, identity = (launched or {}).get(head.name, (None, None))
            if ((identity is not None and host.process_identity(pid) == identity)
                    or state.get("state") != "waiting"
                    or record.read_state(head) != state or record.process_active(state)
                    or any(writes for _, writes in watch.resumes(head).values())):
                return False
            pid = watch.launch_resume(head.name, log)
            if not pid:
                return False
            if launched is not None:
                launched[head.name] = (pid, host.process_identity(pid))
        log(f"{head.name} delivers next in {turn.name}, {len(green) - 1} waiting behind it")
        return True
    except (OSError, config.Error) as exc:
        log(f"WARN could not wake the next delivery in {turn.name}: {exc}")
        return False


def start_line(turn, log=lambda _: None):
    """Start a fresh checker when no pass is running; the tick and every follower of a
    member (`job.job_await`) retry a missed start."""
    from . import host, orch, run, worker
    turn = Path(turn)
    if turn.parent != config.RUNS or not turn.name.startswith(".merge-"):
        return False
    try:
        with turn.with_suffix(".lander.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            members = line(turn)
            if not any(state.get("state") == "waiting" and not record.process_active(state)
                       for _, state in members):
                return False
        # The suite gets the run's derived allowance or the largest recorded need,
        # never the small scope of the run or tick that happened to start this pass.
        readings = host.host_readings(slice_dir=orch.slice_cgroup)
        total = host._reading(readings, "mem_total_mb", "total_mb", "mem_total")
        ceiling = orch.slice_memory_max_mb(total) or total
        caps = [value for _, state in members for key in ("memory_cap_mb", "peak_rss_mb")
                if type(value := state.get(key)) in (int, float)
                and math.isfinite(value) and value > 0]
        if ceiling and ceiling > 0:
            caps.append(run.memory_cap_mb(ceiling))
        # Every passed run waits behind this check: it outweighs every run for the CPU.
        properties = ("-p", f"CPUWeight={host.CPU_WEIGHT_MAX}")
        if caps:
            _, properties = run.run_scope_limits(cap_mb=math.ceil(max(caps)),
                                                 cpu_weight=host.CPU_WEIGHT_MAX)
        env = config.child_env()
        # This work outlives its caller and must not belong to the caller's stop sweep.
        for key in (worker.RUN_MARKER, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_ROLE",
                    config.JOB_DIR_ENV, config.SESSION_ENV, config.UNATTENDED_ENV):
            env.pop(key, None)
        env["AK_RUN_DEPTH"] = "0"
        return orch.start_in_slice(
            [sys.executable, str(versions.installed_ak()), "run", "--lander", turn.name],
            f"agentkit-lander-{turn.stem.removeprefix('.merge-')}-{time.time_ns()}",
            env, turn.with_suffix(".log"), log, target_slice=orch.run_slice_name(),
            properties=properties, nice=True)
    except (OSError, config.Error) as exc:
        log(f"WARN could not start lander for {turn.name}: {exc}")
        return False


def paused(red):
    """Whether a red target entry holds the line on the retry ladder: probed red on the
    target's tip alone, with no repair started and the ladder not yet climbed.  An entry an
    earlier lander kept counts no probes: it is the target's own, as that lander judged."""
    return (bool(red) and not red.get("run")
            and 0 < red.get("probes", 0) <= len(turns.TRANSIENT_BACKOFF))


def _scratch(repo, commit, opened):
    """A scratch checkout of `commit`, removed when `opened` closes, or None with why not."""
    from . import run
    config.WT.mkdir(parents=True, exist_ok=True)
    scratch = Path(opened.enter_context(tempfile.TemporaryDirectory(dir=config.WT, prefix="land-")))
    opened.callback(os.close, os.open(scratch, os.O_RDONLY))
    code, out = gitcall.add_worktree(repo, scratch, "--detach", commit, mark=SCRATCH_MARK)
    opened.callback(run.git_out, repo, "worktree", "remove", "--force", str(scratch))
    return (scratch, "") if not code else (None, f"[exit {code}]\nERROR: checkout of {commit} failed\n{out}")


def _clear_left():
    """Remove each scratch checkout (`_scratch`), of any line, whose checker is gone: a killed
    one removes none of its own (two left 187, about 28 GiB, 10 Nov 2026).  One whose mark names
    no maker yet is gc's."""
    for scratch in config.WT.glob("land-*"):
        code, private = gitcall.git_out(scratch, "rev-parse", "--absolute-git-dir")
        try:
            maker = None if code else json.loads(Path(private, SCRATCH_MARK).read_text())
        except (OSError, ValueError):
            continue
        if isinstance(maker, dict) and not record.process_active(maker):
            # twice: one killed before `add_worktree` unlocked it is still locked as its own
            gitcall.git_out(scratch, "worktree", "remove", "--force", "--force", str(scratch))


def _probe_tip(turn, directory, state, scratch, tip, upstream, tree, suite, piece, log, green,
               tests=None, over=(), behind=False):
    """Run the red `piece` of `suite` ("" for the suite whole) on `scratch`, the target's tip
    alone, for the member in `directory`: True when it passes there, so the red is the
    member's own, the piece then in `green`, what the tip passed on this pass.  Where
    the stack's red was its `tests` failing again alone, those alone run there first: passing
    there, each named as run (`gate.run_suite(only=)`), the member's change is what fails them,
    and the piece need not run.  Failing there again, named as run and as failed by a run that
    ended in a failing exit on the pinned tip (`gate.run_suite(confirmed=)`), they are a red that
    repeats, which no step of the retry ladder would clear: the target's own, repaired at once,
    and the piece need not run either.  A probe that neither passes nor confirms one of them
    (the tests are not on the tip, as a test the member added is not; its runner named nothing)
    proves nothing, so the whole piece then decides, but for a member `behind` green stacks
    (`blame`): the red stays the member's own and no whole piece runs on the tip, as the member
    alone on the tip did fail them, nothing says the tip does, and a piece on the tip for every
    member blamed for its own new test would cost each pass minutes.
    Red there is the target's: the entry under `tree` counts the probe and holds the line
    (`paused`) until the retry ladder's next step, and red through the whole ladder starts the
    target's one repair (`_repair`); a repeat of named tests keeps them in the entry, with those
    it kept before, excuses them in the fixes the line gave before (`_excuse`), and walks for
    the commit that first turned the target red (`_blame_tip`).
    Where the stack excused `over`, the target's named red, the suite whole decides instead: red
    there in nothing else, the red is the member's own, and the entry stays as it is."""
    path = directory / "target-probe.log"
    again = None
    if tests:
        ok, probe, red = _check(directory, state, scratch, [suite], path, log, suite=suite,
                                shard=piece or None, only=tests, kind="tip")
        again = red.get("tests")
        if ok:
            log(f"{upstream} at {tip[:12]} passes the tests that failed {directory.name}'s "
                f"piece AK_SHARD={piece}, run alone: the red is the member's own")
            return True
        _put_back(scratch, tip)
        if behind and not again:
            return True
    if not again:       # a repeat needs no piece to say the tip is red
        # a pinned piece confirms none of the tests it failed: only those say a red is `over`'s
        piece = "" if over else piece
        ok, probe, red = _check(directory, state, scratch, [suite], path, log,
                                shard=piece or None, kind="tip", over=over)
        if "over" in red:
            green.add(piece)
            return True
    if ok:
        # the pass is the piece's, named so it covers no stack's own checks
        note(turn, [tree], directory.name, checks=[f"{suite} (AK_SHARD={piece})" if piece else suite],
             red={tree: None})
        green.add(piece)
        return True
    held = _red(turn, tree)[1] or {}
    # A repeat is kept as the whole ladder climbed: a later pass, after a PR's fixer took the
    # red or a crash came before its repair was noted, finds the target's own red, never a pause.
    probes = (len(turns.TRANSIENT_BACKOFF) + 1 if again else
              held.get("probes", 0) + 1 if (held.get("probe") or {}).get("sha") == tip else 1)
    red = {"probe": {"command": suite, "piece": piece, "check": f"{suite}  # once", "sha": tip,
                     "text": prompts.red_target_text(suite, upstream, tip, probe, directory,
                                                     piece=piece)},
           "at": time.time(), "probes": probes,
           **({"tests": sorted({*held.get("tests", ()), *again})} if again else {})}
    # A stack found red on this tip may have been red in nothing but the tip's own red.
    note(turn, [], directory.name, red={tree: red}, red_stacks={})
    what = f"its piece AK_SHARD={piece}" if piece else "its suite"
    if probes > len(turns.TRANSIENT_BACKOFF):
        how = (f"{' '.join(again)} of {what} again, run alone" if again else
               f"{what} alone through the retry ladder")
        log(f"{upstream} at {tip[:12]} fails {how}: the target's own red, repaired")
        _repair(turn, directory, state, tree, red, log)
        # A red that named no test blames nobody: on an earlier commit a piece's number holds
        # other tests, and a walk of whole suites is not worth a history row.
        if again:
            _excuse(turn, red["tests"], suite)
            _blame_tip(directory, state, scratch, tip, suite, piece, again, log)
    else:
        log(f"{upstream} at {tip[:12]} fails {what} alone: the line waits, nobody is blamed; "
            f"probed again in {turns.transient_delay(probes) // 60} min")
    return False


def _excuse(turn, tests, command):
    """Name `tests`, the target's own red just found, `excused` in each parked fix the line's
    checks gave (`red_part`): one given before they were known, often on the very pass that
    found them, tells its fixer of them as one given after does (`prompts.excused`).  As there,
    a stack that held a repair of `command`, the repair or a member behind it (`after`), answers
    for them (`_check_members`)."""
    members = line(turn)
    repairs = {directory.name for directory, state in members
               if (state.get("repair") or {}).get("command") == command}
    for directory, state in members:
        fix = state["waiting_on"].get("fix") or {}
        if ("command" not in fix or fix.get("excused") == tests    # a conflict, moved head or rule
                or repairs & {directory.name, *state["waiting_on"].get("after", ())}):
            continue
        with record.recovery_lock(directory):
            if record.read_state(directory) == state and not record.process_active(state):
                with record.record(directory) as current:
                    current["waiting_on"] = {**current["waiting_on"],
                                             "fix": {**fix, "excused": tests}}


def _blame_tip(directory, state, scratch, tip, suite, piece, tests, log):
    """Find the first red first-parent commit within KEEP and 64 commits, by just the `tests`
    of `suite`'s `piece` that failed again alone on the tip: the oldest first, then halving.

    A red the clock or the host made (a fixture's date passed) fails on every commit, and the
    pass, and so the line, waits for each check: the oldest red ends the walk at one check
    where halving takes six, at the price of one more for a commit's red.

    The tip already failed twice. Start its repair before walking; no blame waits on a
    repair's outcome, and no repair waits on these checks. A commit that does not hold the
    tests passes them (`gate.passes_what_it_holds`); one red without failing them again by name
    ends the walk, as a fail followed by a pass does, never a green boundary.
    """
    from . import history, run
    try:
        commits = run.git(scratch, "rev-list", "--first-parent", "--max-count=64",
                          f"--since=@{int(time.time() - KEEP)} +0000", tip).splitlines()[::-1]
        low, high = -1, len(commits) - 1
        while high - low > 1:
            mid = (low + high) // 2 if low >= 0 else 0
            sha = commits[mid]
            _put_back(scratch, sha)
            exits, flaky, absent = [], [], []
            ok, _, red = _check(directory, state, scratch, [suite], directory / f"tip-{sha}.log",
                                log, suite=suite, shard=piece or None, only=tests, kind="tip",
                                exits=exits, flaky=flaky, absent=absent)
            if flaky or any(0 in attempts and any(code != 0 for code in attempts)
                            for attempts in exits):
                log(f"{sha[:12]} is flaky: nobody is blamed")
                return
            ok = ok or bool(absent)
            repeated = any(len(attempts) >= 2 and all(code is not None and code > 0
                                                     for code in attempts) for attempts in exits)
            if not exits or red.get("short") or not (ok or repeated and red.get("tests")):
                log(f"{sha[:12]} has no repeated red: nobody is blamed")
                return
            if ok:
                low = mid
            else:
                high = mid
        if not commits:
            return
        if high == 0:
            log(f"red before {commits[0][:12]}: nobody is blamed")
            return
        sha = commits[high]
        name = history.blame_merge(sha, "tip", log=log)
        log(f"{sha[:12]} first turned the target red: {name}" if name else
            f"{sha[:12]} merged outside ak: no history row to blame")
    except (OSError, config.Error) as exc:
        log(f"WARN could not find the target's first red commit: {exc}")
    finally:
        _put_back(scratch, tip)


def _repair(turn, directory, state, tree, red, log):
    """Keep the probe before launch: a crash can reuse its repair receipt without a suite.

    A PR's own seat is its fixer, as for its review findings: a PR never gets a repair run,
    and is handed the red target as its own landing finding -- its next head is checked on
    its own merits, so one that repairs the target lands (see `check_line`).
    """
    if state.get("review_pr"):
        path = directory / "target-red.log"
        path.write_text(red["probe"]["text"] + "\n")
        with record.recovery_lock(directory):
            if record.read_state(directory) != state or record.process_active(state):
                return None
            with record.record(directory) as current:
                current["waiting_on"] = {**current["waiting_on"], "fix": {
                    "line": red["probe"]["text"].splitlines()[0], "log": str(path)}}
        return None     # the pass wakes it (`_waking`)
    name = _start_repair(state, directory, red["probe"], log)
    if name:
        note(turn, [], directory.name, red={tree: {**red, "run": name}})
    return name


def _start_repair(state, directory, repair, log):
    """The member in `directory`'s repair run of the target: started, already open, or None."""
    from . import handback
    try:
        return handback.start_followups(state, directory, log, repair=repair)
    except record.StopRequested:
        raise
    except Exception as exc:  # a refused repair leaves the line waiting, unblamed
        log(f"WARN no repair could start: {exc}")
        return None


def _file(test):
    """The file `test` is in: its name up to its first `::` (a pytest node) or `#` (a smoke
    block), all of it with neither."""
    return test.split("::")[0].split("#")[0]


def _first_holding(stacks, red, tests):
    """The first of `stacks` whose tree holds a file (`_file`) of `tests`, where the stack at
    `red` holds each one's, else 0: a test named by no file there may fail anywhere.  Each path
    is read as a revision names it once rid of what changes nothing on disk, a leading `./` and
    a `/` or `./` after a `/`, so `./t/a.sh` and `t//a.sh` are `t/a.sh`.  The rest stays, so a
    `..` (a symlink may stand before it), a trailing `/` or `/.` (a directory's), a directory,
    or a name no path can be, is no file."""
    from . import run
    files = {re.sub(r"^(\./)+|(?<=/)\.?/", "", _file(test)) for test in tests}

    def holds(index):
        return [run.git_out(stacks[red][2], "cat-file", "-t", f"{stacks[index][3]}:{path}")
                == (0, "blob") for path in files]
    return next(index for index in range(red + 1) if any(holds(index))) if all(holds(red)) else 0


def _flaked(turn, directory, state, scratch, tree, log_path, log, flaky, failed, passed):
    """Keep in the record of the line `turn` the tests that failed, then passed, on `tree`, as
    this member's check there found them: `flaky`, those `gate.run_done_when` names, and those
    a check confirmed red there (`failed`, by command) once a later one passes them (`passed`,
    by command: the tests it ran, None for all), each toward its file.  A file seen so on two
    trees within FLAKY, whichever of its tests, gets one repair of the target, owned by this
    member, and holds it until a change editing it merges or FLAKY has passed; what its tests
    saw before then is that repair's."""
    from . import run
    now = time.time()
    with turn.with_suffix(".flakes.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = turn.with_suffix(".flakes")
        try:
            kept = json.loads(path.read_text())
        except (OSError, ValueError):
            kept = {}
        seen, repairs = kept.get("seen", []), kept.get("repairs", [])
        for name, entry in kept.get("tests", {}).items():     # kept by test before files
            seen += [{"test": name, **sight} for sight in entry.get("seen", ())]
            repairs += [{"file": _file(name), **entry["repair"]}] if "repair" in entry else []
        seen = [sight for sight in seen if now - sight["at"] < FLAKY]
        repairs = [repair for repair in repairs if now - repair["at"] < FLAKY]
        logs, reds = {test: [] for test in flaky}, []     # each test seen, its red's log first
        for red in (red for red in kept.get("red", ()) if now - red["at"] < FLAKY):
            ran = passed.get(red["command"], ()) if red["tree"] == tree else ()
            logs.update((test, [red["log"]]) for test in red["tests"] if ran is None or test in ran)
            rest = [test for test in red["tests"] if ran is not None and test not in ran]
            if rest:
                reds.append({**red, "tests": rest})
        if not (logs or any(failed.values())):
            return
        # a later check of the tree writes over its log: the one that shows it is kept
        handle, shown = tempfile.mkstemp(dir=log_path.parent, prefix=f"{log_path.stem}-seen-",
                                         suffix=log_path.suffix)
        os.close(handle)
        shutil.copyfile(log_path, shown)
        reds += [{"tree": tree, "command": cmd, "tests": named, "at": now, "log": shown}
                 for cmd, named in failed.items() if named]
        for file in dict.fromkeys(map(_file, logs)):
            upstream = _upstream(state)
            held = max((repair for repair in repairs if repair["file"] == file),
                       key=lambda repair: repair["at"], default=None)
            if held and not run.git_out(scratch, "diff", "--quiet", held["sha"], upstream, "--",
                                        file)[0]:
                seen = [sight for sight in seen if _file(sight["test"]) != file]    # the repair's
                continue
            repairs = [repair for repair in repairs if repair["file"] != file]  # released for good
            seen += [{"test": test, "tree": tree, "at": now, "logs": [*before, shown]}
                     for test, before in logs.items() if _file(test) == file]
            sights = [sight for sight in seen if _file(sight["test"]) == file]
            trees = {sight["tree"] for sight in sights}
            if len(trees) > 1:
                tip = run.git(scratch, "rev-parse", f"{upstream}^{{commit}}")
                suite = gitcall.declared_suite(scratch, ref=tip)
                # its first sight keys the repair: no run of an earlier hold answers for it
                name = _start_repair(state, directory, {
                    "command": file, "check": f"{suite}  # once", "sha": tip,
                    "flaky": min(sight["at"] for sight in sights),
                    "text": prompts.flaky_test_text(file, state["repo"], upstream, sights)}, log)
                if name:
                    log(f"{file} failed, then passed, on {len(trees)} trees: repaired by {name}")
                    seen = [sight for sight in seen if _file(sight["test"]) != file]
                    repairs.append({"file": file, "run": name, "at": now, "sha": tip})
        fresh = path.with_name(path.name + ".new")
        fresh.write_text(json.dumps({"red": reds, "seen": seen, "repairs": repairs}))
        fresh.replace(path)


def check_line(turn, log=lambda _: None):
    """Check ready stacks from the first member without a verdict, under the singleton flock.

    The singleton is separate from delivery so checks and merges can overlap.
    Saved verdicts are woken again if a crash or refused launch left them parked.  A member
    can resume or stop during its check: only an unchanged, processless parked record gets
    the verdict.  The recovery lock covers that write and the wake, never the suite.
    """
    from . import handback, history, roundloop, run
    turn = Path(turn)
    _code()     # read as the pass starts: an update installed during a check is not this pass's
    with _pass(turn) as held, ExitStack() as waking:
        if not held:
            return
        _clear_left()
        # Checks may return after their first group; no saved red waits for that walk to reach it.
        wake = waking.enter_context(_waking(turn, log))
        target, prefix, tip_green = None, [], set()    # the pieces the tip passed on this pass
        looks = set()   # the members of looks alone (`looks_alone`): first place, own verdicts
        members = copy.deepcopy(line(turn))     # its own: it writes its answers into them
        for index, (directory, state) in enumerate(members):
            with record.recovery_lock(directory):
                if record.read_state(directory) != state or record.process_active(state):
                    if green_delivery(state["waiting_on"]):
                        prefix.append((directory, state))
                    continue
                if "fix" in state["waiting_on"]:
                    continue
            if state.get("state") != "waiting":
                prefix.append((directory, state))
                continue
            if target is None:
                # The project's checkout, not the member's: a member delivers as soon as it
                # has its `land`, its checkout going with it, while this pass goes on.
                repo = Path(state["repo"])
                gitcall.no_auto_gc(repo)
                # The repository's machine-side settings, as a run's own checks get them.
                os.environ.update(config.repo_env(repo))
                upstream = _upstream(state)
                run.fetch(repo, "origin", "--prune", check=True)
                tip = run.git(repo, "rev-parse", f"{upstream}^{{commit}}")
                target = tip, run.git(repo, "rev-parse", f"{tip}^{{tree}}")
                # Changes of looks alone go behind the deliveries, ahead of every member
                # waiting for its verdict: each gets its own (`_looks`) before any suite starts.
                # That runs only the tests a change brings and its task's `# once` commands, so a
                # member is one only where its review's record holds `chosen_passed`, set only by
                # `roundloop._review` when that PASS itself ran its chosen tests green (owner,
                # 13 Nov 2026: "always fully tested before going live").  No commit is asked
                # about in `history.checks`: once ak rebases a change after PASS keeping its
                # review (`integrate`, `deliver.land_from_line`), `head_sha` is the new commit
                # while the `chosen` row sits under the old one -- measured on 27 Nov 2026 in
                # logs of runs whose chosen tests ended green, 33 of 66 and 48 of 109 on two
                # busy projects (3 of 31 on two quiet ones) were rebased right after their PASS.
                # Every rebase keeping a review copies its record whole, while a fresh review
                # replaces it and `pending_review` drops it, and a PASS without review never
                # sets it.
                ready = {saved["review"]["head_sha"]: member for member, saved in members[index:]
                         if saved.get("state") == "waiting" and not record.process_active(saved)
                         and (saved.get("review") or {}).get("verdict") == "PASS"
                         and saved["review"].get("chosen_passed")
                         and not {"land", "fix"} & saved["waiting_on"].keys()}
                # a head from a clone of its own is fetched as it is asked about: only on a
                # target that lets any change of looks alone through
                states = dict(members)
                looks = {ready[head] for head in looks_alone.changes(repo, tip, (
                    head for head, member in ready.items()
                    if not _member_commit(repo, states[member], head)[0]))}
                members[index:] = sorted(members[index:], key=lambda member: (
                    not green_delivery(member[1]["waiting_on"]), member[0] not in looks))
                directory, state = members[index]
            tip, target_tree = target
            root, red = _red(turn, target_tree)
            name = over = None
            if paused(red):
                # the target's tip fails a piece of its suite alone: the line waits on the
                # retry ladder, nobody woken, and at each step the piece runs there again
                if time.time() - red["at"] < turns.transient_delay(red["probes"]):
                    return
                with ExitStack() as opened:
                    scratch, text = _scratch(repo, tip, opened)
                    if scratch is None:
                        log(f"WARN {text.splitlines()[-1]}")
                        return
                    piece = red["probe"].get("piece") or ""
                    if not _probe_tip(turn, directory, state, scratch, tip, upstream, target_tree,
                                      red["probe"]["command"], piece, log, tip_green):
                        return
                red = None
            if red and (passed(turn, target_tree) or {}).get("tested") != target_tree:
                name = red.get("run")
                repair = record.read_state(config.RUNS / name) if name else None
                holds = repair and handback.repair_open(repair, red["probe"]["sha"])
                if not (holds or repair and transitions.delivered(repair)
                        or state.get("review_pr")):
                    # none yet, or the last let go of this red unmended: another goes first
                    if repair:
                        log(f"{name} ended without mending {upstream} at {tip[:12]}: "
                            f"another repair")
                    name = holds = _repair(turn, directory, state, root, red, log)
                    if not name:
                        continue    # refused: a later member may start it, a PR may mend it
                if holds and red.get("tests"):
                    # named tests are their repair's alone: the line lands over them meanwhile
                    over, name = {"tree": root, "tests": red["tests"], "run": name}, None
                elif not holds or state.get("review_pr"):
                    name = None     # it mended the target, or a PR's own tree may mend it
                if name and directory.name != name:
                    continue
            verdict = {key: state["waiting_on"][key] for key in ("land", "fix")
                       if key in state["waiting_on"]}
            if directory in looks and not name:
                verdict = _looks(directory, state, repo, tip, prefix, log)
            checked = not verdict
            if checked:
                if any(saved["waiting_on"].get("looks") for _, saved in prefix):
                    # no suite stands on one before it is on the target, whose tip answers for
                    # its red: its delivery starts the next pass (`deliver.land_from_line`)
                    return
                if (state.get("review") or {}).get("verdict") != "PASS":
                    continue
                candidates = [(directory, state)]
                for later, saved in members[index + 1:] if not name else ():
                    with record.recovery_lock(later):
                        if (record.read_state(later) != saved or record.process_active(saved)
                                or saved.get("state") != "waiting" or "fix" in saved["waiting_on"]):
                            continue
                        if ((saved.get("review") or {}).get("verdict") == "PASS"
                                and "land" not in saved["waiting_on"]):
                            candidates.append((later, saved))
                # After passes that moved nobody, fewer: one alone always ends in a verdict or
                # in the target's own red.
                take = max(1, len(candidates) >> held.fruitless)
                if take < len(candidates):
                    log(f"{held.fruitless} pass{'es' if held.fruitless > 1 else ''} in a row "
                        f"checked this line and moved nobody: this one checks the first {take} of "
                        f"the {len(candidates)} members waiting, as fewer change under a shorter pass")
                    candidates = candidates[:take]
            else:
                candidates = [(directory, state)]
            sent, snapshots, offered, cut = set(), dict(candidates), {}, len(candidates)

            def publish(answers):
                """Write each verdict offered this pass that still stands, under the recovery
                locks, and say how many candidates, from the first, a verdict of it could still
                go to.  Candidates stack in line order, so a candidate's tree holds the prefix
                and those ahead of it, never one behind: the first that changes under the pass,
                the cut, costs the verdicts from it on, and nothing ahead of it.  A verdict a
                later stack's check covered (`tested`) stands only while that stack is ahead of
                the cut too, as its member must land with it.  A changed prefix member or first
                candidate leaves none: every tree stands on it.  A pass that had checked 3.5
                hours with 60 stacked was thrown away for one member that changed, one of 32
                such passes in the logs (13 Nov 2026)."""
                nonlocal cut
                if checked and held.moved is None:
                    # asked before each check: a pass that never came to one only waited
                    held.moved = False
                if not cut:
                    return 0
                offered.update(answers)
                # Delivery rewrites ownership and rebase receipts, but keeps the reviewed
                # work and tested tree. Only an unwoken recipient must stay processless.
                with ExitStack() as locks:
                    for place, (member, saved) in enumerate(prefix + candidates[:cut]):
                        locks.enter_context(record.recovery_lock(member))
                        if member in sent and "fix" in saved["waiting_on"]:
                            continue  # this member is already omitted from rebuilt stacks
                        current = record.read_state(member)
                        if member not in snapshots or member in sent:
                            review = (current or {}).get("review") or {}
                            tree = saved["waiting_on"]["land"]
                            same = (current and review.get("verdict") == "PASS"
                                    and roundloop.passed_review_head(current) == roundloop.passed_review_head(saved)
                                    and ((current.get("waiting_on") == saved["waiting_on"]
                                          and current.get("state") not in record.ENDED
                                          and (current.get("state") == "waiting"
                                               or (handback.followup_open(current)
                                                   and (record.process_active(current) or transitions.tick_resumes(current))))
                                          and review.get("tree_sha") in (saved["review"].get("tree_sha"), tree))
                                         or ((current.get("merged") or current.get("on_target"))
                                             and review.get("tree_sha") == tree)))
                        else:
                            same = current == saved and not record.process_active(current)
                        if not same:
                            cut = max(0, place - len(prefix))
                            if cut:
                                log(f"{member.name} changed during this pass, which goes on for the "
                                    f"{cut} ahead of it: it and the {len(candidates) - cut - 1} "
                                    "behind it wait for the next pass")
                            break
                    # the member a covered verdict's check ran on gives its own verdict just after
                    tested = {answer["land"]: member for member, answer in offered.items()
                              if "land" in answer and "tested" not in answer}
                    places = {member: place for place, (member, _) in enumerate(candidates)}

                    def stands(member, answer):
                        under = tested.get(answer["tested"]) if "tested" in answer else member
                        return max(places[member], places.get(under, cut)) < cut

                    fresh = {member: answer for member, answer in offered.items() if member not in sent
                             and (cut == len(candidates) or stands(member, answer))}
                    if not fresh:
                        # No answers asks only whether a verdict of this pass could still be
                        # written: not once each candidate ahead of the cut has had its own.
                        return cut if answers or cut == len(candidates) or any(
                            member not in sent for member, _ in candidates[:cut]) else 0
                    for member, answer in sorted(fresh.items(), key=lambda item: "land" in item[1]):
                        with record.record(member) as current:
                            current["waiting_on"] = {**current["waiting_on"], **answer}
                        # Later answers still compare against this pass's own writes.
                        snapshots[member]["waiting_on"] = dict(current["waiting_on"])
                        # A landing's reds, once, as the verdict blaming them is written: a
                        # check's red the pass then found the target's own blames nobody.
                        fix = answer.get("fix") or {}
                        history.test_reds((member, None, "landing", fix.get("commit")),
                                          {fix.get("piece"): fix.get("tests") or
                                           fix.get("failed", ())}, ())
                    sent.update(fresh)
                    if checked and not held.moved:
                        # kept at once: a pass killed after this moved the line all the same
                        held.moved = True
                        _keep_passes(turn, {**held.start, "moved": True})
                    wake()      # fixes, and the line's next delivery (`deliver_next`)
                return cut

            if checked and over:
                log(f"{upstream} fails {' '.join(over['tests'])} of its own, which {over['run']} "
                    "repairs: this pass lands a stack red in nothing else over them, unproven")
            verdicts = (_check_members(turn, candidates, repo, tip, target_tree, log, prefix=prefix,
                                      ready=publish, held=held, tip_green=tip_green, over=over)
                        if checked else {directory: verdict})
            if not verdicts:
                return
            if publish(verdicts) and checked:
                # A reparked member must retry red suffixes discarded during rebuilding.
                note(turn, [], directory.name, red_stacks={})
            if checked:
                return
            if green_delivery(state["waiting_on"]):    # as its record took it: a fresh one
                prefix.append((directory, state))     # it refused stacks nothing


def red_part(cmds, marks, pieces, confirmed, suite, ok, parts=None, over=()):
    """What the checks found red, from the exits the runner saw (`marks`, and `pieces` by
    command and share): the first failing `command`, its first confirmed red `piece`'s share
    (`k/N`), or its first red piece where none is confirmed, and
    the `tests` that piece named that failed, or hung, again alone (`confirmed`), if any; a
    command run whole runs none alone, and names as `failed` those its last go failed, for its
    verdict to keep (`check_line`).  The
    piece is "" where the command ran whole or a piece was killed confirming none -- at the
    limit, which stops its siblings with it, or for silence -- and the suite whole where no
    command failed and yet the checks did not pass (the
    checkout changed under them, the suite's own doing as far as the lander can tell); {}
    where the checks passed or no exits were reported.  A piece out of memory
    (`gate.OUT_OF_MEMORY`) is red only where no other is, and then `short`: the host's red,
    nobody's.  `parts`, a list, gets every red piece of that command that confirmed tests no
    piece before it did, each as this names one, with just those tests, and this one first, where
    this one confirmed any.
    Tests among `over`, the target's own red, are named by none: a piece that confirmed nothing
    else is not red, checks red in nothing else are `over` those they failed, and a red of
    anything else has them all `excused`."""
    from . import gate
    if ok or not marks:
        return {}
    landed = []     # the tests of `over` the checks failed
    excused = {"excused": list(over)} if over else {}
    for cmd, mark in zip(cmds, marks):
        if mark == 0:
            continue
        codes, named = pieces.get(cmd, {}), confirmed.get(cmd) or {}
        own = {share: [test for test in named.get(share, ()) if test not in over]
               for share in codes}
        reds = sorted((share for share, code in codes.items()
                       if code != 0 and (own[share] or not named.get(share))),
                      key=lambda share: (codes[share] == gate.OUT_OF_MEMORY, not own[share],
                                         int(share.split("/")[0])))
        if not reds and any(code != 0 for code in codes.values()):
            landed += [test for tests in named.values() for test in tests]
            continue
        piece = "" if not reds or any(code is None and not named.get(share)
                                      for share, code in codes.items()) else reds[0]
        if piece and codes[piece] == gate.OUT_OF_MEMORY:
            return {"command": cmd, "piece": piece, "short": True}
        tests = own[piece] if piece else None
        if tests and parts is not None:
            # A test every piece runs, red in each, is one question: asked once for each piece,
            # it ran alone on the top rebuilt without the culprit 21 times, passing each time,
            # before that top went whole (14 Nov 2026).
            asked = set()
            for share in reds:
                still_open = [test for test in own[share] if test not in asked]
                if codes[share] != gate.OUT_OF_MEMORY and still_open:
                    parts.append({"command": cmd, "piece": share, "tests": still_open})
                    asked.update(still_open)
        failed = [] if codes else [test for tests in named.values() for test in tests
                                   if test not in over]
        return {"command": cmd, "piece": piece, **({"tests": tests} if tests else {}),
                **({"failed": failed} if failed else {}), **excused}
    if landed:
        return {"over": sorted(set(landed))}
    return {"command": suite, "piece": "", **excused} if suite else {}


def _check(directory, state, scratch, cmds, log_path, log, *, suite=None, shard=None,
           only=None, kind="landing", exits=None, flaky=None, absent=None, parts=None, over=()):
    """(whether the checks passed, their output, what they found red as `red_part` reads it,
    with the `commit` checked, `suite` standing for a red no command showed, `parts` getting its
    pieces that confirmed tests where those cost less together than the commands took); with
    `shard` every command runs as that one piece alone, on one turn, and with `only` just those
    tests, on none, `absent` getting those not there where it passed the rest
    (`gate.passes_what_it_holds`).
    Each command, or piece of one, leaves its `kind` row in history under the member's run, on
    the commit checked: `landing`, its reds kept by the verdict that blames them on a change
    (`check_line`), or `tip` for a probe of the target's. `exits` keeps each
    piece's attempt exits and `flaky` the tests that failed, then passed; a moved checkout
    clears the exits and `absent`.  `over`, the target's own red tests, is `red_part`'s and
    `run_suite`'s `known`."""
    from . import gate, run
    identity = gitcall.commit_identity(scratch)
    clean = run.git_out(scratch, "diff", "--quiet", "HEAD")[0] == 0
    # The checker takes a heavy turn without marking any member's record.
    wait = state["waiting_on"]
    context = {"repo": state["repo"], "run_id": directory.name, "landing": True,
               "since": wait["joined"], "line": wait["line"]}
    sharded = None if shard else next((cmd for cmd in cmds if gate.names_shard(cmd)), None)
    marks, pieces, confirmed = [], {}, {}
    timings, lengths = {}, {}
    flaky = [] if flaky is None else flaky
    absent = [] if absent is None else absent
    # Tests named alone cost what a model's own test does, which takes no turn: on a host out of
    # CPU none comes until it is idle, and the wait held whole lines up to an hour (30 Oct 2026).
    with nullcontext() if only else gate.gate_turn(None, log_path, log, sharded, scratch,
                                                   context=context):
        started = time.monotonic()      # a wait for the turn is no part of what a check costs
        ok, text = gate.run_done_when(
            cmds, scratch, log_path, set(),
            3600 * state.get("ceiling_hours", record.CEILING_HOURS), log,
            silence=60 * state.get("silence_minutes", record.SILENCE_MINUTES), heavy=True,
            marks=marks, shard=shard, pieces=pieces, only=only, confirmed=confirmed,
            flaky=flaky, checked=(directory, None, kind, identity["head_sha"]), exits=exits,
            timings=timings, took=lengths, absent=absent, known=over, blamed=kind == "landing")
        took = time.monotonic() - started
    if ok and suite and kind == "landing" and not shard and not only:
        if failure := suite_times.refusal(scratch, _upstream(state), suite, timings):
            ok = False
            text += "\n\n" + failure
    moved = (not clean or gitcall.commit_identity(scratch) != identity
             or run.git_out(scratch, "diff", "--quiet", "HEAD")[0])
    if moved:
        ok = False
        if exits is not None:
            exits.clear()
        confirmed.clear()   # a test that failed on whatever it moved to says nothing of the pin
        absent.clear()      # nor one that was not there
        text += ("\n\nCheckout changed during the final check; "
                 "these commands do not verify the pinned commit.")
    if ok and not shard and not only:
        # Green only here: a suite's pieces end on a helper, in retries or at the deadline after
        # the gate's own measure, and a suite that passed is refused above.
        gate.checked_green(scratch, lengths)
    text = f"Commit: {identity['head_sha']}\nTree: {identity['tree_sha']}\n\n{text}"
    log_path.write_text(text)
    if not moved:
        # a pinned piece passing ran just `only` of its tests, and without them, none it names
        _flaked(config.RUNS / wait["line"], directory, state, scratch, identity["tree_sha"],
                log_path, log, flaky,
                {cmd: [test for tests in confirmed.get(cmd, {}).values() for test in tests]
                 for cmd in cmds},
                {cmd: only if shard else None for cmd, mark in zip(cmds, marks)
                 if mark == 0 and (only or not shard)})
    red = red_part(cmds, marks, pieces, confirmed, suite, ok, parts, over)
    # Parts run alone one after another, at what the record holds for their tests, where the
    # check runs its pieces at once: a change that broke every piece left 22 parts, close to two
    # hours, ahead of a whole check that took one (14 Nov 2026).
    if parts:
        times = suite_times.read(suite_times.handed(scratch))
        if sum(times.get(test, 0) for part in parts for test in part["tests"]) > took:
            parts.clear()
    return ok, text, red and {**red, "commit": identity["head_sha"]}


def _upstream(state):
    """The remote branch `state`'s run lands on."""
    upstream = state.get("target") or state["base"]
    return upstream if upstream.startswith("origin/") else f"origin/{upstream}"


def _put_back(scratch, commit):
    """Put `scratch` at `commit`, clean, for the next check on it: detached, as a branch a check
    checked out there is shared with the repository and keeps its commit."""
    from . import run
    run.git(scratch, "checkout", "--force", "--detach", commit)
    run.git(scratch, "clean", "-fdx")


def _member_commit(repo, state, head):
    """One remote's line can contain private commits from separate clones."""
    from . import run
    if run.git_out(repo, "cat-file", "-e", f"{head}^{{commit}}")[0] == 0:
        return 0, ""
    source = state.get("worktree") or state.get("repo") or str(repo)
    return run.git_out(repo, "fetch", "--no-tags", "--no-write-fetch-head", "--", str(source), head)


def _pr_moved(state, heads):
    """Why a PR in the line no longer holds the head that passed its review, or "": its seat
    pushed since.  `heads` keeps each PR's head for the pass; an unreadable one is not moved."""
    from . import deliver, run
    url = state.get("review_pr")
    if not url:
        return ""
    if url not in heads:
        try:
            heads[url] = run.pr_view(url).get("headRefOid")
        except config.Error:
            heads[url] = None
    head = heads[url]
    if not head or head in deliver.own_pr_heads(state):
        return ""
    return (f"its PR's head moved to {head[:12]} after review of "
            f"{(state.get('head_sha') or '?')[:12]}: the new commits are reviewed before "
            "the line checks them")


def _stack_member(repo, state, top, upstream, opened, scratch=None):
    """Integrate a reviewed head in scratch, the one given put back at the head; no scratch
    means setup failed."""
    from . import roundloop, run
    head = (state.get("review") or {}).get("head_sha")
    if not head:
        # A green delivery whose review an older ak erased in the line: its resume takes it
        # out (`transitions.leaves_line`), and the line is checked without it.
        return None, "ERROR: no reviewed commit: the run's review is gone\n"
    if scratch:
        _put_back(scratch, head)
    else:
        code, out = _member_commit(repo, state, head)
        if code:
            return None, f"[exit {code}]\nERROR: reviewed commit {head} is unavailable\n{out}"
        scratch, text = _scratch(repo, head, opened)
        if text:
            return None, text
    lp = SimpleNamespace(state=state, wt=scratch,
                         base_sha=state.get("base_sha") or
                         run.git(scratch, "merge-base", head, top))
    how = roundloop.how_to_integrate(lp)
    # A detached rebase must not rewrite the member's branch through Git config.
    args = ("merge", "--no-edit", top) if how == "merge" else (
        "-c", "rebase.updateRefs=false", "rebase", top)
    code, out = gitcall.merge(scratch, top) if how == "merge" else run.git_out(scratch, *args)
    text = (f"$ git {' '.join(args)}\n[exit {code}]\n"
            f"ERROR: {how} of {upstream} failed\n{out}") if code else ""
    return scratch, text


def _landing_checks(directory, state, scratch, tip):
    """The member's own landing checks on `scratch`: its `# once` commands and the suite.

    The target's suite judges the change, and a `tests:` line the change rewrites must pass
    too: once on the target it is the only suite every later change lands through, and one
    that cannot run there would refuse them all (owner rule, 21 Oct 2026: "landing also runs a
    branch's changed tests: line, besides main's, and refuses the branch if that new line
    fails")."""
    from . import gate, task
    _, body, _ = task.parse_task(directory / "task.md")
    # A review PR owes the target's suite, never an earlier head's suite too.
    cmds = [] if state.get("review_pr") else task.done_when(body, directory / "task.md")
    # A `# once` line written as the suite the member started from is that suite: it runs once,
    # as the target declares it now, not in both spellings.  So is a repair's, written as the
    # suite of the tip it repairs (`_probe_tip`, `_flaked`): started as the target's line
    # changed, or rebased onto the change since, its base declares the new line already.
    earlier = [(gitcall.declared_at(scratch, state[commit], "tests"), True)
               for commit in ("base_sha", "repair_tip") if state.get(commit)]
    cmds = [cmd for cmd in cmds if task.split_once(cmd) not in earlier]
    once = task.group_commands(gitcall.with_suite(cmds, scratch, ref=tip))[1]
    # Added after grouping: a shell line with an odd quote would hide a `# once` marker.
    own = gitcall.declared(scratch, "tests")
    suite = gitcall.declared_suite(scratch, ref=tip)
    if own and suite and own != suite:
        # A line starts as many pieces at once as the host fits at its cost: unmeasured, a
        # rewritten line took twice the places its suite's cost fits (11 Nov 2026).
        gate.inherit_suite_cost(own, suite, scratch)
    if own and own not in (suite, *once):
        once.append(own)
    return tuple(once)


def _check_tests(directory, state, scratch, tree, command, piece, tests, log, over=()):
    """The stack's answer from just `tests` of `command`'s `piece`, or {} if inconclusive.  A
    pass, each test named as run or as not there, one a later member adds
    (`gate.passes_what_it_holds`), moves the narrowing deeper and answers for nothing else; a
    failure, of the tests confirmed, moves it earlier.  Anything else proves nothing -- a test
    the suite skips without naming it -- so that stack gets its whole check on its original
    checkout.  Those among `over`, the target's own red, the stack passes unrun.
    """
    from . import run
    tests = [test for test in tests if test not in over]
    if not tests:
        return {"land": tree}
    head = run.git(scratch, "rev-parse", "HEAD")
    log_path = directory / f"lander-{tree}-tests.log"
    absent = []
    ok, text, red = _check(directory, state, scratch, [command], log_path, log, suite=command,
                           shard=piece or None, only=list(tests), absent=absent, over=over)
    _put_back(scratch, head)
    if ok or absent:
        return {"land": tree}
    return {"fix": {"line": prompts.first_failure(text), "log": str(log_path),
                    **red}} if red.get("tests") else {}


def _probe(directory, state, scratch, tree, command, tests, cost, here=False):
    """Whether just `tests` of `command` pass on the stack `scratch` holds, run once as a suite
    helper's piece of `cost` (CPUs, MiB) runs them (`gate.pinned`), on a helper or `here` in a
    box as the single step runs them: True where each was named as run (`AK_RAN`) or as not
    there (`gate.passes_what_it_holds`), False where the run failed naming one of them both as
    run and as failed (`AK_FAILED`), or silence stopped it before it ended one of them
    (`gate.unfinished`), and None where it proved neither -- no helper took it, it was stopped
    otherwise, the helper lost it, had no room or handed back no names, a test was not named as
    run.
    It takes no turn, leaves its `checks` row and records nothing else, no flaky sighting
    either: a red only a probe shows is no evidence (`_check_tests` decides)."""
    from . import gate, helper, history, run, worker
    asked, head = time.time(), run.git(scratch, "rev-parse", "HEAD")
    times = suite_times.handed(scratch)
    there, files = gate.pinned(command, times, only=tests)
    away = None if here else helper.start(*cost, scratch, lambda _: None, there, one=True,
                                          files=files)[0]
    if not (here or away):
        return None
    log_path = directory / f"lander-{tree}-probe.log"
    silence = 60 * state.get("silence_minutes", record.SILENCE_MINUTES)
    named = {"ran": [], "failed": [], "absent": []}     # what a run here names
    stops = []
    try:
        with log_path.open("wb") as output, history.check(
                (directory, None, "landing", head), command, asked, away and away.alias) as ended:
            # A hang ends as a suite piece's first go does, at its suite's pace: its round
            # waits for it.
            how = {"cwd": str(scratch), "activity": log_path, "output": output,
                   "silence": gate.quiet_window(command, scratch, None, silence) or silence,
                   "on_timeout": lambda why, _pid: stops.append(why),
                   "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
            limit = 3600 * state.get("ceiling_hours", record.CEILING_HOURS)
            code, _, killed = (
                worker.limited(helper.piece(away, "1/1", there), limit, env=gate.suite_env(),
                               **how) if away else
                worker.boxed(["bash", "-c", there], limit, used=ended, times=times, only=tests,
                             env={**gate.suite_env(), "AK_SHARD": "1/1"}, **named, **how))
            ended["exit"] = None if killed else code
        if stops == ["silence"] and gate.unfinished(tests, log_path, named["failed"]):
            return False
        if killed or code < 0 or away and code in (*helper.GONE, helper.FULL):
            return None
        ran, failed, absent = ([helper.failed(away, "1/1", which)
                                for which in ("ran", "failed", "not-there")] if away else
                               named.values())
        if None in (ran, failed, absent):
            return None
        if code and set(tests) & set(ran) & set(failed):
            return False
        return gate.passes_what_it_holds(code, tests, ran, failed, absent) or None
    finally:
        if away:
            helper.finish(away)
        else:
            _put_back(scratch, head)


def _round(stacks, floor, high, command, tests, log):
    """One round of a red stack's narrowing: probes (`_probe`) of the stacks between `floor` and
    `high`, as many as the suite helpers have places for, or where they have none as this host
    fits (`gate.places`), spread evenly and all at once, and each probed stack's answer once
    the last has ended; {} where neither has a place.  Probes running the same tests end about
    together, so waiting for the last costs little, and none outlives its round: nothing is
    ever called off on a helper."""
    from . import gate, helper
    cost = gate.suite_cost(command, stacks[high][2], None)[1:]
    away = helper.places(*cost, stacks[high][2])
    count = min(away or gate.places(*cost), high - floor - 1)
    picked = [floor + (n + 1) * (high - floor) // (count + 1) for n in range(count)]
    with ThreadPoolExecutor(max_workers=max(1, count)) as pool:
        probes = {index: pool.submit(_probe, *stacks[index][:4], command, tests, cost, not away)
                  for index in picked}
    answers = {index: probe.result() for index, probe in probes.items()}
    if answers:
        said = {True: "passes", False: "fails", None: "proves nothing"}
        log(f"{' '.join(tests)} {'on the suite helpers' if away else 'on this host'}: " +
            ", ".join(f"{said[answer]} up to {stacks[index][0].name}"
                      for index, answer in answers.items()))
    return answers


def _check_tree(directory, state, scratch, tree, checks, log, suite, over=()):
    """The stack's answer from its whole check, a red one with the `parts` it confirmed
    (`red_part`), or {} where it ran out of memory again."""
    log_path = directory / f"lander-{tree}.log"
    parts = []
    ok, text, red = _check(directory, state, scratch, list(checks), log_path, log, suite=suite,
                           parts=parts, over=over)
    if red.get("short"):
        log(f"AK_SHARD={red['piece']} of {directory.name}'s tree ran out of memory again, run "
            "alone: nobody is blamed; the next pass checks it again")
        return {}
    return {"land": tree, **red} if ok or "over" in red else {"fix": {
        "line": prompts.first_failure(text), "log": str(log_path), **red}, "parts": parts}


def _looks(directory, state, repo, tip, prefix, log):
    """The verdict of its own a change of looks alone (`looks_alone`) gets at a pass's start,
    before any suite, so no whole run is under way when it lands: stacked on the target's `tip`
    and the deliveries ahead of it, `prefix`, as they land, and of looks alone there too, on
    what it lands on, the tests it brings run by name with the target's suite line, as a round
    runs them, then its task's `# once` commands, never a whole suite, then `land` with
    `looks`, or a red of its own after them; {} where anything else stands in its way or a test
    it brings fails, and the pass checks it as any, so the whole suite blames it or clears it."""
    from . import roundloop, run
    upstream = _upstream(state)
    with ExitStack() as opened:
        top = tip
        for member, saved in [*prefix, (directory, state)]:
            below = top
            scratch, text = _stack_member(repo, saved, top, upstream, opened)
            if text:
                return {}
            top, tree = (run.git(scratch, "rev-parse", ref) for ref in ("HEAD", "HEAD^{tree}"))
            if member != directory and tree != saved["waiting_on"]["land"]:
                return {}
        tests = looks_alone.changes(scratch, below, [top]).get(top)
        if (tests is None or _pr_moved(state, {})
                or roundloop.rules_check(SimpleNamespace(wt=scratch, base_sha=tip, scratch=False))):
            return {}
        suite = gitcall.declared_suite(scratch, ref=tip)
        if tests and not _check(directory, state, scratch, [suite],
                                directory / f"lander-{tree}-tests.log", log, shard="1/1",
                                only=tests)[0]:
            return {}
        whole = {suite, gitcall.declared(scratch, "tests")}
        checks = [cmd for cmd in _landing_checks(directory, state, scratch, tip)
                  if cmd not in whole]
        answer = (_check_tree(directory, state, scratch, tree, checks, log, None) if checks
                  else {"land": tree})
    answer.pop("parts", None)
    return answer and {**answer, "after": {member.name: saved["waiting_on"]["land"]
                                           for member, saved in prefix},
                       **({"looks": True} if "land" in answer else {})}


def _waits_for_company(turn, held, stacks, checks, suite, log):
    """Whether `checks`, the whole check of the last of `stacks` on those before it, wait, the
    pass then ending with none started: where they run a suite, the target's `suite` or a
    `tests:` line one of `stacks` declares (`_landing_checks`), while the host has no room
    for all its pieces at once (`gate.fits_whole`), the line holds no member launched
    `--first`, no repair and no held install's fix (`update.first_place`, admitted as `--first`
    is), and its longest-ready member without a verdict, one `check_line` checks, has been in
    line under COMPANY times the longest any of those suites took in its last green whole check,
    and under BATCH: a suite never measured green waits none, as its first check measures it.
    Nor do they wait where every suite without that room has a kept use (`gate.green_cpus`)
    above 0 and no higher than the processors the host had idle on average since the line's
    kept reading (`_idle_mean`): two lines held 64 hours from 17 to 20 Nov 2026 while their
    suites, using 3.8 and 5.3 processors, would have fitted in idle ones in four of five held
    minutes.
    The owner, 24 Nov 2026: landing's speed-up stops at this hold.  A line still checks with its
    whole suite, and a piece still counts `gate.HEAVY_CPUS` at least: only the tests a change can
    reach would find a red late and put several merges back, and more pieces at once fail tests
    on timing, either for minutes off a check of 20 to 26 (measured 22 and 23 Nov 2026).
    Lines ran their suites whole back to back, 19 to 32 runs a day a project, each for the few
    members that joined during the last, on a host loaded over twice its processors (13 to 16
    Nov 2026): one run now covers up to two hours of changes.  A run's end left a processor idle
    for a minute, and 27 of a day's 65 runs started in that dip for the one or two members there
    (16 Nov 2026): a suite takes every free turn for some 40 minutes, so only room for all of it
    says no other work waits on it, or its use idle on average a minute and more.  Asked of
    the clock, the readings and the line as they are, whatever led the pass to the run, and
    nothing kept but the host's reading: the callers that retry a pass ask again.
    The test suites' `AK_MAX_RUNS=0` lifts it, as every host gate."""
    from . import gate
    if os.environ.get("AK_MAX_RUNS") == "0":
        return False
    members = [state for _, state in line(turn)]
    since = min((state["waiting_on"]["joined"] for state in members
                 if state.get("state") == "waiting" and not record.process_active(state)
                 and (state.get("review") or {}).get("verdict") == "PASS"
                 and not {"land", "fix"} & state["waiting_on"].keys()), default=0)
    if any(state.get("first") or state.get("repair") or update.first_place(state)
           for state in members):
        return False
    cwd = stacks[-1][2]
    suites = {suite, *(gitcall.declared_at(scratch, tree, "tests")
                       for _, _, scratch, tree, *_ in stacks)} & set(checks)
    ends = since + min(BATCH, COMPANY * max(
        (gate.green_seconds(command, cwd) for command in suites), default=0))
    if time.time() >= ends:
        return False
    cramped = [command for command in suites if not gate.fits_whole(command, cwd)]
    mean = _idle_mean(held) if cramped else None
    # the use as its decimal was kept: the float 2.1 is above 21/10
    if not cramped or mean is not None and all(
            0 < Fraction(str(gate.green_cpus(command, cwd))) <= mean for command in cramped):
        return False
    # half up, as the float 2.55 is below 51/20
    log(f"no room for all the suite's pieces at once: it runs whole for everyone in line by "
        f"{time.strftime('%H:%M', time.localtime(ends))}" + ("" if mean is None else
        f", {math.floor(mean * 10 + Fraction(1, 2)) / 10:.1f} processors idle on average"))
    return True


def _idle_mean(held):
    """The processors the host had idle on average since the line's kept reading (`held.idle`),
    a Fraction, or None: the host unread, no reading kept, or one of another start of the host
    (its boot clock or idle ticks above now's) or under IDLE_SPAN old.  The host is read once a pass, and
    `held.idle` left as what the pass keeps should it wait: the kept reading where that is under
    IDLE_SPAN old or the host unread, else now's."""
    from . import host
    if "mean" not in vars(held):
        now, kept, held.mean = host.idle_reading(), held.idle, None
        if now and kept and kept.boot_ns <= now.boot_ns and (
                kept.cpu_idle_ticks <= now.cpu_idle_ticks):
            if now.boot_ns - kept.boot_ns < IDLE_SPAN * 10**9:
                return None
            held.mean = Fraction((now.cpu_idle_ticks - kept.cpu_idle_ticks) * 10**9,
                                 now.clk_tck * (now.boot_ns - kept.boot_ns))
        if now:
            held.idle = now
    return held.mean


def _check_members(turn, members, repo, tip, target_tree, log, *, ready, held, prefix=(),
                   tip_green=None, over=None):
    from . import gate, roundloop, run
    if prefix:
        wait = prefix[-1][1]["waiting_on"]
        # A cut-short batch must finish delivering before its target can be probed.
        if wait.get("tested", wait["land"]) != wait["land"]:
            return {}
    directory, state = members[0]
    upstream = _upstream(state)
    pending, verdicts = list(members), {}
    heads = {}      # each PR's head on GitHub, read once a pass
    tip_green = set(tip_green or ())   # the pieces the target's tip passed on this pass, the
                                       # pass's own re-probe of a paused piece included
    limit = None
    carried = []    # the red parts the pass's last red whole check confirmed (`_check_tree`)

    def ahead(index):
        """The runs under the stack at `index`, by name, with the tree each was checked as."""
        return {m.name: s["waiting_on"]["land"] for m, s in prefix} | {
            previous[0].name: previous[3] for previous in stacks[:index]}

    def alone(member, answer):
        # A verdict no stack ahead can change -- the member against the target's bare tip --
        # goes out at once, so its fix runs beside the checks of the members behind it.
        verdicts[member] = answer
        ready({member: answer})

    while pending:
        with ExitStack() as opened:
            top, stacks = tip, []
            # `over`'s tests are no stack's to answer for below the one holding its repair `run`
            holding = not over or over["run"] in [member.name for member, _ in prefix]
            for _, saved in prefix:
                scratch, text = _stack_member(repo, saved, top, upstream, opened)
                if text:
                    return verdicts
                top = run.git(scratch, "rev-parse", "HEAD")
                if run.git(scratch, "rev-parse", "HEAD^{tree}") != saved["waiting_on"]["land"]:
                    return verdicts
            for member, saved in pending:
                moved = _pr_moved(saved, heads)
                if moved:
                    # The seat pushed past the head that passed review: checking that head
                    # tests code nobody will land, so the PR goes back to be reviewed.
                    log_path = member / "lander.log"
                    log_path.write_text(moved + "\n")
                    alone(member, {"fix": {"line": moved, "log": str(log_path), "moved": True}})
                    continue
                # Earlier changes can hide a target conflict, so try the bare tip first, then the
                # stack in the same checkout: a checkout of a large repository takes half a minute
                # on a busy disk (two for each of 24 members held a pass 28 minutes, 30 Oct 2026).
                scratch, text = _stack_member(repo, saved, tip, upstream, opened)
                if text:
                    if member == directory or scratch is not None:
                        log_path = member / "lander.log"
                        log_path.write_text(text)
                        alone(member, {"fix": {"line": prompts.first_failure(text), "log": str(log_path),
                                               **({"conflict": True} if scratch is not None else {})}})
                    continue
                if top != tip:
                    scratch, text = _stack_member(repo, saved, top, upstream, opened, scratch)
                    if text:
                        continue
                # AGENTS.md is measured on the tree that lands, before any evidence answers it: a
                # tree green on a target with larger rules says nothing about the ceiling.
                failure = roundloop.rules_check(SimpleNamespace(wt=scratch, base_sha=tip, scratch=False))
                if failure:
                    # Changes ahead of it can lengthen or shorten the file: it waits for their
                    # verdicts, and only with none ahead is the size its own to fix.
                    if top == tip:
                        log_path = member / "lander.log"
                        log_path.write_text(failure + "\n")
                        alone(member, {"fix": {"line": failure, "log": str(log_path)}})
                    continue
                top = run.git(scratch, "rev-parse", "HEAD")
                tree = run.git(scratch, "rev-parse", "HEAD^{tree}")
                holding = holding or member.name == over["run"]
                # what a stack excuses is its answer's, as its tree and checks are: two stacks
                # of one tree either side of the repair are answered each its own way
                stacks.append((member, saved, scratch, tree,
                               _landing_checks(member, saved, scratch, tip),
                               () if holding else tuple(over["tests"])))
            if not stacks:
                break
            suite = gitcall.declared_suite(stacks[0][2], ref=tip)
            if limit is None:
                limit = gate.whole_checks_that_fit(suite)
            green, red = (_answering(turn, kind) for kind in ("trees", "red_stacks"))
            # The first stack has no green prefix to attribute a cached failure to.
            # Retry its own check after a kill or flake; later evidence survives a crash.
            if not prefix:
                red.pop(stacks[0][3], None)
            # Evidence answers a stack only for the checks it ran: two tasks can stack
            # the same tree, and each owes its own `# once` commands.
            def checked(entry, checks):
                ran = iter(entry.get("checks", ()))
                return all(cmd in ran for cmd in checks)

            def cached_red(tree, checks, excused):
                kept = red.get(tree, {})
                if kept.get("checks") == list(checks) and kept.get("excused", []) == list(excused):
                    return {"fix": {key: kept[key] for key in (
                        "line", "log", "command", "piece", "tests", "failed", "excused",
                        "commit") if key in kept}}

            def green_answer(tree, tested):
                return {"land": tree} if tree == tested else {"land": tree, "tested": tested}

            def commands(index):
                # A covered member still owes its own once-commands, on the tested tree.  What
                # two of them owe runs there once: a `tests:` line a change ahead rewrote is
                # every later stack's own too.
                owed = dict.fromkeys(cmd for stack in stacks[:index + 1] for cmd in stack[4])
                return tuple(cmd for cmd in owed if cmd != suite) + ((suite,) if suite else ())

            positions = {stack[3]: index for index, stack in enumerate(stacks)}
            # Coverage can be reused only when this line can still deliver its tested tip.
            green = {tree: entry for tree, entry in green.items()
                     if entry.get("tested") == tree
                     or (tree in positions
                         and positions.get(entry.get("tested"), -1) >= positions[tree]
                         and checked(entry, commands(positions[entry["tested"]])))}
            answers = {}
            passed_alone = {}   # (index, what failed): whether just that passed run alone there
            probed_red = set()  # (index, what failed): a probe found just that red there
            for _, _, _, tree, checks, excused in stacks:
                if tree in green and checked(green[tree], checks):
                    answers[tree, checks, excused] = green_answer(tree, green[tree]["tested"])
                elif cached := cached_red(tree, checks, excused):
                    answers[tree, checks, excused] = cached
            batched = len({stack[3:] for stack in stacks if stack[3:] not in answers}) > limit

            def cover(index, checks, tested, at=None, code=None, failed=()):
                covered = stacks[:index + 1] if batched else [stacks[index]]
                # landed over the target's red, proven green by none: each tree holds that red
                note(turn, [] if failed else [stack[3] for stack in covered], directory.name,
                     checks=checks, tested=tested, at=at, code=code,
                     red=failed and {stack[3]: {"as": over["tree"]} for stack in covered
                                     if stack[3] != over["tree"]})
                for _, _, _, tree, own, excused in covered:
                    answers[tree, own, excused] = {**green_answer(tree, tested),
                                          **({"over": failed} if failed else {})}

            if batched:
                for index, (_, _, _, tree, checks, excused) in enumerate(stacks):
                    if cached := cached_red(tree, commands(index), excused):
                        answers[tree, checks, excused] = cached
                    evidence = green.get(tree)
                    if evidence and checked(evidence, commands(index)):
                        cover(index, evidence["checks"], evidence["tested"], evidence["at"],
                              evidence.get("code"))

            def answer_tree(index, checks, check, failed=None):
                nonlocal short
                answer = check.result()
                if failed is not None:
                    passed_alone[index, failed] = "land" in answer
                    if "fix" not in answer:
                        return
                    # A confirmed failed part makes the stack's planned check red.
                    checks = commands(index)
                tree, own, excused = stacks[index][3:]
                if not answer:      # the host's red (`_check_tree`): this pass ends
                    short = True
                elif "land" in answer:
                    cover(index, checks, tree, failed=answer.get("over"))
                else:
                    if failed is None:
                        carried[:] = answer.pop("parts")
                    answers[tree, own, excused] = answer
                    if not target_red:  # beside the target's own red, it may be nothing else
                        note(turn, [], directory.name, checks=checks,
                             red_stacks={tree: answer["fix"]})

            rebuild, target_red, stale, short = False, False, False, False

            def stopped():
                """Has the line changed under this pass?  Asked before every check it would
                start.  Where none of its verdicts could be written any more, it starts no
                check, and the next pass checks the line as it is now.  Where only the members
                from one that changed on can get none (`ready`), the stacks are rebuilt without
                them, as without a culprit: a check green with one answers nobody ahead of it."""
                nonlocal stale, pending, rebuild
                if stale:
                    return True
                standing = ready({})
                if not standing:
                    stale = True
                    log("the line changed during this pass; the next pass checks it afresh")
                    return True
                behind = dict(members[standing:])
                if not any(member in behind for member, _ in pending):
                    return False
                pending = [(m, s) for m, s in pending if m not in behind]
                for member, _ in pending:
                    # a green verdict a stack behind covered is offered again once its own
                    # stack is answered without them
                    verdicts.pop(member, None)
                rebuild = True
                return True

            def blame(index, answer):
                """Give the member of the red stack at `index`, right behind green ones, its
                verdict, and leave it out of the stacks rebuilt next.  With runs under it, the
                tests it failed run once more on the target's tip with it alone, on its stack's
                checkout, whose check has answered: red there, the red is its own, and that
                check's verdict goes out as one against the bare tip does, its fix at once
                (blamed for a name one test refuses anywhere, a member waited two hours for the
                24 runs ahead of it to land, 14 Nov 2026).  A red of the suite, but for a
                repair's, first answers on the bare tip (`_probe_tip`): the green stacks ahead
                say the tip passed those tests only when they were checked, and a test the clock
                turned red there was each member's in turn (seven fixers over a fixture's date
                in an hour, 16 Nov 2026).  Only the tests that probe confirms as failed again
                (`again`) are the target's (`target_red`), nobody's, and its repair starts.  A
                probe that neither passes nor confirms one of them (the tests are not on the
                tip, as a test the member added is not; its runner named nothing) leaves the red
                its own and runs no whole piece on the tip: the member alone on the tip did fail
                them, nothing says the tip does, and a piece on the tip for every member blamed
                for its own new test would cost each pass minutes.  Otherwise the red may need a
                run ahead, and its verdict names them (`after`)."""
                nonlocal pending, rebuild, target_red
                member, saved, scratch = stacks[index][:3]
                fix, after, there = answer["fix"], ahead(index), {}
                if member not in verdicts:
                    if after and fix.get("tests") and not stopped():
                        _, text = _stack_member(repo, saved, tip, upstream, opened, scratch)
                        if not text:
                            # alone on the tip it stands on no repair of `over` but its own
                            there = _check_tests(member, saved, scratch,
                                                 run.git(scratch, "rev-parse", "HEAD^{tree}"),
                                                 fix["command"], fix["piece"], fix["tests"], log,
                                                 () if not over or member.name == over["run"]
                                                 else tuple(over["tests"]))
                    if "fix" in there and fix["command"] == suite and not saved.get("repair"):
                        _put_back(scratch, tip)
                        if not _probe_tip(turn, member, saved, scratch, tip, upstream, target_tree,
                                          suite, fix["piece"], log, tip_green,
                                          there["fix"]["tests"], behind=True):
                            target_red = True
                            return
                    if "fix" in there:
                        log(f"{' '.join(fix['tests'])} fail on {upstream} at {tip[:12]} with "
                            f"{member.name} alone: its fix starts now")
                        alone(member, there)
                    else:
                        verdicts[member] = {**answer, "after": after}
                        ready({member: verdicts[member]})
                pending = [(m, s) for m, s in pending if m not in verdicts or "land" in verdicts[m]]
                rebuild = True

            def decide():
                nonlocal target_red
                if target_red:
                    return
                for index, (member, saved, scratch, tree, checks, excused) in enumerate(stacks):
                    answer = answers.get((tree, checks, excused))
                    # A red is blamed only behind stacks all answered green: an unanswered
                    # one ahead may be the culprit, and removing it changes every later tree.
                    if answer is None:
                        break
                    # The target's tip answers for a red suite before anyone is blamed, whatever
                    # pass the target has on record, as the host, not the change, may have
                    # failed it: the red piece's failed tests (`red_part`, from the exits the
                    # runner saw) run there alone, and a red that named none asks the suite
                    # whole there, as the suite deals each tree's test files into its pieces,
                    # so on the tip that piece's number holds other tests (11 Nov 2026).  A red
                    # check of the member's own is the member's.  What the tip passed on this
                    # pass, that piece or the suite whole, answers again, tests named or not:
                    # failing there, they would hand the probe back to that piece.
                    fix = answer.get("fix") or {}
                    tests = fix.get("tests")
                    piece = fix.get("piece") if tests else ""
                    if (index == 0 and not prefix and "piece" in fix and fix["command"] == suite
                            and not saved.get("repair") and not {piece, ""} & tip_green):
                        if stopped():
                            return
                        _put_back(scratch, tip)
                        if not _probe_tip(turn, member, saved, scratch, tip, upstream,
                                          target_tree, suite, piece, log, tip_green, tests,
                                          excused):
                            target_red = True
                            return
                    if "fix" in answer:
                        # Only this green-to-red transition identifies a culprit.
                        # Later stacks need new checks on trees without this member.
                        blame(index, answer)
                        return
                    if member not in verdicts:
                        verdicts[member] = {**answer, "after": ahead(index)}
                        ready({member: verdicts[member]})

            with ThreadPoolExecutor(max_workers=max(1, limit)) as pool:
                running = {}
                try:
                    decide()
                    # The parts the pass's last red whole check confirmed, where quicker than it
                    # (`_check`), run alone on the top rebuilt without the culprit, before any
                    # whole check: checked whole, it failed again on those known red since, two
                    # more whole checks a culprit (a stack of 61 holding five landed nothing in
                    # 14 hours, 11 Nov 2026).
                    # Failing, a part is that top's red, narrowed as a batch's however many whole
                    # checks fit, and tried again on the next top, as another member may break
                    # it too; passing, proving nothing or its command run there no more, it is
                    # dropped.  Then the top goes whole, no stack under it first: it is red again
                    # only on what no part showed, and so is the stack just below the culprit,
                    # whose whole check, first, held a line 87 minutes at a time to land one to
                    # five members (13 Nov 2026).
                    top = len(stacks) - 1
                    carried[:] = [part for part in carried if part["command"] in commands(top)]
                    for part in list(carried):
                        if (tuple(stacks[top][3:]) in answers or rebuild or target_red
                                or stopped()):
                            break
                        answer_tree(top, None, pool.submit(
                            _check_tests, *stacks[top][:4], part["command"], part["piece"],
                            part["tests"], log, stacks[top][5]),
                            (part["command"], tuple(part["tests"])))
                        if tuple(stacks[top][3:]) in answers:
                            batched = True
                        else:
                            carried.remove(part)
                        decide()
                    while not rebuild and not target_red and not short and not stopped():
                        unchecked = [index for index, stack in enumerate(stacks)
                                     if stack[3:] not in answers]
                        narrowing, command, owner = None, None, 0
                        if batched and unchecked:
                            # Narrow the first unresolved red between the last green and it.
                            red_index = next((index for index in range(unchecked[0], len(stacks))
                                              if "fix" in answers.get(tuple(stacks[index][3:]), {})), None)
                            low = unchecked[0] - 1
                            high = red_index
                            if red_index is not None:
                                # Each step runs just the tests of the first failing command's
                                # piece that failed again alone, from the deepest stack they
                                # passed in; a failure narrows earlier, and only an inconclusive
                                # run gets its whole check.  A piece that named none narrows by
                                # whole checks: the suite deals each tree's test files into its
                                # pieces, so on another stack its number stands for other tests,
                                # and passing there it sent bystanders to their fixers
                                # (10 Nov 2026).
                                failing = answers[tuple(stacks[red_index][3:])]
                                command = failing["fix"].get("command")
                                tests = tuple(failing["fix"].get("tests") or ())
                                if command and tests:
                                    narrowing = command, tests
                                    owner = next((index for index, stack in enumerate(stacks)
                                                  if command in stack[4]), 0)
                                    # No stack below the first holding their file can fail
                                    # them: run there, a suite that names no test as not there
                                    # proved nothing, and that stack went whole (13 Nov 2026).
                                    low = max(low, _first_holding(stacks, red_index, tests) - 1)
                                    # a probe's red bounds it sooner, though it blames nobody,
                                    # until a pass here outweighs it
                                    high = min([red_index] + [
                                        index for index, failed in probed_red
                                        if failed == narrowing and index > low
                                        and not passed_alone.get((index, failed))])
                                    low = max([low] + [
                                        index for (index, failed), ok in passed_alone.items()
                                        if ok and failed == narrowing and index < high])
                            if narrowing and low + 1 == red_index:
                                # It passes alone on the stack just ahead and fails on its own:
                                # its change turned it red, whatever the stacks ahead hold.
                                blame(red_index, failing)
                                break
                            # No stack below the command's first runs it: the search starts
                            # just ahead of that one, and it reaches lower only on evidence.
                            floor = max(low, owner - 1)
                            if narrowing and floor + 1 < high:
                                # The stacks between go many at once, a round at a time, to
                                # the suite helpers or else this host: one step at a time took
                                # 127 of a pass's 370 minutes (5 Nov 2026).  A round that proves
                                # nothing leaves the step to this host.
                                probed = _round(stacks, floor, high, command, tests, log)
                                passed_alone.update(((index, narrowing), True)
                                                    for index, ok in probed.items() if ok)
                                probed_red.update((index, narrowing)
                                                  for index, ok in probed.items() if ok is False)
                                if any(ok is not None for ok in probed.values()):
                                    continue
                            # A probe's red right after a pass runs here: it decides the blame,
                            # with the flaky handling a probe has none of, and passing here it
                            # moves the narrowing on above it.
                            unchecked = [unchecked[-1] if red_index is None else
                                         high if low + 1 == high else (floor + high) // 2]
                        active = {tuple(stacks[index][3:]) for index, *_ in running.values()}
                        for index in unchecked:
                            member, saved, scratch, tree, own, excused = stacks[index]
                            if stacks[index][3:] in active or len(running) >= limit:
                                continue
                            # Ahead of the command's first stack the target's suite runs where
                            # that stack's `tests:` line does: its tests that failed run there.
                            runs = narrowing and (index, narrowing) not in passed_alone and (
                                command if index >= owner else suite)
                            if runs:
                                job = pool.submit(_check_tests, member, saved, scratch, tree,
                                                  runs, failing["fix"]["piece"], tests, log,
                                                  excused)
                                running[job] = index, None, narrowing
                            else:
                                checks = commands(index) if batched else own
                                if _waits_for_company(turn, held, stacks[:index + 1], checks,
                                                      suite, log):
                                    held.waited = short = True      # this pass ends
                                    break
                                running[pool.submit(_check_tree, member, saved, scratch, tree,
                                                    checks, log, suite, excused)] = (
                                    index, checks, None)
                            active.add(stacks[index][3:])
                        if not running:
                            break
                        check = next(as_completed(running))
                        index, checks, failed = running.pop(check)
                        answer_tree(index, checks, check, failed)
                        decide()
                finally:
                    # Keep suffix evidence even if a wake or verdict write crashes.
                    for check, (index, checks, failed) in running.items():
                        answer_tree(index, checks, check, failed)
            if target_red or stale or short or not rebuild:
                break
    return verdicts
