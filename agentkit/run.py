"""The review loop: executor -> done-when -> review, until PASS, then deliver.py's delivery.

The reviewer is another model where the workers allow one, else the executor's own:
a model tends to miss the mistakes it makes, so its own review is the last choice,
never a refusal.

The loop derives a review's verdict from its checked hand-in records.

`ak run --review-pr <url>` is the same reviewer with no executor: a PR checked out at
its head, judged against the repo and posted back as a GitHub review. The seat's own
PR merges on PASS with green checks; anyone else's asks the inbox. The seat's own PRs of
documents alone skip review and join the line like any passed review.
"""

import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path

from . import (box, command_help, config, gate, gc, gitcall, history, host, job as jobs,
               land as landing, orch, plan, record as run_record, status, stop, task as taskfile,
               turns, usage, watch, worker, worktrees)
from .deliver import (GITHUB_RETRIES, MERGE_METHODS, PICKUP_HELD, do_merge, end_on_dependency,
    finish_blocked, join_line, land, merge, merge_own_pr, own_pr_heads, pr_head,
    push_pr_branch, release_line)
from .deliver import (LANDING_COUNTS, PUSH_RIGHTS, checks, gh_json, github_body,
    push, require_review_pass, rights,
    text_only_pr, wait_checks)
from .roundloop import execute, final_check, integrate, review, rounds
from .roundloop import (Loop, note,
    restore_review_checkout, rules_check, verify_work)
from .handback import (announce, announce_safely, clear_delivery, join_session_project,
    launch_line, printed_at_launch, reap, record_result, redress_seat, settle_delivered_line, stamp_origin,
    start_followups, task_project, write_result)
from .staffing import (barred_refusal, best_pair, collect_usage, head_writers, next_executor,
    note_handover, pair_refusal, pick_models, ready_order, refuse_outside_group,
    refuse_unready, reviewer_order, run_workers, same_model, started_round)
from .transitions import (carried_lines, change_budget, change_on, replacement_refusal,
    change_reviewed, delivery, diff_lines, failed_at_budget, failed_in_integration,
    history_finish, history_start, integration_note, interrupt,
    invalidate_saved_pass, judged_in_integration, landing_line, launched_session, needs_recovery, over_lineage, park_error, park_exhausted, PR_PARTS,
    queued, report_config, review_pass, review_providers, round_budget, settled, stands_on_dependency)
from .prompts import (HANDOVER, done_when_block, fix_body, fixer_words, overridden_section,
    placed, plan_context, saved_findings, without_followups)
from .turns import (Blocked, Dead, Exhausted, Killed, NotNeeded, QuotaDry, _scope_units,
    answered, finished_answer, scope_is_real,
    shell_foreground_note, stop_run_tree, tail)
from .gitcall import (Stopped, TOOL_CAP, _RUN_CONTEXT, commit_identity, commit_leftovers,
    default_base, exclude_junk, fetch, git, git_out, log_is_stdout, logger, make_worktree, origin_default, repo_line, repo_rules, round_commands, run_depth, say,
    slugify, stopped, tool_env, tool_run, with_suite)

_PICKUP_START = None    # the installed agentkit this process started on, for in-flight pickup


def ignore_time_keys(run_dir, meta, log):
    """Warn once per retired key, including across preflight, launch and resume."""
    path = Path(run_dir) / "log.txt"
    logged = path.read_text(errors="replace") if path.exists() else ""
    for key in ("done_when_minutes", "turn_hours", "stall_minutes"):
        line = f"ignoring {key}: the loop watches for silence"
        if key in meta and line not in logged:
            log(line)


def task_repo(meta, task_path, task_file=None):
    """`repo:` if the task names one, else the git repository the `ak run` was invoked from,
    else the checkout its task folder is named for.

    `task_file` is the file the run was launched from, where `task_path` is the run's own
    copy of it: only the original stands in a task folder.

    A task file that names no repo is the common case: the orchestrator writes it under
    ~/.agentkit/tasks/<project>/, and launches it from that checkout or from a folder of
    checkouts such as ~/code.  None means there is no repository in this job at all -- `repo:
    none`, or a launch outside any checkout of a task filed under none -- and the run works in
    a scratch workspace instead.
    """
    if meta.get("repo"):
        if meta["repo"].lower() == "none":
            return None
        repo = repo_line(meta, task_path).resolve()
        if not (repo / ".git").exists():
            raise config.Error(f"{task_path}: repo {repo} is not a git repository")
        return repo
    code, out, err = tool_run(["git", "rev-parse", "--show-toplevel"])
    if stopped(code, err):
        # "no repository here" is an answer; a git that never gave one must not be read as it,
        # or the work asked for in a checkout would quietly run in a scratch workspace instead
        raise Stopped(f"git rev-parse --show-toplevel failed: {err.strip()}")
    if code != 0:
        checkout = task_project(None, str(task_file or task_path))
        return checkout.resolve() if checkout else None
    return Path(out.strip()).resolve()


def from_refusal(task_path, from_branch, repo, no_worktree):
    """Why no run can start `from:` that branch, or None: a scratch run has no branch, a run
    with no worktree no checkout of its own, and the branch must be a local one."""
    if not from_branch:
        return None
    if repo is None:
        return f"{task_path}: from: needs a repository; a scratch run has no branch to start from"
    if no_worktree:
        return (f"{task_path}: from: needs a worktree; "
                "drop --no-worktree so the run gets its own checkout")
    if not git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{from_branch}", check=False):
        return f"{task_path}: from: {from_branch!r} is not a local branch"
    return None


def loop(cfg, run_dir, task_path, opts, log, prior=None):
    receipt = run_record.read_state(run_dir) or {}
    # a --bg parent's pick, consumed here: one launch, one pick, whichever process prints it
    preset_exec = receipt.pop("launch_executor", None)
    preset_rev = receipt.pop("launch_reviewer", None)
    session_at_launch = launch_session(run_dir)
    meta, body, title = taskfile.parse_task(task_path)
    ignore_time_keys(run_dir, meta, log)
    cmds = taskfile.done_when(body, task_path)
    sized_words, sized_points, sized_checks = taskfile.task_size(body, cmds)
    on_dependency = stands_on_dependency(prior or receipt)
    if on_dependency:
        # before any checkout, pick or round: nothing here can stand on what it was cut from
        return end_on_dependency(cfg, run_dir, stamp_origin(
            {**(prior or receipt), "run_id": run_dir.name, "title": title,
             "task": str(task_path)}), log, on_dependency)
    gc.before_run(log)     # before this run adds a worktree of its own
    if prior:
        state = stamp_origin(prior)
        state.update(state="running", **run_record.process_owner(), finished_at=None, error=None,
                     reported=False, task_words=sized_words, task_points=sized_points,
                     task_checks=sized_checks)
        clear_delivery(state)
        state.setdefault("stalls", [])
        repo = Path(state["repo"]) if state.get("repo") else None
        wt = Path(state["worktree"])
        if repo:
            gitcall.no_auto_gc(wt)
        log(f"resuming at round {len(state['round_summaries']) + 1}/{state['rounds']}: {wt}"
            + (f" on {state['branch']}" if state.get("branch") else ""))
        history_start(state, log)
    else:
        # who launched this run goes on disk first of all: a base that does not resolve or a
        # worktree that cannot be made ends the run before the full state below is written, and
        # mark_state can only keep what run.json already says -- without this, an early error
        # would be a run with no owner, and the dead-seat fallback would have nobody to tell
        run_record.save_state(run_dir, stamp_origin({**receipt, "run_id": run_dir.name, "title": title, "task": str(task_path),
                             "launched_session": session_at_launch, "state": "running",
                             "verdict": None, **run_record.process_owner(), "started_at": time.time(),
                             "reported": False, "task_words": sized_words,
                             "task_points": sized_points, "task_checks": sized_checks}))
        history_start(run_record.read_state(run_dir) or receipt, log)
        # Detached starts and unstarted resumes may no longer stand in the launch checkout.
        if "repo" in receipt:
            repo = Path(receipt["repo"]) if receipt["repo"] else None
        else:
            repo = task_repo(meta, task_path, receipt.get("task_file"))  # receipts before preflight saved it
        scratch = repo is None
        raw_rounds = opts["--rounds"] or meta.get("rounds") or 3
        try:
            n_rounds = int(raw_rounds)
        except (TypeError, ValueError):
            n_rounds = 0
        if n_rounds < 1:
            raise config.Error(f"{task_path}: rounds must be a positive integer (got {raw_rounds!r})")
        method = (meta.get("merge") or "squash").lower()
        if method not in MERGE_METHODS:
            raise config.Error(f"{task_path}: merge must be one of "
                               f"{', '.join(MERGE_METHODS)} (got {meta.get('merge')!r})")
        from_branch = (meta.get("from") or "").strip()
        # refused at launch too (`preflight`); here again, as the branch can go while the run waits
        why = from_refusal(task_path, from_branch, repo, opts["--no-worktree"])
        if why:
            raise config.Error(why)
        change = None
        if scratch:
            # nothing to branch from: the run gets a workspace of its own, and whatever it
            # leaves there is the deliverable
            base = target = base_sha = branch = None
            wt = config.WORK / run_dir.name
            wt.mkdir(parents=True, exist_ok=True)
        else:
            gitcall.no_auto_gc(repo)
            # cut from the base as origin has it now: a local branch, or a tracking ref nothing
            # has fetched lately, can stand merges behind, and a round spent there is spent on
            # code that no longer exists.  Offline, or for a base origin has no branch of, the
            # local ref is the best there is.  Every branch, not only those the clone's own
            # refspec follows (--single-branch follows one): the base, the target whose suite
            # the run reads and origin's default can each be any of them.
            try:
                code, out = fetch(repo, "origin", "--prune", "+refs/heads/*:refs/remotes/origin/*")
            except Stopped as stop:
                code, out = None, str(stop)
            spelled = meta.get("base") or default_base(repo, log)
            # where the PR goes: a run cut from `dev` can still be meant for `main`.  Every later
            # step reads both as `<b>` or `origin/<b>`, so a full ref name is kept as the latter
            base, target = (re.sub(r"^refs/(heads|remotes/origin)/", "origin/", spelling)
                            for spelling in (spelled, meta.get("target") or spelled))
            name = base.removeprefix("origin/")
            # the tracking ref named in full, as `origin/main` could be a tag
            ref = f"refs/remotes/origin/{name}"
            if code == 0 and git_out(repo, "show-ref", "--verify", "--quiet", ref)[0] != 0:
                code, out = 1, f"origin has no branch {name}"
            if code != 0:
                # git's reason is its first line; the rest is advice
                why = out.partition(chr(10))[0]
                if receipt.get("followup"):
                    # a fix run may end not needed on what its checkout shows, and is told that
                    # checkout is origin's tip: a local ref could predate the defect.  Stopped
                    # leaves it for a resume, which starts it afresh with this fetch
                    raise Stopped(f"could not fetch {name} from origin, and a fix run starts "
                                  f"only on origin's tip: {why}")
                log(f"WARN could not fetch {name} from origin; basing this run on the local "
                    f"{spelled}: {why}")
                ref = spelled
            # a branch name moves with the executor's commits, so pin the diff to the commit it names
            base_sha = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
            if from_branch:
                # the change continues on that branch: the run the branch belongs to names it,
                # and the rounds earlier runs spent on it are spent
                change = change_on(from_branch, repo, exclude=run_dir)
                n_rounds, why = round_budget(n_rounds, change=change, exclude=run_dir,
                                             what=f"branch {from_branch}")
                if why:
                    raise config.Error(f"{task_path}: {why}")
            if opts["--no-worktree"]:
                wt, branch = repo, git(repo, "rev-parse", "--abbrev-ref", "HEAD")
                log(f"no worktree: working directly in {wt} on {branch}")
            elif from_branch:
                # A relaunch from a stopped or blocked run's committed work: the new
                # checkout starts where that branch left off before taking in `target`.
                wt, branch = make_worktree(repo, run_dir.name, slugify(title), from_branch)
            else:
                wt, branch = make_worktree(repo, run_dir.name, slugify(title), base_sha)
        # run.json names the worktree before anything else can fail: a step that ends the run here
        # -- exclude_junk does -- would otherwise leave a worktree `ak run clean` cannot find
        state = stamp_origin({**receipt, "run_id": run_dir.name, "title": title, "task": str(task_path),
                 "launched_session": session_at_launch,
                 "repo": str(repo) if repo else None, "scratch": scratch,
                 "base": base, "target": target, "base_sha": base_sha, "branch": branch,
                 "worktree": str(wt), "stalls": [],
                 "executor": None, "reviewer": None, "rounds": n_rounds, "state": "running",
                 "verdict": None, **run_record.process_owner(), "started_at": time.time(),
                 "finished_at": None, "round_summaries": [], "findings": "",
                 "merge_method": method, "no_merge": bool(opts["--no-merge"]) or scratch,
                 "pr": None, "merged": False, "merge_note": None, "reported": False,
                 # a scratch run has no base to prove anything on
                 **({"base_proof": None} if scratch else {}),
                 "task_words": sized_words, "task_points": sized_points,
                 "task_checks": sized_checks})
        if from_branch:
            state["from"] = from_branch
        if change:
            state["change"] = change
        if scratch:
            log(f"scratch workspace {wt}: no repository, so no branch, no PR and no merge")
        elif not opts["--no-worktree"]:
            if from_branch:
                log(f"worktree {wt} on {branch} from {from_branch}, "
                    f"base {base} ({base_sha[:12]})"
                    + (f", merging into {target}" if target != base else ""))
            else:
                log(f"worktree {wt} on {branch} from {base} ({base_sha[:12]})"
                    + (f", merging into {target}" if target != base else ""))
        history_start(state, log)
    invalidate_saved_pass(state, cfg, log)
    try:
        run_record.save_state(run_dir, state)
    except run_record.StopRequested:
        # A stop landed after a fresh checkout was cut but before its paths reached
        # the record: the stop removed nothing for lack of paths, so the checkout
        # goes here instead of orphaning a worktree and branch nobody names.  A
        # resumed run's paths were recorded long ago -- the stop removes those itself.
        if prior is None and not state.get("scratch") and not opts["--no-worktree"]:
            worktrees.drop_unrecorded_checkout(repo, wt, branch, log)
        raise
    if prior is None and state.get("from"):
        upstream = target if target.startswith("origin/") else f"origin/{target}"
        source = upstream
        # Pin the commit so another worktree's fetch cannot move what this run takes in.
        tip = git(wt, "rev-parse", "--verify", "--quiet",
                  f"refs/remotes/{upstream}^{{commit}}", check=False)
        if not tip:
            name = upstream.removeprefix("origin/")
            source = f"local {name}"
            tip = git(wt, "rev-parse", "--verify", "--quiet",
                      f"refs/heads/{name}^{{commit}}", check=False)
        if not tip:
            log(f"from: {upstream} unavailable; branch unchanged; "
                f"{upstream} will be taken in at landing")
        else:
            log(f"from: merging {source} ({tip[:12]}) into {state['branch']} before round 1")
            try:
                rc, out = git_out(wt, "merge", "--no-edit", tip)
            except Stopped:
                git(wt, "merge", "--abort", check=False)
                raise
            if rc != 0:
                if not git(wt, "diff", "--name-only", "--diff-filter=U"):
                    raise config.Error(f"could not merge {source} before round 1: {out}")
                git(wt, "merge", "--abort")
                log(f"from: {source} conflicts; merge aborted, branch unchanged; "
                    f"{upstream} will be taken in at landing")
            else:
                state["base_sha"] = tip
                run_record.save_state(run_dir, state)
                log(f"from: merged {source} into {state['branch']} before round 1")
    join_session_project(session_at_launch)     # this run on disk, so it votes too
    if not state.get("scratch"):
        exclude_junk(wt, log)

    # a repo's test secrets live on this machine and never in the repo; from here they are in
    # the environment of every worker and every done-when command, via config.seatless_env()
    env = config.repo_env(repo) if repo else {}
    if env:
        os.environ.update(env)
        log(f"env: {config.ENV / f'{repo.name}.env'} -> {', '.join(sorted(env))}")

    # Reject an explicit pair before even probing usage (some adapters make paid probes).
    workers, reviewers = config.role_groups(cfg, run_workers(cfg, state), state.get("reviewers"))
    if reviewers is not None:
        refuse_outside_group(cfg, opts["--exec"], workers, "worker")
        refuse_outside_group(cfg, opts["--review"], reviewers, "reviewer")
    if opts["--exec"] and opts["--review"]:
        review_providers(cfg, opts["--exec"], opts["--review"])
    providers = collect_usage(cfg)
    order = ready_order(cfg, providers, reviewers if reviewers is not None else workers,
                        role="reviewer", repo=repo)
    handed = None               # the model this resume took the work away from, if any
    if prior and state["executor"]:
        executor, reviewer = state["executor"], state.get("reviewer")
        if not review_pass(state, cfg):
            # A saved reviewer must still be eligible. The executor keeps its work's identity.
            if reviewer not in reviewer_order(cfg, executor, order):
                reviewer = None
            # Nor is a saved executor: relaunching a model whose provider is spent would only
            # earn the same refusal, so the work is handed over here exactly as it is mid-round,
            # note and all -- the round it was cut off in resumes with another model in it.
            spent, why = usage.model_exhausted(cfg, executor, providers)
            gone = usage.unready(cfg, executor, providers)
            if spent or gone:
                log(f"saved executor {executor} cannot run: {why or gone}")
                try:
                    picked = next_executor(
                        cfg, providers, {config.model(cfg, executor)["provider"]} if spent
                        else set(), reviewer, log, workers=workers, reviewers=reviewers)
                except (Exhausted, config.Error):
                    # nowhere to hand the saved turn to: keep the saved pair and let the
                    # round itself surface the quota, exactly as a fresh launch would.
                    picked = None
                if picked is None:
                    handed = None
                    executor, reviewer = pick_models(cfg, providers, executor, reviewer,
                                                     log, resuming=True, repo=repo,
                                                     workers=workers, reviewers=reviewers)
                else:
                    handed = executor
                    executor, reviewer = picked
                    note_handover(state, handed, "ran dry" if spent else gone,
                                  started_round(run_dir, state), to=executor, reason="dry")
                    log(f"handing executor to {executor}: {handed} "
                        + ("ran dry" if spent else gone))
            else:
                executor, reviewer = pick_models(cfg, providers, executor, reviewer, log,
                                                 resuming=True, repo=repo, workers=workers,
                                                 reviewers=reviewers)
                if reviewer is not None and same_model(cfg, executor, reviewer):
                    # A saved self-review steps aside when a better pair is ready: its own
                    # model reviews only as the last choice, never while another pair runs.
                    # Once the round's executor has answered, only the reviewer moves: the
                    # work is already its author's, and handing it over would record the
                    # review against a model that never ran it.
                    answered = bool(state.get("review_pending"))
                    if not answered:
                        try:
                            nxt = len(state.get("round_summaries") or []) + 1
                            rd = Path(run_dir) / f"round-{nxt}"
                            answered = (finished_answer(rd, "executor") is not None or
                                        finished_answer(rd, "fixer") is not None)
                        except (OSError, ValueError, TypeError, AttributeError):
                            answered = False
                    try:
                        if answered:
                            better = best_pair(cfg, [executor], order)
                        else:
                            exec_order = ready_order(cfg, providers, workers, None, repo=repo,
                                                     reviewers=reviewers, quiet=True)
                            better = best_pair(cfg, exec_order, order)
                    except (config.Error, OSError, ValueError, KeyError, TypeError,
                            AttributeError):
                        better = None
                    if better is not None and not same_model(cfg, *better):
                        if better[0] != executor:
                            handed = executor
                            executor, reviewer = better
                            note_handover(state, handed, "self-review",
                                          started_round(run_dir, state), to=executor,
                                          reason="self-review")
                            log(f"handing executor to {executor}: {handed} "
                                "was to review its own work")
                        else:
                            executor, reviewer = better
        if reviewer != state.get("reviewer"):
            state["review_session"] = None
    elif (preset_exec and not opts["--exec"] and not opts["--review"]
          and not usage.unready(cfg, preset_exec, providers)):
        # the --bg parent already picked and printed this pair: adopt it through the
        # same resuming validation a resume uses, so the line stays truthful when
        # usage moved between the two picks.  An explicit pair re-picks, as before.
        if preset_rev not in order:
            preset_rev = None   # a saved reviewer keeps its identity; a stale one does not
        executor, reviewer = pick_models(cfg, providers, preset_exec, preset_rev, log,
                                         resuming=True, repo=repo, workers=workers,
                                         reviewers=reviewers)
    else:
        try:
            executor, reviewer = pick_models(cfg, providers, opts["--exec"], opts["--review"],
                                             log, repo=repo, workers=workers, reviewers=reviewers)
        except QuotaDry:
            refusal = pair_refusal(cfg, providers, workers, opts["--exec"], opts["--review"],
                                   reviewers)
            if refusal:
                raise config.Error(refusal) from None
            raise
    log(f"executor={executor} reviewer={reviewer} rounds={state['rounds']}")
    state["executor"], state["reviewer"] = executor, reviewer
    run_record.save_state(run_dir, state)
    if prior is None and session_at_launch and not preset_exec:
        # A launch from a seat says where to look: this run counts on the seat's own
        # bar and in the menu from here, and the seat is told when it ends.  A plain
        # print, not the timestamped log: this one line is the launch announcement.
        # A --bg child stays silent -- its stdout is the log, and the parent, which
        # picked first, already printed it on the terminal.
        print(launch_line(run_dir.name, title, executor, reviewer,
                          self_review=same_model(cfg, executor, reviewer)))

    # Recover an interrupted probe before reading the checkout's suite and worker rules.
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, "")
    target = state.get("target") or state.get("base")
    if state.get("scratch"):
        where = (f"Workspace: {wt}\nThere is no git repository here: nothing to commit, no branch "
                 "and no PR. What you leave in the workspace is the deliverable.")
    else:
        where = (f"Repo checkout: {wt}\nBranch: {state['branch']} (based on {state['base']}"
                 + (f", to be merged into {target}" if target != state["base"] else "") + ")")
    cmds = round_commands(cmds, wt, target, scratch=state.get("scratch"), landing=not state.get("no_merge"))
    every, once = taskfile.group_commands(cmds)
    body += repo_rules(wt, state.get("base_sha"))
    run_record.save_state(run_dir, state)
    context = (f"{where}\n\n{body}\n\n"
               f"{shell_foreground_note()}\n\n"
               f"Done-when commands, all must exit 0 (run them in {wt}):\n"
               + "\n".join(f"  $ {c}" for c in every))
    if once:
        context += ("\nThe loop runs these once at landing on the commit to be merged; "
                    "do not run them yourself:\n"
                    + "\n".join(f"  $ {c}" for c in once))
    if handed:
        # a handover on resume is the same handover as one mid-round, and the model taking over
        # is owed the same note: the round it is joining was already started by another
        context = f"{HANDOVER.format(before=handed)}\n\n{context}"
    lp.body, lp.cmds, lp.context = body, cmds, context
    lp.every, lp.once = every, once
    try:
        rounds(lp)
        if (not state.get("no_merge")
                and (review_pass(state, cfg) or (state.get("waiting_on") or {}).get("line"))):
            try:
                merge(lp)
            except config.Error as exc:
                # The work is reviewed and the rounds are spent, so a git or gh that stopped
                # here leaves a PASS needing one command -- `merge_failed` is what lets
                # `ak run merge` pick it up -- rather than a run nothing can finish.
                note(lp, str(exc), failed=True)
                if state.get("review_pending"):
                    # unless integration had already invalidated the review: there is review
                    # work outstanding, which only a resume can finish, so say so
                    raise Exhausted(str(exc)) from None
    except NotNeeded as exc:
        state.update(state="not_needed", verdict=None, not_needed=str(exc),
                     finished_at=time.time())
        run_record.save_state(run_dir, state)
        write_result(run_dir, state, cmds, log, cfg)
        worktrees.settle_run(state, run_dir, log)
        return state
    except Dead as exc:
        log(f"ERROR {exc}")
        state.update({"state": "error", "verdict": "ERROR", "error": str(exc),
                      "finished_at": time.time()})
        park_error(run_dir, state)
        run_record.save_state(run_dir, state)
        write_result(run_dir, state, cmds, log, cfg)
        worktrees.settle_run(state, run_dir, log)
        return state
    except Blocked as exc:
        return finish_blocked(run_dir, state, exc, log, cfg)

    # a parked run is no ending at all: `waiting` is the tick's, and its reason stands
    if state.get("state") != "waiting":
        state["state"] = "pass" if review_pass(state, cfg) else "fail"
    # a finished run waits on nothing: a quota mark, a refusal's retry, an error's
    # retry, or the harness a login parked it on, all die here, so a later delivery
    # retry inherits none of them.
    state.pop("quota_dry", None)
    state.pop("refusal_retry", None)
    state.pop("error_retry_at", None)
    state.pop("error_retries", None)
    for key in ("waiting_for", "login_resume_at", "login_back_at"):
        state.pop(key, None)
    state["finished_at"] = (None if state.get("state") == "waiting"
                            and (state.get("waiting_on") or {}).get("line") else time.time())
    run_record.save_state(run_dir, state)
    write_result(run_dir, state, cmds, log, cfg)
    worktrees.settle_run(state, run_dir, log)
    return state


def mark_state(run_dir, name, error=None, log=None):
    """Record how a run died, so `ak run status` never shows a dead run as running.

    A concurrent stop wins over the mark: the record already says `stopped`, the
    history and the tally already heard it from the stop, and there is nothing left
    to record, so the disk as it stands is returned instead of raising.
    """
    state = run_record.read_state(run_dir)
    if state is None:
        state = {"run_id": run_dir.name, "verdict": None}
    if not state.get("title"):
        # nothing had written the title yet, and the message the user gets has to carry it
        try:
            state["title"] = taskfile.parse_task(run_dir / "task.md")[2]
        except (OSError, config.Error):
            pass
    state["state"], state["finished_at"] = name, time.time()
    if name != "waiting_login":
        # the harness a login parked it on, and the stamps that paced and released the
        # retry: none means anything to a run that is no longer parked on one
        for key in ("waiting_for", "login_resume_at", "login_back_at"):
            state.pop(key, None)
    if name == "error":
        # an error is born with the tick's retry scheduled, or parked for a person
        park_error(run_dir, state)
    else:
        # an error's retry belongs to the error: any other mark ends that episode
        state.pop("error_retry_at", None)
        state.pop("error_retries", None)
    if name == "exhausted":
        park_exhausted(state, error)
    elif error:
        state["error"] = error
    try:
        run_record.save_state(run_dir, state)
    except run_record.StopRequested:
        return run_record.read_state(run_dir) or state
    history_finish(state, log)
    try:
        redress_seat(launched_session(state))   # every state change lands on the bar
    except config.Error:
        pass
    return state


# --- status, clean, resume --------------------------------------------------


def installed_head():
    """This process's checkout at `bin/ak`, as a short commit, or "" when it cannot be read.

    A read that fails or runs slow is no version, never a failed run: the checkout may
    be no checkout at all, or git waiting on a prompt or a network nobody here can answer.
    """
    try:
        proc = subprocess.run(["git", "-C", str(config.REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=10, stdin=subprocess.DEVNULL, env=tool_env())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def pickup_new_code(lp, execv=None, current=None):
    """Replace this process with the installed agentkit when it has moved, at a safe boundary.

    Before a round -- an own PR's review round too, once its push arrives -- and before
    landing verification the run holds no gate turn, no delivery lock and no child, so a
    process driving this one run replaces itself with `ak run resume
    <id>` and the resume continues in place on the new code: the pid, the scope and the slot
    stay the same, and a saved PASS is kept as a resume keeps it.  A job's threads share one
    process, and a delivery retry must stay one, so neither ever moves; any turn held or
    waited for, any child still marked, or a version that cannot be read means no move, never
    a failed run. `execv` and `current` are the injected exec and installed version
    the tests use.
    """
    global _PICKUP_START
    if threading.current_thread() is not threading.main_thread():
        return False
    if getattr(jobs._JOB_MUTE, "depth", 0) or getattr(lp, "no_pickup", False):
        return False
    if lp.state.get("state") != "running":
        return False
    if execv is None:
        execv = os.execv
    try:
        now = installed_head() if current is None else current
    except Exception:
        return False
    if not now:
        return False
    start = _PICKUP_START
    if not start:
        _PICKUP_START = now
        return False
    if now == start:
        return False
    try:
        if gate.gate_turn_note(lp.state):
            return False
    except Exception:
        return False
    if gate.turn_held() or getattr(PICKUP_HELD, "count", 0):
        return False
    try:
        children = worker.marked_pids(worker.run_marker(lp.state.get("run_id")))
    except Exception:
        return False
    if children:
        return False
    try:
        # the options this process runs with: a review reads them every round
        lp.state["pickup"] = {"pid": os.getpid(), "from": start, "to": now, "opts": lp.opts}
        lp.write()
    except run_record.StopRequested:
        raise
    except Exception:
        return False
    ak = str(config.REPO / "bin" / "ak")
    try:
        execv(sys.executable, [sys.executable, ak, "run", "resume", lp.run_dir.name])
    except OSError:
        return False
    return True


def pickup_while_queued(run_dir, execv=None, current=None):
    """A launch waiting for its slot holds nothing: where the installed agentkit moved since it
    started, it replaces itself with the same launch on the new code, which takes up the same
    receipt -- the pid and `queued_at`, so its place in line, stay -- and a change to admission
    reaches the runs already waiting, as `pickup_new_code` brings new code to a run before a
    round.  Only a detached launch's own process moves (`spawn_bg`); a job's threads share one.
    `execv` and `current` are the injected exec and installed version the tests use."""
    if (os.environ.get(config.RUN_DIR_ENV) != str(run_dir)
            or threading.current_thread() is not threading.main_thread()
            or getattr(jobs._JOB_MUTE, "depth", 0)):
        return False
    now = installed_head() if current is None else current
    if not now or not _PICKUP_START or now == _PICKUP_START:
        return False
    logger(run_dir)(f"picked up agentkit {_PICKUP_START}..{now} while waiting for a slot")
    sys.stdout.flush()
    # ak's own entry, not `sys.argv[0]`: a link that started the launch may since point elsewhere
    ak = str(config.REPO / "bin" / "ak")
    try:
        (execv or os.execv)(sys.executable, [sys.executable, ak, *sys.argv[1:]])
    except OSError:
        return False
    return True


def seat_refusal(opts, flags):
    """Why a seat's launch is refused: a seat names no model, no place in the queue and no
    second run of a change under way, since ak picks the models, decides what goes first and
    refuses the rival itself; and it launches only while its plan has an open line, since the
    plan is what its bar counts and what a review of its pull request checks against
    (`prompts.plan_context`).  A seat is a recorded session (`config.session_records`);
    a shell naming none is no seat, and outside a seat neither holds.  Nor in a queued child,
    which `spawn_bg` starts under the seat's name: it is ak's own pick (a job's rerun on the
    next executor) or the seat's launch, judged at its parsing."""
    if not from_seat():
        return None
    given = ([flag for flag in ("--exec", "--review") if opts.get(flag)]
             + [flag for flag in ("--anyway", "--first") if flags.get(flag)])
    if given:
        return (f"{', '.join(given)}: not a seat's; ak picks the models, decides what "
                "goes first and refuses a second run of a change under way, so launch without")
    if not plan.open_lines(config.current_session()):
        return ("your plan has no open line, and the plan is what your bar counts: first run "
                "ak plan add \"<outcome>\" --check '<command>'")
    return None


def from_seat():
    """Whether this launch is a seat's own: a recorded session's (`config.session_records`),
    outside any run (`RUN_DIR_ENV`)."""
    seat = config.current_session()
    return bool(seat and seat in config.session_records()
                and not os.environ.get(config.RUN_DIR_ENV))


def rival_advice():
    """What a launch refused for a run already under way may do: wait for it, or, outside a
    seat, start a second run regardless with `--anyway`, which a seat may not give
    (`seat_refusal`)."""
    return "wait for it" + ("" if from_seat() else ", or add --anyway to start a second run")


def depth_refused():
    depth = run_depth()
    if depth < 2:
        return False
    print(f"a worker's worker may not start runs (depth {depth}); "
          "only the orchestrator, and a worker for its tests, may", file=sys.stderr)
    return True


@contextmanager
def run_slot(run_dir, prior=None):
    state = gate.wait_for_slot(run_dir, between=lambda: pickup_while_queued(run_dir))
    if prior is not None:
        prior.update({key: state[key] for key in (
            "state", "run_depth", "parent_run", "queued_at", "slot_waiting", "slot_started_at")
                      if key in state})
        prior.pop("resume_from", None)
    previous = getattr(_RUN_CONTEXT, "state", {})
    _RUN_CONTEXT.state = state
    try:
        yield
    finally:
        _RUN_CONTEXT.state = previous


# One run's memory, below the slice ceiling.  40% of that ceiling: a leak has to die
# inside its own scope, while the seat slice -- accounted apart, and with the higher
# weight -- is never the thing the kernel throttles.  Swap is capped at the same size
# so the excess cannot hide there.  4 GB is only the fallback where there is no
# ceiling to read.
RUN_MEMORY_DEFAULT_MB = 4096
RUN_MEMORY_SHARE = 40


def memory_cap_mb(ceiling_mb=None):
    """The cap for one run, in mebibytes.

    `run_memory_max_mb` in the config, when it is set.  Otherwise 40% of the
    slice's MemoryMax, with no top: a larger machine grows the slice, and the
    run's share grows with it.  No ceiling at all -- a host with no drop-in, a
    Mac -- falls back to 4 GB, which is still below an uncapped user unit.  The
    share is integer arithmetic so 40% of an odd ceiling does not drift.
    """
    configured = config.run_memory_max_mb()
    if configured is not None:
        return configured
    if ceiling_mb is None:
        ceiling_mb = orch.slice_memory_max_mb()
    if (isinstance(ceiling_mb, (int, float)) and not isinstance(ceiling_mb, bool)
            and ceiling_mb > 0):
        return max(1, (int(ceiling_mb) * RUN_MEMORY_SHARE) // 100)
    return RUN_MEMORY_DEFAULT_MB


def run_scope_limits(ceiling_mb=None, *, cap_mb=None, cpu_weight=40):
    """(cap in MiB, systemd properties) for one run scope.

    CPU and I/O weight stay above the seats', and the memory cap is applied
    as both MemoryMax and MemorySwapMax: the same number, so a leak cannot trade
    one for the other and keep going.  OOMPolicy=continue, where the manager takes
    it, has the kernel end only the process that grew, not the whole scope: the
    loop, its harness session and its worktree go on, and `memory_cap_note` says
    so.  The properties are what `systemd-run -p` takes; the cap is what the
    receipt records, so the reason can still name the number after the process
    that knew it is gone. A lander supplies its recorded suite need as `cap_mb`,
    and its own CPU weight, above every run's.
    """
    cap = memory_cap_mb(ceiling_mb) if cap_mb is None else cap_mb
    return cap, ("-p", f"CPUWeight={cpu_weight}", "-p", "IOWeight=40",
                 "-p", f"MemoryMax={cap}M", "-p", f"MemorySwapMax={cap}M",
                 *(("-p", "OOMPolicy=continue") if orch.scope_oom_policy() else ()))


def run_placement(run_dir, previous):
    """(unit, cap in MiB, properties): where a run goes, in `--bg` and in the foreground alike.

    Its own `agentkit-run-<id>` in the runs slice, under `run_scope_limits`.  A name an earlier
    attempt's scope may still hold is not reused, unless that attempt left its claim: then
    `start_in_slice` reads the claim and asks the manager about it before anything starts.
    """
    unit = f"agentkit-run-{run_dir.name}"
    if scope_is_real(previous.get("scope")) and not (config.TMP / f"{unit}.placed").exists():
        unit = orch.next_scope_unit(unit)
    cap, properties = run_scope_limits()
    return unit, cap, properties


def place_here(run_dir, log):
    """Put a foreground run's own process where `--bg` puts its child; the record, or None.

    Nothing new is started: the user manager moves this very process into the run's scope,
    so the terminal keeps its output and its Ctrl-C, and the pid on the receipt stays the
    run's.  Where no scope can be made the run goes on here as it always did, and the log
    says why.  Only a process that is this one run is moved: `ak` itself, never a caller
    that imported this module (a test), and from its main thread, never a job's, whose
    process all its tasks share.  One already in the scope its receipt names -- a recovery
    the tick placed -- is where it belongs.
    """
    if (Path(sys.argv[0]).resolve() != (config.REPO / "bin" / "ak").resolve()
            or threading.current_thread() is not threading.main_thread()):
        return None
    with run_record.record(run_dir) as state:
        if state.stopped or any(host.cgroup_contains(f"/{unit}")
                                for unit in _scope_units(state.get("scope"))):
            return None
        placement, cap, placed = {}, None, False
        try:
            unit, cap, properties = run_placement(run_dir, state)
            placed = orch.scope_self(unit, orch.run_slice_name(), properties, placement)
        except OSError as exc:
            placement = {"scope": "none", "scope_reason": str(exc)}
        state.update(scope=placement["scope"], scope_reason=placement.get("scope_reason"))
        remember_memory_cap(state, placement, cap)
    if placed:
        try:
            os.nice(10)   # the work `--bg` puts in a scope runs under `nice -n 10`
        except OSError:
            pass          # a priority it may not lower is no reason to leave the scope unsaid
    log(f"scope: {scope_line(state)}")
    return dict(state)


def remember_memory_cap(state, placement, cap):
    """Record the cap only on a scope that was actually given one."""
    scope = placement.get("scope") if isinstance(placement, dict) else None
    if scope_is_real(scope):
        state["memory_cap_mb"] = cap
    else:
        state.pop("memory_cap_mb", None)
    return state


def seat_launch(state):
    """Whether the tick launched that run for a seat (`launch_for_seat`): a fix run
    (`followup`) or a task started again (`restarted`), whose receipt names the seat and its
    lists, and which descends from nothing that launched it."""
    return bool(state.get("followup") or state.get("restarted"))


def launch_for_seat(directory, state, origin, cfg=None, opts=None, task_file=None):
    """Launch the task.md in that new run directory, or the pull request's review `opts` name,
    as the tick does for a seat, the one `state` was launched from: `origin` on its receipt
    says why (`seat_launch`), with the seat's lists now, the given run's only for a seat with
    no record of its own -- checked against the config now, as that run's may predate a model
    it names -- and `opts` over the defaults."""
    session = launched_session(state)
    try:
        lists = (config.load_session(config.load(), session, required=False) if session
                 else None) or state
    except config.Error:
        lists = state
    receipt = {**origin, "launched_session": session,
               **{role: list(lists[role]) for role in ("workers", "reviewers")
                  if isinstance(lists.get(role), list) and lists[role]},
               **({"notify_sink": state["notify_sink"]} if state.get("notify_sink") else {})}
    opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
            "--no-worktree": False, "--no-merge": False, **(opts or {}), "--bg": True}
    prepare(directory, opts, logger(directory), report_config(cfg), task_file=task_file,
            receipt=receipt)
    spawn_bg(directory, ["--review-pr", opts["--review-pr"]] if opts["--review-pr"]
             else [str(directory / "task.md")])


def spawn_bg(run_dir, argv, expected=None, park_as=False):
    """Start `ak run <argv>` detached, from the record it reads under the recovery lock.

    `park_as` is for a pass that parked the run itself and stamped its own retry: a launch
    that never starts puts that record back as read, inside the same hold that wrote the
    launch, so a write landing after the hold is never taken for this failure and undone.
    """
    log_path = run_dir / "log.txt"
    env = dict(os.environ, **{config.RUN_DIR_ENV: str(run_dir)})
    child = [sys.executable, str(config.REPO / "bin" / "ak"), "run"] + [a for a in argv if a != "--bg"]
    with gate.slot_lock(), run_record.recovery_lock(run_dir):
        previous = run_record.read_state(run_dir) or {}
        if seat_launch(previous):
            # These are siblings owned by the seat, not descendants for the ending's
            # process sweep to kill or tests sharing its admission slot.
            for key in (worker.RUN_MARKER, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_SCOPE",
                        config.UNATTENDED_ENV, config.JOB_DIR_ENV, "AK_RUN_ROLE"):
                env.pop(key, None)
            seat = launched_session(previous)
            if seat:
                env[config.SESSION_ENV] = seat
            else:
                env.pop(config.SESSION_ENV, None)
        if expected is not None and previous != expected:
            raise config.Error("the run changed while choosing recovery; select it again")
        if previous.get("state") == "stopped":
            # A stop won the race to this launch: report the deliberate end the way
            # every caller already reports a refused launch, instead of saving over
            # it and dying on the guard with a traceback no terminal could read.
            raise config.Error(f"{run_dir.name} was stopped before it could start; "
                               "nothing was launched")
        # A fresh launch already claimed any free slot. Transfer it to the child without
        # releasing it or moving behind later waiters while preflight was running.
        claimed = (argv[:1] != ["resume"] and previous.get("state") == "running"
                   and previous.get("pid") == os.getpid()
                   and previous.get("slot_waiting") is False)
        state = {**previous, "run_id": run_dir.name, "state": "running" if claimed else "queued",
                 "queued_at": (previous.get("queued_at") if claimed or previous.get("state") == "queued"
                               else None) or time.time(),
                 "slot_waiting": not claimed, "launch_pending": True, **run_record.process_owner()}
        state.setdefault("scope", None)
        state.setdefault("run_depth", run_depth())
        if previous.get("state") != "queued":
            state.pop("slot_waited", None)
        env["AK_RUN_DEPTH"] = str(state["run_depth"])
        if argv[:1] == ["resume"]:
            state["resume_from"] = previous.get("resume_from") or (
                "interrupted" if previous.get("state") == "queued" else previous["state"])
        run_record.save_state(run_dir, state)
        try:
            unit, cap, properties = run_placement(run_dir, previous)
            # Into agentkit's slice, like every other agent process: a run started from a seat
            # is already inside it, and one started from the owner's own shell -- or by a tick
            # from cron -- would otherwise be the one heavy thing on the machine with no
            # ceiling over it.  The pid that comes back is the one really doing the work.
            placement = {}
            # kept past a death: the reaper reads there whether the memory cap ended it, then stops it
            pid = orch.start_in_slice(
                child, unit, env, log_path,
                log=note_in(log_path), target_slice=orch.run_slice_name(),
                properties=properties,
                nice=True, placement=placement, ends=False)
            # The child waits on this lock before adopting the receipt. The parent can never
            # overwrite a running child's state, and reaping sees the child, not its launcher.
            state.update(run_record.process_owner(pid), scope=placement.get("scope"),
                         scope_reason=placement.get("scope_reason"))
            remember_memory_cap(state, placement, cap)
            state["launch_pending"] = False
            state.pop("reservation_pending", None)
            run_record.save_state(run_dir, state)
            update_scope_line(run_dir, state)
        except (OSError, config.Error) as exc:
            reason = f"Could not launch the run: {exc}"
            if park_as:
                state = previous
            elif (previous.get("reservation_pending") and
                    previous.get("pid") == os.getpid()):
                state = interrupt(previous, reason)
            elif previous.get("slot_waiting"):
                state = {**previous, "pid": None, "process_identity": None,
                         "launch_pending": False, "launch_error": reason}
            else:
                state = interrupt(previous, reason)
            run_record.save_state(run_dir, state)
            update_scope_line(run_dir, state)
            raise config.Error(reason) from exc
    print(run_dir.name)
    print(run_dir / "result.md")
    return 0


def note_in(path):
    """A logger for a launch that has nobody to print to: one line in the work's own log.

    A detached start has no terminal and no tick behind it, and a placement that had to fall
    back is exactly the kind of thing to find later in the log of the run it was for.
    """
    def note(message):
        try:
            with Path(path).open("a") as fh:
                fh.write(f"[{datetime.now():%H:%M:%S}] {message}\n")
        except OSError:
            pass
    return note


def foreground_cli(run_dir):
    return (not getattr(jobs._JOB_MUTE, "depth", 0)
            and threading.current_thread() is threading.main_thread()
            and Path(sys.argv[0]).resolve() == (config.REPO / "bin" / "ak").resolve()
            and not log_is_stdout(run_dir))


def launch_session(run_dir):
    """The owner captured by the parent before preflight, including an explicit no-seat."""
    state = run_record.read_state(run_dir) or {}
    return (state["launched_session"] if "launched_session" in state else
            config.current_session())


def capture_launch(run_dir, opts=None, job_id=None, cfg=None, task_file=None, receipt=None):
    """The owner, and whether anybody owns this launch at all.

    `unattended` is the run nobody started: no seat, and no terminal either, because a worker
    or a done-when command below another run started it.  Nothing is told about it and the
    menu does not offer it -- `ak run status` has it, though never the smoke suite's own runs.

    The session's role lists go on the receipt here too: later edits cannot widen a run's
    choices. Defaults with separate reviewers bind both lists outside a session as well;
    old selections keep their original receipt shape.

    A job names itself here, in the same write as the scheduler pid the receipt
    records: the scheduler only writes `task["run_id"]` after preflight, and a stop
    in between must still recognise one of its tasks and spare the scheduler.

    The task file it was launched from goes on too, because the run keeps only a copy:
    where the file lives is what files a scratch run's seat under a project (`run_project`).
    """
    receipt = (run_record.read_state(run_dir) or {}) if receipt is None else receipt
    # launched by the tick for a seat: the receipt says whose, and which lists, and no slot
    # is reserved before the launch
    bound = seat_launch(receipt)
    session_at_launch = receipt["launched_session"] if bound else config.current_session()
    workers = (receipt.get("workers") if bound else
               config.workers(cfg) if cfg is not None and session_at_launch else None)
    if bound:
        # It keeps the lists launch_for_seat bound when it wrote the receipt.
        groups = {role: list(receipt[role]) for role in ("workers", "reviewers")
                  if isinstance(receipt.get(role), list) and receipt[role]}
    else:
        selection = (config.active_session(cfg) or cfg["defaults"]) if cfg is not None else {}
        groups = {"workers": workers} if workers else {}
        if "reviewers" in selection:
            groups = {role: list(selection[role]) for role in ("workers", "reviewers")}
    limit = config.max_runs()
    with gate.slot_lock():
        state = stamp_origin({**receipt, "run_id": run_dir.name, "state": "queued", "verdict": None,
                         "launched_session": session_at_launch, "started_at": time.time(),
                         "queued_at": time.time(), "slot_waiting": True,
                         "run_depth": 0 if bound else run_depth(),
                         "parent_run": None if bound else os.environ.get("AK_PARENT_RUN"),
                         "reservation_pending": True,
                         "unattended": not session_at_launch and config.unattended(),
                         **run_record.process_owner(), "launch_opts": opts or {},
                         **groups,
                         "review_pr": (opts or {}).get("--review-pr"), "reported": False,
                         # launched under the rule: one of its checks must fail on base
                         # (`fails_on_base`), unless its receipt holds the proof -- a repair's,
                         # from the lander; a PR review's proof is its plan's lines
                         "base_proof": None if (opts or {}).get("--review-pr")
                                       else receipt.get("base_proof") or "owed"})
        if job_id is not None:
            state["job_id"] = job_id
        if task_file is not None:
            state["task_file"] = str(task_file)
        if (opts or {}).get("--first"):
            state["first"] = True
        if not bound:
            # A fix run waits for its slot from its first record on: whatever cuts its handoff
            # off before the launch, it is a slot wait, which the tick resumes.
            gate.reserve_slot(state, limit)
        run_record.save_state(run_dir, state)
    history_start(state)
    redress_seat(session_at_launch)   # the seat's bar says it from the start


def preset_models(cfg, opts, log, run_dir):
    """Pick executor/reviewer in the parent, saving them for the --bg child to adopt.

    The seat's terminal can only name the models if they are picked where the
    terminal is.  The child adopts the pick through the same resuming validation a
    resume uses, so the line stays truthful when usage moves between the two picks.
    (None, None) when nothing can be picked yet -- spent providers, a stopped probe
    -- and the child then picks exactly as it always did, so a launch that cannot
    be named yet still starts unnamed.  A pick no launch can make is refused here, and
    no child starts.
    """
    try:
        providers = collect_usage(cfg)
        state = run_record.read_state(run_dir) or {}
        workers, reviewers = run_workers(cfg, state), state.get("reviewers")
        try:
            executor, reviewer = pick_models(cfg, providers, opts["--exec"], opts["--review"],
                                             log, quiet=True, workers=workers, reviewers=reviewers)
        except QuotaDry:
            refusal = pair_refusal(cfg, providers, workers, opts["--exec"], opts["--review"],
                                   reviewers)
            if not refusal:
                raise
            raise config.Error(refusal) from None
    except config.Error as exc:
        refused(run_dir, exc, log, cfg, printed=True)    # only the seat's own `ak run` asks
        raise
    except Exception:  # noqa: BLE001 - the child reproduces any real failure itself
        return None, None
    run_record.save_state(run_dir, {**(run_record.read_state(run_dir) or {}),
                         "launch_executor": executor, "launch_reviewer": reviewer})
    return executor, reviewer


def preset_review_model(cfg, opts, workers=None, *, reviewers=None):
    """The reviewer for a --review-pr launch, picked in the parent, or None.

    Same shape as the pick inside review_pr, minus the checkout the parent has not
    done: an explicit --review, else the first reviewer in the order.  A bare None
    means the child picks exactly as it always did; an explicit one that cannot run is
    refused here. The seat's own PR already picks against its orchestrator here, so
    the launch line names the reviewer the child will keep.
    """
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    if reviewers is not None:
        refuse_outside_group(cfg, opts["--review"], reviewers, "reviewer")
    try:
        providers = collect_usage(cfg)
        exec_for_rule = None
        try:
            session = config.current_session()
            if session and (opts or {}).get("--review-pr"):
                author = pr_view(opts["--review-pr"]).get("author")
                is_own, orch = own_pr_orchestrator(cfg, session, author)
                if is_own and orch:
                    exec_for_rule = orch
        except Exception:  # noqa: BLE001 - unknown PR or login picks as before
            exec_for_rule = None
        order = reviewer_order(cfg, exec_for_rule, ready_order(
            cfg, providers, reviewers if reviewers is not None else workers,
            role="reviewer", quiet=True))
        if not opts["--review"]:
            return order[0] if order else None
        config.model(cfg, opts["--review"])
    except Exception:  # noqa: BLE001 - the child reproduces any real failure itself
        return None
    refuse_unready(cfg, providers, opts["--review"], "reviewer")
    if exec_for_rule:
        review_providers(cfg, exec_for_rule, opts["--review"])
    return opts["--review"]


def refused(run_dir, exc, log, cfg, printed=False):
    """A launch refused before it ran ends as any run does: recorded, its result written, and
    its seat told -- by the `ak run` the seat typed itself when `printed`, which prints the
    refusal where it was asked (`printed_at_launch`), else by a hand-back."""
    state = mark_state(run_dir, "error", str(exc), log)
    record_result(run_dir, state, log, cfg)
    if printed:
        printed_at_launch(run_dir, state, log)
    else:
        announce_safely(state, run_dir, log, cfg)


def prepare(run_dir, opts, log, cfg=None, job_id=None, task_file=None, receipt=None,
            printed=False):
    capture_launch(run_dir, opts, job_id, cfg, task_file, receipt)
    try:
        preflight(run_dir, opts, log)
    except (Stopped, config.Error, OSError) as exc:
        # The launch receipt is already visible to `r`; a rejected preflight must not leave
        # it queued forever, or lose the seat it belonged to before the check began.  It is
        # an ending like any other, so a result is written and the seat that launched it
        # hears why -- a hand-back naming a result.md nothing wrote is no hand-back.  Repository
        # discovery that never answered (`Stopped`) did nothing, so relaunch is its recovery.
        refused(run_dir, exc, log, cfg, printed)
        raise


def preflight(run_dir, opts, log):
    """A compact launch receipt, also printed by the foreground parent of a background run."""
    url = opts.get("--review-pr")
    alongside = None
    if url:
        info = pr_view(url)
        owner, name, number = PR_PARTS.match(url).groups()
        state = run_record.read_state(run_dir) or {}
        state["title"] = f"Review PR #{number}: {info['title']}"
        # a config that cannot be read refuses the launch rather than judge the PR external,
        # and a writer already on the record (`leases.restart` carries one) stays there
        # whatever the config says of its model now: only a probed writer is written down
        is_own, orch, effort = pr_writer(config.load(), state, state.get("launched_session"),
                                         info["author"])
        state.setdefault("own_pr", is_own)
        state.setdefault("own_orchestrator", orch if is_own else None)
        state.setdefault("own_orchestrator_effort", effort if is_own else None)
        run_record.save_state(run_dir, state)
        if is_own and not orch:
            raise config.Error(f"no session record names the writer of this PR; "
                               f"review of the seat's own PR needs its orchestrator")
        if is_own:
            # the budget is the pull request's: earlier runs' rounds on it are spent
            why = own_pr_budget(url, run_dir)[1]
            if why:
                raise config.Error(why)
            # ... and a PR too large for the seat is refused before it waits for a slot
            checkout = checkout_for(f"{owner}/{name}", log)
            default = origin_default(checkout)
            if info["baseRefName"] != default:
                # it would land on its base: stacked on an unmerged change, into that change's
                # branch under that change's own review, never on the default branch
                raise config.Error(f"PR #{number} is based on {info['baseRefName']}, not {default}: "
                                   f"ak lands a seat's own PR on {default} only. If it builds on "
                                   f"an unmerged change, wait for that to land, then rebase this "
                                   f"branch onto origin/{default} and point the PR at {default}")
            head = info["headRefOid"]
            fetch_pr(checkout, number, info["baseRefName"], log)
            target_sha = git(checkout, "rev-parse", f"origin/{info['baseRefName']}^{{commit}}")
            base_sha = git(checkout, "merge-base", target_sha, head)
            why = (own_pr_first_review(checkout, url, number, base_sha, target_sha, head, run_dir)
                   or (0, None))[1]
            if why:
                raise config.Error(why)
        repo, base, target = f"{owner}/{name}", info["baseRefName"], info["baseRefName"]
        if is_own:
            method, action = ("squash",
                              f"review {url} at {info['headRefOid']}; merge on PASS with green checks")
        else:
            method, action = ("none (review only)",
                              f"review {url} at {info['headRefOid']}; publish findings")
        commands = "AGENTS.md tests: command from the target, else the PR checkout"
    else:
        meta, body, title = taskfile.parse_task(run_dir / "task.md")
        state = run_record.read_state(run_dir) or {}
        state["title"] = title
        run_record.save_state(run_dir, state)
        cmds = taskfile.done_when(body, run_dir / "task.md")
        repo = task_repo(meta, run_dir / "task.md", state.get("task_file"))
        base = (meta.get("base") or default_base(repo, log)) if repo else "none"
        target, method = meta.get("target") or base, meta.get("merge") or "squash"
        # the checks a round runs, settled as the loop settles them, against the same target
        every, once = taskfile.group_commands(round_commands(
            cmds, repo, target, scratch=repo is None, landing=not opts["--no-merge"]))
        refusal = (taskfile.checks_refusal(every)
                   or from_refusal(run_dir / "task.md", (meta.get("from") or "").strip(), repo,
                                   opts["--no-worktree"]))
        if refusal:
            raise config.Error(refusal)
        commands = " ; ".join(every)
        if once:
            commands += f"{' ; ' if commands else ''}once: {' ; '.join(once)}"
        # What this run will deliver, settled before it ever waits for a slot: a scratch task
        # and `--no-merge` both push nothing, and the receipt is read long before the loop
        # writes the same answer into the full state -- `ak watch` reads it to know which
        # seats a logged-out gh is holding up.  So is the project its seat is filed under, the
        # same queued and once it works (`run_project`), and the seat is filed now.  Resolved
        # here because only the process that launched the run stands in the checkout the task
        # inherits when it names none, or the one a relative `repo:` means.
        checkout = task_project(repo if meta.get("repo") else None, state.get("task_file"))
        run_record.save_state(run_dir, {**(run_record.read_state(run_dir) or {}),
                             "repo": str(repo) if repo else None, "scratch": repo is None,
                             "no_merge": bool(opts["--no-merge"]) or repo is None,
                             "project": str(checkout) if checkout else None})
        join_session_project(state.get("launched_session"))
        branch = (git(repo, "rev-parse", "--abbrev-ref", "HEAD") if repo and opts["--no-worktree"]
                  else f"new ak/{slugify(title)} branch (unique suffix if needed)")
        action = (f"push {branch} to origin (fork if needed); PR into {target}; merge after PASS"
                  if repo and not opts["--no-merge"] else
                  "no push or merge; local commits" if repo else "deliver scratch workspace files")
        ignore_time_keys(run_dir, meta, log)
        if opts.get("--anyway"):
            # the run starts regardless; name the run it starts next to, read-only
            rivals = already_under_way(run_dir / "task.md", meta, title,
                                       taskfile.done_when(body, run_dir / "task.md"),
                                       exclude=run_dir)
            alongside = rivals[0]["id"] if rivals else None
    log("--- preflight")
    if alongside:
        log(f"--- preflight: started alongside {alongside} (--anyway)")
    log(f"repo: {repo or 'none (scratch)'} | base: {base} | target: {target} | merge: {method}")
    log(f"delivery: {action}")
    log(f"done-when: {commands}")
    for role in ("workers", "reviewers"):
        if state.get(role) is not None:
            log(f"{role}: {', '.join(state[role])}")
    log(f"limits: silence {state['silence_minutes']:g}m | "
        f"done-when ceiling {state['ceiling_hours']:g}h | git/gh {TOOL_CAP}s")
    # a job's task runs where its job puts it; every other launch is placed after this line
    log(f"scope: {scope_line(state) or ('none (foreground launch)' if state.get('job_id') else 'pending')}")
    log(f"result: {run_dir / 'result.md'} | log: {run_dir / 'log.txt'}")
    session = launch_session(run_dir)
    if url:
        if state.get("own_pr"):
            log("notification: verdict on GitHub; PASS with green checks merges, FAIL hands back "
                "to the seat (stderr if unconfigured)")
        else:
            log(f"notification: verdict on GitHub; PASS with green checks offered to {config.inbox()} "
                "and needs to Discord (stderr if unconfigured)")
    else:
        log(f"notification: {session}; dead-seat fallback: needs to Discord if that seat is gone "
            "at the end (stderr if unconfigured)" if session else
            "notification: none: no orchestrator session launched this run, so nothing is sent; "
            "the result is here and in `ak run status`")


def scope_line(state):
    """Where the receipt says the run is: its unit, or `none (why)`; None before it is placed."""
    scope = state.get("scope")
    if scope == "none":
        scope = f"none ({state.get('scope_reason') or 'plain process session'})"
    return scope


def update_scope_line(run_dir, state):
    """Append the detached placement after it starts, without racing its live log writer."""
    scope = scope_line(state)
    if not scope:
        return
    path = Path(run_dir) / "log.txt"
    try:
        with path.open("a") as fh:
            fh.write(f"[{datetime.now():%H:%M:%S}] scope: {scope}\n")
    except OSError:
        pass


def finish(state, run_dir, log, cfg=None):
    settle_delivered_line(state, log)
    try:
        start_followups(state, run_dir, log, cfg)
    except run_record.StopRequested as exc:
        # A stop on a fix run being launched is that fix's failure, not this
        # run's: only this run's own `stopped` receipt aborts its ending.
        if (run_record.read_state(run_dir) or {}).get("state") == "stopped":
            raise
        log(f"WARN could not start follow-ups: {exc}")
    except Exception as exc:  # noqa: BLE001 - the ending matters, not the follow-ups
        log(f"WARN could not start follow-ups: {exc}")
    try:
        redress_seat(launched_session(state))   # the ending lands on the bar too
    except run_record.StopRequested:
        raise
    except Exception as exc:  # noqa: BLE001 - the ending matters, not the bar
        log(f"WARN could not redraw the seat's bar: {exc}")
    announce(state, run_dir, log, cfg)
    history_finish(state, log)
    worktrees.settle_run(run_record.read_state(run_dir) or state, run_dir, log)
    if state["state"] == "error":
        log(f"FAIL -> {run_dir / 'result.md'} (error)")
        return 2
    cfg = report_config(cfg)
    log(f"{delivery(state, cfg)} -> {run_dir / 'result.md'}")
    if state.get("state") == "not_needed":
        return 0
    if state.get("state") == "waiting" or not review_pass(state, cfg):
        return 1
    return 1 if state.get("merge_failed") else 0


def cmd_merge(argv):
    """Finish a saved PASS: retry its delivery PR, or the delivery that never reached one.

    A PASS whose push was rejected has no PR to verify and nothing to resume -- the work is
    reviewed and the rounds are spent -- so it is delivered again from the top instead of
    being a dead end.
    """
    if len(argv) != 1 or Path(argv[0]).name != argv[0] or argv[0] in (".", ".."):
        raise config.Error("usage: ak run merge <runid>")
    run_dir = config.RUNS / argv[0]
    # under the handoff lock: `watch.launch_resume` saves a detached retry's new scope
    # under it after the start, and a copy read before that would save the old one back
    with run_record.recovery_lock(run_dir) if run_dir.is_dir() else nullcontext():
        state = run_record.read_state(run_dir)
    if state is not None:
        # a finished PASS waits on no window: a quota mark left over from an earlier
        # stop is stale by definition, so a delivery retry that exhausts cannot
        # inherit it.
        state.pop("quota_dry", None)
    if not state or state.get("verdict") != "PASS" or state.get("state") != "pass":
        raise config.Error(f"{argv[0]}: merge requires a finished PASS")
    if stands_on_dependency(state):
        raise config.Error(f"{argv[0]}: {stands_on_dependency(state)}")
    if (state.get("review_pr") or state.get("scratch")
            or not (state.get("pr") or state.get("merge_failed"))):
        raise config.Error(f"{argv[0]}: no delivery PR to merge")
    box.check()
    cfg = config.load()
    if not review_pass(state, cfg):
        raise config.Error(f"{argv[0]}: merge requires a successful reviewer allowed by the model policy; "
                           f"run ak run resume {argv[0]} to obtain review")
    log = logger(run_dir)
    if state.get("merged"):
        log(delivery(state, cfg))
        return 0
    head = state.get("delivery_sha")
    if state.get("pr") and not head:
        raise config.Error(f"{argv[0]}: no recorded delivery SHA; cannot safely retry the merge")
    _, body, _ = taskfile.parse_task(run_dir / "task.md")
    cmds = with_suite(taskfile.done_when(body, run_dir / "task.md"), state["worktree"],
                      state.get("target") or state.get("base"))
    body += repo_rules(state["worktree"], state.get("base_sha"))
    run_record.save_state(run_dir, state)  # the Loop measures its saves against the record it is handed
    lp = Loop(cfg, run_dir, state, {}, log, Path(state["worktree"]),
              body, cmds, f"Repo checkout: {state['worktree']}\n\n{body}")
    # A delivery retry stays a delivery retry: a pickup would resume the run through
    # `drive` and re-verify a head this already checked and pushed.
    lp.no_pickup = True
    stopped_on = state.get("merge_note") or "delivery did not finish"
    # This process owns the run while it delivers: a retry that is killed here must leave a
    # `running` receipt with this pid on it, so the reaper -- the menu, `ak run status` or the
    # watch tick -- marks it interrupted, rather than a finished PASS with its failure cleared
    # off and nobody to pick it up.  The step is what `ak run status` shows while it works.
    state.update(state="running", merge_failed=False, merge_note=None, on_target=False,
                 reported=False, finished_at=None, **run_record.process_owner())
    # The delivery below runs fixer turns and gates outside run_slot: they still need
    # the run's marker, so this merge lends them its run context until it is done.
    previous = getattr(_RUN_CONTEXT, "state", {})
    _RUN_CONTEXT.state = state
    clear_delivery(state)
    # the merge step's time is checkpointed as a loop's is, so a retry killed here keeps it
    sampler = history.Sampler(run_dir.name, log=log)
    sampler.start()
    lp.step("merge")
    try:
        # A run whose push was rejected has no PR to check; there is a whole delivery to retry.
        info = pr_view(state["pr"]) if state.get("pr") else None
        if info is not None:
            if info.get("headRefOid") != head or info.get("baseRefName") != lp.target.removeprefix("origin/"):
                note(lp, "PR head or target changed since PASS; a new run is required", failed=True)
            elif info.get("state") == "MERGED":
                # a delivery whose merge went through before its record did: what proving
                # it live stands on is recorded here as on every merge path
                state.update(merged=True, **watch.merge_record(lp.wt, head))
            elif info.get("state") != "OPEN":
                note(lp, "PR is closed without a merge", failed=True)
        if not state.get("merged") and not state.get("merge_failed"):
            require_review_pass(lp)
            if info and state["review"].get("head_sha") != head:
                raise Exhausted("saved delivery SHA has no matching done-when and review; "
                                "resume the run to obtain review")
            if state.get("repo"):
                os.environ.update(config.repo_env(Path(state["repo"])))
            if info is None:
                log(f"no delivery PR: {stopped_on}; delivering again from integration")
                merge(lp)
            else:
                upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
                upstream_repo, permission = rights(lp)

                def deliver():
                    return ((git(lp.wt, "rev-parse", "HEAD") == head or push(lp))
                            and wait_checks(lp, state["pr"])
                            and do_merge(lp, state["pr"], upstream))

                if upstream_repo and permission not in PUSH_RIGHTS:
                    verify = lambda: (integrate(lp, upstream)
                                      and (git(lp.wt, "rev-parse", "HEAD") == head
                                           or final_check(lp, upstream)))
                    land(lp, upstream, verify, deliver)
                else:
                    join_line(lp, upstream, deliver)
    except worker.LoginExpired as expired:
        # a conflict fixer's turn during delivery can hit an expired login like any other:
        # a retry would park it anyway, and letting it escape here would leave the receipt
        # saying `running` with this pid on it for the reaper to call an interruption
        state.update(state="waiting_login", waiting_for=expired.harness, error=str(expired))
        note(lp, str(expired), failed=True)
    except Killed as exc:
        # ... and a conflict fixer killed twice is parked the same way, as the
        # interruption it is, rather than escaping into a finished PASS with its
        # failure cleared off and nobody to pick it up
        interrupt(state, str(exc))
        note(lp, str(exc), failed=True)
    except Exhausted as exc:
        park_exhausted(state, exc)
        note(lp, str(exc), failed=True)
    except Dead as exc:
        state.update(state="error", verdict="ERROR", error=str(exc), finished_at=time.time())
        park_error(run_dir, state)
        note(lp, str(exc), failed=True)
    except Blocked as exc:
        # a fixer here can say the task is wrong as readily as one in a round: the delivery
        # retry ends `blocked` with the section, and no later command picks it up
        state.update(state="blocked", verdict="BLOCKED", error=str(exc), blocked=exc.section)
        note(lp, str(exc), failed=True)
    except config.Error as exc:
        # a git or gh that stopped -- including the one that reads the PR -- must leave this
        # run retryable by the same command, not raise past the receipt that says so; with the
        # review invalidated by integration it is `ak run resume` that finishes it instead
        if state.get("review_pending"):
            park_exhausted(state, exc)
        else:
            state["state"] = "pass" if review_pass(state, cfg) else "fail"
        note(lp, str(exc), failed=True)
    else:
        if state.get("state") != "waiting":
            state["state"] = "pass" if review_pass(state, cfg) else "fail"
    finally:
        _RUN_CONTEXT.state = previous
        sampler.stop()
        sampler.join(timeout=2)
        history.close_step(run_dir.name, log=log)
    state["finished_at"] = (None if state.get("state") == "waiting"
                            and (state.get("waiting_on") or {}).get("line") else time.time())
    run_record.save_state(run_dir, state)
    write_result(run_dir, state, cmds, log, cfg)
    if state.get("state") == "waiting" and (state.get("waiting_on") or {}).get("line"):
        follow = foreground_cli(run_dir)
        offset = (run_dir / "log.txt").stat().st_size if follow else 0
        release_line(run_dir, note_in(run_dir / "log.txt") if follow else log)
        return follow_run(run_dir, cfg, offset) if follow else 0
    result = finish(state, run_dir, log, cfg)
    stop_run_tree(state, log)
    return result


def cmd_resume(argv):
    """Resume interrupted/exhausted work or obtain the review missing from a legacy PASS."""
    if depth_refused():
        return 2
    try:
        return resume_run(argv)
    except (config.Error, OSError) as exc:
        # A queued child that cannot replay its saved task/workspace must release its
        # place, otherwise every later receipt would wait behind it forever.
        child = os.environ.get(config.RUN_DIR_ENV)
        if child:
            directory = Path(child)
            if not directory.is_dir():
                raise
            with run_record.recovery_lock(directory):
                state = run_record.read_state(directory) or {}
                if (state.get("state") == "queued" and state.get("slot_waiting") and
                        state.get("pid") == os.getpid()):
                    # the ending is announced from here on, and a hand-back naming a
                    # result.md nothing wrote -- or the attempt before this one's -- is no
                    # hand-back: the reason goes in the file before anything reads it
                    state = mark_state(directory, "error", str(exc))
                    record_result(directory, state, logger(directory))
                stop_run_tree(state)
        raise


def resume_run(argv):
    ids = [arg for arg in argv if not arg.startswith("-") and arg != "--bg"]
    if ids and jobs.receipt_path(config.JOBS / ids[0]).exists():
        result = jobs.cmd_job_resume(argv)
        if result is not None:
            return result
    background = "--bg" in argv
    argv = [arg for arg in argv if arg != "--bg"]
    requested = list(argv)
    n_rounds = None
    if len(argv) == 3 and argv[1] == "--rounds" and argv[2].isdigit() and int(argv[2]) > 0:
        n_rounds = int(argv[2])
        argv = argv[:1]
    if len(argv) != 1 or Path(argv[0]).name != argv[0] or argv[0] in (".", ".."):
        raise config.Error("usage: ak run resume <runid> [--rounds N] [--bg]")
    refusal = taskfile.rounds_refusal(n_rounds, "--rounds")
    if refusal:
        raise config.Error(refusal)
    config.ensure_dirs()
    run_dir = config.RUNS / argv[0]
    state = run_record.read_state(run_dir) if (run_dir / "run.json").exists() else None
    if state is None:
        raise config.Error(f"no resumable run: {argv[0]} (looked in {config.RUNS})")
    box.check()
    # spawn_bg has already handed this queued receipt to this particular child. Ordinary
    # invocations must never adopt another process's launch, even with an inherited variable.
    with run_record.recovery_lock(run_dir):
        state = run_record.read_state(run_dir)
    # The lander's verdict authorizes the member to take back its own record.
    if landing_line(state) and not any(key in state["waiting_on"] for key in ("land", "fix")):
        raise config.Error(f"{argv[0]} is in line to land; only the lander moves it")
    child = (os.environ.get(config.RUN_DIR_ENV) == str(run_dir) and
             state.get("state") == "queued" and state.get("resume_from") and
             state.get("pid") == os.getpid() and run_record.process_active(state))
    pickup = state.get("pickup") if isinstance(state.get("pickup"), dict) else None
    in_place = (pickup is not None and not background and not child
                and state.get("state") == "running"
                and pickup.get("pid") == os.getpid()
                and state.get("pid") == os.getpid()
                and run_record.process_active(state))
    if in_place:
        # The same process, new code: the pickup before a round exec'd to this resume.
        # The pid, the scope and the slot stay the same, so the run is not queued
        # again, and a saved PASS is kept as a resume keeps it.
        old, new = pickup.get("from"), pickup.get("to")
        expected = dict(state)
        wt = Path(state["worktree"]) if state.get("worktree") else None
        if wt is not None and not wt.is_dir():
            raise config.Error(f"{argv[0]}: its worktree {wt} is gone; there is nothing to resume")
        if n_rounds is not None:
            if n_rounds < (state.get("rounds") or 0):
                raise config.Error("--rounds cannot reduce the saved round budget")
            over_lineage(state, run_dir, n_rounds)
            state["rounds"] = n_rounds
        state.pop("pickup", None)
        state.setdefault("merge_method", "squash")
        state.setdefault("target", state.get("base"))
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": bool(state.get("no_merge")),
                "--no-worktree": bool(state.get("repo")) and wt == Path(state["repo"]),
                "--bg": False}
        with gate.slot_lock(), run_record.recovery_lock(run_dir):
            if run_record.read_state(run_dir) != expected:
                raise config.Error("the run changed while choosing recovery; select it again")
            run_record.save_state(run_dir, state)
        cfg = config.load()
        log = logger(run_dir)
        log(f"picked up agentkit {old}..{new}; continuing on it")
        if state.get("review_pr"):
            # a review reads its options every round, its reviewer among them: the moved
            # process goes on with the ones it had
            opts = pickup.get("opts") or opts
            return drive(cfg, run_dir, opts, log,
                         job=lambda: review_pr(cfg, run_dir, state["review_pr"], opts, log))
        return drive(cfg, run_dir, opts, log, prior=state)
    if not child and state.get("state") in run_record.ACTIVE:
        if run_record.process_active(state):
            raise config.Error(f"{argv[0]} is still running as pid {state['pid']}")
        state = reap(run_dir, state)
    if state.get("state") == "blocked":
        # The task itself is what failed, so there is nothing here to carry on: another
        # round would spend a model turn to be told the same thing again.
        raise config.Error("blocked runs are not resumed; the orchestrator writes a new task")
    if state.get("state") == "not_needed":
        raise config.Error(f"not needed: {state['not_needed']}")
    if state.get("state") == "stopped":
        # A deliberate end, not an accident: there is nothing to carry on, and the
        # branch the stop printed is what a relaunch starts from.
        raise config.Error("stopped runs are not resumed; start a new task from its branch")
    # The tick stopped a silent loop and ordered this resume, or is holding a dead one
    # through its backoff: the record still says `running`, which is the order itself,
    # not a live run to refuse.
    tick_resume = (not child and state.get("state") == "running"
                   and any(isinstance(state.get(key), (int, float))
                           and not isinstance(state.get(key), bool)
                           for key in ("stall_resume_at", "resume_after")))
    expected = dict(state)
    queued_resume = state.get("state") == "queued" and state.get("slot_waiting")
    if child:
        state["state"] = state.pop("resume_from")
        state.pop("stall_resume_at", None)
    elif state.get("state") == "queued" and state.get("slot_waiting"):
        state["state"] = state.pop("resume_from", "interrupted")
    cfg = config.load()
    legacy_pass = (state.get("state") == "pass" and not state.get("merged")
                   and not state.get("review_pr") and
                   (not review_pass(state, cfg) or (state.get("repo") and
                    state["review"].get("head_sha") != git(state["worktree"], "rev-parse", "HEAD"))))
    # A FAIL that only ran out of rounds continues on its saved work, but the rounds are what
    # it ran out of: without more of them the resume has nothing to spend. Checked before
    # `needs_recovery`, because a resume of its own records `recovery_pending`, and a second
    # FAIL at the same cap must be refused exactly like the first rather than repeat itself.
    at_budget = failed_at_budget(state)
    if at_budget:
        # the change's budget with this run's own rounds counted: spent, no --rounds carries
        # it on and the task is what changes; else the way on names the bound `over_lineage`
        # holds a --rounds to
        left, why = change_budget(state, run_dir, taskfile.TASK_MAX_ROUNDS, own=state["rounds"])
        if why:
            raise config.Error(f"{argv[0]} FAILed at its round budget ({state['rounds']}); {why}")
        if n_rounds is None or n_rounds <= state["rounds"]:
            raise config.Error(f"{argv[0]} FAILed at its round budget ({state['rounds']}); "
                               f"give --rounds N above it, at most {state['rounds'] + left}, to continue")
    # A FAIL recorded by integration below its budget carries its branch and its rounds
    # with it: the work is reviewed and only the merge is left to try again.
    integration_fail = failed_in_integration(state, run_dir)
    # A judged FAIL after the rebase with rounds left carries its branch, its rounds and
    # the reviewer's findings with it: a fixer round works through them, then review,
    # then the merge -- the way a FAIL at budget continues after `--rounds`, but with
    # the rounds it still has.  No `recovery_pending` is required for either path.
    judged_fail = judged_in_integration(state, run_dir)
    # Classified here, before the stale delivery note below is cleared: the resume
    # recovery that follows needs to know the FAIL came from integration.
    integration_record = integration_note(state, run_dir)
    # Exhaustion leaves work waiting for a provider. An unverified legacy PASS also needs
    # review; a completed, verified run must not push a branch its merge already deleted.
    # An error is unfinished work too: whatever stopped it -- a dead provider, a killed
    # tool -- the tick retries it on its ladder, and a hand on the command may hurry it.
    # A merge wait also resumes with its saved budget: conflict rounds spend no task round.
    parked = state.get("state") in ("error", "waiting")
    if (not needs_recovery(state) and not legacy_pass and not at_budget and not tick_resume
            and not integration_fail and not judged_fail and not queued_resume
            and not parked):
        raise config.Error(f"{argv[0]} is {state.get('state')!r}, not interrupted or exhausted; "
                           "only unfinished work or an unverified PASS can be resumed")
    # An abandoned queued launcher has not allocated its workspace yet. Replay only the
    # saved task/launch options, on an explicit resume. Old receipts have no option record;
    # the conservative fallback keeps all work local instead of guessing permission to push.
    unstarted = not state.get("worktree")
    needed = () if unstarted else (("worktree", "rounds") if state.get("scratch") else (
        "repo", "worktree", "branch", "base", "base_sha", "rounds"))
    for key in needed:
        if not state.get(key):
            raise config.Error(f"{argv[0]}: run.json records no {key}; there is nothing to resume")
    wt = Path(state["worktree"]) if not unstarted else None
    if wt is not None and not wt.is_dir():
        raise config.Error(f"{argv[0]}: its worktree {wt} is gone; there is nothing to resume")
    if not state.get("review_pr"):
        _, body, _ = taskfile.parse_task(run_dir / "task.md")
        taskfile.done_when(body, run_dir / "task.md")
    if n_rounds is not None:
        if n_rounds < (state.get("rounds") or 0):
            raise config.Error("--rounds cannot reduce the saved round budget")
        over_lineage(state, run_dir, n_rounds)
        state["rounds"] = n_rounds
    # A failed review or aborted integration carries a stale pending review. A
    # landing gate wait keeps its non-task review so recovery first updates the
    # target, then fixes and reviews without spending another task round.
    # Its delivery note is stale in the same way -- what it says did not deliver is exactly
    # what this resume is about to do again -- so it goes too, the way `ak run merge` drops it
    # before its own retry; `note` writes a fresh one the moment anything fails again.
    if state.get("state") in ("fail", "waiting"):
        if (state.get("state") == "fail"
                or (state.get("review_pending") or {}).get("record") is not False):
            state.pop("review_pending", None)
        state.update(merge_failed=False, merge_note=None)
    if integration_record and (state.get("review_pending") or {}).get("record") is not False:
        # Resume at the integration step, not with another executor round: the branch is
        # saved and only the merge is left to try again.  Integration invalidated the saved
        # PASS verdict when it started, so without this `drive` enters ordinary rounds and
        # spends a fixer turn on work nobody faulted.  Classified without regard to budget,
        # so an integration FAIL at its budget resumes the same way once `--rounds` grows.
        try:
            identity = commit_identity(wt) if wt is not None and wt.is_dir() else {}
        except config.Error:
            identity = {}
        if not identity.get("head_sha") or not identity.get("tree_sha"):
            identity = {}
        review = state.get("review")
        if (identity and isinstance(review, dict) and review.get("verdict") == "PASS"
                and review.get("done_when") is True
                and review.get("head_sha") == identity["head_sha"]
                and review.get("tree_sha") == identity["tree_sha"]):
            state["verdict"] = "PASS"
        elif identity:
            summaries = state.get("round_summaries") or []
            match = next((e for e in reversed(summaries)
                          if e.get("verdict") == "PASS" and e.get("done_when") is True
                          and e.get("head_sha") == identity["head_sha"]
                          and e.get("tree_sha") == identity["tree_sha"]), None)
            if match is not None:
                try:
                    exec_provider, review_provider = review_providers(
                        cfg, state["executor"], state["reviewer"])
                except config.Error:
                    exec_provider = review_provider = None
                if exec_provider and review_provider:
                    state["review"] = {
                        "executor": state["executor"], "executor_provider": exec_provider,
                        "reviewer": state["reviewer"], "reviewer_provider": review_provider,
                        "returncode": 0, "verdict": "PASS", "done_when": True,
                        "head_sha": identity["head_sha"], "tree_sha": identity["tree_sha"]}
                    state["verdict"] = "PASS"
            if state.get("verdict") != "PASS":
                # a finished-but-unverified tree, as the reported race left behind: no
                # recorded review covers this HEAD, so re-verify it in place.  A pending
                # review spends the round number below, never an executor turn.
                last = summaries[-1] if summaries else {}
                state["review_pending"] = {
                    "round": len(summaries) + 1,
                    "summary": last.get("summary") or "",
                    "reason": "Resume the unfinished integration review."}
    state.setdefault("merge_method", "squash")
    # a run.json written before `target:` existed merged into its base, and still should
    state.setdefault("target", state.get("base"))
    # --no-merge was a choice about this run, not about this invocation: run.json keeps it
    opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
            "--no-merge": bool(state.get("no_merge")),
            "--no-worktree": bool(state.get("repo")) and wt == Path(state["repo"]),
            "--bg": False}
    if unstarted:
        opts.update(state.get("launch_opts") or {"--no-merge": True})
        if n_rounds is not None:
            opts["--rounds"] = str(n_rounds)
    if background:
        return spawn_bg(run_dir, ["resume", *requested], expected=expected)
    if (not child and not state.get("no_merge") and not state.get("scratch")
            and foreground_cli(run_dir)):
        offset = (run_dir / "log.txt").stat().st_size
        spawn_bg(run_dir, ["resume", *requested], expected=expected)
        return follow_run(run_dir, cfg, offset)
    with gate.slot_lock(), run_record.recovery_lock(run_dir):
        if run_record.read_state(run_dir) != expected:
            raise config.Error("the run changed while choosing recovery; select it again")
        state.update(resume_from=state["state"], state="queued", slot_waiting=True,
                     queued_at=(expected.get("queued_at") if expected.get("state") == "queued"
                                else None) or time.time(),
                     **run_record.process_owner(), recovery_pending=not legacy_pass,
                     recovery_acknowledged_at=None, error=None, finished_at=None)
        clear_delivery(state)
        # the harness a login parked it on, and the stamps that paced and released the
        # retry: this resume is the answer to all of them, and a later stop for another
        # reason must not inherit any
        for key in ("waiting_for", "login_resume_at", "login_back_at"):
            state.pop(key, None)
        # the wait this resume answers is over too: main moved, or a hand hurried it
        if not (state.get("waiting_on") or {}).get("line"):
            state.pop("waiting_on", None)
        state.pop("waiting_resume_at", None)
        state.setdefault("run_depth", run_depth())
        if not queued_resume:
            # A new queue episode starts with no memory of the last one's wait.
            for key in ("slot_waited", "slot_wait_reason", "slot_wait_kind"):
                state.pop(key, None)
        # the ordered resume has adopted the record, and no backoff outlives it
        state.pop("stall_resume_at", None)
        state.pop("resume_after", None)
        state.pop("pickup", None)
        run_record.save_state(run_dir, state)
    log = logger(run_dir)
    log(f"resume {run_dir.name}: {run_dir / 'task.md'}")
    if not child:
        # the loop goes on from this copy and saves it: it carries the new scope, not the last
        state = place_here(run_dir, log) or state
    if unstarted and not state.get("launch_opts"):
        log("old launch receipt has no saved options; recovery keeps work local (--no-merge)")
    if state.get("review_pr"):
        return drive(cfg, run_dir, opts, log,
                     job=lambda: review_pr(cfg, run_dir, state["review_pr"], opts, log))
    return drive(cfg, run_dir, opts, log, prior=None if unstarted else state)


def drive(cfg, run_dir, opts, log, prior=None, job=None):
    """The loop plus every way it can end: one place decides the exit code and who is told."""
    global _PICKUP_START
    if _PICKUP_START is None:
        try:
            _PICKUP_START = installed_head() or None
        except Exception:
            pass
    existing = run_record.read_state(run_dir)
    if existing is not None and existing.get("state") == "stopped":
        return 1  # a stop landed before this attempt started; the record stands as left
    sampler = history.Sampler(run_dir.name, log=log)
    stop_after_finally = False
    sampler.start()
    try:
        with run_slot(run_dir, prior):
            state = job() if job else loop(cfg, run_dir, run_dir / "task.md", opts, log, prior)
    except run_record.StopRequested:
        # A stop landed mid-attempt: the disk already says `stopped`, so there is
        # nothing to write and -- a deliberate end -- nothing to announce either.
        return 1
    except worker.LoginExpired as expired:
        # Nothing was executed and nothing was judged: the harness could not authenticate.
        # So the run waits for that login instead of dying on it -- `error` at one in the
        # morning is a remedy nobody can act on until somebody wakes up -- and the tick
        # resumes it the moment that harness's `auth` verb passes, on the same worktree,
        # the same round and the same conversation.
        log(f"waiting for login: {expired}")
        # the harness goes down before the state word does, so there is never a
        # `waiting_login` receipt on disk without the login it names: a tick that read one
        # between the two writes would have a parked run and nothing to watch for it
        parked = run_record.read_state(run_dir) or {}
        parked["waiting_for"] = expired.harness
        run_record.save_state(run_dir, parked)
        state = mark_state(run_dir, "waiting_login", str(expired))
        record_result(run_dir, state, log, cfg)
        announce(state, run_dir, log, cfg)
        stop_run_tree(run_record.read_state(run_dir) or state, log)
        return 1
    except Killed as exc:
        # A worker turn killed by signal twice within a minute: nothing was executed and
        # nothing was judged, and retrying into it is how a run burns a night being
        # killed.  The run parks as an interruption -- resumable, reading `needs you`
        # with the signal for a reason -- on the worktree, the round and the session.
        log(f"killed: {exc}")
        parked = run_record.read_state(run_dir) or {}
        interrupt(parked, str(exc))
        run_record.save_state(run_dir, parked)
        state = parked
        record_result(run_dir, state, log, cfg)
        announce(state, run_dir, log, cfg)
        stop_run_tree(run_record.read_state(run_dir) or state, log)
        return 1
    except (Exhausted, Stopped) as exc:
        # Both leave work a later run can pick up -- a provider that is spent, or a git or gh
        # that stopped -- and `exhausted` is the state the menu and `ak run resume` offer
        # recovery for.  An `error` here would be a remedy nothing can act on.  Only the
        # quota kind waits on a window: the tick resumes nothing else by itself.
        log(f"exhausted: {exc}")
        state = mark_state(run_dir, "exhausted", exc, log)
        record_result(run_dir, state, log, cfg)
        announce(state, run_dir, log, cfg)
        stop_after_finally = True
        return 1
    except config.Error as exc:
        # why it stopped -- a killed git or gh call says what to do about it -- belongs in
        # result.md too, not only in the log and the exception the caller prints
        state = mark_state(run_dir, "error", str(exc), log)
        record_result(run_dir, state, log, cfg)
        announce(state, run_dir, log, cfg)
        stop_after_finally = True
        raise
    except Exception as exc:  # noqa: BLE001 - a crashed run must still leave its state on disk
        log(f"error: {exc!r}")
        state = mark_state(run_dir, "error", repr(exc), log)
        record_result(run_dir, state, log, cfg)   # the hand-back names it; it has to exist
        announce(state, run_dir, log, cfg)
        stop_after_finally = True
        return 2
    finally:
        sampler.stop()
        sampler.join(timeout=2)
        # the loop's work ends here however it ended, parked or killed with no receipt of it
        history.close_step(run_dir.name, log=log)
        latest = history.sample_rss(run_dir.name, log=log)
        if latest is not None:
            state = run_record.read_state(run_dir) or state
            state["peak_rss_mb"] = max(float(state.get("peak_rss_mb") or 0), latest)
            run_record.save_state(run_dir, state)
        if stop_after_finally:
            stop_run_tree(run_record.read_state(run_dir) or state, log)
        # Endings that raise never reach finish(); the checkout and the tabs still go.
        try:
            settled = run_record.read_state(run_dir) or state
        except NameError:
            settled = None  # the stop landed before the loop saved anything
        if isinstance(settled, dict):
            worktrees.settle_run(settled, run_dir, log)
    if state.get("state") == "waiting" and (state.get("waiting_on") or {}).get("line"):
        release_line(run_dir, log)
        return 0
    result = finish(state, run_dir, log, cfg)
    stop_run_tree(run_record.read_state(run_dir) or state, log)
    return result


def follow_run(run_dir, cfg, offset=0):
    """A foreground terminal follows the record and log, outside the worker's scope."""
    with (run_dir / "log.txt").open() as output:
        output.seek(offset)
        def show():
            print(output.read(), end="", flush=True)

        state = jobs.job_await(run_dir, poll=show)
        show()
    if state.get("state") == "error":
        return 2
    if state.get("state") == "not_needed":
        return 0
    return 0 if (state.get("state") == "pass" and review_pass(state, cfg)
                 and not state.get("merge_failed")) else 1


# --- a PR reviewed alone: the reviewer only ------------------------------------


def pr_view(url):
    """The PR as GitHub describes it, its state, base and head as one `pr_head` read gives them:
    a state from another read beside that head could name a merge of a commit that never merged."""
    data, why = gh_json(config.RUNS, "pr", "view", url, "--json", "number,title,body,author,url,isDraft")
    if not isinstance(data, dict):
        raise config.Error(f"gh pr view {url} failed: {why}")
    author, current = data.get("author") or {}, pr_head(config.RUNS, url)
    data.update(author=author.get("login") or "?", headRefOid=current["head"]["sha"],
                baseRefName=(current.get("base") or {}).get("ref"),
                state="MERGED" if current.get("merged") else (current.get("state") or "?").upper())
    return data


def fetch_pr(repo, number, base, log):
    """GitHub can publish a PR before its pull ref: wait for that ref alone."""
    ref = f"pull/{number}/head"
    for tried in range(GITHUB_RETRIES + 1):
        code, out = fetch(repo, "origin", ref, base)
        if code == 0:
            return
        if out != f"fatal: couldn't find remote ref {ref}" or tried == GITHUB_RETRIES:
            raise config.Error(f"git fetch origin {ref} {base} failed in {repo}: {out}")
        delay = turns.transient_delay(tried + 1)
        log(f"WARN GitHub has not published {ref}; fetching again in {delay}s "
            f"({tried + 1}/{GITHUB_RETRIES})")
        time.sleep(delay)


def viewer_login():
    """This host's GitHub login, or None when gh cannot say.

    Unknown means not the seat's own PR: a review that cannot tell whose PR it
    is asks the inbox, never merges.
    """
    try:
        data, _ = gh_json(config.RUNS, "api", "user")
    except (Stopped, config.Error, OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("login"), str) and data["login"]:
        return data["login"]
    return None


def by_viewer(author):
    """Whether `author` is this host's GitHub login, the account ak posts with; unknown is not."""
    if not author or author == "?":
        return False
    try:
        viewer = viewer_login()
    except Exception:  # noqa: BLE001 - an unknown login is nobody's
        return False
    return bool(viewer) and author.lower() == viewer.lower()


def own_pr_orchestrator(cfg, session_name, author):
    """(is_own, orchestrator) for a --review-pr of `author` launched from `session_name`.

    The seat's own PR is a review launched from a seat on a PR by this host's
    GitHub login: the orchestrator did the work itself and opened the PR, so its
    reviewer is picked against that model as if it had executed, through the
    same `reviewer_order` preference. Ownership is the launch plus the author; the
    orchestrator is the writer whose identity the independence check needs. An
    own PR with no session record or an unknown orchestrator model keeps its
    classification but cannot be reviewed or merged until the writer is known.
    """
    if not session_name or not by_viewer(author):
        return False, None
    try:
        selection = config.load_session(cfg, session_name, required=False)
        orchestrator = (selection or {}).get("orchestrator")
        if not orchestrator:
            return True, None
        config.model(cfg, orchestrator)
    except (config.Error, OSError, ValueError, KeyError, TypeError):
        return True, None
    return True, orchestrator


def pr_writer(cfg, state, session_name, author):
    """(is_own, orchestrator, effort) for the review `state` records: the writer it captured at
    launch, in preflight or the first attempt, or carried from a stopped run (`leases.restart`),
    stands -- a session record rewritten since must not replace it, or the reviewer's
    independence check would judge another model than the one that wrote this -- and a record
    with none asks the seat (`own_pr_orchestrator`).  A captured model the config no longer
    names is unknown, as the seat's would be.  The effort is the writer's as it was captured
    (the config's for its orchestrator role then; a record from before it was kept has none),
    never the config's since: `ak models` counts the pull request under it."""
    if "own_pr" not in state:
        is_own, orchestrator = own_pr_orchestrator(cfg, session_name, author)
        return is_own, orchestrator, config.worker_effort(cfg, orchestrator, "orchestrator")
    orchestrator = state.get("own_orchestrator") if state["own_pr"] else None
    if orchestrator:
        try:
            config.model(cfg, orchestrator)
        except (config.Error, OSError, ValueError, KeyError, TypeError):
            orchestrator = None
    effort = state.get("own_orchestrator_effort") if orchestrator else None
    return bool(state["own_pr"]), orchestrator, effort


def checkout_for(name_with_owner, log):
    """The checkout of that GitHub repo (`orch.checkouts`, so agentkit's own is ~/agentkit),
    cloned under ~/code with gh if there is none yet."""
    want = name_with_owner.lower()
    for path in orch.checkouts():
        remote = git(path, "remote", "get-url", "origin", check=False)
        tail = "/".join(remote.rstrip("/").removesuffix(".git").replace(":", "/").split("/")[-2:])
        if tail.lower() == want:
            return path
    target = config.CODE / name_with_owner.split("/")[1]
    if target.exists():
        raise config.Error(f"{target} exists and is not a clone of {name_with_owner}")
    config.CODE.mkdir(mode=0o700, parents=True, exist_ok=True)
    log(f"cloning {name_with_owner} into {target}")
    rc, out = gitcall.gh(config.CODE, "repo", "clone", name_with_owner, str(target), "--", "-q")
    if rc != 0:
        if stopped(rc, out):
            raise Stopped(out)
        raise config.Error(f"gh repo clone {name_with_owner} failed: {out[-400:]}")
    return target


def post_review(lp, url, verdict):
    """The findings, as a GitHub review: a comment on PASS, changes requested on FAIL.

    A PR the account ak posts with opened always comments, the seat's own or not: GitHub
    rejects a changes-requested review from the PR's author, which would turn a FAIL into
    an error.
    """
    head = lp.state["head_sha"]
    lp.state["review_posted"] = False
    lp.state.pop("review_stale", None)
    lp.state.pop("review_error", None)
    try:
        current = pr_view(url)
    except Stopped:
        raise
    except config.Error as exc:
        lp.state["review_error"] = f"cannot verify the PR head: {exc}"
        lp.write()
        return False
    if current["headRefOid"] != head or current.get("state") != "OPEN":
        lp.state["review_stale"] = True
        lp.state["review_error"] = "PR head changed or closed; discarded review"
        if not lp.state.get("own_pr"):
            lp.state["review_error"] += "; watcher will re-queue"
        lp.log(f"WARN {lp.state['review_error']}")
        lp.write()
        return False
    path = lp.run_dir / "review.md"
    path.write_text(github_body(
        f"agentkit review of {head[:12]} by {lp.reviewer} (run {lp.run_dir.name})\n\n"
        + overridden_section(lp.state) + lp.findings.strip() + "\n", lp.run_dir.name))
    how = ("COMMENT" if verdict == "PASS" or lp.state.get("own_pr") or by_viewer(lp.state.get("author"))
           else "REQUEST_CHANGES")
    owner, repo, number = PR_PARTS.match(url).groups()
    rc, out = gitcall.gh(lp.run_dir, "api", f"repos/{owner}/{repo}/pulls/{number}/reviews",
                 "--method", "POST", "-f", f"commit_id={head}", "-f", f"event={how}",
                 "-F", f"body=@{path}")
    lp.state["review_posted"] = rc == 0
    if rc == 0:
        lp.log(f"--- review posted to {url} ({how})")
    else:
        lp.state["review_error"] = f"gh api review {how} exited {rc}: {out[-300:]}"
        lp.log(f"WARN could not post the review to {url}: {out[-300:]}")
    lp.write()
    return rc == 0


def own_pr_fix(state):
    """(round, turn name) of the fix a seat's own PR's next head comes from, which its review
    shares: the next round's `executor`, or a landing red's (`landing_fix`) in the round whose
    PASS it repairs, under a name for each red, so neither that round's fixer nor an earlier
    red's stands for it, and the next round still starts in a directory of its own."""
    done = len(state.get("round_summaries") or [])
    if state.get("landing_fix"):
        return done, f"landing-{sum(state.get(key, 0) for key in LANDING_COUNTS)}-fixer"
    return done + 1, "executor"


def pr_context(state, body):
    """What a worker on a PR review's checkout is told first: where it is and on what branch."""
    number = PR_PARTS.match(state["review_pr"]).group(3)
    return (f"Repo checkout: {state['worktree']}\nBranch: {state['branch']} (PR #{number} head, "
            f"based on origin/{state['target']})\n\n{body}")


def own_pr_first_review(repo, url, number, base_sha, target_sha, head, run_dir):
    """(the lines a seat's own PR's first review reads, the sentence refusing that review or
    None), or None where no first review is ahead: a PR of wording alone, or one a review
    already judged in this run or any, whose later rounds review whatever the fix left.  The
    seat builds under `task.SEAT_TASK_LINES` added lines, the ones moved unchanged aside
    and the files the target's tip marks generated, as the change will land on it, and a PR
    that re-adds most of a budget-failed one's lines, no real split of it, inherits that one's
    rounds (`replacement_refusal`)."""
    if text_only_pr(repo, base_sha, head) or change_reviewed(pr=url):
        return None
    lines, carried = diff_lines(repo, target_sha, head, added_only=True), carried_lines(repo, target_sha, head)
    read = lines - carried
    if read >= taskfile.SEAT_TASK_LINES:
        return read, (f"PR #{number} adds {read} lines (generated files and unchanged moves aside): "
                      f"too big for the seat, which builds under {taskfile.SEAT_TASK_LINES} added "
                      "lines. Write it as a task and launch it; a worker builds it")
    return read, replacement_refusal(repo, target_sha, head, number, read, exclude=run_dir)


def pr_review_blocked(lp, exc):
    """A PR review's blocked ending, from a round, its fixer turn or the size gate before any
    reviewer is picked: no reviewer's harness can run, the task cannot be done as written, or
    the PR is more than a first review takes.  Recorded as a task run's is, its result
    written, its wait for a push and its pending round over; never an `error` the tick would
    retry into the same harness."""
    lp.log(f"BLOCKED {exc}")
    lp.state.update({"state": "blocked", "verdict": "BLOCKED", "error": str(exc),
                     "blocked": exc.section, "finished_at": time.time()})
    for key in ("own_pr_wait", "own_pr_round_pending"):
        lp.state.pop(key, None)
    lp.write()
    write_result(lp.run_dir, lp.state, lp.cmds or ["(none declared)"], lp.log, lp.cfg)
    return lp.state


def pr_review_failed(lp, why):
    """A seat's own PR review's `fail` ending on a changed fact -- the PR closed, its head
    moved under a fix, a head that needs a round the change no longer has -- for its seat to
    decide.  Its result written, and nothing left to act on: no wait for a push, no pending
    round, no landing fix, no place in the line."""
    lp.state.update(state="fail", error=why, finished_at=time.time())
    for key in ("own_pr_wait", "own_pr_round_pending", "landing_fix", "waiting_on"):
        lp.state.pop(key, None)
    lp.write()
    write_result(lp.run_dir, lp.state, lp.cmds or ["(none declared)"], lp.log, lp.cfg)
    lp.log(f"FAIL {why}")
    return lp.state


def fix_own_pr(cfg, run_dir, url, state, opts, log):
    """The fixer turn a FAIL on a seat's own PR gets while rounds are left.

    The findings go to a model on the run's own checkout of the reviewed head, as a task
    run's fixer gets them, and what it commits is pushed to the PR branch over that head
    (`--force-with-lease`) for the next round to review.  Nothing is typed into the seat and
    no process waits for it: the seat hears the ending, as of any run.  A fixer that commits
    nothing -- a dispute, `not-needed` -- leaves the head where it is, reviewed again with
    what it handed in.  The push is written down (`delivery_sha`) before it is tried, so a
    resume after a crash pushes again instead of fixing twice.  A head pushed by
    hand before the fix starts is what the next round reviews; one pushed while the fix was
    made, or a PR closed, ends the run `fail`: a changed fact means a new review, never a fix
    pushed over somebody's commit.  Returns whether the next round may run.
    """
    reviewed = state["head_sha"]
    number = PR_PARTS.match(url).group(3)
    lp = pr_loop(cfg, run_dir, state, opts, log)
    lp.rnd, turn = own_pr_fix(state)
    state.update(state="running", **run_record.process_owner(), finished_at=None)
    run_record.save_state(run_dir, state)

    current = pr_head(lp.run_dir, url)
    if current.get("state") != "open":
        pr_review_failed(lp, f"{url} is {current.get('state', '?')}, not open")
        return False
    remote, pushed = current["head"], state.get("delivery_sha")
    if pushed == reviewed:
        # the landing's own delivery of the reviewed head, recorded before a required check
        # went red: no fix of this round was pushed
        pushed = None
    head = git(lp.wt, "rev-parse", "HEAD")
    if remote["sha"] != reviewed and remote["sha"] != pushed:
        if turns.latest_worker_turn(lp.round_dir, turn) is not None and not pushed:
            # the seat pushed while the fix was made (the turn cut off before its push):
            # never pushed over its commit, never reviewed as if it were the seat's
            pr_review_failed(lp, "the PR head moved while the fix was made; review it with a new run")
            return False
        # pushed by hand before the fix started, or after the fix was pushed: that head is
        # what the next round judges, from a checkout the round accepts, the reviewed head
        # or the fix it pushed (`own_pr_heads`)
        if not pushed and head != reviewed:
            git(lp.wt, "reset", "--hard", reviewed)
        # the seat's own head is reviewed as a round, as any new head is (`review_pr_round`
        # holds a landing fix to the heads the run wrote), and a head that needs a round the
        # change no longer has goes back to its seat
        why = own_pr_budget(url, run_dir, len(state.get("round_summaries") or []))[1]
        if why:
            pr_review_failed(lp, why)
            return False
        lp.write()
        log(f"the PR head moved to {remote['sha'][:12]} since the review; reviewing it")
        return True
    if not (pushed and pushed != reviewed and head == pushed):
        # the round's fixer turn, as its directory records it (`latest_worker_turn`, which
        # sees a turn handed to another model too): one that closed did its work and HEAD is
        # what it left; one the host cut off is resumed by execute on the checkout as it
        # left it, under its own name; none yet starts from the reviewed head
        turned = turns.latest_worker_turn(lp.round_dir, turn) is not None
        name = turns.open_worker(lp, turn)[0]
        if not (turned and name is None):
            if not turned and head != reviewed:
                git(lp.wt, "reset", "--hard", reviewed)     # the line left the checkout elsewhere
            if name is None:
                # a fresh turn is the seat's own model, headless: a fix to the orchestrator's
                # PR is its work; one cut off is resumed by the model it was handed to, which
                # execute recorded, and the next round's reviewer is picked against whoever
                # wrote the fix
                lp.executor = state["executor"] = state["own_orchestrator"]
            log(f"--- {'landing fixer' if state.get('landing_fix') else f'round {lp.rnd}/{lp.rounds}: fixer'} "
                f"{lp.executor} (findings on PR #{number})")
            lp.context = pr_context(state, fix_body(state, current.get("body"), lp.cmds, number)
                                    + repo_rules(lp.wt, state["base_sha"]))
            fix = f"{lp.context}\n\n## Reviewer findings to fix\n{without_followups(lp.findings)}"
            try:
                # what the fixer says stays in its turn's directory, where the next round's
                # record reads it (`fixer_words`), resumed after a cut or not
                execute(lp, "fixer", fix, name or turn)
            except Blocked as exc:
                pr_review_blocked(lp, exc)
                return False
        commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
        head = git(lp.wt, "rev-parse", "HEAD")
        # the PR as it stands after the fix, whatever the fix left: a closed PR or a head
        # pushed meanwhile ends the run, never a review of what the fixer did not see
        current = pr_head(lp.run_dir, url)
        remote = current["head"]
        if current.get("state") != "open":
            pr_review_failed(lp, f"{url} is {current.get('state', '?')}, not open")
            return False
        if remote["sha"] != reviewed:
            pr_review_failed(lp, "the PR head moved while the fix was made; review it with a new run")
            return False
        if head == reviewed:
            log("the fixer committed nothing; the next round reviews this head with what it handed in")
            lp.write()
            return True
        state["delivery_sha"] = head
        lp.write()
    if remote["sha"] != head:
        push_pr_branch(lp, remote, reviewed)
        log(f"--- pushed the fix {head[:12]} to {remote['ref']}")
    return True


def pr_loop(cfg, run_dir, state, opts, log):
    """A PR review's record as a loop, for the steps between its rounds: a merge, a settled
    round, a move onto new code.  Like every loop it writes back only what it changed."""
    _, body, _ = taskfile.parse_task(run_dir / "task.md")
    cmds = taskfile.done_when(body, run_dir / "task.md")
    return Loop(cfg, run_dir, state, opts, log, Path(state["worktree"]), body, cmds, body)


def review_pr(cfg, run_dir, url, opts, log):
    """Own PRs get a fixer turn between reviews; other authors get a single review."""
    while True:
        state = run_record.read_state(run_dir) or {}
        if state.get("own_pr_wait") and state.get("own_pr"):
            if not fix_own_pr(cfg, run_dir, url, state, opts, log):
                return state
            # the fix starts a round, and a round runs on the agentkit installed now
            pickup_new_code(pr_loop(cfg, run_dir, state, opts, log))
        if (state.get("waiting_on") or {}).get("line") and not state.get("merged"):
            # a merge already recorded is settled below, never sent back to a line that skips it
            state.update(state="running", **run_record.process_owner(), error=None, finished_at=None)
            run_record.save_state(run_dir, state)
            lp = pr_loop(cfg, run_dir, state, opts, log)
            merge_own_pr(lp, url)
            if state.get("state") != "waiting":
                state.pop("own_pr_round_pending", None)
            if state.get("state") != "waiting" and not state.get("own_pr_wait"):
                state.pop("waiting_on", None)
                state.update(state="pass" if state["verdict"] == "PASS" else "fail",
                             finished_at=time.time())
            lp.write()
            write_result(run_dir, state, lp.cmds or ["(none declared)"], log, cfg)
        elif (state.get("merged") or (state.get("own_pr") and state.get("own_pr_round_pending")
                                      and state.get("verdict"))):
            # A durable verdict still owes its post and delivery, even in round three or of
            # a landing fix's re-review, which records no round.
            state.update(state="running", **run_record.process_owner(), error=None, finished_at=None)
            run_record.save_state(run_dir, state)
            state = settle_pr_round(pr_loop(cfg, run_dir, state, opts, log), url, pr_view(url))
        else:
            state = review_pr_round(cfg, run_dir, url, opts, log)
        if not state.get("own_pr_wait"):
            return state


def review_pr_round(cfg, run_dir, url, opts, log):
    """Check out the PR head, have the reviewer judge it, post the verdict, land or offer."""
    receipt = run_record.read_state(run_dir) or {}
    workers, reviewers = config.role_groups(cfg, run_workers(cfg, receipt),
                                            receipt.get("reviewers"))
    if reviewers is not None:
        refuse_outside_group(cfg, opts.get("--review"), reviewers, "reviewer")
    reviewers = reviewers if reviewers is not None else workers
    session_at_launch = launch_session(run_dir)
    info = pr_view(url)
    prior = run_record.read_state(run_dir) or {}
    if info.get("state") != "OPEN":
        raise config.Error(f"{url} is {info.get('state', '?')}, not open")
    is_own, orchestrator, writer_effort = pr_writer(cfg, prior, session_at_launch, info["author"])
    if is_own and not orchestrator:
        raise config.Error("no session record names the writer of this PR; "
                           "review of the seat's own PR needs its orchestrator")
    summaries = prior.get("round_summaries", []) if is_own else []
    # a landing fix (`fail_pr_landing`) is re-reviewed in the round whose PASS it repairs, which
    # enters no round history and spends no round, however the budget stands -- on a head the
    # run wrote (`own_pr_heads`): one the seat pushed meanwhile is the seat's own, a round
    landing_fix = bool(is_own and prior.get("landing_fix")
                       and info["headRefOid"] in own_pr_heads(prior))
    if is_own and prior.get("landing_fix") and not landing_fix:
        # off the record as it stands now, under its lock: a whole save of `prior` would put
        # the record as it was read over a watcher's write since
        prior.pop("landing_fix")
        with run_record.record(run_dir) as current:
            current.pop("landing_fix", None)
    rnd, turn = own_pr_fix(prior if is_own else {})
    n_rounds = 1
    if is_own:
        # the pull request's budget, less what earlier runs spent on it: this run's rounds
        # are what is left, and a fourth round is refused whichever run would spend it
        n_rounds = own_pr_budget(url, run_dir)[0]
        why = own_pr_budget(url, run_dir, 0 if landing_fix else len(summaries))[1]
        if why and summaries and prior.get("head_sha") != info["headRefOid"]:
            # a head the seat pushed needs a round the change no longer has: the run ends
            # with the budget's own sentence, for its seat to decide
            lp = pr_loop(cfg, run_dir, prior, opts, log)
            lp.state["head_sha"] = info["headRefOid"]
            return pr_review_failed(lp, why)
        if why:
            raise config.Error(why)
    advancing = bool(summaries and (summaries[-1]["verdict"] == "FAIL" or prior.get("review_stale")
                                   or prior.get("own_pr_wait"))
                     and prior.get("head_sha") != info["headRefOid"])
    if prior.get("worktree"):
        at = git(prior["worktree"], "rev-parse", "HEAD")
        recorded = (prior.get("review") or {}).get("head_sha") or prior.get("head_sha")
        # a reset to the head this round moves to may have finished just before a crash;
        # the checkout stands on the fix the run pushed when the seat pushed over it
        moved = advancing and at in (info["headRefOid"], *own_pr_heads(prior))
        if ((at != recorded and not moved)
                or (prior.get("head_sha") != info["headRefOid"] and not advancing)):
            raise config.Error("the PR head or review checkout changed; existing work is kept "
                               "for inspection")
    previous = saved_findings(run_dir, prior) if is_own else ""
    # Persist before fetch/checkout/provider work: the PR can move at any of those steps.
    receipt = stamp_origin({**(run_record.read_state(run_dir) or {}), "run_id": run_dir.name,
                         "state": "running", **run_record.process_owner(),
                         "launched_session": session_at_launch,
                         "review_pr": url, "head_sha": prior["head_sha"] if advancing else info["headRefOid"],
                         "own_pr": is_own, "own_orchestrator": orchestrator if is_own else None,
                         "own_orchestrator_effort": writer_effort if is_own else None,
                         "started_at": prior.get("started_at") or time.time(), "review_posted": False})
    # `own_pr_wait` stays until the new head's checkout is written down below: a fetch that
    # fails or a process that dies before then still lets the next attempt move to that head
    if advancing:
        receipt["review_session"] = None
    run_record.save_state(run_dir, receipt)
    owner, name, number = PR_PARTS.match(url).groups()
    repo = checkout_for(f"{owner}/{name}", log)
    gc.before_run(log)
    base, head = info["baseRefName"], info["headRefOid"]
    fetch_pr(repo, number, base, log)
    git(repo, "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}")
    target_sha = git(repo, "rev-parse", f"origin/{base}^{{commit}}")
    base_sha = git(repo, "merge-base", target_sha, head)
    # read before any checkout is made: a plan that refuses the review leaves nothing behind
    planned = plan_context(session_at_launch) if is_own else ""
    if prior.get("worktree"):
        wt, branch = Path(prior["worktree"]), prior["branch"]
        if advancing:
            git(wt, "reset", "--hard", head)
    else:
        wt, branch = make_worktree(repo, run_dir.name, f"pr-{number}", head)
    tests = gitcall.declared_suite(wt, base, ref=target_sha)
    # an own PR's suite runs once, at landing; somebody else's PR has no line behind it --
    # only the inbox's yes -- so its suite runs here, in its one review round
    cmds = [f"{tests}  # once" if is_own else tests] if tests else []
    title = f"Review PR #{number}: {info['title']}"
    if is_own:
        # what the seat wrote of its own PR stays on GitHub: its reviewer judges the diff
        # against the plan ak holds, never the author's account of its work
        wrote = (f"The {session_at_launch} seat's orchestrator {orchestrator} wrote this diff; "
                 "review it as that model's work.\n\n")
    else:
        wrote = ("Nobody from agentkit executed anything here; the diff is the author's, and the "
                 f"PR states its intent.\n\n## The PR says\n"
                 f"{(info.get('body') or '(no description)').strip()}\n\n")
    body = (f"# {title}\n\n## Goal\nJudge {url} by {info['author']} against this repository: "
            f"its AGENTS.md, README, tests and conventions. {wrote}"
            + planned + done_when_block(cmds))
    (run_dir / "task.md").write_text(f"---\nrepo: {repo}\nrounds: {n_rounds}\n---\n{body}")
    state = stamp_origin({**(run_record.read_state(run_dir) or {}), "run_id": run_dir.name,
             "title": title, "task": str(run_dir / "task.md"),
             "launched_session": session_at_launch, "repo": str(repo), "scratch": False,
             "review_pr": url, "pr": url, "head_sha": head, "author": info["author"],
             "own_pr": is_own, "own_orchestrator": orchestrator if is_own else None,
             "own_orchestrator_effort": writer_effort if is_own else None,
             "base": f"origin/{base}", "target": base, "base_sha": base_sha,
             "target_sha": target_sha, "branch": branch,
             "worktree": str(wt), "executor": prior.get("executor"), "reviewer": None, "rounds": n_rounds,
             "state": "running", "verdict": None, **run_record.process_owner(), "started_at": receipt["started_at"],
             "finished_at": None, "round_summaries": summaries, "findings": previous, "merge_method": "squash",
             "no_merge": not is_own or bool(opts.get("--no-merge")), "merged": False,
             "merge_note": None, "reported": False})
    # a review is a run like any other: its history row carries its task's size, measured
    # off the same body the task file on disk holds
    sized_words, sized_points, sized_checks = taskfile.task_size(
        body, taskfile.done_when(body, run_dir / "task.md"))
    state.update(task_words=sized_words, task_points=sized_points,
                 task_checks=sized_checks)
    if is_own:
        # Kept through post failures and cleared only when this verdict is settled.
        state["own_pr_round_pending"] = rnd
    state.pop("own_pr_wait", None)       # this head is checked out and recorded
    state.pop("delivery_sha", None)      # a push an earlier round meant to make proves nothing here
    state.pop("review", None)            # nor does its review: this head's comes with this round
    run_record.save_state(run_dir, state)
    join_session_project(session_at_launch)     # a review is a launch too, and votes
    history_start(state, log)
    log(f"worktree {wt} on {branch}: PR #{number} by {info['author']} at {head[:12]}, "
        f"base origin/{base} ({base_sha[:12]})")
    exclude_junk(wt, log)
    env = config.repo_env(repo)
    if env:
        os.environ.update(env)
        log(f"env: {config.ENV / f'{repo.name}.env'} -> {', '.join(sorted(env))}")

    text_only = is_own and text_only_pr(repo, base_sha, head)
    first = is_own and own_pr_first_review(repo, url, number, base_sha, target_sha, head, run_dir)
    if first:
        # preflight refuses it before the run waits for a slot; here again on the head checked
        # out, which may have moved since, as on a resume or a restart
        read, why = first
        if why:
            lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, body)
            return pr_review_blocked(lp, Blocked(why, f"## Blocked\n\n{why}"))
        # what the first review reads, whatever the run's ending (`roundloop.first_review_ceiling`)
        history.first_review(state.get("run_id"), read, log=log)
    if text_only:
        # The seat's own wording needs no reviewer: it joins the line like a passed review,
        # where the repository's suite and CI still check it.
        summary = "Documents only; review skipped."
        # this head's verdict replaces the last one's findings: a later failure is its own
        state.update(verdict="PASS", review_posted=True, findings="",
                     review={**commit_identity(wt), "verdict": "PASS", "skipped": True})
        state.pop("review_records", None)
        state.pop("findings_file", None)
        state["round_summaries"] = [*summaries, {"round": len(summaries) + 1, "verdict": "PASS",
                                                 "done_when": None, "summary": summary,
                                                 "head_sha": head}]
        run_record.save_state(run_dir, state)
        log(summary)
        lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, body)
        lp.rnd += 1
        return settle_pr_round(lp, url, info)
    providers = collect_usage(cfg)
    # the reviewer is picked against everyone who wrote part of the head under review: the
    # orchestrator, and every model a fixer turn ran on or was handed to; none comes first
    writers = head_writers({**prior, "own_orchestrator": orchestrator, "own_pr": True}) if is_own else []
    order = reviewer_order(cfg, writers, ready_order(cfg, providers,
                                                           reviewers, log,
                                                           role="reviewer"))
    # a --bg parent's reviewer, adopted when it is still in the live order
    preset_rev = (run_record.read_state(run_dir) or {}).get("launch_reviewer")
    try:
        if preset_rev:
            config.model(cfg, preset_rev)
    except config.Error:
        preset_rev = None
    if preset_rev and preset_rev not in order:
        preset_rev = None   # a saved reviewer keeps its identity; a stale one does not
    if opts["--review"]:
        config.model(cfg, opts["--review"])
        refuse_unready(cfg, providers, opts["--review"], "reviewer")
        if is_own:
            review_providers(cfg, orchestrator, opts["--review"])
        reviewer = opts["--review"]
    elif preset_rev or order:
        reviewer = preset_rev or order[0]
    elif barred := barred_refusal(cfg, reviewers or config.reviewers(cfg)):
        raise config.Error(barred)
    else:
        raise QuotaDry("every worker has a gate meter at 100% used")
    state["reviewer"] = reviewer
    state.pop("launch_reviewer", None)   # consumed: a resume re-picks, as before
    run_record.save_state(run_dir, state)
    if is_own:
        log(f"reviewer={reviewer} (own PR of the {session_at_launch} seat; "
            f"picked against orchestrator {orchestrator})")
    else:
        log(f"reviewer={reviewer} (no executor: this is a review of somebody else's PR)")
    if session_at_launch and not prior.get("reviewer"):
        # the first reviewer pick starts the review: the launch line (on the terminal
        # for a foreground launch, in the log for a --bg child whose parent printed it)
        print(launch_line(run_dir.name, title, None, reviewer,
                          self_review=bool(is_own and same_model(cfg, orchestrator,
                                                                 reviewer))))
    body += repo_rules(wt, base_sha)
    run_record.save_state(run_dir, state)
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, pr_context(state, body))
    lp.rnd = rnd
    lp.round_dir.mkdir(parents=True, exist_ok=True)
    state.pop("final_check", None)
    if tests and not is_own:
        ok, dw_log = verify_work(lp)
        log(f"tests ({tests}): {'passed' if ok else 'FAILED'}")
    else:
        ok = None
        dw_log = ("(the repository suite runs once at landing; nothing was run in this review round)"
                  if tests else "(AGENTS.md declares no `tests:` command; nothing was run)")
        log(dw_log)
        # no suite stands in for it, and a PASS on this head is what merges
        failure = rules_check(lp)
        if failure:
            ok, dw_log = False, f"{dw_log}\n\n{failure}"
            log(failure)
    if is_own:
        summary = (f"PR #{number} by {info['author']}: {info['title']}. "
                   f"{orchestrator} wrote this; review its diff.")
        said = fixer_words(lp.round_dir, turn)      # the fixer's own words, for the record alone
        if said:
            summary += f"\n\n## What the fixer said\n{said}"
    else:
        summary = (f"PR #{number} by {info['author']}: {info['title']}. agentkit executed nothing; "
                   "review the author's diff.")
    try:
        if landing_fix:
            verdict = review(lp, summary, ok, dw_log, record=False,
                             preface=f"Re-review after the landing fix.\n\n## The last round\n{previous}")
        elif summaries:
            verdict = review(lp, summary, ok, dw_log,
                             preface=f"Re-review after a push.\n\n## The last round\n{previous}")
        else:
            verdict = review(lp, summary, ok, dw_log)
    except Blocked as exc:
        return pr_review_blocked(lp, exc)
    return settle_pr_round(lp, url, info)


def settle_pr_round(lp, url, info):
    """Finish a recorded round without spending another review on the same head."""
    cfg, run_dir, state, log, cmds = lp.cfg, lp.run_dir, lp.state, lp.log, lp.cmds
    verdict, head, is_own = state["verdict"], state["head_sha"], state.get("own_pr")
    number = PR_PARTS.match(url).groups()[-1]
    if not state.get("merged"):
        restore_review_checkout(lp, "reviewer")
    posted = state.get("review_posted") or post_review(lp, url, verdict)
    if not posted and not (is_own and state.get("review_stale")):
        # the job was a review on GitHub; a verdict nobody can read there is not one, so the
        # run is an error -- no merge offer -- and `ak watch` launches it again next tick
        state["error"] = f"the review was not posted to {url}: {state.get('review_error')}"
        state["state"], state["finished_at"] = "error", time.time()
        run_record.save_state(run_dir, state)
        write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
        log(f"ERROR {state['error']}")
        return state
    if is_own and state.get("no_merge") and verdict == "PASS" and posted:
        # launched with --no-merge: the verdict is the whole delivery
        state["merge_note"] = "not merged: the review was launched with --no-merge"
    elif verdict == "PASS" and posted and not state.get("merged"):
        if is_own:
            # the verdict owes its delivery until it lands, fails or goes back to its writer:
            # a delivery that errors keeps the mark, and with it the checkout a retry needs
            merge_own_pr(lp, url)
            if state.get("state") != "waiting":
                state.pop("own_pr_round_pending", None)
            if state.get("state") != "waiting" and not state.get("own_pr_wait"):
                state.pop("waiting_on", None)
                state.update(state="pass" if state["verdict"] == "PASS" else "fail",
                             finished_at=time.time())
            if not state.get("own_pr_wait"):
                state.pop("landing_fix", None)  # a new landing red still owes its fixer
            lp.write()
            write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
            return state
        green, why = checks(lp, url)
        try:
            current = pr_view(url)
        except Stopped:
            raise
        except config.Error:
            current = {}
        if green and current.get("headRefOid") == head and current.get("state") == "OPEN":
            question = f"PR #{number} by {info['author']}: {info['title']}. Merge? yes/no"
            pending = {"question": question, "url": url, "sha": head, "asked": False}
            if watch.ask_inbox(cfg, question, url, head, log,
                               typed=lambda: pending.update(asked=True)) == 0:
                state["merge_note"] = f"offered to the {config.inbox()} session at {head[:12]}"
            else:
                state["merge_note"] = "merge question requires retry"
                state["pending_inbox"] = pending
        else:
            if green:
                why = "the PR head changed, closed, or could not be verified after the checks"
            state["merge_note"] = f"not offered for merge: {why}"
            log(f"WARN {state['merge_note']}")
    # An obsolete verdict still supplies the next round's findings. The push wait
    # observes the moved head or closure immediately, including after a post retry.
    state.pop("waiting_on", None)        # whatever this round settled to, it is out of the line
    if is_own and (verdict == "FAIL" or not posted) and lp.rnd < lp.rounds:
        state.update(state="running", finished_at=None, own_pr_wait=head)
        state.pop("recovery_pending", None)
    else:
        state["state"] = "pass" if verdict == "PASS" and posted else "fail"
        state["finished_at"] = time.time()
        if not posted:
            state["error"] = state["review_error"]
    state.pop("own_pr_round_pending", None)
    state.pop("landing_fix", None)
    run_record.save_state(run_dir, state)
    write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
    return state


def own_pr_budget(url, run_dir, own=0):
    """`round_budget` for a seat's own pull request, `own` the rounds this run spent on it:
    the one place its arguments are read."""
    return round_budget(taskfile.TASK_MAX_ROUNDS, pr=url, exclude=run_dir,
                        what=f"PR #{PR_PARTS.match(url).group(3)}", own=own)


def already_under_way(task_path, meta, title, cmds, exclude=None):
    """Runs still going in the same repository that look like the same job, newest first.

    A match is a run whose state is `running` or `queued` with a live process
    (`process_active`), in the task's repository, launched by anybody, where either a
    done-when of the new task and of the running run name the same test file -- not a
    general check, which three other jobs there whose titles do not name it ran too,
    unless both titles name it -- or their titles share at least four significant words.  Each match is a dict with the run's
    id, seat (None for nobody's), started_at, title, shared test files and shared
    title-word count.  Read-only: run state comes only from run_dirs(), read_state()
    and process_active(), and a run's done-when from its own task.md.  A
    scratch task, or one whose repository cannot be resolved, is never checked.
    """
    stop = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
            "is", "are", "that", "this", "from", "into"}

    def test_files(commands):
        """Done-when tokens naming a test file, quotes stripped for the comparison.

        The basename itself has to look like a test: a shared runner such as
        `bash tests/smoke.sh` names no test file, however many jobs run it.
        A glob pattern names no single test file.
        """
        found = set()
        for command in commands:
            for token in command.split():
                name = token.strip("\"'")
                if not name or any(char in name for char in "*?["):
                    continue
                stem = name.rsplit("/", 1)[-1]
                base = stem.rsplit(".", 1)[0] if "." in stem else stem
                if stem.startswith("test_") or base.endswith("_test"):
                    found.add(name)
        return found

    def significant_words(text, repo_name):
        """Lowercased words of four or more letters outside the stop list."""
        words = (text or "").lower()
        if repo_name and words.startswith(repo_name.lower() + ":"):
            words = words[len(repo_name) + 1:]
        return {word for word in re.findall(r"[a-z0-9]+", words)
                if len(word) >= 4 and word not in stop}

    try:
        repo = task_repo(meta, task_path)
    except Exception:  # noqa: BLE001 - an unresolvable repository means no check
        # ... and the launch's own preflight reports the real problem: this refusal
        # must never break a launch that used to start, whatever the tool below git
        # did instead of answering
        return []
    if repo is None:
        return []
    def ours(directory, state, run_meta):
        """Whether a run works in the task's repository.

        Old receipts have no `repo` until the run builds its worktree, so those
        are matched through the repo their own task names; without one there is
        nothing to compare.
        """
        try:
            if state.get("repo"):
                return Path(state["repo"]).expanduser().resolve() == repo
            return bool(run_meta.get("repo")) and \
                task_repo(run_meta, directory / "task.md") == repo
        except (config.Error, OSError):
            return False

    def names(text, name):
        """Whether a title names what the test file `name` checks.

        A title word is a word of the file's own name, or one of three or more letters
        with a plain ending added (invoice and invoices, round and rounding); any longer
        prefix would read `allow` as naming test_all.py.
        """
        subject = set(re.findall(r"[a-z0-9]+",
                                 name.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())) - {"test"}
        for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
            for part in subject:
                short, long = sorted((word, part), key=len)
                if long == short or (len(short) >= 3 and long.startswith(short)
                                     and long[len(short):] in ("s", "es", "d", "ed", "ing")):
                    return True
        return False

    named = None

    def specific(files, other_title):
        """The files among `files` both titles name, or fewer than three unrelated jobs ran.

        A check such as a docs test sits in the done-when of job after job whatever they
        change, so sharing it says nothing about the work; a test only the jobs changing
        its behaviour name still does, and so does any test both titles name, whoever
        else ran it.  A job whose title names the file changes what it checks, so it
        never makes the file general; a job is a title, so relaunches of one count once.
        """
        nonlocal named
        if named is None and files:
            named = {}
            for directory in run_record.run_dirs():
                state = run_record.read_state(directory)
                if not state:
                    continue
                try:
                    run_meta, body, parsed_title = taskfile.parse_task(directory / "task.md")
                    found = test_files(taskfile.done_when(body, directory / "task.md"))
                except (OSError, config.Error):
                    continue
                if not ours(directory, state, run_meta):
                    continue
                job = state.get("title") or parsed_title
                for name in found:
                    if not names(job, name):
                        named.setdefault(name, set()).add(job)
        return {name for name in files
                if names(title, name) and names(other_title, name)
                or len(named.get(name, set()) - {title, other_title}) < 3}

    mine_files = test_files(cmds)
    mine_words = significant_words(title, repo.name)
    matches = []
    for directory in run_record.run_dirs():
        if exclude is not None and Path(directory) == Path(exclude):
            continue
        state = run_record.read_state(directory)
        if not state or state.get("state") not in run_record.ACTIVE:
            continue
        if not run_record.process_active(state):
            continue
        try:
            rival_meta, body, parsed_title = taskfile.parse_task(directory / "task.md")
            other_cmds = taskfile.done_when(body, directory / "task.md")
        except (OSError, config.Error):
            rival_meta, other_cmds, parsed_title = {}, [], None
        if not ours(directory, state, rival_meta):
            continue
        other_title = state.get("title") or parsed_title or directory.name
        shared = sorted(specific(mine_files & test_files(other_cmds), other_title))
        words = (len(mine_words & significant_words(other_title, repo.name))
                 if state.get("title") or parsed_title else 0)
        if not shared and words < 4:
            continue
        try:
            seat = launched_session(state)
        except config.Error:
            owner = state.get("launched_session") or state.get("session")
            seat = owner if isinstance(owner, str) and owner else None
        started = state.get("started_at")
        matches.append({"id": directory.name, "seat": seat,
                        "started": started if isinstance(started, (int, float)) else None,
                        "title": other_title, "files": shared, "words": words})
    matches.sort(key=lambda match: (match["started"] if match["started"] is not None
                                    else float("-inf"), match["id"]), reverse=True)
    return matches


def review_pr_main(cfg, opts, flags, argv, resumed):
    url = opts["--review-pr"]
    _, name, number = PR_PARTS.match(url).groups()
    if resumed:
        run_dir = Path(resumed)
    else:
        run_id = f"{datetime.now():%Y%m%d-%H%M}-review-pr-{slugify(name)}-{number}"
        run_dir = config.RUNS / run_id
        n = 1
        while run_dir.exists():
            n += 1
            run_dir = config.RUNS / f"{run_id}-{n}"
        run_dir.mkdir(parents=True)
        (run_dir / "log.txt").touch()
        try:
            prepare(run_dir, opts, logger(run_dir), cfg, printed=True)
        except run_record.StopRequested:
            # A stop landed during preflight: the receipt already says so, and the
            # stopper printed the line -- this end names it and stands down alike.
            print(stop.stop_line(run_dir.name, None, False))
            return 1
        if flags["--bg"]:
            try:
                receipt = run_record.read_state(run_dir) or {}
                reviewer = preset_review_model(cfg, opts, run_workers(cfg, receipt),
                                               reviewers=receipt.get("reviewers"))
            except config.Error as exc:
                refused(run_dir, exc, logger(run_dir), cfg, printed=True)
                raise
            title = (run_record.read_state(run_dir) or {}).get("title")
            if reviewer:
                try:
                    run_record.save_state(run_dir, {**(run_record.read_state(run_dir) or {}),
                                         "launch_reviewer": reviewer})
                except run_record.StopRequested:
                    print(stop.stop_line(run_dir.name, None, False))
                    return 1
            rc = spawn_bg(run_dir, argv)
            if reviewer and title and launch_session(run_dir):
                # the seat's terminal sees the launch line; the child's stdout is the log
                saved = run_record.read_state(run_dir) or {}
                print(launch_line(run_dir.name, title, None, reviewer,
                                  self_review=bool(saved.get("own_pr") and same_model(
                                      cfg, saved.get("own_orchestrator"), reviewer))))
            return rc
    if not resumed and foreground_cli(run_dir):
        # as a task run: a worker reviews the PR and parks it in its line, processless, and
        # this terminal follows the record to its real ending
        offset = (run_dir / "log.txt").stat().st_size
        spawn_bg(run_dir, argv)
        return follow_run(run_dir, cfg, offset)
    opts = dict(opts, **flags)
    log = logger(run_dir)
    log(f"run {run_dir.name}: review of {url}")
    if not resumed:
        place_here(run_dir, log)
    rc = drive(cfg, run_dir, opts, log, job=lambda: review_pr(cfg, run_dir, url, opts, log))
    if (rc == 0 and not log_is_stdout(run_dir)
            and (run_record.read_state(run_dir) or {}).get("state") == "waiting"):
        return 1        # a caller that does not follow it hears the truth: reviewed, not landed
    return rc


def main(argv):
    if command_help.show("run", argv):
        return 0
    if argv[:1] == ["--lander"]:
        if len(argv) != 2 or Path(argv[1]).name != argv[1] or not argv[1].startswith(".merge-"):
            raise config.Error("usage: ak run --lander LINE")
        landing.check_line(config.RUNS / argv[1], say)
        return 0
    if argv[:1] == ["status"]:
        return status.cmd_status(argv[1:])
    if argv[:1] == ["show"]:
        # The same screen as naming a run in status: deaths are listed there.
        return status.cmd_status(argv[1:])
    if argv[:1] == ["clean"]:
        return stop.cmd_clean(argv[1:])
    if argv[:1] == ["gc"]:
        return gc.cmd_gc(argv[1:])
    if argv[:1] == ["resume"]:
        return cmd_resume(argv[1:])
    if argv[:1] == ["merge"]:
        return cmd_merge(argv[1:])
    if argv[:1] == ["stop"]:
        return stop.cmd_stop(argv[1:])
    if depth_refused():
        return 2
    opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
            "--parallel": None}
    flags = {"--no-worktree": False, "--no-merge": False, "--bg": False, "--anyway": False,
             "--first": False}
    positional, i = [], 0
    while i < len(argv):
        arg = argv[i]
        if arg in opts:
            if i + 1 >= len(argv):
                raise config.Error(f"{arg} needs a value")
            opts[arg], i = argv[i + 1], i + 2
        elif arg in flags:
            flags[arg], i = True, i + 1
        elif arg.startswith("-"):
            raise config.Error(f"unknown flag {arg!r}; ak run <task.md> [--rounds N] [--exec MODEL] "
                               "[--review MODEL] [--anyway] [--first] [--no-worktree] [--no-merge] "
                               "[--bg] [--parallel N] | ak run --review-pr <url> [--review MODEL] "
                               "[--first] [--bg]")
        else:
            positional.append(arg)
            i += 1
    refused = seat_refusal(opts, flags)
    if refused:
        raise config.Error(refused)
    if opts["--review-pr"]:
        if positional or opts["--rounds"] or opts["--exec"] or flags["--no-worktree"] \
                or opts["--parallel"] is not None:
            raise config.Error("usage: ak run --review-pr <url> [--review MODEL] [--first] [--bg]: "
                               "no task file, no executor, no rounds")
        if not PR_PARTS.match(opts["--review-pr"]):
            raise config.Error(f"--review-pr needs a GitHub PR URL (got {opts['--review-pr']!r})")
    elif len(positional) < 1:
        raise config.Error("usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] "
                           "[--anyway] [--first] [--no-worktree] [--no-merge] [--bg] "
                           "[--parallel N] | ak run --review-pr <url> | "
                           "ak run status [<runid>] | ak run resume <runid> | "
                           "ak run stop <runid> [--keep] | ak run clean <runid> | ak run gc")
    if opts["--rounds"] is not None and not (opts["--rounds"].isdigit() and int(opts["--rounds"]) > 0):
        raise config.Error(f"--rounds must be a positive integer (got {opts['--rounds']!r})")
    refusal = taskfile.rounds_refusal(opts["--rounds"], "--rounds")
    if refusal:
        raise config.Error(refusal)
    parallel = None
    if opts["--parallel"] is not None:
        if not (str(opts["--parallel"]).isdigit() and int(opts["--parallel"]) > 0):
            raise config.Error(f"--parallel must be a positive integer (got {opts['--parallel']!r})")
        parallel = int(opts["--parallel"])
    opts.update(flags)
    box.check()
    cfg = config.load()
    # read here, not first where the run is placed: by then its record exists, and a refusal
    # would leave a run that status lists and watch resumes
    config.run_memory_max_mb()
    queued_child = os.environ.get(config.RUN_DIR_ENV)
    # a --bg child carries on the receipt its launch prepared, with the executors it saved
    if not opts["--review-pr"] and not (queued_child and queued(Path(queued_child))):
        selection = config.active_session(cfg)
        if selection and selection.get("workers") == []:
            raise config.Error(f"{selection['name']} has no executor: build it in the session, "
                               "or add an executor on its models screen.")
        if not selection and (cfg.get("defaults") or {}).get("workers") == []:
            raise config.Error("defaults have no executor: start a session with an executor.")
    config.ensure_dirs()
    if not opts["--review-pr"] and len(positional) == 1 and parallel is not None:
        raise config.Error("usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] "
                           "[--anyway] [--first] [--no-worktree] [--no-merge] [--bg]: --parallel "
                           "needs more than one task file")
    if not opts["--review-pr"] and len(positional) > 1:
        job_dir, job = jobs.job_create(cfg, positional, opts, parallel)
        if opts["--bg"]:
            return jobs.spawn_job_bg(job_dir)
        log = jobs.job_logger(job_dir)
        log(f"job {job_dir.name}: {len(positional)} tasks")
        return jobs.run_job_loop(cfg, job_dir, job)

    resumed = os.environ.get(config.RUN_DIR_ENV)
    if resumed and not queued(Path(resumed)):
        receipt = run_record.read_state(Path(resumed)) or {}
        name = receipt.get("run_id") or Path(resumed).name
        if needs_recovery(receipt):
            raise config.Error(f"this launch was interrupted; ak run resume {name} to recover it")
        if (receipt.get("state") == "stopped" and receipt.get("pid") == os.getpid()
                and run_record.process_active(receipt)):
            # this very process's launch, stopped as it waited: a pickup's exec keeps the pid
            raise config.Error(f"{name} was stopped before it could start; nothing was launched")
        # a stale variable inherited from some other run: start our own instead of stealing it
        print(f"ak run: ignoring {config.RUN_DIR_ENV}={resumed}: not a queued run",
              file=sys.stderr)
        resumed = None
    if resumed:
        # a queued child runs with the options its receipt recorded, as a resume of a run that
        # never started does (`cmd_resume`): a --bg launch's own argv repeats them, and the
        # tick's launch for a seat (`launch_for_seat`) sends none
        recorded = (run_record.read_state(Path(resumed)) or {}).get("launch_opts") or {}
        flags.update({flag: recorded[flag] for flag in flags if flag in recorded})
        opts.update(recorded)
    if opts["--review-pr"]:
        return review_pr_main(cfg, opts, flags, argv, resumed)
    if resumed:
        # the child runs the copy in the run dir; the source may have moved since --bg forked
        run_dir = Path(resumed)
        task_path = run_dir / "task.md"
    else:
        task_path = Path(positional[0]).expanduser().resolve()
        if not task_path.is_file():
            raise config.Error(f"no such task file: {task_path}")
        meta, body, title = taskfile.parse_task(task_path)
        # reject malformed commands before allocating a run directory, as well as a task
        # over the round budget or whose `repo:` names no home here, which nothing waives,
        # and a job that looks already under way in the same repository -- unless --anyway
        # says to start regardless.  A run's own child launch never runs the
        # already-under-way check.
        cmds = taskfile.done_when(body, task_path)
        refusal = taskfile.launch_refusal(meta, cmds)
        if refusal:
            print(f"ak run: {refusal}", file=sys.stderr)
            return 2
        repo_line(meta, task_path)
        if not os.environ.get(config.RUN_DIR_ENV):
            rivals = already_under_way(task_path, meta, title, cmds)
            if rivals and not opts["--anyway"]:
                first = rivals[0]
                if first["files"]:
                    detail = ", ".join(first["files"])
                else:
                    detail = f"{first['words']} title words"
                if len(rivals) > 1:
                    detail += f" and {len(rivals) - 1} more"
                try:
                    started = datetime.fromtimestamp(first["started"]).strftime("%H:%M")
                except (OSError, OverflowError, ValueError, TypeError):
                    started = "??:??"
                seat = first["seat"] or "nobody's"
                print(f"ak run: this looks already under way: {first['id']} ({seat}, "
                      f"started {started}, \"{first['title']}\") shares {detail}; "
                      f"{rival_advice()}", file=sys.stderr)
                return 2
        run_id = f"{datetime.now():%Y%m%d-%H%M}-{slugify(title)}"
        run_dir = config.RUNS / run_id
        n = 1
        while run_dir.exists():
            n += 1
            run_dir = config.RUNS / f"{run_id}-{n}"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(task_path.read_text())
        (run_dir / "log.txt").touch()
        try:
            prepare(run_dir, opts, logger(run_dir), cfg, task_file=task_path, printed=True)
        except run_record.StopRequested:
            # A stop landed during preflight: the receipt already says so, and the
            # stopper printed the line -- this end names it and stands down alike.
            print(stop.stop_line(run_dir.name, None, False))
            return 1
        if opts["--bg"]:
            try:
                executor, reviewer = preset_models(cfg, opts, logger(run_dir), run_dir)
            except run_record.StopRequested:
                print(stop.stop_line(run_dir.name, None, False))
                return 1
            rc = spawn_bg(run_dir, argv)
            if executor and reviewer and launch_session(run_dir):
                # the seat's terminal sees the launch line; the child's stdout is the log
                print(launch_line(run_dir.name, title, executor, reviewer,
                                  self_review=same_model(cfg, executor, reviewer)))
            return rc

    if not resumed and not opts["--no-merge"] and foreground_cli(run_dir):
        offset = (run_dir / "log.txt").stat().st_size
        spawn_bg(run_dir, argv)
        return follow_run(run_dir, cfg, offset)
    log = logger(run_dir)
    log(f"run {run_dir.name}: {task_path}")
    if not resumed:
        place_here(run_dir, log)
    return drive(cfg, run_dir, opts, log)
