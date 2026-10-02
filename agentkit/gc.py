"""What collection may remove: the planner, sweep and their schedule.

Retention supplies the ownership proofs and deletion primitives; harness plugins
supply their temporary-folder rules.
"""

from contextlib import nullcontext
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from . import config, host, job as jobs, orch, proc_snapshot, record, retention, run
from .harness import load as harness_plugin

GC_INTERVAL = 86400             # background retention inspects old state at most once a day
GC_LOG_LIMIT = 1024 * 1024      # retain two bounded automatic-collection logs
GC_AGE = 7 * 86400              # failed/blocked/stopped checkouts, finished jobs, the status window
RUN_DIR_AGE = 30 * 86400        # a run directory whose session is gone is removed whole after this
TMP_BASE = Path("/tmp")         # seats and hand-run tools leave RAM-disk files nobody removes
VAR_TMP_BASE = Path("/var/tmp")  # a repository's TMPDIR is swept only directly under here
TMP_AGE = 2 * 86400             # a /tmp entry nothing changed for two days goes
DISK_LIMIT = 85                 # pressure shortens retention, never below one day


def disk_pressure():
    """(percent used, limit) when the disk holding ~/.agentkit is over the limit, else None.

    $AGENTKIT_GC_DISK_PERCENT moves the limit, which is how the smoke suite gets a full disk.
    """
    raw = os.environ.get("AGENTKIT_GC_DISK_PERCENT")
    try:
        limit = float(raw) if raw not in (None, "") else float(DISK_LIMIT)
    except ValueError:
        limit = float(DISK_LIMIT)
    try:
        usage_ = shutil.disk_usage(config.HOME if config.HOME.exists() else Path.home())
    except OSError:
        return None
    pct = 100.0 * usage_.used / usage_.total if usage_.total else 0.0
    return (pct, limit) if pct > limit else None


def collectible_worktree(directory, state):
    """Only this run's registered checkout, with its delivered commit and no unique files."""
    repo, value = state.get("repo"), state.get("worktree")
    if (not isinstance(repo, str) or not isinstance(value, str)
            or not repo or not value or Path(value) != config.WT / directory.name):
        return False
    wt = Path(value)
    if not retention.safe(Path(repo)) or not retention.safe(config.WT):
        return False
    if not retention.present(wt):
        return not wt.is_symlink()      # already cleaned; the history can still be compressed
    return retention.clean_worktree(Path(repo), wt, state, run.JUNK)


def seat_file_stale(path, now):
    """The seat a `<kind>-<name>.*` state file is named for, when that seat has no record and
    the file has not been written for a day; None for anything else."""
    owner = config.seat_file_owner(path)
    if not owner or not retention.safe(path) or not path.is_file():
        return None
    name = owner[1]
    try:
        if retention.present(config.session_path(name)):
            return None
    except config.Error:
        return None
    return name if retention.expired(path.lstat().st_mtime, now, retention.EPHEMERAL_AGE) else None


def stale_seat_files(now):
    """Every `<kind>-<name>.*` state file of a seat that is gone, a day after its last write.

    Gone is no record and no tmux session under the name, and no run of that name still
    going or still waiting to be handed back: the stop mark is what that hand-back reads.
    A seat tmux lost, or one `orch.sweep` retired, leaves these behind the way a stop no
    longer does, and 87 of them sat on the host for 36 seats that no longer existed.
    """
    if not retention.safe(config.STATE):
        return []
    try:
        held = {config.normalize_session(s["name"]) for s in orch.sessions()}
    except (config.Error, OSError, TypeError, ValueError, KeyError):
        return []                # a tmux that cannot be asked is no proof of absence
    for directory in retention.children(config.RUNS):
        state = retention.read_json(directory / "run.json")
        if state and (run.unfinished(state) or state.get("handback_pending")):
            try:
                held.add(run.launched_session(state))
            except config.Error:
                pass
    found = []
    for path in retention.children(config.STATE):
        name = seat_file_stale(path, now)
        if name and name not in held:
            found.append({"action": "remove", "kind": "seat-file", "path": str(path),
                          "why": f"seat {name} is gone"})
    return found


def compact_pid(path):
    """The wrapper's pid an `idle-compact/[<seat>-]<pid>.json` stamp is named for."""
    return path.name.rpartition(".")[0].rpartition("-")[2]


def compact_stamp_stale(path, now):
    """`idle-compact/[<seat>-]<pid>.json` of a wrapper that is gone, a day after its last write.

    tools/idle-compact.py removes its own on the way out; one killed outright cannot.
    """
    pid, ext = compact_pid(path), path.name.rpartition(".")[2]
    return (ext == "json" and pid.isdigit() and not host.alive(int(pid)) and retention.safe(path)
            and path.is_file()
            and retention.expired(path.lstat().st_mtime, now, retention.EPHEMERAL_AGE))


def stale_compact_stamps(now):
    return [{"action": "remove", "kind": "compact-stamp", "path": str(path),
             "why": f"its wrapper, pid {compact_pid(path)}, is gone"}
            for path in retention.children(config.STATE / "idle-compact")
            if compact_stamp_stale(path, now)]


def tmp_protected(name):
    """Dot entries, tmux sockets and systemd-private directories: never the collector's."""
    return (name.startswith(".") or name.startswith("tmux-")
            or name.startswith("systemd-private-"))


def tmp_hidden_processes(pids):
    """Inspect hidden handles with existing noninteractive sudo; never delete as root."""
    try:
        probe = subprocess.run(["sudo", "-n", "/usr/bin/python3", "-I", "-S", "-B",
                                proc_snapshot.__file__, *map(str, pids)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, timeout=10)
        if probe.returncode:
            return None
        inspected, hidden = json.loads(probe.stdout)
        return None if hidden else {int(pid): row for pid, row in inspected.items()}
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return None


def tmp_processes():
    """Paths and identities from every user's processes, or no proof /tmp is idle.

    Unlike exited pids and kernel threads, hidden foreign processes may hold our
    files. Ask the read-only inspector rather than ignoring them or giving up at pid 1.
    """
    try:
        table, hidden = proc_snapshot.collect(retention.process_dirs())
        if hidden:
            inspected = tmp_hidden_processes(hidden)
            if inspected is None:
                return None, None
            table.update(inspected)
        return {path for row in table.values() for path in row["paths"]}, table
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None, None


def tmp_listdir(path):
    """Sorted names in that directory, its atime unchanged when possible.

    /tmp itself is root's, so O_NOATIME refuses it; its own atime is evidence
    for nobody, and the entries' modification/change times determine age. Raises
    OSError when the directory cannot be listed at all.
    """
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if hasattr(os, "O_NOATIME"):
            flags |= os.O_NOATIME
        fd = os.open(path, flags)
    except OSError:
        return sorted(os.listdir(path))
    try:
        return sorted(os.listdir(fd))
    finally:
        os.close(fd)


def tmp_tree_newest(path):
    """The newest modification/change time, or None when it is not ours alone to take.

    Ours alone is every entry owned by this user, no link at the top, and no
    socket, fifo or device inside: links inside are unlinked, never traversed,
    and anything else is left for a person.  An unreadable entry is uncertainty,
    never evidence of age.
    """
    if not retention.safe(path):
        return None
    try:
        info = path.lstat()
        newest = max(info.st_mtime, info.st_ctime)
    except OSError:
        return None
    if not path.is_dir():
        return newest
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            names = tmp_listdir(current)
        except OSError:
            return None
        for name in names:
            child = current / name
            try:
                info = child.lstat()
            except OSError:
                return None
            if info.st_uid != os.getuid():
                return None
            if child.is_symlink():
                newest = max(newest, info.st_mtime, info.st_ctime)
                continue
            if not retention.safe(child):
                return None
            newest = max(newest, info.st_mtime, info.st_ctime)
            if child.is_dir():
                stack.append(child)
    return newest


def tmp_entry_stale(path, now, paths):
    """Why that top-level /tmp entry goes, or None when it stays.

    Ours, untouched for two days, and held by nobody: anything a running
    process holds stays where it is.
    """
    if tmp_protected(path.name) or retention.busy(path, paths):
        return None
    newest = tmp_tree_newest(path)
    if newest is None or not retention.expired(newest, now, TMP_AGE):
        return None
    return f"untouched for {int((now - newest) // 86400)} days"


def tmp_harness_rules(table):
    """Ask each harness once; a hook without a rule owns no temp entry."""
    roots = [config.REPO / "adapters"]
    if override := os.environ.get(config.ADAPTER_DIR_ENV):
        roots.append(Path(override).expanduser())
    names = dict.fromkeys(path.stem for root in roots for path in root.glob("*.sh"))
    return [rule for name in names if (rule := harness_plugin(name).tmp_rule(table))]


def tmp_top_stale(path, now, paths, rules):
    """The reason a top-level entry goes and nested candidates, from its owner or the default."""
    for rule in rules:
        answer = rule(path, now, paths, top=True)
        if answer is not None:
            return answer
    return tmp_entry_stale(path, now, paths), ()


def stale_tmp_entries(now, base=None):
    """Every stale top-level entry under that base and harness-owned session folder.

    The base is /tmp unless a repository pass names its own TMPDIR; the rule is
    the same either way. Tests replace TMP_BASE and retention.process_dirs with
    temporary directories. A session folder under an entry going whole is not
    planned twice.
    """
    base = TMP_BASE if base is None else base
    try:
        names = tmp_listdir(base)
    except OSError:
        return []
    if not names:
        return []
    paths, table = tmp_processes()
    if paths is None:
        return []
    rules = tmp_harness_rules(table)
    found, nested = [], []
    for name in names:
        if tmp_protected(name):
            continue
        path = base / name
        why, entries = tmp_top_stale(path, now, paths, rules)
        if why:
            found.append({"action": "remove", "kind": "tmp-entry", "path": str(path),
                          "why": why})
        else:
            nested.append(entries)
    for entries in nested:
        found.extend({**item, "tmp": True} for item in entries)
    return found


def repo_tmp_base(value):
    """That TMPDIR as a sweepable base, or None when gc must leave it alone.

    Only the plain case: a canonical path directly under /var/tmp.  Canonical
    means realpath spells it exactly as configured, so no symlink however short
    the chain and no `..`; directly under means its parent is the base itself,
    so /tmp, the base itself and anything nested deeper are all skipped.  The
    parent check runs first and reads nothing.
    """
    if Path(value).parent != VAR_TMP_BASE:
        return None
    try:
        if os.path.realpath(value) != value:
            return None
    except (OSError, ValueError):
        return None
    return Path(value)


def stale_repo_tmp_entries(now):
    """The /tmp rule for every repository TMPDIR under /var/tmp; the rest is named once.

    A repository's env file under ~/.agentkit/env/ may set TMPDIR, and every run
    of that repository writes its temporary files there.  A canonical path
    directly under /var/tmp is swept entry by entry through the same selection,
    planned as tmp-entry items; the directory itself stays.  Any other value is
    yielded once as a repo-tmp skip and never touched.
    """
    try:
        # tmp_listdir, not glob: the listing leaves the directory's atime alone.
        names = sorted(name for name in tmp_listdir(config.ENV) if name.endswith(".env"))
    except OSError:
        return
    seen = set()
    for name in names:
        try:
            value = config.repo_env(Path(name).stem).get("TMPDIR")
        except (config.Error, OSError):
            continue
        if value is None or value in seen:
            continue
        seen.add(value)
        base = repo_tmp_base(value)
        if base is None:
            yield {"action": "skip", "kind": "repo-tmp", "path": value,
                   "why": f"not a canonical path directly under {VAR_TMP_BASE}"}
            continue
        yield from stale_tmp_entries(now, base)


def leftovers():
    """{path: when reported} of checkouts gc could not take whole and will not try again."""
    return retention.read_json(config.STATE / "gc-leftovers.json") or {}


def stale_worktree(wt, now, paths, left):
    """The collector's item for a checkout under ~/.agentkit/wt nothing comes back for, or None.

    One whose run left no record, a day old: a smoke suite's, whose record went with its
    sandbox, or one whose run never wrote its `run.json` -- unless one is being written or
    somebody is in the run's directory.  A record that cannot be read is still a record.
    And a run that passed and whose delivery
    ended without a merge -- the merge failed, or none was asked for -- a week after it
    ended: its branch keeps the commits, and `from:` relaunches from it.  A pass whose
    delivery never got that far keeps its tree for the `ak run resume` that finishes it.
    Never one gc already reported as left behind, one somebody is in, or one `clearable`
    refuses.
    """
    if (str(wt) in left or wt.parent != config.WT or not clearable(wt)
            or retention.busy(wt, paths)):
        return None
    directory = config.RUNS / wt.name
    if not retention.present(directory / "run.json"):
        if (not record.writing(directory) and not retention.busy(directory, paths)
                and retention.expired(wt.lstat().st_mtime, now, retention.EPHEMERAL_AGE)):
            return {"action": "remove", "kind": "orphan-worktree", "path": str(wt),
                    "why": "no run record"}
        return None
    state = retention.read_json(directory / "run.json")
    finished = (state or {}).get("finished_at")
    if (state and state.get("run_id") == wt.name and state.get("worktree") == str(wt)
            and state.get("state") == "pass" and not state.get("merged")
            and (state.get("merge_note") or state.get("no_merge"))
            and not state.get("scratch") and run.provably_final(state)
            and retention.expired(finished, now, GC_AGE)
            and not record.writing(directory)):
        return {"action": "remove", "kind": "unmerged-worktree", "path": str(wt),
                "why": f"passed, never merged, ended {int((now - finished) // 86400)} days ago"}
    return None


def stale_worktrees(now, paths):
    if not retention.safe(config.WT):
        return []
    left = leftovers()
    return [item for wt in retention.children(config.WT)
            if (item := stale_worktree(wt, now, paths, left))]


def worktree_repo(wt):
    """The repository a checkout's `.git` pointer names, `<repo>/.git/worktrees/<name>`, or None."""
    try:
        prefix, sep, value = retention.read_bytes(wt / ".git").decode().strip().partition(": ")
    except (OSError, UnicodeDecodeError):
        return None
    gitdir = Path(value)
    if (prefix != "gitdir" or not sep or not gitdir.is_absolute()
            or gitdir.parent.name != "worktrees" or gitdir.parents[1].name != ".git"):
        return None
    return gitdir.parents[2]


def clear_tree(tree, report):
    """Everything of a tree this user can remove, then git's registration of it."""
    repo = worktree_repo(tree)
    retention.remove(tree, directory=True, ignore_errors=True)
    if repo is not None and repo != tree and repo.is_dir():
        try:
            run.git(repo, "worktree", "prune", check=False)
        except run.Stopped as exc:
            report(f"gc: {tree}: {exc}")


def unremovable(tree):
    """Whether a tree holds a directory this user cannot empty: another user's, or one shut
    to writing.  No retry changes either."""
    def shut(path):
        return not os.path.islink(path) and not os.access(path, os.R_OK | os.W_OK | os.X_OK)
    if shut(tree):
        return True
    return any(shut(os.path.join(root, name)) for root, dirs, _ in os.walk(tree) for name in dirs)


def clearable(tree):
    """Whether gc may empty that tree by hand: straight under ~/.agentkit/wt, work or tmp,
    this user's, reached through no link, and nowhere under ~/code."""
    return (tree.parent in (config.WT, config.WORK, config.TMP) and retention.safe(tree)
            and tree.is_dir() and not run.under_code(tree))


def left_behind(tree, report):
    """Whether a tree gc just tried to remove is still there.

    One that holds what this user cannot remove -- root's, from a container build inside
    a checkout -- gives up what is ours, is written down in gc-leftovers.json and is
    reported once; every planner passes it by from then on, since no daily retry changes
    it.  One still there for any other reason, or one `clearable` refuses, is left as it is.
    """
    if not retention.present(tree):
        return False
    if not clearable(tree) or not unremovable(tree):
        return True
    clear_tree(tree, report)
    if not retention.present(tree):
        return False
    left = {path: at for path, at in leftovers().items() if retention.present(Path(path))}
    if str(tree) not in left:
        left[str(tree)] = time.time()
        config._write_json(config.STATE / "gc-leftovers.json", left)
        report(f"gc: left {tree}: it holds files this user cannot remove; "
               f"`sudo rm -rf {tree}` takes them, and gc will not try again")
    return True


def own_tree(state):
    """A run's own checkout or scratch workspace, `~/.agentkit/wt/<id>` or
    `~/.agentkit/work/<id>`: the one tree of a run gc removes.  None for anything else."""
    run_id, value = state.get("run_id"), state.get("worktree")
    if not isinstance(run_id, str) or not run_id or not isinstance(value, str) or not value:
        return None
    tree = Path(value)
    return tree if tree in (config.WT / run_id, config.WORK / run_id) else None


def drop_tree(state, tree, report, keep_branch=None, with_run=False):
    """`drop_checkout` for gc: True when the tree is gone.

    What a removal it was allowed to make could not take is `left_behind`'s to judge, and
    an error it met stands unless the tree is now recorded there.  A refusal -- a loop still
    going, a tree that is not the run's own, one reached through a link or under ~/code --
    is never followed by a removal by hand.
    """
    allowed = (tree is not None and own_tree(state) == tree and run.provably_final(state)
               and clearable(tree)
               and (tree.parent == config.WORK and with_run if state.get("scratch")
                    else run.checkout_removable(state)))
    try:
        run.drop_checkout(state, report, keep_branch=keep_branch, with_run=with_run)
    except OSError:
        if not allowed or (left_behind(tree, report) and str(tree) not in leftovers()):
            raise
        return not retention.present(tree)
    if not allowed:
        return tree is None or not retention.present(tree)
    return not left_behind(tree, report)


def gc_candidates(now=None):
    """Incremental read-only planner shared by dry-run and collection."""
    now = time.time() if now is None else now
    pressure = disk_pressure()
    age = retention.PRESSURE_AGE if pressure else GC_AGE
    paths = retention.process_paths()
    left = leftovers()
    for directory in retention.children(config.RUNS):
        candidates = []
        state = retention.read_json(directory / "run.json")
        finished = (state or {}).get("finished_at")
        # A run of a throwaway repo under ~/.agentkit/tmp is the smoke suite's own: its
        # checkout is gone, it is on nobody's list and it names no project, so the whole
        # record goes once it is old enough -- that is how the menu stays free of them
        # without anybody tidying up by hand.
        if (state and state.get("run_id") == directory.name
                and retention.throwaway(state.get("repo"))
                and retention.expired(finished or state.get("started_at"), now, age)
                and not state.get("notification_pending") and not state.get("pending_inbox")
                and not state.get("handback_pending")
                and not retention.writer_active(state) and not retention.busy(directory, paths)
                and not record.writing(directory)
                and retention.safe(directory)):
            yield {"action": "remove", "kind": "throwaway-run", "path": str(directory),
                   "run": str(directory), "throwaway": True,
                   "state_identity": retention.fingerprint(directory / "run.json")}
            continue
        # One age for the directory itself. A seat that still exists keeps its
        # runs however old they are; the seat is what they belong to. Pending
        # hand-backs and cards are not consulted: with the session gone there is
        # no seat left to tell, and the directory goes with them untold.
        if (state and state.get("run_id") == directory.name and run.provably_final(state)
                and run_aged_out(directory, state, now)
                and not retention.writer_active(state) and not retention.busy(directory, paths)
                and not record.writing(directory) and retention.safe(directory)):
            try:
                owner = run.launched_session(state)
            except config.Error:
                owner = ""
                keep_for_seat = True
            else:
                keep_for_seat = run.session_lives(owner)
            if not keep_for_seat:
                yield {"action": "remove", "kind": "old-run", "path": str(directory),
                       "run": str(directory), "whole": True, "final": True,
                       "state_identity": retention.fingerprint(directory / "run.json")}
                continue
        # A failed, blocked, stopped or error checkout goes when the seat has been
        # told, or a week later, whichever is first -- unless a resume can still
        # take the run, which holds the checkout until the week is out. The seat
        # reads result.md. The branch stays: a run that never pushed holds its
        # only copy there.
        if (state and state.get("run_id") == directory.name
                and state.get("state") in ("fail", "error", "blocked", "stopped")
                and run.provably_final(state)
                and not retention.writer_active(state) and not retention.busy(directory, paths)
                and not record.writing(directory)
                and (retention.expired(finished, now, GC_AGE)
                     or (run.already_handed_back(state)
                         and not run.resume_holds_tree(state, directory)))
                and run.disposable_workspace(directory, state) and state["worktree"] not in left
                and not retention.busy(Path(state["worktree"]), paths)):
            yield {"action": "remove", "kind": "ended-worktree", "path": str(state["worktree"]),
                   "run": str(directory), "loose": True, "final": True,
                   "state_identity": retention.fingerprint(directory / "run.json")}
        if (not state or state.get("run_id") != directory.name or state.get("scratch")
                or state.get("state") != "pass" or not state.get("merged")
                or not run.provably_final(state)
                or state.get("notification_pending") or state.get("pending_inbox")
                or state.get("handback_pending")
                or retention.writer_active(state) or retention.busy(directory, paths)
                or record.writing(directory) or not collectible_worktree(directory, state)):
            continue
        wt = Path(state["worktree"])
        if retention.busy(wt, paths):
            continue
        identity = retention.fingerprint(directory / "run.json")
        if retention.present(wt) and str(wt) not in left:
            candidates.append({"action": "remove", "kind": "merged-worktree", "path": str(wt),
                               "run": str(directory), "final": True, "state_identity": identity})
        # Keep task, result, prompts, final answers and arbitrary attachments in place. Only
        # known generated streams are compressed, losslessly, beside their original paths.
        # A provably final run does not wait for those streams to go quiet: the first
        # pass gzips them. The fingerprint on the stream itself still has to match.
        snapshot = retention.tree(directory)
        for value, info in (snapshot or {}).items():
            path = Path(value)
            relative = path.relative_to(directory).as_posix()
            generated = re.fullmatch(r"log\.txt|round-[0-9]+/donewhen\.log|"
                                     r"round-[0-9]+/(?:executor|reviewer)(?:-[A-Za-z0-9_-]+)?/"
                                     r"(?:events\.jsonl|stderr\.log|stdout\.log)", relative)
            if (not generated
                    or not retention.safe(path) or not path.is_file()
                    or (retention.present(path.with_name(path.name + ".gz")) and not retention.same_archive(path))):
                continue
            candidates.append({"action": "compress", "kind": "merged-log", "path": str(path),
                               "run": str(directory), "final": True,
                               "state_identity": identity, "identity": info})
        yield from candidates
    if retention.safe(config.JOBS):
        for directory in retention.children(config.JOBS):
            job = jobs.read_job_safely(directory)
            finished = (job or {}).get("finished_at")
            if (not job or not isinstance(job.get("tasks"), list) or not job["tasks"]
                    or not all(task.get("state") in jobs.JOB_TERMINAL for task in job["tasks"])
                    or not retention.expired(finished, now, age)
                    or job.get("handback_pending")
                    or retention.writer_active(job) or retention.busy(directory, paths)
                    or retention.present(directory / "job.tmp")):
                continue
            yield {"action": "remove", "kind": "finished-job", "path": str(directory),
                   "job": str(directory),
                   "state_identity": jobs.job_fingerprint(directory)}
    yield from retention.ephemeral_plan(now, pressure, paths)
    yield from stale_worktrees(now, paths)
    yield from stale_seat_files(now)
    yield from stale_compact_stamps(now)
    yield from retention.harness_plan()
    yield from stale_tmp_entries(now)
    yield from stale_repo_tmp_entries(now)


def gc_plan(now=None):
    return list(gc_candidates(now))


def gc_due():
    last = retention.read_json(config.STATE / "gc.json") or {}
    at, now = last.get("started_at"), time.time()
    return not (type(at) in (int, float) and now - GC_INTERVAL < at <= now)


def schedule_gc(log):
    """Keep filesystem scans off the menu and health tick; concurrent workers share a lock."""
    # Do not repeatedly spawn a collector on platforms/filesystems where its read-only
    # primitives cannot work. This probe neither creates nor changes state.
    try:
        with retention.reading(config.HOME, directory=True):
            pass
    except OSError:
        return
    if not gc_due():
        return
    try:
        subprocess.Popen([sys.executable, "-m", "agentkit.retention", "collect"],
                         cwd=config.REPO, env=config.child_env(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        log(f"WARN could not start retention: {exc}")


def record_gc(message):
    """Bounded local audit trail, called only while collection holds the home lock."""
    path, previous = config.STATE / "gc.log", config.STATE / "gc.log.1"
    if any(retention.present(p) and not retention.safe(p) for p in (path, previous)):
        raise OSError("unsafe collection log")
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n".encode()
    if retention.present(path) and path.stat().st_size + len(line) > GC_LOG_LIMIT:
        path.replace(previous)
    with path.open("ab") as output:
        output.write(line)


def gc(report, automatic=False):
    """Apply the planner conservatively; changed, busy or unverifiable candidates stay put."""
    removed = []
    # Serialize automatic passes without creating a lock file (dry-run never takes this lock).
    try:
        with retention.reading(config.HOME, directory=True) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if automatic:
                stamp = config.STATE / "gc.json"
                if (not gc_due() or not retention.safe(config.STATE)
                        or any(retention.present(p) and not retention.safe(p)
                               for p in (stamp, stamp.with_suffix(".tmp")))):
                    return []
                caller = report
                def report(message):
                    record_gc(message)
                    caller(message)
                report("gc: automatic collection started")
                config._write_json(stamp, {"started_at": time.time()})
            tmp_inventory = None
            for item in gc_candidates():
                path = Path(item["path"])
                try:
                    # the planner's own proof once more, now: a seat launched under the name,
                    # a wrapper or a run back in the checkout since, and it all stays
                    if item["kind"] in ("seat-file", "compact-stamp"):
                        if not (seat_file_stale if item["kind"] == "seat-file"
                                else compact_stamp_stale)(path, time.time()):
                            continue
                        retention.remove(path)
                        done = True
                    elif item["kind"] in ("orphan-worktree", "unmerged-worktree"):
                        # A resume commits under the run's recovery lock: it lands before
                        # the second look, and the tree stays, or finds the tree gone.
                        directory = config.RUNS / path.name
                        recovery = directory / record.RECOVERY_LOCK
                        if retention.present(directory) and (
                                not retention.safe(directory) or recovery.is_symlink()
                                or (recovery.exists() and not retention.safe(recovery))):
                            continue
                        paths = retention.process_paths()   # before our own lock is open
                        with (record.recovery_lock(directory) if retention.present(directory)
                              else nullcontext()):
                            if not stale_worktree(path, time.time(), paths, leftovers()):
                                continue
                            if item["kind"] == "unmerged-worktree":
                                run.run_repo_cleanup(path, directory)
                            clear_tree(path, report)
                            done = not left_behind(path, report)
                    elif item["kind"] == "harness-entries":
                        done = retention.prune_harness(path)
                    elif item["kind"] == "tmp-entry" or item.get("tmp"):
                        # One fresh inventory for the batch, then recheck each tree's age.
                        if tmp_inventory is None:
                            paths, table = tmp_processes()
                            tmp_inventory = paths, tmp_harness_rules(table)
                        paths, rules = tmp_inventory
                        if item["kind"] == "tmp-entry":
                            ok = tmp_top_stale(path, time.time(), paths, rules)[0] is not None
                        else:
                            ok = any((answer := rule(path, time.time(), paths, top=False))
                                     is not None and answer[0] is not None for rule in rules)
                        if not ok or path.is_symlink():
                            continue
                        if path.is_dir():
                            retention.remove(path, directory=True)
                        else:
                            retention.remove(path)
                        done = not retention.present(path)
                    elif item["kind"] == "repo-tmp":
                        # A TMPDIR gc never sweeps: named once per pass, then left alone.
                        report(f"gc: {item['action']} {item['kind']} {path}{gc_why(item)}")
                        continue
                    elif item.get("throwaway") or item.get("whole"):
                        directory = Path(item["run"])
                        recovery = directory / record.RECOVERY_LOCK
                        if (not retention.safe(directory) or recovery.is_symlink()
                                or (recovery.exists() and not retention.safe(recovery))):
                            continue
                        paths = retention.process_paths()
                        with record.recovery_lock(directory):
                            state = retention.read_json(directory / "run.json")
                            # A provably final run does not wait for a second look at
                            # its fingerprint. A run that has since resumed still does.
                            same = (item.get("final") and run.provably_final(state or {})) or (
                                retention.fingerprint(directory / "run.json") == item["state_identity"])
                            if (not same or retention.writer_active(state or {})
                                    or retention.busy(directory, paths)):
                                continue
                            if item.get("whole"):
                                try:
                                    owner = run.launched_session(state or {})
                                except config.Error:
                                    continue
                                if run.session_lives(owner) or not run.provably_final(state or {}):
                                    continue
                                # The directory is going. Its checkout would otherwise
                                # stay behind with nothing pointing at it. A dirty tree
                                # goes with it: the run is final, its loop is gone,
                                # and at thirty days nobody is coming back for it. The
                                # branch goes too: the record that names it is forgotten
                                # in the same step, and a branch nothing points at only
                                # clutters the next run's name check. A tree already
                                # reported as left behind is not tried again.
                                tree = own_tree(state)
                                if tree is not None and str(tree) in leftovers():
                                    run.drop_local_branch(state.get("repo"), state.get("branch"),
                                                      report)
                                else:
                                    drop_tree(state, tree, report, keep_branch=False,
                                              with_run=True)
                            retention.remove(directory, directory=True)
                            done = not directory.exists()
                    elif "run" not in item and "job" not in item:
                        done = retention.remove_ephemeral(item)
                    elif "job" in item:
                        directory = Path(item["job"])
                        if not retention.safe(directory):
                            continue
                        paths = retention.process_paths()
                        with record.recovery_lock(directory):
                            job = jobs.read_job_safely(directory)
                            tasks = (job or {}).get("tasks")
                            if (jobs.job_fingerprint(directory) != item["state_identity"]
                                    or retention.writer_active(job or {})
                                    or retention.busy(directory, paths)
                                    or not isinstance(tasks, list) or not tasks
                                    or not all(task.get("state") in jobs.JOB_TERMINAL for task in tasks)):
                                continue
                            retention.remove(directory, directory=True)
                            done = not directory.exists()
                    else:
                        directory = Path(item["run"])
                        paths = retention.process_paths()
                        recovery = directory / record.RECOVERY_LOCK
                        if recovery.is_symlink() or (recovery.exists() and not retention.safe(recovery)):
                            continue
                        with record.recovery_lock(directory):
                            state = retention.read_json(directory / "run.json")
                            # Final and the loop gone: do not wait for the fingerprint
                            # taken while planning. Anything that has started again stays.
                            same = (item.get("final") and run.provably_final(state or {})) or (
                                retention.fingerprint(directory / "run.json") == item["state_identity"])
                            worktree = (state or {}).get("worktree")
                            if (not same or retention.writer_active(state or {})
                                    or retention.busy(directory, paths)
                                    or (isinstance(worktree, str) and retention.busy(Path(worktree), paths))
                                    or (not item.get("loose")
                                        and not collectible_worktree(directory, state))):
                                continue
                            if not run.provably_final(state or {}):
                                continue
                            if item["action"] == "compress":
                                done = retention.compress(path, item["identity"])
                            elif item.get("loose"):
                                if not (
                                        retention.expired(
                                            state.get("finished_at"), time.time(), GC_AGE)
                                        or (run.already_handed_back(state)
                                            and not run.resume_holds_tree(state, directory))):
                                    continue
                                done = drop_tree(state, path, report)
                            else:
                                run.run_repo_cleanup(path, directory)
                                try:
                                    code, _ = run.git_out(state["repo"], "worktree", "remove",
                                                      str(path))
                                except run.Stopped as exc:
                                    # a stop is not a verdict on the candidate: it stays put,
                                    # and the remedy is reported rather than raised past the pass
                                    report(f"gc: {item['kind']} {path} left in place: {exc}")
                                    continue
                                gone = not left_behind(path, report)
                                done = code == 0 and gone
                                if done:
                                    run.drop_local_branch(state.get("repo"), state.get("branch"), report)
                    if done:
                        removed.append(item["path"])
                        report(f"gc: {item['action']} {item['kind']} {path}{gc_why(item)}")
                except (OSError, ValueError, TypeError, AttributeError, KeyError, subprocess.TimeoutExpired) as exc:
                    report(f"gc: kept {path}: {exc}")
    except (OSError, BlockingIOError):
        pass                           # another tick owns collection, or ownership is uncertain
    return removed


def sweep_plan(now=None):
    """What `ak run gc` takes past the collector's proofs: every merged checkout, and
    every `smoke-*` a day old.  Read-only; the dry run prints it.

    The collector's merged-worktree candidate needs a clean tree and a registration git
    still lists.  A merged run whose tree holds an ignored build directory, or whose repo
    was cloned afresh, never qualifies, and 166 of them sat on the host that way.  A run
    that is `pass` and merged has delivered: its checkout goes, whatever it holds and
    whatever repository it came from, as long as it is this run's own registered path
    under ~/.agentkit/wt, its loop is gone and nobody is in it.  Never ~/code, never the
    repo itself, never a symlink.
    """
    now = time.time() if now is None else now
    paths = retention.process_paths()
    left = leftovers()
    found = []
    for directory in retention.children(config.RUNS):
        state = retention.read_json(directory / "run.json")
        if (not state or state.get("run_id") != directory.name or state.get("scratch")
                or state.get("state") != "pass" or not state.get("merged")
                or not run.provably_final(state) or record.writing(directory)):
            continue
        repo, worktree = state.get("repo"), state.get("worktree")
        if (not isinstance(repo, str) or not repo or not isinstance(worktree, str)
                or Path(worktree) != config.WT / directory.name or Path(repo) == Path(worktree)):
            continue
        wt = Path(worktree)
        if (run.under_code(wt) or not retention.present(wt) or not retention.safe(wt)
                or retention.busy(wt, paths) or str(wt) in left):
            continue
        found.append({"action": "remove", "kind": "merged-worktree", "path": str(wt),
                      "run": str(directory)})
    found.extend(item for item in retention.stale_sandboxes(now, paths)
                 if item["path"] not in left)
    return found


def tree_bytes(path):
    """What a tree occupies on disk, a link counted as a link: what removing it gives back."""
    total = 0
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


def size_words(count):
    """`16.0 GB`, `220.5 MB`: the space freed, the way `du -h` counts it."""
    for unit in ("B", "kB", "MB", "GB"):
        if count < 1024:
            break
        count /= 1024
    else:
        unit = "TB"
    return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"


def sweep_checkout(state, wt, report):
    """A merged checkout, registered or not: git first, then the directory, then prune.

    `git worktree remove --force` takes what git still lists, whatever the tree holds.
    A directory git no longer knows -- its registration pruned, its repo cloned afresh --
    is taken as a directory, and `git worktree prune` in the repo forgets whatever
    registration is left.  The local branch goes with a merged checkout, as everywhere.
    """
    repo = state["repo"]
    run_id = state.get("run_id")
    if isinstance(run_id, str) and run_id:
        run.run_repo_cleanup(wt, config.RUNS / run_id)
    run.git_out(repo, "worktree", "remove", "--force", str(wt))
    if retention.present(wt):
        retention.remove(wt, directory=True)
    if Path(repo).is_dir():
        run.git(repo, "worktree", "prune", check=False)
    run.drop_local_branch(repo, state.get("branch"), report)


def sweep(report):
    """Apply `sweep_plan` under the collector's lock: the items removed, `bytes` on each."""
    removed = []
    try:
        with retention.reading(config.HOME, directory=True) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for item in sweep_plan():
                path = Path(item["path"])
                size = tree_bytes(path)
                try:
                    if item["kind"] == "merged-worktree":
                        state = retention.read_json(Path(item["run"]) / "run.json") or {}
                        sweep_checkout(state, path, report)
                    else:
                        retention.remove(path, directory=True)
                except run.Stopped as exc:
                    # a stop is no verdict on the tree, and a record gone meanwhile is no
                    # removal made: neither is followed up by hand
                    report(f"gc: {item['kind']} {path}: {exc}")
                    continue
                except (KeyError, TypeError) as exc:
                    report(f"gc: kept {path}: {exc}")
                    continue
                except OSError as exc:
                    report(f"gc: kept {path}: {exc}")
                if left_behind(path, report):
                    continue
                removed.append({**item, "bytes": size})
                report(f"gc: {item['action']} {item['kind']} {path}")
    except (OSError, BlockingIOError):
        pass                           # another tick owns collection, or ownership is uncertain
    return removed


def gc_why(item):
    """`: <reason>` after an item's path, where the planner gave one."""
    return f": {item['why']}" if item.get("why") else ""


def cmd_gc(argv):
    if argv not in ([], ["--dry-run"]):
        raise config.Error("usage: ak run gc [--dry-run]")
    if argv:
        plan = sweep_plan()
        listed = {item["path"] for item in plan}
        plan += [item for item in gc_plan() if item["path"] not in listed]
        for item in plan:
            print(f"gc: would {item['action']} {item['kind']} {item['path']}{gc_why(item)}")
        if not plan:
            print("gc: no eligible artifacts")
        return 0
    # The sweep goes first, so every merged checkout and day-old sandbox `ak run gc` removes
    # is counted on the one line below; the collector's own pass then finds its logs to gzip.
    swept = sweep(print)
    removed = gc(print)
    if swept:
        trees = sum(item["kind"] == "merged-worktree" for item in swept)
        boxes = len(swept) - trees
        print(f"gc: removed {trees} merged worktree{'s' if trees != 1 else ''} and "
              f"{boxes} smoke sandbox{'es' if boxes != 1 else ''}, "
              f"{size_words(sum(item['bytes'] for item in swept))} freed")
    elif not removed:
        print("gc: no eligible artifacts")
    return 0


def run_aged_out(directory, state, now):
    """Whether this run directory is past the one age the collector uses for it.

    The clock is the run's own, newest of when it started and when it finished.
    A directory with neither falls back to its mtime, which is the only age a
    record that never wrote one still has.
    """
    stamps = []
    for key in ("finished_at", "started_at"):
        value = (state or {}).get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            stamps.append(value)
    when = max(stamps) if stamps else None
    if when is None:
        try:
            when = directory.stat().st_mtime
        except OSError:
            return False
    return when <= now - RUN_DIR_AGE
