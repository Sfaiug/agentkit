"""Collisions between the live runs of one repository: the tick's scan, and what it enforces.

A run's lease is its own diff against where its checkout meets the base it was cut from (a
`from:` run's branch may predate that base), uncommitted edits included as a commit would take them (`gitcall.committable_paths`; what its checks generated is written
down by the run and left out); no model declares, renews or releases anything.  Each tick, every pair of live runs of a repository is merged in memory (`git
merge-tree --write-tree`, git's own conflict rule), each run's own diff brought onto the
newer of their two bases first with main's side kept where the run clashes with it, so
main's movement between the bases is nobody's diff and a run's conflict with main is not
one with its neighbour.  A pair with a conflict outside `*.md` is written down on the younger run,
by the start of its first attempt (`transitions.first_started`: a restart keeps it), as waiting
on the older (wait-die: the older never waits on the younger, so no cycle can form).  A younger run still before its review -- its executor turn, or ak's
commit step, which runs this scan itself -- is stopped there with its branch kept, waiting
on the holder (`park`): what it built cannot land as it is.  Once the holder has landed or is
over, the tick starts its task again on the newest base (`restart`); until then the stopped
run is `parked`: going, so its seat is working and a wait on it follows the restart, and
stoppable, so its owner's stop or its seat's close calls the restart off.  A younger run past
that point, a pull request's review (its work is built already, so a park would only delay it,
and the landing line fixes its conflict), a job's task, a red target's repair and a suite's
split are only written down: the lander orders their landings.  The record under
`~/.agentkit/state/leases/` holds the collisions as the last scan saw them.  A diff counts
only while its run holds its lines (`holds`: going, and not waiting on a person or a spent
provider window), is to land and its checkout is there; a record
whose pair no longer collides, or whose holder is gone, is cleared on the next scan.
Lines, never declared paths or whole files: declared paths are guesses, a hold on a whole file
stalls the files most changes share, and about 6% of
concurrent pairs touch the same lines (13 Oct 2026).
"""

import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from . import config, gitcall, history, transitions, turns
from . import record as run_record

DIR = "leases"


@functools.lru_cache(maxsize=256)
def home(path):
    """The main checkout a recorded path is of (`gitcall.main_checkout`, the one reading of a
    repository's identity): a run launched from inside a linked worktree records that
    worktree, and is of the repository it was added from.  Remembered for one scan."""
    try:
        return gitcall.main_checkout(Path(path)).resolve()
    except OSError:
        return Path(path)


def same_repo(a, b):
    """Whether two recorded checkouts are of one repository."""
    return bool(a) and bool(b) and home(str(a)) == home(str(b))


def path(repo):
    """The record of one repository's collisions, named by its main checkout."""
    key = hashlib.sha256(str(home(str(repo))).encode()).hexdigest()[:16]
    return config.STATE / DIR / f"{home(str(repo)).name}-{key}.json"


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


# what a going run can wait on that ak does not move: an expired login, a stall only a resume
# ends, a spent provider window that may take days
STILL = ("waiting_login", "stalled", "exhausted")


def holds(state, now=None):
    """Whether that run's diff holds its lines: going (`transitions.going`) and moved by ak
    itself, not waiting on a person or a provider window (`STILL`).  A younger run never waits
    on work nothing moves: once its holder stands still it starts again, and where the two
    still clash when both land, the landing line fixes it."""
    return transitions.going(state, now=now) and state.get("state") not in STILL


def live(repo):
    """The runs of that repository whose diffs count: holding their lines (`holds`), to land (a `--no-merge` run, a
    scratch one among them, keeps its work local and stands in nobody's way), cut from a base,
    with a checkout of their own that is still there; oldest first by start."""
    found = []
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        if (not state or state.get("no_merge") or not state.get("base_sha")
                or not holds(state) or state.get("lease_wait") or not same_repo(state.get("repo"), repo)):
            continue
        worktree = Path(state.get("worktree") or "")
        if (not state.get("worktree") or not worktree.is_dir()
                or worktree.resolve() == Path(state["repo"]).resolve()):
            continue        # a run working in the checkout it was launched from holds no diff of its own
        # its base is where its checkout meets the recorded one: a `from:` run's older branch
        # holds none of what main gained since it was cut, which is no change of the run's
        base = gitcall.git(worktree, "merge-base", "HEAD", state["base_sha"], check=False) or state["base_sha"]
        found.append({"run": run_dir.name, "worktree": worktree, "base": base,
                      "started": transitions.first_started(state),
                      "artifacts": state.get("artifacts") or []})
    return sorted(found, key=lambda each: (each["started"], each["run"]))


def before_review(state):
    """Whether the run is a build with nothing reviewed yet: no round with a verdict, and its
    loop in its executor turn or at ak's commit step, where what it built can still be set
    aside.  A pull request's review builds nothing to set aside, a job's task is its job's to
    settle, as `transitions.parkable_conflict` leaves it, and a red target's repair and a suite's split
    are waited on: stopped, either would hold its line (`handback.repair_open`) or its suite
    (`handback.open_followup`) for good.  A run parked already is not: a second scan that
    saw it live would move its wait and the moment of its stop (`parked_at`)."""
    if state.get("review_pr") or parked(state):
        return False
    return (not any(state.get(key) for key in ("job_id", "repair", "split_suite", "round_summaries"))
            and state.get("step") in (None, "executor", "done-when"))


def parked(state):
    """Whether that run is stopped waiting on an older run's change (`park`) and its task is
    not started again yet (`restart`)."""
    return (state.get("state") == "stopped" and isinstance(state.get("lease_wait"), dict)
            and not state.get("lease_restarted"))


def park(entry, holder, files, now):
    """Stop that run before its review, its branch and checkout kept, waiting on the holder:
    the record says what it waits on (`lease_wait`), for `restart` to read.  Decided on the
    record read under the stop's lock, as the scan takes a while: the state as stopped, or
    None where the run had ended or reached its review meanwhile.  A run this call stopped
    has the moment stamped on its history row (`parked_at`), what the scoreboard counts."""
    from . import stop
    why = f"waits on {holder}: both change {', '.join(files)}"
    wait = {"on": holder, "files": files, "since": now}
    stopped = stop.end(config.RUNS / entry["run"], keep=True, why=why, only_if=before_review,
                       extra={"lease_wait": wait})
    if stopped is not None and stopped.get("lease_wait") == wait:
        history.update_run(entry["run"], parked_at=now)
    return stopped


# One identity and moment for every commit the scan writes: a tree compared before hashes to
# the same commit again, so an unchanged pair writes nothing into the repository
STAMP = {"GIT_AUTHOR_NAME": "ak", "GIT_AUTHOR_EMAIL": "ak@localhost",
         "GIT_COMMITTER_NAME": "ak", "GIT_COMMITTER_EMAIL": "ak@localhost",
         "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}


def tree(worktree, artifacts, log=lambda _: None):
    """The checkout's tree as it stands: HEAD with the uncommitted paths a commit would take
    (`gitcall.committable_paths`: never test sandboxes, dependency trees, run locks, what
    `.gitignore` names or what the run's checks generated, its `artifacts`), read and written
    through an index of its own in the repository's object store: the checkout's own index is
    neither read, locked nor rewritten (`git diff` refreshes and rewrites the index it reads,
    optional locks or not), and its files are never touched.  A file that vanished since it
    was listed, or one git cannot read, is left out, the latter said once: neither costs a
    pair its record."""
    from . import run
    with tempfile.NamedTemporaryFile(dir=config.TMP, prefix="lease-index-") as index:
        env = {**os.environ, "GIT_INDEX_FILE": index.name}
        run.git(worktree, "read-tree", "HEAD", env=env)
        real, _ = gitcall.committable_paths(worktree, artifacts, env=env)
        if real:
            staged(worktree, real, env, log)
        return run.git(worktree, "write-tree", env=env)


def staged(worktree, paths, env, log):
    """`paths` staged in the index `env` names (HEAD's, `tree` read it so): a path gone from
    disk that HEAD has is a deletion a commit would take, one HEAD has not vanished since it
    was listed (a working executor's temp file) and is left out; the rest added in one call,
    or, when that still fails, one by one, so a file git cannot read costs only itself, said
    once.  Decided by what is on disk, what the index holds and git's exit, never by its
    words, which it says in the host's language."""
    from . import run
    present = [path for path in paths if os.path.lexists(worktree / path)]
    tracked = set(run.git(worktree, "ls-files", "-z", env=env).split("\0"))
    deleted = [path for path in paths if path not in present and path in tracked]
    if deleted:
        run.git(worktree, "update-index", "--force-remove", "--", *deleted, env=env)
    try:
        if present:
            run.git(worktree, "add", "--ignore-errors", "--", *present, env=env)
        return
    except run.Stopped:
        raise
    except config.Error:
        pass
    unreadable = []
    for path in present:
        if not os.path.lexists(worktree / path):
            continue
        try:
            run.git(worktree, "add", "--ignore-errors", "--", path, env=env)
        except run.Stopped:
            raise
        except config.Error as exc:
            unreadable.append(str(exc))
    if unreadable:
        log(f"WARN lease scan: left unreadable paths of {worktree} out: {unreadable[0]}")


def merged(repo, base, ours, theirs, ours_wins=False):
    """(the merged tree, the paths that could not be merged) of two trees over the commit
    `base`, in memory: each tree is held by a commit on `base` (`STAMP`ed, so the same tree
    is the same commit) for `git merge-tree`, which takes commits on every git ak runs on
    (bare trees only from 2.45) and finds their base itself.  With `ours_wins` a hunk the two
    sides clash on is `ours` (`favour_ours`), and nothing is left unmerged."""
    from . import run
    env = {**os.environ, **STAMP}
    sides = [run.git(repo, "commit-tree", each, "-p", base, "-m", "lease", env=env)
             for each in (ours, theirs)]
    code, out = run.git_out(repo, "merge-tree", "--write-tree", "--name-only", "-z", *sides)
    if code not in (0, 1):
        raise config.Error(f"git merge-tree in {repo}: {out}")
    # the merged tree's id, then each conflicted path raw and NUL-ended (never quoted), an
    # empty field, then git's messages
    parts = out.split("\0")
    tree, clashes = parts[0], (sorted(set(parts[1:parts.index("", 1)])) if code == 1 else [])
    if ours_wins and clashes:
        return favour_ours(repo, base, ours, theirs, tree, clashes), []
    return tree, clashes


def entry(repo, ref, path):
    """(mode, blob) of the file at `path` in `ref`'s tree, or None."""
    from . import run
    for line in run.git(repo, "ls-tree", "-z", ref, "--", path).split("\0"):
        meta, _, name = line.partition("\t")
        if name == path and meta.split()[1] == "blob":
            return meta.split()[0], meta.split()[2]
    return None


def favour_ours(repo, base, ours, theirs, tree, clashes):
    """`tree`, the merge of the trees `ours` and `theirs` over the commit `base`, with each
    clashing path settled on `ours`' side hunk by hunk: `git merge-file --ours`, the
    three-way merge every git has (`merge-tree -X ours` is git 2.43's, and ak runs on 2.39).
    A path one side has not is as `ours` has it, and so is one `merge-file` cannot merge."""
    from . import run
    with tempfile.NamedTemporaryFile(dir=config.TMP, prefix="lease-index-") as index, \
            tempfile.TemporaryDirectory(dir=config.TMP, prefix="lease-merge-") as work:
        env = {**os.environ, "GIT_INDEX_FILE": index.name}
        run.git(repo, "read-tree", tree, env=env)
        for path in clashes:
            mine, old, other = (entry(repo, ref, path) for ref in (ours, base, theirs))
            if mine is None and other is None:
                continue
            if mine and other:
                files = []
                for n, side in enumerate((mine, old, other)):
                    target = Path(work) / str(n)
                    target.write_bytes(gitcall.git_bytes(repo, "cat-file", "blob", side[1])
                                       .encode("utf-8", "surrogateescape") if side else b"")
                    files.append(str(target))
                if run.git_out(repo, "merge-file", "--ours", *files)[0] == 0:
                    mine = (mine[0], run.git(repo, "hash-object", "-w", "--", files[0]))
            if mine:
                run.git(repo, "update-index", "--add", "--cacheinfo", f"{mine[0]},{mine[1]},{path}", env=env)
            else:
                run.git(repo, "update-index", "--force-remove", "--", path, env=env)
        return run.git(repo, "write-tree", env=env)


def collide(repo, older, younger, trees):
    """The paths the younger run's own diff cannot be merged with the older's: git's own
    conflict rule, run in memory, each diff against the base its run was cut from (`trees`
    holds each run's tree by its name).  With bases that differ, the run on the older base
    has its change brought onto the newer base first, main's side kept at the hunks where it
    clashes -- that run's conflict with main, not with its neighbour -- and the rest of its
    diff compared.  Runs cut from bases that never met (a `base:` branch and main) collide
    with nobody here: there is no one line of history to lay both diffs on.  Empty when they
    merge."""
    from . import run
    trees = {"older": trees[older["run"]], "younger": trees[younger["run"]]}
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


def diff_paths(repo, base, tree):
    """(the files a run's diff changes, a rename as its two; the directories above them; the
    directories it removed, as moving one does), for `may_clash`."""
    from . import run
    words = run.git(repo, "diff-tree", "-r", "-t", "-z", "--no-renames", base, tree).split("\0")
    # each entry is ":<old mode> <new mode> <old id> <new id> <status>", then its path
    entries = [(meta[1:].split()[:2], path) for meta, path in zip(words[::2], words[1::2])]
    files = [Path(path) for modes, path in entries if "040000" not in modes]
    return ({str(path) for path in files},
            {str(parent) for path in files for parent in path.parents} - {"."},
            {path for modes, path in entries if modes == ["040000", "000000"]})


def may_clash(repo, older, younger, diffs):
    """Whether `collide` has anything to decide for the pair (`diffs` holds each run's
    `diff_paths`), as most pairs of 64 live runs have not: a file both change, a file where the
    other has a directory, or a directory one removed, perhaps moved, the other changes in; on
    bases that differ, also a rename on main between them, or a directory either removed, which
    takes along what main added to it: either carries the diff `collide` brings onto the newer
    base to paths that diff never changed."""
    one, other = diffs[older["run"]], diffs[younger["run"]]
    return bool(one[0] & (other[0] | other[1]) or other[0] & one[1] or one[2] & other[1]
                or other[2] & one[1] or older["base"] != younger["base"]
                and (one[2] or other[2] or renamed_between(repo, older["base"], younger["base"])))


@functools.lru_cache(maxsize=1024)      # commits never change
def renamed_between(repo, base, other):
    """Whether main renamed a file between two bases: `collide` follows it, so diffs of
    different paths may meet.  No rename limit (`-l0`): a merge's own (`merge.renameLimit`)
    may find more than `diff.renameLimit` lets a diff, and either may change between scans."""
    from . import run
    return bool(run.git(repo, "diff-tree", "-r", "-M", "-l0", "--name-only", "--diff-filter=R",
                        base, other))


def scan(repo, log=lambda _: None, now=None):
    """One repository's pass: each younger run that collides with an older one is written
    down as waiting on the oldest such holder, with the paths and since when; the rest of
    the record is cleared.  A holder counts only while its record, read again, says it is
    going: one this scan parked, or one that ended while it ran, holds no diff.  Returns the
    record."""
    now = time.time() if now is None else now
    home.cache_clear()          # repository identity is read afresh each scan
    before = read(repo)
    runs = live(repo)
    trees = {each["run"]: tree(each["worktree"], each["artifacts"], log) for each in runs}   # each read once
    diffs = {each["run"]: diff_paths(repo, each["base"], trees[each["run"]]) for each in runs}
    waits = {}
    for at, younger in enumerate(runs):
        for older in runs[:at]:
            files = collide(repo, older, younger, trees) if may_clash(repo, older, younger, diffs) else []
            # Markdown-only conflicts can be settled at landing without rebuilding.
            if not files or all(path.endswith(".md") for path in files):
                continue
            holder = run_record.read_state(config.RUNS / older["run"]) or {}
            if not holds(holder) or parked(holder):
                continue        # one this scan parked, or that ended, holds no diff
            kept = before.get(younger["run"]) or {}
            since = kept.get("since") if kept.get("waits_on") == older["run"] else None
            waits[younger["run"]] = {"waits_on": older["run"], "files": files,
                                     "since": since if isinstance(since, (int, float)) else now}
            stopped = park(younger, older["run"], files, now)
            log(f"collision: {younger['run']} and {older['run']} change the same lines of "
                f"{', '.join(files)}; the younger "
                + ("is stopped, its branch kept, to start again once the older has landed "
                   "or is over" if stopped else "is only written down"))
            break
    if waits or before:
        write(repo, waits)
    return waits


def scan_all(log=lambda _: None, now=None):
    """The tick's pass: every repository a live run works in, scanned once."""
    home.cache_clear()
    repos = []
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        repo = (state or {}).get("repo")
        if repo and not any(same_repo(repo, seen) for seen in repos):
            repos.append(repo)
    for repo in repos:
        if Path(repo).is_dir():
            scan_safely(repo, log, now)


def scan_safely(repo, log=lambda _: None, now=None):
    """`scan`, a failure said and nothing more: it belongs to no one run (a checkout read
    after its run ended, say), so it stops neither the tick's next repository nor the commit
    step of the run that ran it."""
    try:
        scan(repo, log, now)
    except (config.Error, OSError) as exc:
        log(f"WARN lease scan of {repo} did not finish: {exc}")


# what a fix run's receipt carries that its gates read: it rides into its restart
CARRIED = ("followup", "base_proof")


def task_naming(run_dir, directory, repo, landed=False):
    """The stopped run's task, started again in that directory: its front matter naming `repo`,
    absolute -- started again by the tick, a task naming none, or a relative one, would be
    resolved in the tick's directory -- and the new run where it names the stopped one (a fix
    run's check, the regression script it may write and the run its search leaves out,
    `handback.start_followups`).  With `landed`, its `from:` branch is on its base already
    (`landed_with`), so it starts from there: built on the branch, its change would count the
    landed lines again, from where the branch left a base it can no longer merge."""
    from . import task
    pairs, body = task.front_matter(run_dir / "task.md")
    drop = {"repo", *(("from",) if landed else ())}
    return ("---\n" + "".join(f"{key}: {value}\n" for key, value in pairs if key not in drop)
            + f"repo: {repo}\n---\n" + body.replace(run_dir.name, directory.name))


def landed_with(state, holder):
    """Whether the `from:` branch of `state`, a run stopped waiting on `holder`, holds nothing
    beyond what `holder` landed on the base `state` builds from: `holder` merged into that base,
    and the branch's tip, the local one a build cuts from (origin's once that is gone), is
    `holder`'s landed head or behind it.  A branch neither has, or one moved on since, is not
    landed."""
    from . import watch
    branch, head = state.get("from"), holder and holder.get("merged") and holder.get("head_sha")
    if not (branch and head and state.get("repo") and state.get("base")
            and watch.after_merge_target(holder) == state["base"].removeprefix("origin/")):
        return False
    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        tip = gitcall.git(state["repo"], "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if tip:
            return gitcall.git_out(state["repo"], "merge-base", "--is-ancestor", tip.strip(), head)[0] == 0
    return False


def restart(log=print, now=None):
    """The tick's pass: a run stopped waiting on a holder (`park`) is started again once the
    holder has landed, is over (stopped or failed: its diff no longer counts) or stands still
    (`holds`: waiting on a person or a provider window) -- its task
    naming its repository and the new run (`task_naming`), with a fix run's regression folder and
    receipt (`CARRIED`), or a pull request's review as that review again (`--review-pr`), with
    the writer the stopped run captured at its launch (`own_pr`, `own_orchestrator` and its
    effort: the seat may run another model, or the same at another effort, by now), a new run
    of its seat (`run.launch_for_seat`).  The stopped
    run names the new one first, and the launch follows, under the lock a stop and a seat's
    close take (as `handback.start_followups` holds it), so a stop before it calls it off, a
    closed seat gets none, and none starts twice whatever the launch did."""
    from . import handback, run, watch
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        if not state or not parked(state) or not isinstance(state["lease_wait"].get("on"), str):
            continue
        wait = state["lease_wait"]
        holder_dir = config.RUNS / wait["on"]
        holder = run_record.read_state(holder_dir) if holder_dir.is_dir() else None
        if holder and holds(holder, now=now):
            continue
        why = f"{wait['on']} " + ("has landed" if holder and holder.get("merged") else
                                  f"stands still ({holder['state']})" if holder and transitions.going(holder, now=now)
                                  else "is over")
        try:            # asked before the claim: a git that never answered leaves it for the next tick
            landed = not state.get("review_pr") and landed_with(state, holder)
        except config.Error as exc:
            log(f"WARN {run_dir.name} waits a tick to start again: {exc}")
            continue
        directory = handback.free_run_dir(run_dir.name.split("-", 2)[-1])
        session = transitions.launched_session(state)
        with watch.state_lock():
            with run_record.recovery_lock(run_dir):
                state = run_record.read_state(run_dir) or {}
                if not parked(state) or (session and watch.seat_closed(session)):
                    continue
                with run_record.record(run_dir) as current:
                    current["lease_restarted"] = directory.name
            directory.mkdir(parents=True)
            review = state.get("review_pr")
            try:
                if review:
                    carried = {key: state.get(key) for key in
                               ("own_pr", "own_orchestrator", "own_orchestrator_effort")}
                    kept = f"the review of {review} starts again on the landed base"
                else:
                    (directory / "task.md").write_text(
                        task_naming(run_dir, directory, state.get("repo"), landed), encoding="utf-8")
                    if (run_dir / turns.REGRESSION.parent).is_dir():      # links kept as links
                        shutil.copytree(run_dir / turns.REGRESSION.parent,
                                        directory / turns.REGRESSION.parent, symlinks=True)
                    carried = {key: state[key] for key in CARRIED if key in state}
                    kept = f"its earlier attempt is kept on branch {state.get('branch')}" + (
                        f"; {state['from']} landed with it, so it starts from {state['base']}" if landed else "")
                (directory / "log.txt").touch()
                gitcall.logger(directory)(f"started again for {run_dir.name}: {why}; {kept}")
                run.launch_for_seat(
                    directory, state,
                    {"restarted": {"run": run_dir.name, "why": why}, "repo": state.get("repo"),
                     "first_started_at": transitions.first_started(state),
                     "first_queued_at": transitions.first_queued(state), **carried},
                    opts={**{key: value for key, value in (state.get("launch_opts") or {}).items()
                             if key != "--first"},
                          **({"--review-pr": review} if review else {}),
                          **({"--first": True} if state.get("first") else {})},
                    task_file=state.get("task_file"))
                log(f"{run_dir.name} started again as {directory.name}: {why}")
            except (config.Error, OSError, run_record.StopRequested) as exc:
                log(f"WARN {run_dir.name} could not start again as {directory.name}: {exc}")
