"""Restart legacy parks and keep old loops' scan calls harmless.

Their stopped records still wait for the older run to land, end or stand still;
then the tick starts their tasks again. New builds meet main before review.
"""

import shutil

from . import config, gitcall, transitions, turns
from . import record as run_record


# Old loops import scan_safely at commit and scan_all on a tick, so keep these entry points
# until those loops end: updating ak must not break an ongoing build.
def scan_safely(repo, log=lambda _: None, now=None):
    pass


def scan_all(log=lambda _: None, now=None):
    pass


# A stable identity keeps temporary suite commits of the same tree and parents identical.
STAMP = {"GIT_AUTHOR_NAME": "ak", "GIT_AUTHOR_EMAIL": "ak@localhost",
         "GIT_COMMITTER_NAME": "ak", "GIT_COMMITTER_EMAIL": "ak@localhost",
         "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}


# what a going run can wait on that ak does not move: an expired login, a stall only a resume
# ends, a spent provider window that may take days
STILL = ("waiting_login", "stalled", "exhausted")


def holds(state, now=None):
    """Whether a legacy parked run still waits on this holder: going and moved by ak,
    rather than waiting on a person or a provider window (`STILL`)."""
    return transitions.going(state, now=now) and state.get("state") not in STILL


def parked(state):
    """Whether a legacy parked run is still awaiting its restart."""
    return (state.get("state") == "stopped" and isinstance(state.get("lease_wait"), dict)
            and not state.get("lease_restarted"))


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
    """The tick's pass: a legacy run stopped waiting on a holder is started again once the
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
