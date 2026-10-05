"""A run's worktree and local branch: whether they may go, and taking them."""

import os
import shutil
import subprocess
from pathlib import Path

from . import config, retention, run
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
    return isinstance(state, dict) and state.get("state") in run.ENDED and pid_gone(state)


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
    under ~/code, and the branch is the only thing that goes.
    """
    if not isinstance(branch, str) or not branch.startswith("ak/"):
        return
    if not run.git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        return
    try:
        code, out = run.git_out(repo, "branch", "-D", branch)
    except run.Stopped as exc:
        log(f"WARN could not delete branch {branch}: {exc}")
        return
    if code != 0:
        log(f"WARN could not delete branch {branch}: {out}")


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
        return bool(run.needs_recovery(state) or run.failed_at_budget(state)
                    or (state.get("state") == "error" and state.get("own_pr_round_pending"))
                    or run.failed_in_integration(state, run_dir)
                    or run.judged_in_integration(state, run_dir))
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
    if state.get("state") in ("fail", "error", "blocked", "stopped"):
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
    if not provably_final(state):
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
    unless a resume can still take it, or its ending kept it for the seat
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
    if state.get("merged") or state.get("state") == "not_needed":
        drop_checkout(state, log, keep_branch=False)
        return
    if (state.get("state") in ("fail", "error", "blocked", "stopped")
            and run.already_handed_back(state) and not resume_holds_tree(state, run_dir)
            and not state.get("checkout_kept")):
        drop_checkout(state, log)


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
        cmd = run.declared(wt, "cleanup")
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


def stop_checkout(state, log, keep_branch=False):
    """Remove a stopped run's worktree, and its local branch unless kept.

    Taken worktree first -- the branch is checked out there -- then the branch
    itself.  A branch already gone is not a failure worth warning about: the line
    reports it removed either way.  A loop that is still alive, and anything under
    ~/code, is not this run's to delete.

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
        return False
    if not pid_gone(state):
        log(f"WARN left worktree {wt}: the run is still going")
        return False
    run_id = state.get("run_id")
    if isinstance(run_id, str) and run_id:
        run_repo_cleanup(wt, config.RUNS / run_id)
    try:
        code, out = run.git_out(repo, "worktree", "remove", "--force", str(wt))
    except run.Stopped as exc:
        log(f"WARN could not remove worktree {wt}: {exc}")
        return False
    if code != 0 and wt.exists():
        log(f"WARN could not remove worktree {wt}: {out}")
        return False
    run.git(repo, "worktree", "prune", check=False)
    if not keep_branch:
        drop_local_branch(repo, branch, log)
    return True
