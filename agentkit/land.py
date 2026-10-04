"""Check parked landing-line stacks and wake each run to deliver or fix its own work.

Only the tested tree carries suite evidence. A red stack after a green one wakes
its newest member to fix; later stacks are rebuilt without it. A red target gets
one repair first. The lander never owns a member's process or delivery.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
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
    """The suite evidence for `tree` on `turn` -- `leader`, `tested`, `at` -- or None."""
    return _trees(turn)[1].get(tree)


def note(turn, trees, leader, *, red=None, red_stacks=None):
    """Keep stack evidence separately from target probes awaiting their repair."""
    path, kept = _trees(turn)
    failed = {} if red_stacks == {} else _trees(turn, "red_stacks")[1]
    repairs = _trees(turn, "red")[1]
    kept.update({tree: {"at": time.time(), "tested": tree, "leader": leader}
                 for tree in trees})
    repairs.update(red or {})
    failed.update({tree: {"at": time.time(), **fix} for tree, fix in (red_stacks or {}).items()})
    for tree in trees:
        failed.pop(tree, None)
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(json.dumps({"trees": kept, "red": repairs,
                                "red_stacks": failed}))
    fresh.replace(path)


def line(turn):
    """Members including green deliveries that continue themselves: green deliveries first,
    then first runs, each group in join order."""
    from . import run
    members = []
    for directory in record.run_dirs():
        state = record.read_state(directory) or {}
        wait = state.get("waiting_on")
        if (isinstance(wait, dict) and not state.get("merged")
                and (state.get("state") == "waiting"
                     or (_green(wait)
                         and state.get("state") not in run.ENDED
                         and run.followup_open(state)
                         and (record.process_active(state) or run.tick_resumes(state))))
                and wait.get("line") == turn.name
                and type(wait.get("joined")) in (int, float)):
            members.append((directory, state))
    return sorted(members, key=lambda member: (not _green(member[1]["waiting_on"]),
                                              not member[1].get("first"),
                                              member[1]["waiting_on"]["joined"],
                                              member[0].name))


def _green(wait):
    """A green delivery stays ahead: the stacks behind it are the ones that can land."""
    return "land" in wait and "fix" not in wait


def start_line(turn, log=lambda _: None):
    """Start a fresh checker when no pass is running; the tick retries a missed start."""
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
            waiting = next((state for _, state in members if state.get("state") == "waiting"), None)
            if waiting is None or record.process_active(waiting):
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

    The singleton is separate from delivery so checks and merges can overlap.
    Saved verdicts are woken again if a crash or refused launch left them parked.  A member
    can resume or stop during its check: only an unchanged, processless parked record gets
    the verdict.  The recovery lock covers that write and the wake, never the suite.
    """
    from . import run, watch
    turn = Path(turn)
    with turn.with_suffix(".lander.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        target, prefix = None, []
        members = line(turn)
        for index, (directory, state) in enumerate(members):
            with record.recovery_lock(directory):
                if record.read_state(directory) != state or record.process_active(state):
                    if "land" in state["waiting_on"] and "fix" not in state["waiting_on"]:
                        prefix.append((directory, state))
                        continue
                    return  # a live rejoiner still holds its place ahead of later stacks
            if state.get("state") != "waiting":
                prefix.append((directory, state))
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
                        if (record.read_state(later) != saved or record.process_active(saved)
                                or saved.get("state") != "waiting"):
                            break
                        if ((saved.get("review") or {}).get("verdict") == "PASS"
                                and not any(k in saved["waiting_on"] for k in ("land", "fix"))):
                            candidates.append((later, saved))
            else:
                candidates = [(directory, state)]
            sent, snapshots, valid = set(), dict(candidates), True

            def publish(answers):
                nonlocal valid
                if not valid:
                    return False
                fresh = {member: answer for member, answer in answers.items() if member not in sent}
                if not fresh:
                    return True
                # Delivery rewrites ownership and rebase receipts, but keeps the reviewed
                # work and tested tree. Only an unwoken recipient must stay processless.
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
                                    and run.passed_review_head(current) == run.passed_review_head(saved)
                                    and ((current.get("waiting_on") == saved["waiting_on"]
                                          and current.get("state") not in run.ENDED
                                          and (current.get("state") == "waiting"
                                               or (run.followup_open(current)
                                                   and (record.process_active(current) or run.tick_resumes(current))))
                                          and review.get("tree_sha") in (saved["review"].get("tree_sha"), tree))
                                         or ((current.get("merged") or current.get("on_target"))
                                             and review.get("tree_sha") == tree)))
                        else:
                            same = current == saved and not record.process_active(current)
                        if not same:
                            valid = False
                            return False
                    for member, answer in sorted(fresh.items(), key=lambda item: "land" in item[1]):
                        with record.record(member) as current:
                            current["waiting_on"] = {**current["waiting_on"], **answer}
                        # Later answers still compare against this pass's own writes.
                        snapshots[member]["waiting_on"] = dict(current["waiting_on"])
                    sent.update(fresh)
                    for member in fresh:
                        watch.launch_resume(member.name, log)
                return True

            verdicts = (_check_members(turn, candidates, repo, tip, target_tree, log,
                                      prefix=prefix, ready=publish) if checked else {directory: verdict})
            if not verdicts:
                return
            if publish(verdicts) and checked:
                # A reparked member must retry red suffixes discarded during rebuilding.
                note(turn, [], directory.name, red_stacks={})
            if checked:
                return
            if "land" in verdict and "fix" not in verdict:
                prefix.append((directory, state))


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


def _check_members(turn, members, repo, tip, target_tree, log, *, prefix=(), ready=lambda _: None):
    from . import gate, run
    directory, state = members[0]
    upstream = state.get("target") or state["base"]
    upstream = upstream if upstream.startswith("origin/") else f"origin/{upstream}"
    config.WT.mkdir(parents=True, exist_ok=True)
    pending, verdicts = list(members), {}
    remaining = max(1, gate.derived_heavy_limit())
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
            if not prefix:
                red.pop(stacks[0][3], None)
            answers = {tree: {"land": tree} if tree in green else
                       {"fix": {key: red[tree][key] for key in ("line", "log")}}
                       for _, _, _, tree in stacks if tree in green or tree in red}
            unchecked = {}
            for member, saved, scratch, tree in stacks:
                if tree not in answers and len(unchecked) < remaining:
                    unchecked.setdefault(tree, (member, saved, scratch))
            remaining -= len(unchecked)

            def answer_tree(tree, check):
                if tree not in answers:
                    answer = answers[tree] = check.result()
                    note(turn, [tree] if "land" in answer else [], directory.name,
                         red_stacks={tree: answer["fix"]} if "fix" in answer else None)
                return answers[tree]

            rebuild, target_red = False, False

            def decide():
                nonlocal pending, rebuild, target_red
                if target_red:
                    return
                green_prefix = bool(prefix)
                for index, (member, saved, scratch, tree) in enumerate(stacks):
                    answer = answers.get(tree)
                    if answer is None:
                        green_prefix = False
                        continue
                    if "fix" in answer and index and not green_prefix:
                        continue
                    if (index == 0 and not prefix and "fix" in answer
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
                                target_red = True
                                return
                    if (member == directory or "fix" in answer) and member not in verdicts:
                        verdicts[member] = answer
                        ready({member: answer})
                    green_prefix = "land" in answer
                    if "fix" in answer:
                        # Only this green-to-red transition identifies a culprit.
                        # Rebuilding shares the pass's remaining checks.
                        pending = [(m, s) for m, s in pending
                                   if m not in verdicts or "land" in verdicts[m]]
                        rebuild = True
                        return

            with ThreadPoolExecutor(max_workers=max(1, len(unchecked))) as pool:
                checks = {pool.submit(_check_tree, *args, upstream, log): tree
                          for tree, args in unchecked.items()}
                try:
                    decide()
                    for check in as_completed(checks):
                        answer_tree(checks[check], check)
                        decide()
                finally:
                    # Keep suffix evidence even if a wake or verdict write crashes.
                    for check, tree in checks.items():
                        answer_tree(tree, check)
            if target_red or not rebuild:
                break
    return verdicts
