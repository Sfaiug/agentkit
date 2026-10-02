"""Landing together: one suite run for every passed run waiting on a repository's merge turn.

The run holding the turn stacks each waiting run's reviewed commit onto its own, in queue
order, and runs the repository's declared suite once on the top.  When it passes, every
stacked tree is recorded beside the turn's lock: a waiting run whose commit, rebased onto the
target once the runs ahead of it merged, has one of those trees lands on its own turn without
running the suite again, because the same tree is the same code.  A conflict ends the stack
before that run.  A failed suite is split in halves over the stack's prefixes to find the first
run that breaks it: the passing prefix is recorded as above, and that run and the ones after
it check themselves alone on their own turns.  Only a tested tree carries the suite's
evidence.  Offers `passed`, `waiting` and `together`; `run.final_check` is the one caller.
"""

import fcntl
import json
import tempfile
import time
from pathlib import Path

from . import config, record, retention

KEEP = 24 * 3600    # a recorded tree older than a day lands through its own suite again


def _trees(turn, kind="trees"):
    path = turn.with_suffix(".green")
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return path, {}
    kept = data.get(kind) if isinstance(data, dict) else None
    now = time.time()
    return path, {tree: entry for tree, entry in (kept or {}).items()
                  if isinstance(entry, dict) and now - entry.get("at", 0) < KEEP}


def passed(turn, tree):
    """The batch whose suite passed with `tree` on `turn` -- `leader`, `tested`, `at` -- or None."""
    return _trees(turn)[1].get(tree)


def note(turn, trees, leader, alone=()):
    """Record the passing trees and the runs that must check themselves alone."""
    path, kept = _trees(turn)
    solo = _trees(turn, "alone")[1]
    kept.update({tree: {"at": time.time(), "tested": trees[-1], "leader": leader}
                 for tree in trees})
    solo.update({run_id: {"at": time.time()} for run_id in alone})
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(json.dumps({"trees": kept, "alone": solo}))
    fresh.replace(path)


def waiting(turn):
    """(run dir, record) of each live run waiting for `turn`, in queue order.

    A place is `<turn stem>.<rank>-<pid>-<thread>-<ns>.wait` (run.merge_turn_queue), so its
    name sorts in queue order and names the waiting process; the run is the one whose record
    marks that process as waiting for a merge turn.
    """
    pids = []
    for place in sorted(turn.parent.glob(f"{turn.stem}.*.wait")):
        try:
            pid = int(place.name[len(turn.stem) + 1:].split("-")[1])
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
          retention.reading(Path(tmp), directory=True)):
        stack = Path(tmp)
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
