"""Check parked landing-line stacks and wake each run to deliver or fix its own work.

Green evidence names the tested tree, including for stacks it covers. A red stack
after a green one blames its newest member, whose fixer waits until the runs ahead of it in
that stack have left the line; later stacks are rebuilt without it.
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
import functools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import config, gitcall, prompts, record, suite_times, transitions, turns, update

KEEP = 24 * 3600    # a recorded tree older than a day lands through its own suite again
CHECKED = 60        # a pass shorter than a minute checked nothing: it says nothing of the pace
FLAKY = 7 * 24 * 3600   # a file's tests failing, then passing, on two trees this close get one
                        # repair, which holds the file as long unless a change editing it merges
# A stack's scratch checkout says so in its own git directory, naming the checker that made it:
# one a killed checker left goes when a checker next starts a pass (`_clear_left`), or with gc a
# day unused, whatever it holds, and no other checkout for it.
SCRATCH_MARK = "ak-lander-scratch"
WAKE = 10           # a blamed run waits at most this long once no run it waits on is in line


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
    """The line's singleton flock, True while this process holds it, and the time each held
    pass takes: its start and process while it runs, then the last 20 that checked something."""
    with turn.with_suffix(".lander.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        took = passes(turn).get("took") or []
        started = time.time()
        _keep_passes(turn, {"took": took, "started": started, **record.process_owner()})
        try:
            yield True
        finally:
            spent = time.time() - started
            _keep_passes(turn, {"took": (took + [spent])[-20:] if spent >= CHECKED else took})


def passes(turn):
    """The line's passes (`_pass`): `took`, the seconds of its last passes that checked
    something, and while one runs its `started` and process."""
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
    """Green deliveries in tested stack order, then the rest in join order, a held install's
    fix (`update.first_place`) ahead of those; their records every reader's (`record.runs`),
    so only read."""
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
        if green_delivery(member[1]["waiting_on"]) else not update.first_place(member[1]),
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
    merged at 20:26 waited past 22:40 for the next pass, 5 Nov 2026)."""
    from . import watch
    # a resume takes its record a moment after its start, and one refused leaves it parked:
    # that one the next pass wakes again
    woken, done = set(), threading.Event()

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
        # Owner, 5 Nov 2026: a lander fix takes effect when installed, and changes
        # launched on different versions stack, so the lander runs the installed ak.
        installed = Path.home() / ".local" / "bin" / "ak"
        if not installed.is_file():
            installed = config.REPO / "bin" / "ak"
        return orch.start_in_slice(
            [sys.executable, str(installed), "run", "--lander", turn.name],
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
               tests=None):
    """Run the red `piece` of `suite` ("" for the suite whole) on `scratch`, the target's tip
    alone, for the member in `directory`: True when it passes there, so the red is the
    member's own, the piece then in `green`, what the tip passed on this pass.  Where
    the stack's red was its `tests` failing again alone, those alone run there first: passing
    there, each named as run (`gate.run_suite(only=)`), the member's change is what fails them,
    and the piece need not run.  Failing there again, named as run and as failed by a run that
    ended in a failing exit on the pinned tip (`gate.run_suite(confirmed=)`), they are a red that
    repeats, which no step of the retry ladder would clear: the target's own, repaired at once,
    and the piece need not run either.  Anything else proves nothing -- a test the member added
    is not on the tip -- so the whole piece then decides.
    Red there is the target's: the entry under `tree` counts the probe and holds the line
    (`paused`) until the retry ladder's next step, and red through the whole ladder starts the
    target's one repair (`_repair`); a repeat of named tests walks for the commit that first
    turned the target red (`_blame_tip`)."""
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
    if not again:       # a repeat needs no piece to say the tip is red
        ok, probe, _ = _check(directory, state, scratch, [suite], path, log, shard=piece or None,
                              kind="tip")
    if ok:
        # the pass is the piece's, named so it covers no stack's own checks
        note(turn, [tree], directory.name, checks=[f"{suite} (AK_SHARD={piece})" if piece else suite],
             red={tree: None})
        green.add(piece)
        return True
    held = _trees(turn, "red")[1].get(tree) or {}
    # A repeat is kept as the whole ladder climbed: a later pass, after a PR's fixer took the
    # red or a crash came before its repair was noted, finds the target's own red, never a pause.
    probes = (len(turns.TRANSIENT_BACKOFF) + 1 if again else
              held.get("probes", 0) + 1 if (held.get("probe") or {}).get("sha") == tip else 1)
    red = {"probe": {"command": suite, "piece": piece, "check": f"{suite}  # once", "sha": tip,
                     "text": prompts.red_target_text(suite, upstream, tip, probe, directory,
                                                     piece=piece)},
           "at": time.time(), "probes": probes}
    note(turn, [], directory.name, red={tree: red})
    what = f"its piece AK_SHARD={piece}" if piece else "its suite"
    if probes > len(turns.TRANSIENT_BACKOFF):
        how = (f"{' '.join(again)} of {what} again, run alone" if again else
               f"{what} alone through the retry ladder")
        log(f"{upstream} at {tip[:12]} fails {how}: the target's own red, repaired")
        _repair(turn, directory, state, tree, red, log)
        # A red that named no test blames nobody: on an earlier commit a piece's number holds
        # other tests, and six whole suites are not worth a history row.
        if again:
            _blame_tip(directory, state, scratch, tip, suite, piece, again, log)
    else:
        log(f"{upstream} at {tip[:12]} fails {what} alone: the line waits, nobody is blamed; "
            f"probed again in {turns.transient_delay(probes) // 60} min")
    return False


def _blame_tip(directory, state, scratch, tip, suite, piece, tests, log):
    """Find the first red first-parent commit within KEEP and 64 commits (six steps), by just
    the `tests` of `suite`'s `piece` that failed again alone on the tip.

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
            mid = (low + high) // 2
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
    from . import handback, roundloop, run, watch
    turn = Path(turn)
    _code()     # read as the pass starts: an update installed during a check is not this pass's
    with _pass(turn) as held, ExitStack() as waking:
        if not held:
            return
        _clear_left()
        # Checks may return after their first group; no saved red waits for that walk to reach it.
        wake = waking.enter_context(_waking(turn, log))
        target, prefix, tip_green = None, [], set()    # the pieces the tip passed on this pass
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
                repo = Path(state.get("worktree") or state["repo"])
                gitcall.no_auto_gc(repo)
                # The repository's machine-side settings, as a run's own checks get them.
                os.environ.update(config.repo_env(Path(state["repo"])))
                upstream = _upstream(state)
                run.fetch(repo, "origin", "--prune", check=True)
                tip = run.git(repo, "rev-parse", f"{upstream}^{{commit}}")
                target = tip, run.git(repo, "rev-parse", f"{tip}^{{tree}}")
            tip, target_tree = target
            red = _trees(turn, "red")[1].get(target_tree)
            name = None
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
            # a PR waits on no repair: its own tree is checked, and lands if it mends the target
            if (red and (passed(turn, target_tree) or {}).get("tested") != target_tree
                    and not state.get("review_pr")):
                name = red.get("run")
                repair = record.read_state(config.RUNS / name) if name else None
                holds = repair and handback.repair_open(repair, red["probe"]["sha"])
                if not (holds or repair and transitions.delivered(repair)):
                    # none yet, or the last let go of this red unmended: another goes first
                    if repair:
                        log(f"{name} ended without mending {upstream} at {tip[:12]}: "
                            f"another repair")
                    name = _repair(turn, directory, state, target_tree, red, log)
                    if not name:
                        continue    # refused: a later member may start it, a PR may mend it
                elif not holds:
                    name = None     # it mended the target: merged, or found it passing there
                if name and directory.name != name:
                    continue
            verdict = {key: state["waiting_on"][key] for key in ("land", "fix")
                       if key in state["waiting_on"]}
            checked = not verdict
            if checked:
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
            else:
                candidates = [(directory, state)]
            sent, snapshots, valid = set(), dict(candidates), True

            def publish(answers):
                nonlocal valid
                if not valid:
                    return False
                fresh = {member: answer for member, answer in answers.items() if member not in sent}
                # Delivery rewrites ownership and rebase receipts, but keeps the reviewed
                # work and tested tree. Only an unwoken recipient must stay processless.
                # No answers asks only whether the line is still the one this pass checks.
                with ExitStack() as held:
                    for member, saved in prefix + candidates:
                        held.enter_context(record.recovery_lock(member))
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
                            valid = False
                            return False
                    if not fresh:
                        return True
                    for member, answer in sorted(fresh.items(), key=lambda item: "land" in item[1]):
                        with record.record(member) as current:
                            current["waiting_on"] = {**current["waiting_on"], **answer}
                        # Later answers still compare against this pass's own writes.
                        snapshots[member]["waiting_on"] = dict(current["waiting_on"])
                    sent.update(fresh)
                    for member, answer in fresh.items():
                        if "fix" not in answer:
                            watch.launch_resume(member.name, log)
                    wake()
                return True

            verdicts = (_check_members(turn, candidates, repo, tip, target_tree, log, prefix=prefix,
                                      ready=publish, tip_green=tip_green) if checked else {directory: verdict})
            if not verdicts:
                return
            if publish(verdicts) and checked:
                # A reparked member must retry red suffixes discarded during rebuilding.
                note(turn, [], directory.name, red_stacks={})
            if checked:
                return
            if "land" in verdict and "fix" not in verdict:
                prefix.append((directory, state))


def red_part(cmds, marks, pieces, confirmed, suite, ok, parts=None):
    """What the checks found red, from the exits the runner saw (`marks`, and `pieces` by
    command and share): the first failing `command`, its first confirmed red `piece`'s share
    (`k/N`), or its first red piece where none is confirmed, and
    the `tests` that piece named that failed again alone (`confirmed`), if any.  The piece is
    "" where the command ran whole or a piece was killed at the limit, which stops its siblings
    with it, and the suite whole where no command failed and yet the checks did not pass (the
    checkout changed under them, the suite's own doing as far as the lander can tell); {}
    where the checks passed or no exits were reported.  A piece out of memory
    (`gate.OUT_OF_MEMORY`) is red only where no other is, and then `short`: the host's red,
    nobody's.  `parts`, a list, gets every red piece of that command that confirmed tests, each
    as this names one and this one first, where this one confirmed any."""
    from . import gate
    if ok or not marks:
        return {}
    for cmd, mark in zip(cmds, marks):
        if mark == 0:
            continue
        codes = pieces.get(cmd, {})
        reds = sorted((share for share, code in codes.items() if code != 0),
                      key=lambda share: (codes[share] == gate.OUT_OF_MEMORY,
                                         not (confirmed.get(cmd) or {}).get(share),
                                         int(share.split("/")[0])))
        piece = "" if None in codes.values() or not reds else reds[0]
        if piece and codes[piece] == gate.OUT_OF_MEMORY:
            return {"command": cmd, "piece": piece, "short": True}
        tests = (confirmed.get(cmd) or {}).get(piece) if piece else None
        if tests and parts is not None:
            parts.extend({"command": cmd, "piece": share, "tests": confirmed[cmd][share]}
                         for share in reds
                         if codes[share] != gate.OUT_OF_MEMORY and confirmed[cmd].get(share))
        return {"command": cmd, "piece": piece, **({"tests": tests} if tests else {})}
    return {"command": suite, "piece": ""} if suite else {}


def _check(directory, state, scratch, cmds, log_path, log, *, suite=None, shard=None,
           only=None, kind="landing", exits=None, flaky=None, absent=None, parts=None):
    """(whether the checks passed, their output, what they found red as `red_part` reads it,
    `suite` standing for a red no command showed, `parts` getting its pieces that confirmed
    tests); with `shard` every command runs as that one piece alone, on one turn, and with
    `only` just those tests, on none, `absent` getting
    those not there where it passed the rest (`gate.passes_what_it_holds`).  Each command, or
    piece of one, leaves its `kind` row in history under the member's run, on the commit
    checked: `landing`, or `tip` for a probe of the target's. `exits` keeps each piece's attempt
    exits and `flaky` the tests that failed, then passed; a moved checkout clears the exits and
    `absent`."""
    from . import gate, run
    identity = gitcall.commit_identity(scratch)
    clean = run.git_out(scratch, "diff", "--quiet", "HEAD")[0] == 0
    # The checker takes a heavy turn without marking any member's record.
    wait = state["waiting_on"]
    context = {"repo": state["repo"], "run_id": directory.name, "landing": True,
               "since": wait["joined"], "line": wait["line"]}
    sharded = None if shard else next((cmd for cmd in cmds if gate.names_shard(cmd)), None)
    marks, pieces, confirmed = [], {}, {}
    timings = {}
    flaky = [] if flaky is None else flaky
    absent = [] if absent is None else absent
    # Tests named alone cost what a model's own test does, which takes no turn: on a host out of
    # CPU none comes until it is idle, and the wait held whole lines up to an hour (30 Oct 2026).
    with nullcontext() if only else gate.gate_turn(None, log_path, log, sharded, scratch,
                                                   context=context):
        ok, text = gate.run_done_when(
            cmds, scratch, log_path, set(),
            3600 * state.get("ceiling_hours", record.CEILING_HOURS), log,
            silence=60 * state.get("silence_minutes", record.SILENCE_MINUTES), heavy=True,
            marks=marks, shard=shard, pieces=pieces, only=only, confirmed=confirmed,
            flaky=flaky, checked=(directory, None, kind, identity["head_sha"]), exits=exits,
            timings=timings, absent=absent)
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
    return ok, text, red_part(cmds, marks, pieces, confirmed, suite, ok, parts)


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
    head = state["review"]["head_sha"]
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
    from . import task
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
    if own and own not in (gitcall.declared_suite(scratch, ref=tip), *once):
        once.append(own)
    return tuple(once)


def _check_tests(directory, state, scratch, tree, command, piece, tests, log):
    """The stack's answer from just `tests` of `command`'s `piece`, or {} if inconclusive.  A
    pass, each test named as run or as not there, one a later member adds
    (`gate.passes_what_it_holds`), moves the narrowing deeper and answers for nothing else; a
    failure, of the tests confirmed, moves it earlier.  Anything else proves nothing -- a test
    the suite skips without naming it -- so that stack gets its whole check on its original
    checkout.
    """
    from . import run
    head = run.git(scratch, "rev-parse", "HEAD")
    log_path = directory / f"lander-{tree}-tests.log"
    absent = []
    ok, text, red = _check(directory, state, scratch, [command], log_path, log, suite=command,
                           shard=piece or None, only=list(tests), absent=absent)
    _put_back(scratch, head)
    if ok or absent:
        return {"land": tree}
    return {"fix": {"line": prompts.first_failure(text), "log": str(log_path),
                    **red}} if red.get("tests") else {}


def _probe(directory, state, scratch, tree, command, tests, cost):
    """Whether just `tests` of `command` pass on the stack `scratch` holds, run once on a suite
    helper as a piece of `cost` (CPUs, MiB): True where each was named as run (`AK_RAN`) or as
    not there (`gate.passes_what_it_holds`), False where the run failed naming one of them both
    as run and as failed (`AK_FAILED`), and None where it proved neither -- no helper took it,
    it hung, the helper lost it, had no room or handed back no names, a test was not named as
    run.  It leaves its `checks` row and records nothing else, no flaky sighting either: a red
    only a helper shows is no evidence (`_check_tests` decides)."""
    from . import gate, helper, history, run, worker
    asked, head = time.time(), run.git(scratch, "rev-parse", "HEAD")
    there = gate.pinned(command, suite_times.handed(scratch), only=tests)
    away = helper.start(*cost, scratch, lambda _: None, there, one=True)[0]
    if not away:
        return None
    log_path = directory / f"lander-{tree}-probe.log"
    silence = 60 * state.get("silence_minutes", record.SILENCE_MINUTES)
    try:
        with log_path.open("wb") as output, history.check(
                (directory, None, "landing", head), command, asked, away.alias) as ended:
            # A hang ends as a suite piece's first go does, at its suite's pace: its round
            # waits for it.
            code, _, killed = worker.limited(
                helper.piece(away, "1/1", there),
                3600 * state.get("ceiling_hours", record.CEILING_HOURS), cwd=str(scratch),
                activity=log_path, output=output, env=gate.suite_env(),
                silence=gate.quiet_window(command, scratch, None, silence) or silence,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            ended["exit"] = None if killed else code
        if killed or code < 0 or code in (*helper.GONE, helper.FULL):
            return None
        ran, failed, absent = (helper.failed(away, "1/1", named)
                               for named in ("ran", "failed", "not-there"))
        if None in (ran, failed, absent):
            return None
        if code and set(tests) & set(ran) & set(failed):
            return False
        return gate.passes_what_it_holds(code, tests, ran, failed, absent) or None
    finally:
        helper.finish(away)


def _round(stacks, floor, high, command, tests, log):
    """One round of a red stack's narrowing: probes (`_probe`) of the stacks between `floor` and
    `high`, as many as the suite helpers have places for, spread evenly and all at once, and
    each probed stack's answer once the last has ended; {} where the helpers have no place.
    Probes running the same tests end about together, so waiting for the last costs little,
    and none outlives its round: nothing is ever called off on a helper."""
    from . import gate, helper
    cost = gate.suite_cost(command, stacks[high][2], None)[1:]
    count = min(helper.places(*cost, stacks[high][2]), high - floor - 1)
    picked = [floor + (n + 1) * (high - floor) // (count + 1) for n in range(count)]
    with ThreadPoolExecutor(max_workers=max(1, count)) as pool:
        probes = {index: pool.submit(_probe, *stacks[index][:4], command, tests, cost)
                  for index in picked}
    answers = {index: probe.result() for index, probe in probes.items()}
    if answers:
        said = {True: "passes", False: "fails", None: "proves nothing"}
        log(f"{' '.join(tests)} on the suite helpers: " + ", ".join(
            f"{said[answer]} up to {stacks[index][0].name}" for index, answer in answers.items()))
    return answers


def _check_tree(directory, state, scratch, tree, checks, log, suite):
    """The stack's answer from its whole check, a red one with the `parts` it confirmed
    (`red_part`), or {} where it ran out of memory again."""
    log_path = directory / f"lander-{tree}.log"
    parts = []
    ok, text, red = _check(directory, state, scratch, list(checks), log_path, log, suite=suite,
                           parts=parts)
    if red.get("short"):
        log(f"AK_SHARD={red['piece']} of {directory.name}'s tree ran out of memory again, run "
            "alone: nobody is blamed; the next pass checks it again")
        return {}
    return {"land": tree} if ok else {"fix": {"line": prompts.first_failure(text),
                                              "log": str(log_path), **red}, "parts": parts}


def _check_members(turn, members, repo, tip, target_tree, log, *, prefix=(), ready=lambda _: None,
                   tip_green=None):
    from . import gate, roundloop, run
    if prefix:
        wait = prefix[-1][1]["waiting_on"]
        # A cut-short batch must finish delivering before its target can be probed.
        if wait.get("tested", wait["land"]) != wait["land"]:
            return {}
    directory, state = members[0]
    upstream = _upstream(state)
    config.WT.mkdir(parents=True, exist_ok=True)
    pending, verdicts = list(members), {}
    heads = {}      # each PR's head on GitHub, read once a pass
    tip_green = set(tip_green or ())   # the pieces the target's tip passed on this pass, the
                                       # pass's own re-probe of a paused piece included
    limit = None
    below = -1      # the stack just below the last culprit, unchanged by the rebuild without it
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
                stacks.append((member, saved, scratch, tree,
                               _landing_checks(member, saved, scratch, tip)))
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

            def cached_red(tree):
                return {"fix": {key: red[tree][key] for key in (
                    "line", "log", "command", "piece", "tests") if key in red[tree]}}

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
            for _, _, _, tree, checks in stacks:
                if tree in green and checked(green[tree], checks):
                    answers[tree, checks] = green_answer(tree, green[tree]["tested"])
                elif red.get(tree, {}).get("checks") == list(checks):
                    answers[tree, checks] = cached_red(tree)
            unanswered = {index: stack[3:] for index, stack in enumerate(stacks)
                          if stack[3:] not in answers}
            # However many fit, the stack below a culprit goes first, covering those under it.
            batched = below in unanswered or len(set(unanswered.values())) > limit

            def cover(index, checks, tested, at=None, code=None):
                covered = stacks[:index + 1] if batched else [stacks[index]]
                note(turn, [stack[3] for stack in covered], directory.name,
                     checks=checks, tested=tested, at=at, code=code)
                for _, _, _, tree, own in covered:
                    answers[tree, own] = green_answer(tree, tested)

            if batched:
                for index, (_, _, _, tree, checks) in enumerate(stacks):
                    if red.get(tree, {}).get("checks") == list(commands(index)):
                        answers[tree, checks] = cached_red(tree)
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
                tree, own = stacks[index][3:]
                if not answer:      # the host's red (`_check_tree`): this pass ends
                    short = True
                elif "land" in answer:
                    cover(index, checks, tree)
                else:
                    if failed is None:
                        carried[:] = answer.pop("parts")
                    answers[tree, own] = answer
                    note(turn, [], directory.name, checks=checks, red_stacks={tree: answer["fix"]})

            rebuild, target_red, stale, short = False, False, False, False

            def stopped():
                """Has the line changed under this pass?  Asked before every check it would
                start: none of its verdicts could be written any more, so it starts no check,
                and the next pass checks the line as it is now."""
                nonlocal stale
                if not stale and ready({}) is False:
                    stale = True
                    log("the line changed during this pass; the next pass checks it afresh")
                return stale

            def decide():
                nonlocal pending, rebuild, target_red, below
                if target_red:
                    return
                green_prefix = bool(prefix)
                for index, (member, saved, scratch, tree, checks) in enumerate(stacks):
                    answer = answers.get((tree, checks))
                    # A red is blamed only behind stacks all answered green: an unanswered
                    # one ahead may be the culprit, and removing it changes every later tree.
                    if answer is None or ("fix" in answer and index and not green_prefix):
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
                                          target_tree, suite, piece, log, tip_green, tests):
                            target_red = True
                            return
                    if member not in verdicts:
                        answer = verdicts[member] = {**answer, "after": ahead(index)}
                        ready({member: answer})
                    green_prefix = "land" in answer
                    if "fix" in answer:
                        # Only this green-to-red transition identifies a culprit.
                        # Later stacks need new checks on trees without this member.
                        pending = [(m, s) for m, s in pending
                                   if m not in verdicts or "land" in verdicts[m]]
                        rebuild, below = True, index - 1
                        return

            with ThreadPoolExecutor(max_workers=max(1, limit)) as pool:
                running = {}
                try:
                    decide()
                    # The parts the pass's last red whole check confirmed run alone on the top
                    # rebuilt without the culprit, before any whole check: checked whole, it
                    # failed again on those known red since, two more whole checks a culprit (a
                    # stack of 61 holding five landed nothing in 14 hours, 11 Nov 2026).
                    # Failing, a part is that top's red, narrowed as a batch's however many whole
                    # checks fit, and tried again on the next top, as another member may break
                    # it too; passing, proving nothing or its command run there no more, it is
                    # dropped.
                    top = len(stacks) - 1
                    carried[:] = [part for part in carried if part["command"] in commands(top)]
                    for part in list(carried):
                        if (tuple(stacks[top][3:]) in answers or rebuild or target_red
                                or stopped()):
                            break
                        answer_tree(top, None, pool.submit(
                            _check_tests, *stacks[top][:4], part["command"], part["piece"],
                            part["tests"], log), (part["command"], tuple(part["tests"])))
                        if tuple(stacks[top][3:]) in answers:
                            batched = True
                        else:
                            carried.remove(part)
                        decide()
                    while not rebuild and not target_red and not short and not stopped():
                        unchecked = [index for index, (_, _, _, tree, checks) in enumerate(stacks)
                                     if (tree, checks) not in answers]
                        narrowing, command, owner = None, None, 0
                        if below in unchecked and not any("fix" in answer
                                                          for answer in answers.values()):
                            # It waits on no culprit above it: its whole check comes before the
                            # new top's, named tests passing there being no evidence, and green
                            # lands every stack under it (40 members waited, 30 Oct 2026).  A red
                            # already known, a part's on the top, is narrowed first: its steps
                            # run just what failed.
                            unchecked = [below]
                        elif batched and unchecked:
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
                                member = stacks[red_index][0]
                                if member not in verdicts:
                                    verdicts[member] = {**failing, "after": ahead(red_index)}
                                    ready({member: verdicts[member]})
                                pending = [(m, s) for m, s in pending
                                           if m not in verdicts or "land" in verdicts[m]]
                                rebuild, below = True, red_index - 1
                                break
                            # No stack below the command's first runs it: the search starts
                            # just ahead of that one, and it reaches lower only on evidence.
                            floor = max(low, owner - 1)
                            if narrowing and floor + 1 < high:
                                # The stacks between go to the suite helpers, many at once, a
                                # round at a time: here each step took minutes, one after the
                                # other (127 of a pass's 370, 5 Nov 2026).  A round that proves
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
                            member, saved, scratch, tree, own = stacks[index]
                            if (tree, own) in active or len(running) >= limit:
                                continue
                            # Ahead of the command's first stack the target's suite runs where
                            # that stack's `tests:` line does: its tests that failed run there.
                            runs = narrowing and (index, narrowing) not in passed_alone and (
                                command if index >= owner else suite)
                            if runs:
                                job = pool.submit(_check_tests, member, saved, scratch, tree,
                                                  runs, failing["fix"]["piece"], tests, log)
                                running[job] = index, None, narrowing
                            else:
                                checks = commands(index) if batched else own
                                running[pool.submit(_check_tree, member, saved, scratch, tree,
                                                    checks, log, suite)] = index, checks, None
                            active.add((tree, own))
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
