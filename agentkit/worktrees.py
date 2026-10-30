"""A run's worktree and local branch: whether they may go, and taking them."""

import os
import shutil
import subprocess
from pathlib import Path

from . import config, gitcall, handback, retention, run, transitions
from . import record as run_record


def under_code(path):
    """Whether `path` is ~/code or inside it. Uncertain paths count as protected.

    A checkout under ~/code is the owner's, never a run's to delete. A path that
    cannot be resolved is treated the same way: guessing would be the deletion.
    """
    try:
        path = Path(path).resolve()
        code = config.CODE.resolve()
    except (OSError, RuntimeError, ValueError, TypeError):
        return True
    return path == code or code in path.parents


def pid_gone(state):
    """Whether this run's loop is gone, or this process is that loop and is finished.

    The collector must not take a checkout out from under a live loop. The loop
    itself, removing its own tree on the way out, is not that case: its pid is
    still this process because it has not exited yet.
    """
    if not isinstance(state, dict):
        return False
    if state.get("pid") == os.getpid():
        return True
    try:
        return not retention.writer_active(state)
    except (TypeError, ValueError, OSError):
        return False


def provably_final(state):
    """A run whose state is final and whose loop is gone. Nothing here is still using the tree."""
    return isinstance(state, dict) and state.get("state") in run_record.ENDED and pid_gone(state)


def tree_released(state, with_run=False):
    """Whether `drop_checkout` may take this run's tree: the run provably final, or, for the
    collection taking the run directory whole (`with_run`), its loop gone, the collector's own
    rule having proven the run old (an interrupted run nobody resumed for a month)."""
    return provably_final(state) or (with_run and pid_gone(state))


def disposable_workspace(directory, state):
    """This run's own checkout, and not ~/code, the repo itself, or a symlink.

    It has to be the registered worktree under `~/.agentkit/wt/<id>`. A scratch run's
    workspace never is: its files are the delivery, and they go with the run directory.
    """
    value = state.get("worktree") if isinstance(state, dict) else None
    if not isinstance(value, str) or not value:
        return False
    wt = Path(value)
    if under_code(wt) or wt.is_symlink() or not wt.exists():
        return False
    run_id = directory.name
    repo = state.get("repo")
    if not isinstance(repo, str) or not repo or Path(repo) == wt:
        return False
    return wt == config.WT / run_id and retention.safe(wt) and retention.safe(Path(repo))


def drop_local_branch(repo, branch, log):
    """Delete the run's local `ak/` branch once nothing has it checked out.

    The remote branch is the PR's, when there is one, and is not this machine's
    to remove. A branch that is already gone is the outcome the caller wanted.
    The `ak/` prefix is the guard: the repo it lives in is the owner's checkout
    under ~/code, and the branch is the only thing that goes. False, with its WARN,
    when git kept the branch: a ref lock, a checkout elsewhere that holds it, or a
    git that never answered whether it is there.
    """
    if not isinstance(branch, str) or not branch.startswith("ak/"):
        return True
    try:
        if not run.git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                       check=False):
            return True
        code, out = run.git_out(repo, "branch", "-D", branch)
    except run.Stopped as exc:
        log(f"WARN could not delete branch {branch}: {exc}")
        return False
    if code != 0:
        log(f"WARN could not delete branch {branch}: {out}")
        return False
    return True


def resume_holds_tree(state, run_dir=None):
    """Whether a resume can still take this run, so its worktree stays for it.

    `ak run resume` refuses without the checkout; a hand-back that dropped the tree
    would break it, and the `continue:` line `ak run status` prints with it. This mirrors
    the resume's own gate -- recovery-pending work, a FAIL at its budget, an
    integration FAIL with or without a verdict -- so anything that cannot resume
    still drops as told. The seven-day clock still takes a held tree: the hold
    is time, not tenure.
    """
    if not isinstance(state, dict):
        return False
    try:
        return bool(transitions.needs_recovery(state) or transitions.failed_at_budget(state)
                    or (state.get("state") == "error" and state.get("own_pr_round_pending"))
                    or transitions.failed_in_integration(state, run_dir)
                    or transitions.judged_in_integration(state, run_dir))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _drop_told(state, log, run_dir=None):
    """Drop the checkout once the seat has been told, unless something still needs it.

    A pass that did not merge still needs its tree for `ak run merge`, and a FAIL
    a resume can still take needs its tree for that resume. The local branch stays
    in any case: a run that never pushed holds its only copy there, and only a
    merged run or a deliberate stop says otherwise.
    """
    if not isinstance(state, dict):
        return
    if state.get("merged") or state.get("state") == "not_needed":
        drop_checkout(state, log, keep_branch=False)
        return
    if state.get("state") in (*run_record.FAILED, "stopped"):
        if resume_holds_tree(state, run_dir) or state.get("checkout_kept"):
            return
        drop_checkout(state, log)


def drop_checkout(state, log=None, keep_branch=None, with_run=False):
    """Remove a finished run's checkout, and the local branch with a merged run.

    A merged run's work is carried by the remote, so its branch goes with the
    checkout; anything else keeps the branch -- a run that never pushed holds
    its only copy there -- unless the caller is the deliberate stop that takes
    everything. Never a live loop, never ~/code.

    A scratch run's workspace under `~/.agentkit/work/<id>` is what it delivered:
    only the collection that takes its run directory takes it (`with_run`), never an
    ending, a hand-back or a seat's stop, however old the run. A `--no-worktree`
    run worked in the repo itself and is left there. True when nothing asked to go
    is left, like the stop it funnels through.
    """
    log = log or (lambda _message: None)
    if not tree_released(state, with_run):
        return False
    if keep_branch is None:
        keep_branch = not state.get("merged")
    worktree = state.get("worktree")
    if not isinstance(worktree, str) or not worktree or under_code(worktree):
        return False
    wt = Path(worktree)
    if state.get("scratch"):
        run_id = state.get("run_id")
        if (isinstance(run_id, str) and wt == config.WORK / run_id and wt.is_dir()
                and not wt.is_symlink() and retention.safe(wt) and with_run):
            shutil.rmtree(wt)
            return True
        return False
    return stop_checkout(state, log, keep_branch=keep_branch)


def settle_run(state, run_dir, log=None):
    """The ending's housekeeping: its tabs close, and a delivered checkout goes.

    A merged run loses the checkout in this step, and its branch with it; a
    scratch run keeps its workspace, which is the delivery. A failed, blocked,
    stopped or error run loses the checkout once the seat has been told --
    unless a resume can still take it, or its work could not reach its branch
    (`checkout_kept`), which holds the checkout for the seven-day clock --
    and keeps its branch, the only copy a run that never
    pushed has. The run directory stays either way: `result.md` is what is read
    afterwards. Logs are left for the collector to gzip; readers of a run that
    just finished still have `log.txt`.
    """
    from . import browser
    log = log or (lambda _message: None)
    if not provably_final(state):
        return
    run_id = state.get("run_id") or Path(run_dir).name
    try:
        browser.close_owned(run=run_id)
    except (OSError, ValueError, TypeError):
        pass
    if state.get("merged") or state.get("state") == "not_needed" or handback.already_handed_back(state):
        _drop_told(state, log, run_dir)


def checkout_removable(state):
    """Whether a stop without `--keep` takes this run's checkout and branch with it.

    One decider for the removal and for the line that reports it: scratch keeps its
    files as the deliverable, a `--no-worktree` run worked in the repo itself, and a
    run that never got a worktree has nothing to take.  Anything else is the run's
    own checkout on its own branch.
    """
    if state.get("scratch") or not state.get("repo") or not state.get("worktree"):
        return False
    return Path(state["worktree"]) != Path(state["repo"])


def drop_unrecorded_checkout(repo, wt, branch, log):
    """Remove a checkout that never reached its record: the abort path's cleanup.

    A stop that lands after the worktree is cut but before its paths are saved
    removes nothing for lack of paths, and the launch's own save then aborts on
    the guard.  The worktree and branch it just made go here instead of orphaning
    a checkout nobody names.  Best effort, like the stop's own removal.
    """
    stop_checkout({"repo": str(repo), "worktree": str(wt), "branch": branch}, log)


CLEANUP_LIMIT = 600


def run_repo_cleanup(wt, run_dir):
    """A repository's declared `cleanup:` line, once, in the checkout before it goes.

    A repository already names its suite (`tests:`) and its switches (`features:`)
    in its AGENTS.md front matter; `cleanup:` names the shell line that undoes what
    its tools made outside the checkout -- a database, a cluster -- which no removal
    of the checkout itself can reach.  Every path that takes a run's checkout calls
    this first: a merge, `ak run stop`, `ak run clean`, and the collector.

    The line runs once -- `cleanup.log` going up is the mark, claimed atomically, so
    a removal that is retried never re-runs it -- with a ten-minute limit, its output
    beside the run's own log.  It gets the repo's secrets (~/.agentkit/env/<repo>.env)
    as the run's commands did, but only its own environment does: a stop, a sweep or
    the collector may be no run loop at all, and may clean several repositories.
    Whatever it does, the removal goes ahead and the run's record is untouched: a
    failing, missing or timed-out cleanup leaves one line in the run's log and nothing
    else.  No declaration, no checkout, or no run directory
    left to report into, and this is exactly as if it had never been called.
    """
    try:
        cmd = gitcall.declared(wt, "cleanup")
        if not cmd or not Path(wt).is_dir():
            return
        target = Path(run_dir) / "cleanup.log"
        try:
            fh = target.open("x")
        except FileExistsError:
            return                      # it ran once already; a retry removes, never re-runs
        with fh:
            fh.write(f"$ {cmd}\n")
            fh.flush()
            try:
                repo = (run_record.read_state(Path(run_dir)) or {}).get("repo")
                env = {**os.environ, **(config.repo_env(repo) if repo else {})}
                proc = subprocess.run(["bash", "-c", cmd], cwd=str(wt), stdout=fh,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      timeout=CLEANUP_LIMIT, env=env)
            except subprocess.TimeoutExpired:
                outcome = f"timed out after {CLEANUP_LIMIT // 60} minutes"
                fh.write(f"[{outcome}]\n")
            except (OSError, ValueError, subprocess.SubprocessError, config.Error) as exc:
                outcome = f"could not run: {exc}"
                fh.write(f"[{outcome}]\n")
            else:
                outcome = f"exited {proc.returncode}"
        run.note_in(Path(run_dir) / "log.txt")(f"repo cleanup: {cmd} {outcome} (see cleanup.log)")
    except Exception:
        return                          # a cleanup never stops a removal, whatever it meets


def preserve_checkout(state, wt, log):
    """Put the checkout's work on its branch, or hold it for the seven-day clock."""
    branch, artifacts = state.get("branch"), state.get("artifacts", ())
    try:
        if (gitcall.git(wt, "symbolic-ref", "--quiet", "HEAD") != f"refs/heads/{branch}"
                or gitcall.in_progress(wt, "rebase", "merge")):
            raise config.Error(f"the checkout is off {branch} or a rebase or merge is unfinished")
        paths, _junk = gitcall.committable_paths(wt, artifacts)
        if paths:
            # --only takes these paths, leaving staged junk and done-when artifacts out.
            # Hooks may rewrite or refuse work; saving it must do neither.
            gitcall.add_paths(wt, paths)
            paths = [f":(literal){path}" for path in paths]
            gitcall.git(wt, "-c", f"core.hooksPath={os.devnull}", "commit", "--only", "-m",
                        state.get("title") or "Save run work", "--", *paths)
        remaining, junk = gitcall.committable_paths(wt, artifacts)
        # Work staged differently from the working file may be invisible to diff HEAD.
        # It must stay too, unless the classifier already left it out as junk or an artifact.
        staged = gitcall.git(wt, "diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD").split("\0")
        if remaining or any(path and path not in junk and path not in artifacts for path in staged):
            raise config.Error("uncommitted work remains")
        if (gitcall.git(state["repo"], "rev-parse", "--verify", f"refs/heads/{branch}")
                != gitcall.git(wt, "rev-parse", "HEAD")):
            raise config.Error(f"the branch in {state['repo']} does not hold the checkout's commit")
    except (config.Error, OSError) as exc:
        state["checkout_kept"] = True
        run_id = state.get("run_id")
        if run_id:
            try:
                with run_record.record(config.RUNS / run_id) as current:
                    current["checkout_kept"] = True
            except OSError:
                pass
        log(f"WARN left worktree {wt}: could not save its work on {branch}: {exc}")
        return False
    return True


def stop_checkout(state, log, keep_branch=False):
    """Remove a run's worktree, and its local branch unless kept: the one way a checkout goes.

    A kept branch takes the checkout's committable work first, without repository hooks;
    a checkout whose work cannot reach that branch stays. The repo's `cleanup:` line runs
    while the checkout is still there; then `git worktree remove --force`; then what git left of
    the run's own tree under ~/.agentkit/wt -- a registration pruned, a repo cloned
    afresh -- and `git worktree prune` for what git still lists; the branch last, since
    it is checked out in the tree.  A branch already gone is not a failure worth warning
    about.  A loop that is still alive, and anything under ~/code, is not this run's to
    delete.  `ak run stop`, `ak run clean`, an ending and the collector all come here.

    True when nothing asked to go is left: the worktree is gone and the branch is
    gone or kept on purpose.  Anything still on disk -- a live loop, a checkout
    under ~/code, a git that said no -- is a False the caller reports honestly.
    """
    if not checkout_removable(state):
        return True
    repo, worktree, branch = state.get("repo"), state.get("worktree"), state.get("branch")
    wt = Path(worktree)
    # The worktree is what goes; git only runs in the repo, which lives under
    # ~/code on every real machine and is never itself the thing deleted.
    if under_code(wt):
        log(f"WARN left worktree {wt}: it is under {config.CODE}")
        return False
    if not pid_gone(state):
        log(f"WARN left worktree {wt}: the run is still going")
        return False
    run_id = state.get("run_id")
    if keep_branch and wt.exists() and not preserve_checkout(state, wt, log):
        return False
    if isinstance(run_id, str) and run_id:
        run_repo_cleanup(wt, config.RUNS / run_id)
    try:
        code, out = run.git_out(repo, "worktree", "remove", "--force", str(wt))
    except run.Stopped as exc:
        log(f"WARN could not remove worktree {wt}: {exc}")
        return False
    if code != 0 and wt.parent == config.WT and retention.safe(wt):
        shutil.rmtree(wt, ignore_errors=True)
    try:
        run.git(repo, "worktree", "prune", check=False)
    except run.Stopped as exc:
        log(f"WARN could not prune worktrees in {repo}: {exc}")
    if code != 0 and retention.present(wt):
        log(f"WARN could not remove worktree {wt}: {out}")
        return False
    return keep_branch or drop_local_branch(repo, branch, log)
