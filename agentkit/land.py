"""Landing together: one suite run for every passed run waiting on a repository's merge turn.

The run holding the turn stacks each waiting run's reviewed commit onto its own, in queue
order, and runs the repository's declared suite once on the top.  When it passes, every
stacked tree is recorded beside the turn's lock: a waiting run whose commit, rebased onto the
target once the runs ahead of it merged, has one of those trees lands on its own turn without
running the suite again, because the same tree is the same code.  A conflict leaves that
run out and stacking continues.  A failed suite is split in halves over the stack's prefixes
to find the first run that breaks it: the passing prefix is recorded as above, and that run and the ones after
it check themselves alone on their own turns.  Only a tested tree carries the suite's
evidence.  Offers `passed`, `waiting` and `together` for `run.final_check`.

`check_line` checks each parked stack by its tree.  A red stack after a green one wakes only
its newest member to fix, then later stacks are rebuilt without it.  Conflicts with the bare
target wake members to fix at once; conflicts only with earlier members wait. A red target
gets one repair first; the checker owns no member's process or delivery.
"""

from concurrent.futures import ThreadPoolExecutor
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


def note(turn, trees, leader, alone=(), *, red=None, red_stacks=None):
    """Keep stack evidence separately from target probes awaiting their repair."""
    path, kept = _trees(turn)
    solo = _trees(turn, "alone")[1]
    failed = {} if red_stacks == {} else _trees(turn, "red_stacks")[1]
    repairs = _trees(turn, "red")[1]
    kept.update({tree: {"at": time.time(), "tested": trees[-1], "leader": leader}
                 for tree in trees})
    solo.update({run_id: {"at": time.time()} for run_id in alone})
    repairs.update(red or {})
    failed.update({tree: {"at": time.time(), **fix} for tree, fix in (red_stacks or {}).items()})
    for tree in trees:
        failed.pop(tree, None)
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(json.dumps({"trees": kept, "alone": solo, "red": repairs,
                                "red_stacks": failed}))
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
    from . import host, orch, run, worker
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
            if record.process_active(members[0][1]):
                return False  # the joining attempt must finish cleanup before a wake
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
            _, properties = run.run_scope_limits(cap_mb=math.ceil(max(caps)))
        env = config.child_env()
        # This work outlives its caller and must not belong to the caller's stop sweep.
        for key in (worker.RUN_MARKER, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_ROLE",
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
    """Check stacks from the first member without a verdict, under the singleton flock.

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
        members = line(turn)
        for index, (directory, state) in enumerate(members):
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
            name = None
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
                candidates = [(directory, state)]
                for later, saved in members[index + 1:] if not name else ():
                    with record.recovery_lock(later):
                        if (record.read_state(later) == saved and not record.process_active(saved)
                                and (saved.get("review") or {}).get("verdict") == "PASS"
                                and not any(k in saved["waiting_on"] for k in ("land", "fix"))):
                            candidates.append((later, saved))
                verdicts = _check_members(turn, candidates, repo, tip, target_tree, log)
                if not verdicts:
                    return
            else:
                candidates, verdicts = [(directory, state)], {directory: verdict}
            # Every attribution depends on the unchanged members ahead of it.  Hold their
            # recovery locks together so a resume cannot replace that evidence mid-write.
            with ExitStack() as held:
                for member, saved in candidates:
                    held.enter_context(record.recovery_lock(member))
                    if record.read_state(member) != saved or record.process_active(saved):
                        break
                else:
                    # Save red verdicts before the head can advance: a crash must not
                    # lose a failure that only appears together with that head.
                    for member, answer in sorted(verdicts.items(), key=lambda item: "land" in item[1]):
                        with record.record(member) as current:
                            current["waiting_on"] = {**current["waiting_on"], **answer}
                    # A reparked member needs a fresh check, including any red suffix
                    # discarded during rebuilding.  Save verdicts before dropping evidence.
                    note(turn, [], directory.name, red_stacks={})
                    for member in verdicts:
                        watch.launch_resume(member.name, log)
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


def _member_commit(repo, state, head):
    """One remote's line can contain private commits from separate clones."""
    from . import run
    if run.git_out(repo, "cat-file", "-e", f"{head}^{{commit}}")[0] == 0:
        return 0, ""
    source = state.get("worktree") or state.get("repo") or str(repo)
    return run.git_out(repo, "fetch", "--no-tags", "--no-write-fetch-head", "--", str(source), head)


def _stack_member(repo, state, top, upstream, opened):
    """Integrate a reviewed head in scratch; no scratch means setup failed."""
    from . import run
    head = state["review"]["head_sha"]
    code, out = _member_commit(repo, state, head)
    if code:
        return None, f"[exit {code}]\nERROR: reviewed commit {head} is unavailable\n{out}"
    scratch = Path(opened.enter_context(tempfile.TemporaryDirectory(dir=config.WT, prefix="land-")))
    opened.callback(os.close, os.open(scratch, os.O_RDONLY))
    code, out = run.git_out(repo, "worktree", "add", "--detach", str(scratch), head)
    opened.callback(run.git_out, repo, "worktree", "remove", "--force", str(scratch))
    if code:
        return None, f"[exit {code}]\nERROR: checkout of {head} failed\n{out}"
    lp = SimpleNamespace(state=state, wt=scratch,
                         base_sha=state.get("base_sha") or
                         run.git(scratch, "merge-base", head, top))
    how = "rebase" if run.on_pass(lp) else run.how_to_integrate(lp)
    args = (("merge", "--no-edit", top) if how == "merge" else
            ("rebase", "--onto", top, lp.base_sha) if run.on_pass(lp) else
            ("rebase", top))
    if how == "rebase":
        # A detached rebase must not rewrite the member's branch through Git config.
        args = ("-c", "rebase.updateRefs=false", *args)
    code, out = run.git_out(scratch, *args)
    text = (f"$ git {' '.join(args)}\n[exit {code}]\n"
            f"ERROR: {how} of {upstream} failed\n{out}") if code else ""
    return scratch, text


def _check_tree(directory, state, scratch, upstream, log):
    from . import run, task
    tree = run.git(scratch, "rev-parse", "HEAD^{tree}")
    log_path = directory / f"lander-{tree}.log"
    _, body, _ = task.parse_task(directory / "task.md")
    cmds = task.group_commands(run.with_suite(
        task.done_when(body, directory / "task.md"), scratch, upstream))[1]
    ok, text = _check(directory, state, scratch, cmds, log_path, log)
    return {"land": tree} if ok else {"fix": {"line": run.first_failure(text), "log": str(log_path)}}


def _check_members(turn, members, repo, tip, target_tree, log):
    from . import run
    directory, state = members[0]
    upstream = state.get("target") or state["base"]
    upstream = upstream if upstream.startswith("origin/") else f"origin/{upstream}"
    config.WT.mkdir(parents=True, exist_ok=True)
    pending, verdicts = list(members), {}
    while pending:
        with ExitStack() as opened:
            top, stacks = tip, []
            for member, saved in pending:
                # Earlier changes can hide a target conflict, so try the bare tip first.
                scratch, text = _stack_member(repo, saved, tip, upstream, opened)
                if text:
                    if member == directory or scratch is not None:
                        log_path = member / "lander.log"
                        log_path.write_text(text)
                        verdicts[member] = {"fix": {"line": run.first_failure(text), "log": str(log_path)}}
                    continue
                if top != tip:
                    scratch, text = _stack_member(repo, saved, top, upstream, opened)
                    if text:
                        continue
                top = run.git(scratch, "rev-parse", "HEAD")
                tree = run.git(scratch, "rev-parse", "HEAD^{tree}")
                stacks.append((member, saved, scratch, tree))
            if not stacks:
                break
            green, red = _trees(turn)[1], _trees(turn, "red_stacks")[1]
            # The first stack has no green prefix to attribute a cached failure to.
            # Retry its own check after a kill or flake; later evidence survives a crash.
            red.pop(stacks[0][3], None)
            answers = {tree: {"land": tree} if tree in green else
                       {"fix": {key: red[tree][key] for key in ("line", "log")}}
                       for _, _, _, tree in stacks if tree in green or tree in red}
            unchecked = {tree: (member, saved, scratch) for member, saved, scratch, tree in reversed(stacks)
                         if tree not in answers}
            if unchecked:
                # Heavy-turn admission derives how many checks can run; threads only wait.
                with ThreadPoolExecutor(max_workers=len(unchecked)) as pool:
                    checks = {tree: pool.submit(_check_tree, *args, upstream, log)
                              for tree, args in unchecked.items()}
                    for tree, check in checks.items():
                        answer = answers[tree] = check.result()
                        note(turn, [tree] if "land" in answer else [], directory.name,
                             red_stacks={tree: answer["fix"]} if "fix" in answer else None)
            for index, (member, saved, scratch, tree) in enumerate(stacks):
                answer = answers[tree]
                if (index == 0 and "fix" in answer
                        and not saved.get("repair") and not passed(turn, target_tree)):
                    run.git(scratch, "reset", "--hard", tip)
                    run.git(scratch, "clean", "-fdx")
                    suite = run.declared_suite(scratch)
                    if suite:
                        ok, probe = _check(member, saved, scratch, [suite],
                                           member / "target-probe.log", log)
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
                            _repair(turn, member, saved, target_tree, red, log)
                            return verdicts
                if member == directory or "fix" in answer:
                    verdicts[member] = answer
                if "fix" in answer:
                    # Only this green-to-red transition identifies a culprit.  Evidence
                    # behind it includes its changes, so rebuild before deciding again.
                    pending = [(m, s) for m, s in pending if m not in verdicts or "land" in verdicts[m]]
                    break
            else:
                break
    return verdicts


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
                if _member_commit(wt, state, commit)[0]:
                    continue
                base = run.git(stack, "merge-base", commit, upstream, check=False)
                code, _ = run.git_out(stack, "-c", "rebase.updateRefs=false", "rebase",
                                      "--onto", top, base or upstream, commit)
                if code != 0:
                    run.git_out(stack, "rebase", "--abort")
                    # Abort returns to the conflicting commit, not the saved batch top.
                    run.git(stack, "reset", "--hard", top)
                    log(f"--- merge: {state.get('run_id')} does not stack on the batch; "
                        "it lands on its own turn")
                    continue
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
