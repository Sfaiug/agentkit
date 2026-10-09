"""Collisions between the live runs of one repository: the tick's scan, report-only.

A run's lease is its own diff against the base it was cut from, uncommitted edits included
as a commit would take them (`run.committable_paths`); no model declares, renews or releases
anything.  Each tick, every pair of live runs of a repository is merged in memory (`git
merge-tree --write-tree`, git's own conflict rule), each run's own diff brought onto the
newer of their two bases first with main's side kept where the run clashes with it, so
main's movement between the bases is nobody's diff and a run's conflict with main is not
one with its neighbour.  A pair that cannot merge is written down on the younger run,
by start, as waiting on the older (wait-die: the older never waits on the younger, so no
cycle can form).  Nothing is refused here: the record under `~/.agentkit/state/leases/`
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
import tempfile
import time

from . import config
from . import record as run_record

DIR = "leases"


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


# One identity and moment for every commit the scan writes: a tree compared before hashes to
# the same commit again, so an unchanged pair writes nothing into the repository
STAMP = {"GIT_AUTHOR_NAME": "ak", "GIT_AUTHOR_EMAIL": "ak@localhost",
         "GIT_COMMITTER_NAME": "ak", "GIT_COMMITTER_EMAIL": "ak@localhost",
         "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}


def tree(worktree, log=lambda _: None):
    """The checkout's tree as it stands: HEAD with the uncommitted paths a commit would take
    (`run.committable_paths`: never test sandboxes, dependency trees, run locks or what
    `.gitignore` names), written to the repository's object store through an index of its
    own, so the checkout's index and files are never touched.  A file git cannot read is
    left out and said once: one checkout's unreadable file costs no pair its record."""
    from . import run
    with tempfile.NamedTemporaryFile(dir=config.TMP, prefix="lease-index-") as index:
        env = {**os.environ, "GIT_INDEX_FILE": index.name}
        run.git(worktree, "read-tree", "HEAD", env=env)
        real, _ = run.committable_paths(worktree)
        if real:
            try:
                run.git(worktree, "add", "--ignore-errors", "--", *real, env=env)
            except run.Stopped:
                raise
            except config.Error as exc:
                log(f"WARN lease scan: left unreadable paths of {worktree} out: {exc}")
        return run.git(worktree, "write-tree", env=env)


def merged(repo, base, ours, theirs, ours_wins=False):
    """(the merged tree, the paths that could not be merged) of two trees over the commit
    `base`, in memory: each tree is held by a commit on `base` (`STAMP`ed, so the same tree
    is the same commit) for `git merge-tree`, which takes commits on every git ak runs on
    (bare trees only from 2.45) and finds their base itself.  With `ours_wins` a hunk the two
    sides clash on is `ours`, and nothing is left unmerged."""
    from . import run
    env = {**os.environ, **STAMP}
    sides = [run.git(repo, "commit-tree", each, "-p", base, "-m", "lease", env=env)
             for each in (ours, theirs)]
    code, out = run.git_out(repo, "merge-tree", "--write-tree", "--name-only",
                            *(["-X", "ours"] if ours_wins else []), *sides)
    if code not in (0, 1):
        raise config.Error(f"git merge-tree in {repo}: {out}")
    # the merged tree's id, then one conflicted path per line, a blank line, git's messages
    lines = out.split("\n\n", 1)[0].splitlines()
    return lines[0], (sorted(set(lines[1:])) if code == 1 else [])


def collide(repo, older, younger, log=lambda _: None):
    """The paths the younger run's own diff cannot be merged with the older's: git's own
    conflict rule, run in memory, each diff against the base its run was cut from.  With
    bases that differ, the run on the older base has its change brought onto the newer base
    first, main's side kept at the hunks where it clashes -- that run's conflict with main,
    not with its neighbour -- and the rest of its diff compared.  Runs cut from bases that
    never met (a `base:` branch and main) collide with nobody here: there is no one line of
    history to lay both diffs on.  Empty when they merge."""
    from . import run
    trees = {name: tree(each["worktree"], log) for name, each in (("older", older), ("younger", younger))}
    bases = {"older": older["base"], "younger": younger["base"]}
    base = older["base"]
    if bases["older"] != bases["younger"]:
        older_first = run.git_out(repo, "merge-base", "--is-ancestor", older["base"], younger["base"])[0] == 0
        if not older_first and run.git_out(repo, "merge-base", "--is-ancestor",
                                           younger["base"], older["base"])[0] != 0:
            return []
        behind, ahead = ("older", "younger") if older_first else ("younger", "older")
        base = bases[ahead]
        trees[behind], _ = merged(repo, bases[behind], run.git(repo, "rev-parse", f"{base}^{{tree}}"),
                                  trees[behind], ours_wins=True)
    return merged(repo, base, trees["older"], trees["younger"])[1]


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
            files = collide(repo, older, younger, log)
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
        if not Path(repo).is_dir():
            continue
        try:
            scan(repo, log, now)
        except config.Error as exc:
            log(f"WARN lease scan of {repo} did not finish: {exc}")   # the next repository still runs
