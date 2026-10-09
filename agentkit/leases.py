"""Collisions between the live runs of one repository: the tick's scan, report-only.

A run's lease is its own diff against the base it was cut from, uncommitted edits included;
no model declares, renews or releases anything.  Each tick, every pair of live runs of a
repository is merged in memory (`git merge-tree --write-tree`, git's own conflict rule, over
the merge base of their bases), and a pair that cannot merge is written down on the younger
run, by start, as waiting on the older (wait-die: the older never waits on the younger, so
no cycle can form).  Nothing is refused here: the record under `~/.agentkit/state/leases/`
and the tick's log line are what the refusals at ak's commit step, the git shim and the
lander, and the restart on the newest main, stand on.  A diff counts only while its run is
going (`run.going`) and its checkout is there; a record whose pair no longer collides, or
whose holder is gone, is cleared on the next scan.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from . import config
from . import record as run_record

DIR = "leases"


def git(cwd, *args, env=None):
    """One git call in `cwd`; its stdout stripped, or an error with git's words."""
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          env=env)
    if done.returncode:
        raise config.Error(f"git {args[0]} in {cwd}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


def same_repo(a, b):
    """Whether two recorded checkouts name the same repository."""
    try:
        return bool(a) and bool(b) and Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def path(repo):
    """The record of one repository's collisions, named by its checkout."""
    key = hashlib.sha256(str(Path(repo).resolve()).encode()).hexdigest()[:16]
    return config.STATE / DIR / f"{Path(repo).resolve().name}-{key}.json"


def read(repo):
    """The collisions the last scan wrote down: `{younger run: {waits_on, files, since}}`."""
    try:
        found = json.loads(path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def write(repo, waits):
    """The record as this scan saw it, whole: nothing from an earlier scan outlives it."""
    target = path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    with (target.parent / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fresh = target.with_name(target.name + ".new")
        fresh.write_text(json.dumps(waits, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        fresh.replace(target)


def live(repo):
    """The runs of that repository whose diffs count: going, cut from a base, with a checkout
    of their own that is still there; oldest first by start."""
    from . import run
    found = []
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        if (not state or state.get("scratch") or not state.get("base_sha")
                or not same_repo(state.get("repo"), repo) or not run.going(state)):
            continue
        worktree = Path(state.get("worktree") or "")
        if not state.get("worktree") or not worktree.is_dir() or same_repo(worktree, repo):
            continue        # a run working in the repository itself holds no diff of its own
        found.append({"run": run_dir.name, "worktree": worktree, "base": state["base_sha"],
                      "started": state.get("started_at") or 0})
    return sorted(found, key=lambda each: (each["started"], each["run"]))


def tree(worktree):
    """The checkout's tree as it stands, uncommitted edits and untracked files included,
    written to the repository's object store through an index of its own: the checkout's
    index and files are never touched."""
    with tempfile.NamedTemporaryFile(dir=config.TMP, prefix="lease-index-") as index:
        env = {**os.environ, "GIT_INDEX_FILE": index.name}
        git(worktree, "read-tree", "HEAD", env=env)
        git(worktree, "add", "-A", env=env)
        return git(worktree, "write-tree", env=env)


def collide(repo, older, younger):
    """The paths two runs' trees cannot be merged on, over the merge base of the bases they
    were cut from: git's own conflict rule, run in memory.  Empty when they merge."""
    base = git(repo, "merge-base", older["base"], younger["base"])
    done = subprocess.run(["git", "-C", str(repo), "merge-tree", "--write-tree", "--name-only",
                           f"--merge-base={base}", tree(older["worktree"]),
                           tree(younger["worktree"])], capture_output=True, text=True)
    if done.returncode == 0:
        return []
    if done.returncode != 1:
        raise config.Error(f"git merge-tree in {repo}: {done.stderr.strip() or done.stdout.strip()}")
    # the merged tree's id, then one conflicted path per line, a blank line, git's messages
    return sorted(set(done.stdout.split("\n\n", 1)[0].splitlines()[1:]))


def scan(repo, log=lambda _: None, now=None):
    """One repository's pass: each younger run that collides with an older one is written
    down as waiting on the oldest such holder, with the paths and since when; the rest of
    the record is cleared.  Returns the record."""
    now = time.time() if now is None else now
    before = read(repo)
    runs = live(repo)
    waits = {}
    for at, younger in enumerate(runs):
        for older in runs[:at]:
            files = collide(repo, older, younger)
            if not files:
                continue
            kept = before.get(younger["run"]) or {}
            since = kept.get("since") if kept.get("waits_on") == older["run"] else None
            waits[younger["run"]] = {"waits_on": older["run"], "files": files,
                                     "since": since if isinstance(since, (int, float)) else now}
            log(f"collision: {younger['run']} and {older['run']} change the same lines of "
                f"{', '.join(files)}; the younger would wait")
            break
    if waits or before:
        write(repo, waits)
    return waits


def scan_all(log=lambda _: None, now=None):
    """The tick's pass: every repository a live run works in, scanned once."""
    repos = []
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        repo = (state or {}).get("repo")
        if repo and not any(same_repo(repo, seen) for seen in repos):
            repos.append(repo)
    for repo in repos:
        if Path(repo).is_dir():
            scan(repo, log, now)
