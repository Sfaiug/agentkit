"""Landing together: one suite run for every passed run waiting on a repository's merge turn.

The run holding the turn stacks each waiting run's reviewed commit onto its own, in queue
order, and runs the repository's declared suite once on the top.  When it passes, every
stacked tree is recorded beside the turn's lock: a waiting run whose commit, rebased onto the
target once the runs ahead of it merged, has one of those trees lands on its own turn without
running the suite again, because the same tree is the same code.  A conflict ends the stack
before that run.  A failed suite is split in halves over the stack's prefixes to find the first
run that breaks it: the passing prefix is recorded as above, and that run and the ones after
it check themselves alone on their own turns.  Only a tested tree carries the suite's
evidence.  Offers `passed`, `waiting` and `together` for `run.final_check`.

`check_line` checks one parked line member and wakes it to land or fix itself. A red target
gets one repair first, keeping the other members unblamed while it holds that tree. The run
consumes its verdict; this checker never takes ownership of its process or delivery.
"""

from contextlib import ExitStack
import fcntl
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from . import config, record

KEEP = 24 * 3600    # a recorded tree older than a day lands through its own suite again


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
    """The batch whose suite passed with `tree` on `turn` -- `leader`, `tested`, `at` -- or None."""
    return _trees(turn)[1].get(tree)


def note(turn, trees, leader, alone=(), *, red=None):
    """Record passing trees, solo checks and red target probes awaiting their repair."""
    path, kept = _trees(turn)
    solo = _trees(turn, "alone")[1]
    kept.update({tree: {"at": time.time(), "tested": trees[-1], "leader": leader}
                 for tree in trees})
    solo.update({run_id: {"at": time.time()} for run_id in alone})
    repairs = _trees(turn, "red")[1]
    repairs.update(red or {})
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(json.dumps({"trees": kept, "alone": solo, "red": repairs}))
    fresh.replace(path)


def line(turn):
    """Parked members of `turn`, first runs then join order; verdicts stay until resume."""
    members = []
    for directory in record.run_dirs():
        state = record.read_state(directory) or {}
        wait = state.get("waiting_on")
        if (state.get("state") == "waiting" and isinstance(wait, dict)
                and wait.get("line") == turn.name
                and type(wait.get("joined")) in (int, float)):
            members.append((directory, state))
    return sorted(members, key=lambda member: (not member[1].get("first"),
                                               member[1]["waiting_on"]["joined"],
                                               member[0].name))


def start_line(turn, log=lambda _: None):
    """Start a fresh checker when the line is free; the tick retries a missed start."""
    from . import host, orch, run
    turn = Path(turn)
    if turn.parent != config.RUNS or not turn.name.startswith(".merge-"):
        return False
    try:
        with turn.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            members = line(turn)
            if not members:
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
        properties = ()
        if caps:
            cap = math.ceil(max(caps))
            properties = ("-p", f"MemoryMax={cap}M", "-p", f"MemorySwapMax={cap}M")
        env = config.child_env()
        # This work outlives its caller and must not belong to the caller's stop sweep.
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_ROLE",
                    config.JOB_DIR_ENV, config.SESSION_ENV, config.UNATTENDED_ENV):
            env.pop(key, None)
        env["AK_RUN_DEPTH"] = "0"
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


def _repair(turn, directory, state, tree, red, log):
    """Keep the probe before launch: a crash can reuse its repair receipt without a suite."""
    from . import run
    try:
        name = run.start_followups(state, directory, log, repair=red["probe"])
    except record.StopRequested:
        raise
    except Exception as exc:  # a refused repair leaves the line waiting, unblamed
        log(f"WARN no target repair could start: {exc}")
        return None
    if name:
        note(turn, [], directory.name, red={tree: {**red, "run": name}})
    return name


def check_line(turn, log=lambda _: None):
    """Check the first member without a verdict, under the line's singleton flock.

    Saved verdicts are woken again if a crash or refused launch left them parked.  A member
    can resume or stop during its check: only an unchanged, processless parked record gets
    the verdict.  The recovery lock covers that write and the wake, never the suite.
    """
    from . import run, watch
    turn = Path(turn)
    with turn.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        target = None
        for directory, state in line(turn):
            with record.recovery_lock(directory):
                if record.read_state(directory) != state or record.process_active(state):
                    continue
            if target is None:
                repo = Path(state.get("worktree") or state["repo"])
                upstream = state.get("target") or state["base"]
                upstream = upstream if upstream.startswith("origin/") else f"origin/{upstream}"
                run.fetch(repo, "origin", "--prune", check=True)
                tip = run.git(repo, "rev-parse", f"{upstream}^{{commit}}")
                target = tip, run.git(repo, "rev-parse", f"{tip}^{{tree}}")
            tip, target_tree = target
            red = _trees(turn, "red")[1].get(target_tree)
            if red and not passed(turn, target_tree):
                name = red.get("run")
                repair = record.read_state(config.RUNS / name) if name else None
                if repair is None:
                    name = _repair(turn, directory, state, target_tree, red, log)
                    if not name:
                        return
                elif not run.repair_open(repair, red["probe"]["sha"]):
                    name = None
                if name and directory.name != name:
                    continue
            verdict = {key: state["waiting_on"][key] for key in ("land", "fix")
                       if key in state["waiting_on"]}
            checked = not verdict
            if checked:
                if (state.get("review") or {}).get("verdict") != "PASS":
                    continue
                verdict = _check_member(turn, directory, state, tip, target_tree, log)
                if not verdict:
                    return
            with record.recovery_lock(directory):
                with record.record(directory) as current:
                    if current != state or record.process_active(current):
                        if checked:
                            return
                        continue
                    current["waiting_on"] = {**current["waiting_on"], **verdict}
                watch.launch_resume(directory.name, log)
            if checked:
                return


def _check(directory, state, scratch, cmds, log_path, log):
    from . import gate, run
    identity = run.commit_identity(scratch)
    clean = run.git_out(scratch, "diff", "--quiet", "HEAD")[0] == 0
    # The checker takes a heavy turn without marking any member's record.
    context = {"repo": state["repo"], "run_id": directory.name, "landing": True,
               "since": state["waiting_on"]["joined"]}
    suite = next((cmd for cmd in cmds if gate.names_shard(cmd)), None)
    with gate.gate_turn(None, log_path, log, suite, scratch, context=context):
        ok, text = gate.run_done_when(
            cmds, scratch, log_path, set(),
            3600 * state.get("ceiling_hours", record.CEILING_HOURS), log,
            silence=60 * state.get("silence_minutes", record.SILENCE_MINUTES), heavy=True)
    if (not clean or run.commit_identity(scratch) != identity
            or run.git_out(scratch, "diff", "--quiet", "HEAD")[0]):
        ok = False
        text += ("\n\nCheckout changed during the final check; "
                 "these commands do not verify the pinned commit.")
    text = f"Commit: {identity['head_sha']}\nTree: {identity['tree_sha']}\n\n{text}"
    log_path.write_text(text)
    return ok, text


def _check_member(turn, directory, state, tip, target_tree, log):
    from . import run, task
    repo = Path(state.get("worktree") or state["repo"])
    head = state["review"]["head_sha"]
    upstream = state.get("target") or state["base"]
    upstream = upstream if upstream.startswith("origin/") else f"origin/{upstream}"
    log_path = directory / "lander.log"
    config.WT.mkdir(parents=True, exist_ok=True)
    with (tempfile.TemporaryDirectory(dir=config.WT, prefix="land-") as tmp,
          ExitStack() as opened):
        scratch = Path(tmp)
        opened.callback(os.close, os.open(scratch, os.O_RDONLY))
        run.git(repo, "worktree", "add", "--detach", str(scratch), head)
        try:
            lp = SimpleNamespace(state=state, wt=scratch,
                                 base_sha=state.get("base_sha") or
                                 run.git(scratch, "merge-base", head, tip))
            how = "rebase" if run.on_pass(lp) else run.how_to_integrate(lp)
            args = (("merge", "--no-edit", tip) if how == "merge" else
                    ("rebase", "--onto", tip, lp.base_sha) if run.on_pass(lp) else
                    ("rebase", tip))
            if how == "rebase":
                # A detached rebase must not rewrite the member's branch through Git config.
                args = ("-c", "rebase.updateRefs=false", *args)
            code, out = run.git_out(scratch, *args)
            if code:
                text = (f"$ git {' '.join(args)}\n[exit {code}]\n"
                        f"ERROR: {how} of {upstream} failed\n{out}")
            else:
                identity = run.commit_identity(scratch)
                tree = identity["tree_sha"]
                if passed(turn, tree):
                    return {"land": tree}
                _, body, _ = task.parse_task(directory / "task.md")
                cmds = task.group_commands(run.with_suite(
                    task.done_when(body, directory / "task.md"), scratch, upstream))[1]
                ok, text = _check(directory, state, scratch, cmds, log_path, log)
                if ok:
                    note(turn, [tree], directory.name)
                    return {"land": tree}
                if not state.get("repair") and not passed(turn, target_tree):
                    run.git(scratch, "reset", "--hard", tip)
                    run.git(scratch, "clean", "-fdx")
                    suite = run.declared_suite(scratch)
                    if suite:
                        ok, probe = _check(directory, state, scratch, [suite],
                                           directory / "target-probe.log", log)
                        if ok:
                            note(turn, [target_tree], directory.name)
                        else:
                            printed = "\n".join("    " + line
                                                for line in probe[-run.OUT_CAP:].splitlines())
                            red = {"probe": {"command": suite, "check": f"{suite}  # once",
                                   "sha": tip,
                                   "text": f"`{suite}` fails on {upstream} at {tip}, the target's "
                                           f"own tip, whichever branch runs it. What it printed "
                                           f"there:\n\n{printed}"}}
                            note(turn, [], directory.name, red={target_tree: red})
                            _repair(turn, directory, state, target_tree, red, log)
                            return {}
            log_path.write_text(text)
            return {"fix": {"line": run.first_failure(text), "log": str(log_path)}}
        finally:
            run.git_out(repo, "worktree", "remove", "--force", str(scratch))


def waiting(turn):
    """(run dir, record) of each live run waiting for `turn`, in queue order.

    A place is `<turn stem>.<rank>-<joined>-<pid>-<thread>-<ns>.wait` (run.merge_turn_queue), so its
    name sorts in queue order and names the waiting process; the run is the one whose record
    marks that process as waiting for a merge turn.
    """
    pids = []
    for place in sorted(turn.parent.glob(f"{turn.stem}.*.wait")):
        try:
            pid = int(place.name[len(turn.stem) + 1:].split("-")[-3])
            with place.open() as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    continue      # the queue flock, not a reusable pid, proves it is live
        except (IndexError, ValueError, FileNotFoundError):
            continue
        if pid not in pids:
            pids.append(pid)
    found = {}
    for directory in record.run_dirs() if pids else ():
        state = record.read_state(directory) or {}
        mark = state.get("merge_turn")
        if (state.get("state") == "running" and isinstance(mark, dict)
                and mark.get("pid") == state.get("pid") and mark.get("pid") in pids):
            found[mark["pid"]] = (directory, state)
    return [found[pid] for pid in pids if pid in found]


def together(wt, head, upstream, turn, leader, suite_run, log):
    """Stack the waiting runs onto `head` and run the suite once on the top.

    `suite_run(cwd)` runs the declared suite there and returns (ok, text).  Returns
    (ok, the run ids stacked, text); with nobody to stack, (None, [], "") and nothing runs.
    A passing suite records every stacked tree with `note`; a failing one is halved over the
    prefixes until the first failing one is found, and the passing prefix before it recorded.
    """
    from . import run   # here, not at the top: run imports this module
    alone = _trees(turn, "alone")[1]
    if leader in alone:
        return None, [], ""
    trees, members = [run.git(wt, "rev-parse", f"{head}^{{tree}}")], []
    commits, green = [head], 0
    config.WT.mkdir(parents=True, exist_ok=True)
    # The open directory protects a live stack; a dead one's path belongs to the orphan sweep.
    with (tempfile.TemporaryDirectory(dir=config.WT, prefix="land-") as tmp,
          ExitStack() as opened):
        stack = Path(tmp)
        opened.callback(os.close, os.open(stack, os.O_RDONLY))
        run.git(wt, "worktree", "add", "--detach", str(stack), head)
        try:
            top = head
            for _, state in waiting(turn):
                if state.get("run_id") in alone:
                    break
                review = state.get("review") or {}
                commit = review.get("passed_head_sha")
                if (state.get("run_id") == leader or review.get("verdict") != "PASS"
                        or not commit or state.get("merge_method") == "merge"):
                    continue
                base = run.git(stack, "merge-base", commit, upstream, check=False)
                code, _ = run.git_out(stack, "rebase", "--onto", top, base or upstream, commit)
                if code != 0:
                    run.git_out(stack, "rebase", "--abort")
                    # Abort returns to the conflicting commit, not the saved batch top.
                    run.git(stack, "reset", "--hard", top)
                    log(f"--- merge: {state.get('run_id')} does not stack on the batch; "
                        "it lands on its own turn")
                    break
                top = run.git(stack, "rev-parse", "HEAD")
                commits.append(top)
                trees.append(run.git(stack, "rev-parse", "HEAD^{tree}"))
                members.append(state.get("run_id"))
            if not members:
                return None, [], ""
            log(f"--- merge: landing together: {len(members) + 1} runs on {upstream}: "
                f"{', '.join([leader, *members])}")
            ok, text = suite_run(stack)
            green = len(trees) if ok else split(stack, commits, suite_run, [leader, *members],
                                                log)
        finally:
            run.git_out(wt, "worktree", "remove", "--force", str(stack))
    note(turn, trees[:green], leader, [] if ok else [leader, *members][green:])
    return ok, members, text


def split(stack, commits, suite_run, ids, log):
    """How many of the stacked commits pass, the last one known failing: halve the prefixes."""
    from . import run
    passing, failing = 0, len(commits)        # the first `passing` pass; prefix `failing` fails
    while failing - passing > 1:
        middle = (passing + failing) // 2
        # A failed suite can leave tracked edits or build output behind; test a fresh prefix.
        run.git(stack, "reset", "--hard", commits[middle - 1])
        run.git(stack, "clean", "-fdx")
        ok, _ = suite_run(stack)
        passing, failing = (middle, failing) if ok else (passing, middle)
    log(f"--- merge: {ids[failing - 1]} breaks the suite of the batch; "
        + (f"the {passing} run(s) before it pass and land" if passing
           else "it is the first, so each run checks itself alone"))
    return passing
