"""Check parked landing-line members and wake each run to deliver or fix its own work.

Only the tested tree carries suite evidence. The lander never owns a member's
process or delivery.
"""

from contextlib import ExitStack
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from . import config, record

KEEP = 24 * 3600    # a recorded tree older than a day lands through its own suite again


def _trees(turn):
    path = turn.with_suffix(".green")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return path, {}
    kept = data.get("trees") if isinstance(data, dict) else None
    now = time.time()
    return path, {tree: entry for tree, entry in (kept or {}).items()
                  if isinstance(entry, dict) and now - entry.get("at", 0) < KEEP}


def passed(turn, tree):
    """The suite evidence for `tree` on `turn` -- `leader`, `tested`, `at` -- or None."""
    return _trees(turn)[1].get(tree)


def note(turn, trees, leader):
    """Record suite evidence for the tested tree."""
    path, kept = _trees(turn)
    kept.update({tree: {"at": time.time(), "tested": tree, "leader": leader}
                 for tree in trees})
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(json.dumps({"trees": kept}))
    fresh.replace(path)


def line(turn):
    """Parked members of `turn`, oldest joined first; verdicts stay until their runs resume."""
    members = []
    for directory in record.run_dirs():
        state = record.read_state(directory) or {}
        wait = state.get("waiting_on")
        if (state.get("state") == "waiting" and isinstance(wait, dict)
                and wait.get("line") == turn.name
                and type(wait.get("joined")) in (int, float)):
            members.append((directory, state))
    return sorted(members, key=lambda member: (member[1]["waiting_on"]["joined"],
                                               member[0].name))


def check_line(turn, log=lambda _: None):
    """Check the first member without a verdict, under the line's singleton flock.

    Saved verdicts are woken again if a crash or refused launch left them parked.  A member
    can resume or stop during its check: only an unchanged, processless parked record gets
    the verdict.  The recovery lock covers that write and the wake, never the suite.
    """
    from . import watch
    turn = Path(turn)
    with turn.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        for directory, state in line(turn):
            with record.recovery_lock(directory):
                if record.read_state(directory) != state or record.process_active(state):
                    continue
            verdict = {key: state["waiting_on"][key] for key in ("land", "fix")
                       if key in state["waiting_on"]}
            checked = not verdict
            if checked:
                if (state.get("review") or {}).get("verdict") != "PASS":
                    continue
                verdict = _check_member(turn, directory, state, log)
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


def _check_member(turn, directory, state, log):
    from . import gate, run, task
    repo = Path(state.get("worktree") or state["repo"])
    head = state["review"]["head_sha"]
    upstream = state.get("target") or state["base"]
    upstream = upstream if upstream.startswith("origin/") else f"origin/{upstream}"
    run.fetch(repo, "origin", "--prune", check=True)
    tip = run.git(repo, "rev-parse", f"{upstream}^{{commit}}")
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
                clean = run.git_out(scratch, "diff", "--quiet", "HEAD")[0] == 0
                _, body, _ = task.parse_task(directory / "task.md")
                cmds = task.group_commands(run.with_suite(
                    task.done_when(body, directory / "task.md"), scratch, upstream))[1]
                # The checker takes a heavy turn without marking any member's record.
                context = {"repo": str(repo), "run_id": directory.name, "landing": True,
                           "since": state["waiting_on"]["joined"]}
                suite = next((cmd for cmd in cmds if gate.names_shard(cmd)), None)
                with gate.gate_turn(None, log_path, log, suite, scratch, context=context):
                    ok, text = gate.run_done_when(
                        cmds, scratch, log_path, set(),
                        3600 * state.get("ceiling_hours", record.CEILING_HOURS), log,
                        silence=60 * state.get("silence_minutes", record.SILENCE_MINUTES),
                        heavy=True)
                if (not clean or run.commit_identity(scratch) != identity
                        or run.git_out(scratch, "diff", "--quiet", "HEAD")[0]):
                    ok = False
                    text += ("\n\nCheckout changed during the final check; "
                             "these commands do not verify the pinned commit.")
                text = f"Commit: {identity['head_sha']}\nTree: {tree}\n\n{text}"
                log_path.write_text(text)
                if ok:
                    note(turn, [tree], directory.name)
                    return {"land": tree}
            log_path.write_text(text)
            return {"fix": {"line": run.first_failure(text), "log": str(log_path)}}
        finally:
            run.git_out(repo, "worktree", "remove", "--force", str(scratch))
