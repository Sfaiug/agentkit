"""The review loop: executor -> done-when -> review, until PASS, then the merge.

The reviewer is another model where the workers allow one, else the executor's own:
a model tends to miss the mistakes it makes, so its own review is the last choice,
never a refusal.

The loop derives a review's verdict from its checked hand-in records.

`ak run --review-pr <url>` is the same reviewer with no executor: a PR checked out at
its head, judged against the repo and posted back as a GitHub review. The seat's own
PR merges on PASS with green checks; anyone else's asks the inbox. The seat's own text and
translation PRs skip review and join the line like any passed review.
"""

import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import (box, command_help, config, gate, gc, gitcall, hand_in, history, host, job as jobs,
               land as landing, orch, record as run_record, status, stop, task as taskfile, turns,
               usage, watch, worker, worktrees)
from .handback import (announce, announce_safely, clear_delivery, join_session_project,
    launch_line, reap, record_result, redress_seat, settle_delivered_line, stamp_origin,
    start_followups, task_project, write_result)
from .staffing import (best_pair, collect_usage, hand_executor, head_writers, next_executor,
    note_handover, pair_refusal, pick_models, ready_order, refuse_outside_group,
    refuse_unready, reviewer_order, run_reviewers, run_workers, same_model, started_round)
from .transitions import (allowed_rounds, carried_lines, change_budget, change_on,
    delivery, diff_lines, failed_at_budget, failed_in_integration,
    history_finish, history_role_tokens, history_start, integration_note, interrupt,
    invalidate_saved_pass, judged_in_integration, landing_line, launched_session, lineage_cap,
    needs_recovery, over_lineage, park_error, park_exhausted, PR_PARTS,
    queued, report_config, review_pass, review_providers, round_allowed,
    round_budget, rounds_spent_elsewhere, settled, stands_on_dependency, unfinished)
from .prompts import (HANDOVER, LOOP_NOTE, base_proof_line, capped, changed_test_paths,
    dispute_rows, done_when_block, done_when_counts, earlier_findings, failing_blocks,
    failing_checks, first_failure, fix_body, fixer_words, moved_lines, overridden_section,
    placed, plan_context, proof_on, record_findings, record_flakes, red_target_text,
    replay_findings, replay_section, review_disputes, review_files, review_records,
    reviewed_before, saved_findings, weigh_review, without_followups, written_answer)
from .turns import (Blocked, Dead, Exhausted, Killed, NO_CLOSING_ASK, NO_VERDICT_ASK,
    NotNeeded, OUT_CAP, QuotaDry, _scope_units,
    answered, call_retrying, finished_answer, killed_word, regression_script, scope_is_real,
    shell_foreground_note, stop_run_tree, tail, transient_delay)
from .gitcall import (Stopped, TOOL_CAP, _RUN_CONTEXT, commit_identity, commit_leftovers,
    default_base, dirty_paths, exclude_junk, fetch, git, git_out, leftover_junk,
    log_is_stdout, logger, make_worktree, repo_line, repo_rules, round_commands, run_depth,
    slugify, stopped, tool_env, tool_run, with_suite)

GITHUB_BODY_CAP = 60_000         # below GitHub's 65,536-character body limit, including UTF-8
MERGE_METHODS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}
CHECKS_CAP = 60 * 60            # a check suite still running after an hour is not going to finish
CHECKS_POLL = 10
PR_URL = re.compile(r"https://\S+?/pull/\d+")
# the race a merge can lose to a merge to the target between the push and this call; the
# answer is a retry, never an ending -- see `do_merge`
BASE_BRANCH_MODIFIED = re.compile(r"Base branch was modified", re.I)
# the same answer about the head right after delivery pushed it: GitHub has not yet taken the
# push in, and the re-check ends the run if the head really moved
HEAD_BRANCH_MODIFIED = re.compile(r"Head branch was modified", re.I)
# GitHub's own server failing the call, which its answer says to resubmit: the merge may or
# may not have gone through, so it is re-checked and retried like the race above
GITHUB_5XX = re.compile(r"status code: 5\d\d|HTTP 5\d\d|Bad Gateway|Gateway Timeout|"
                        r"Service Unavailable|couldn't respond to your request in time", re.I)
MERGE_RETRIES = 3      # how often any of them is re-fetched, re-checked and tried again
# GitHub refusing a head pushed seconds before, while it has not yet worked out whether it
# merges: its state is asked again while UNKNOWN, and a PR it then calls CLEAN is tried once
# more -- see `do_merge`
NOT_MERGEABLE = re.compile(r"Pull Request is not mergeable", re.I)
PUSH_RIGHTS = ("ADMIN", "MAINTAIN", "WRITE")
FORK_REMOTE = "fork"            # the remote a run adds for its fork; `origin` stays the upstream
CLASSIC_CHECKS_QUERY = (
    "query($owner:String!,$name:String!,$branch:String!){repository(owner:$owner,name:$name){"
    "ref(qualifiedName:$branch){branchProtectionRule{requiresStatusChecks "
    "requiredStatusChecks{context app{databaseId}}}}}}")
# The front matter lines ak reads; any other name (a typo of `tests:` included) is read by nothing.
FRONT_KEYS = ("tests", "health", "cleanup", "users", "features")
BLOCKED_SAME = ("the same checks fail the same way after a fix round: "
                "the task or its checks are wrong")
_PICKUP_START = None    # the installed agentkit this process started on, for in-flight pickup
_PICKUP_HELD = threading.local()   # delivery locks this thread holds or waits for


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


@contextmanager
def released_gate_turn():
    """Let this thread's held gate turn go while slow work runs.

    A rebase conflict, a failing check and a re-review all end in a fixer or a reviewer,
    and a model turn held through them lands nothing for the runs queued behind.  The
    check takes a fresh turn after the fix.
    """
    gate.release_turn()
    yield


class Loop:
    """One run's moving parts, shared by the round loop and the merge pipeline.

    The merge pipeline runs rounds of its own -- a conflicted rebase is fixed, re-tested and
    re-reviewed like any other finding -- so everything a round needs lives here instead of in
    `loop()`'s locals.  `rnd` is the number of rounds already spent, which is where a resumed
    run picks up.
    """

    def __init__(self, cfg, run_dir, state, opts, log, wt, body, cmds, context, spares):
        self.cfg, self.run_dir, self.state, self.opts, self.log = cfg, run_dir, state, opts, log
        self.wt, self.body, self.cmds, self.context = wt, body, cmds, context
        path = run_dir / "task.md"
        self.files = taskfile.task_files(path) if path.is_file() else []
        if self.files:
            self.context += "\n\nfiles: " + ", ".join(self.files)
        # the per-round commands and the ones that run at landing; without a
        # `# once` line the two are the list and the empty one
        self.every, self.once = taskfile.group_commands(cmds)
        self.base, self.rounds = state["base"], state["rounds"]
        # where the PR goes, which is not always where the branch came from
        self.target = state.get("target") or state["base"]
        self.executor, self.reviewer = state["executor"], state["reviewer"]
        self.exec_sid, self.review_sid = state.get("exec_session"), state.get("review_session")
        self.spares = spares
        self.findings = saved_findings(run_dir, state)
        self.artifacts = set()
        self.rnd = len(state["round_summaries"])
        self.scratch = bool(state.get("scratch"))
        # Keep the launch limits on resume; older receipts and review-only runs get defaults.
        self.done_when_limit = 3600 * state.get("ceiling_hours", run_record.CEILING_HOURS)
        self.turn_limit = 60 * state.get("silence_minutes", run_record.SILENCE_MINUTES)
        # the record as this loop was handed it -- every caller saves it first -- or last wrote
        # it: what `save` measures its own changes by.  Never read back off the disk, where a
        # key another writer set since would read as one this loop removed.
        self.written = copy.deepcopy(state)
        if probe := state.get("probe_checkout"):
            log("--- resuming: restoring the interrupted probe's checkout")
            gitcall.restore_probe_checkout(self, **probe)

    def role(self, name):
        """The preamble this run's workers get: a scratch run has no commits to talk about."""
        if self.scratch:
            return f"{name}-scratch"
        if name == "reviewer" and self.state.get("review_pr"):
            return "reviewer-pr"
        return name

    @property
    def base_sha(self):
        return self.state["base_sha"]

    @property
    def round_dir(self):
        return self.run_dir / f"round-{self.rnd}"

    def dir(self, name):
        return self.round_dir / name

    def save(self):
        """`write`, with this loop's seats and sessions on the record and in the history."""
        self.state.update(executor=self.executor, reviewer=self.reviewer,
                          exec_session=self.exec_sid, review_session=self.review_sid)
        self.write()
        history.update_run(self.state.get("run_id"), repo=self.state.get("repo"),
                           executor=self.executor, reviewer=self.reviewer,
                           rounds_used=len(self.state.get("round_summaries") or []),
                           session=launched_session(self.state), log=self.log)

    def write(self):
        """Write what this loop changed since it was handed the record or last wrote it, no more.

        The watcher and a rename write a live run's record too -- a freeze, a stall entry, a
        seat's new name -- and a whole save from this loop's memory would put the old record
        back over them.  `state` is written every time, so a stop that landed in between is
        refused by `record`'s guard as a whole save refused it.  Every save a live loop makes
        ends here; the merge pipeline's and a PR review's change neither seats nor history.
        """
        # what the done-when generated, on the record for readers outside the loop: the lease
        # scan leaves it out of the run's diff as a commit does
        self.state["artifacts"] = sorted(self.artifacts)
        if not (self.run_dir / "run.json").exists():
            run_record.save_state(self.run_dir, self.state)
        else:
            with run_record.record(self.run_dir) as current:
                for key in {"state", *self.state, *self.written}:
                    if key not in self.state:
                        current.pop(key, None)
                    elif (key == "state" or key not in self.written
                          or self.written[key] != self.state[key]):
                        current[key] = self.state[key]
        self.written = copy.deepcopy(self.state)

    def step(self, name):
        """Record which step this run is in, since when and in which round, for `ak run status`
        and the bar: a round's first step is announced before its directory is made."""
        now = time.time()
        history.open_step(self.state.get("run_id"), name, now, log=self.log)
        self.state.update(step=name, step_at=now, step_round=self.rnd)
        self.save()
        redress_seat(launched_session(self.state))


def settled_gate(lp):
    """`(ok, log)` when done-when already finished, else None so the gate runs again.

    A gate cut off mid-command has no settled record: `step` is still `done-when`,
    or the log stops before every command. A later step means the gate completed.

    The commit the gate was pinned to is the first thing it wrote in its own log, and
    the review that follows is judged against it: without reading it back, a resumed
    round would take its own untouched checkout for one that changed under the gate.
    A repo run whose log never recorded one has no settled gate to adopt.
    """
    if lp.state.get("step") == "done-when":
        return None
    if regression_script(lp.run_dir).is_file() and not lp.state.get("regression_checked"):
        return None
    path = lp.round_dir / "donewhen.log"
    if not path.is_file():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    if "[killed at the limit]" in text or "[not run:" in text:
        return None
    passed, total = done_when_counts(text, lp.every)
    if lp.every and total != len(lp.every):
        return None
    pinned = re.match(r"Commit: (\S+)\nTree: (\S+)\n", text)
    if pinned:
        lp.validation = {"head_sha": pinned.group(1), "tree_sha": pinned.group(2)}
    elif not lp.scratch:
        return None
    ok = (passed == len(lp.every)) if lp.every else passed == total
    return ok and not files_scope(lp) and not rules_check(lp), text


def continuation(lp):
    """Where this round was cut off, or None when the round has not started.

    `reviewer` and `done-when` already have the worker's answer. `worker` is an
    executor or fixer turn still open. A round directory that does not exist yet
    is None, which is every ordinary entry into the loop.
    """
    rd = lp.round_dir
    if not rd.is_dir():
        return None
    if (lp.state.get("step") == "reviewer" or turns.open_review(rd)[1]
            or review_files(lp.run_dir, lp.rnd)):
        return "reviewer"
    if turns.open_worker(lp)[0]:
        return "worker"
    if lp.state.get("step") == "done-when" or turns.saved_worker_answer(rd) is not None:
        return "done-when"
    return None


def record_disputes(lp, out):
    """A provider handover must not lose disputes already accepted during the turn."""
    out = Path(out)
    for directory in (out, *out.parent.glob(f"{out.name}-retry*")):
        submitted = hand_in.read(directory / hand_in.FILE)
        if submitted is not None and submitted.disputes:
            path = str(directory / hand_in.FILE)
            files = lp.state.setdefault("dispute_files", [])
            if path not in files:
                files.append(path)
                lp.save()


def worker_result(lp, summary, out):
    """Read the same closing after a call or a host interruption."""
    record_disputes(lp, out)
    answer = written_answer(out, summary).parent
    submitted = hand_in.read(answer / hand_in.FILE)
    closing = submitted.closing if submitted is not None else None
    if closing:
        if closing["kind"] == "blocked":
            raise Blocked(closing["why"], f"## Blocked\n\n{closing['why']}")
        if (closing["kind"] == "not-needed" and lp.state.get("followup")
                and not lp.state.get("round_summaries")):
            raise NotNeeded(closing["why"])
    # A closing reply may be only an acknowledgement; retain the work prose on restart too.
    name = re.split(r"-retry-(?:hand-in|foreground)", answer.name, maxsplit=1)[0]
    work = turns.read_answer(answer.with_name(name) / "final.md")
    if work and work != summary:
        summary = f"{work}\n\n{summary}"
    return summary


def execute(lp, role, text, name):
    """One executor/fixer turn of the current round.  Returns its summary.

    A provider that runs dry mid-round does not end the round: the turn goes to a model
    on a provider that refused nothing yet, in a fresh out dir on a fresh session. Only
    when no provider is left does the round stop -- `exhausted` and resumable, never an
    error for a window that refills.  A turn that fails on the provider twice in a row
    hands over the same way, told another model started it; with nobody else to take it
    the same session is resumed, indefinitely, inside `call_retrying`.

    A harness that cannot authenticate is neither: no other provider is asked, because the
    work is fine and only the login is not, and the run parks `waiting_login` on the session
    this turn left behind.  A turn killed by signal twice within a minute is neither either:
    the run parks as an interruption, reading `needs you` with the signal for a reason.

    A turn that hands in blocked says the task cannot
    be done as written: that ends the run here, with no done-when gate, no reviewer and no
    further round, because there is nothing to judge and nothing another round would change.
    """
    lp.state.update(verdict=None, review=None)
    if hasattr(lp, "step"):
        lp.step("executor")
    else:
        lp.state.update(step="executor", step_at=time.time())
        lp.save()
    if not getattr(lp, "scratch", False) and not lp.state.get("review_pr"):
        gitcall.sweep_sandboxes(lp.wt, lp.log)
    # Read the open attempt before free_dir creates the next one, or the empty new
    # directory would look like a turn that recorded no session.  Off `dir`, which is
    # what free_dir writes through, so the round is read exactly where it is written.
    rd = lp.dir(name).parent
    kind, sid = turns.open_turn(rd, name) if rd.is_dir() else (None, None)
    previous = turns.latest_turn(rd, name) if kind else None
    if previous is not None:
        record_disputes(lp, previous)
    out, body, dry = turns.free_dir(lp, name), text, set()

    def handover(detail):
        return hand_executor(lp, "transient", detail, dry)
    # Only a turn whose body was replaced by the handover has a conversation that can be
    # refused, and only that turn hands the original prompt and the notice down.
    resume = {}
    note = None
    if kind == "resume":
        body = turns.host_ended_prompt(lp.state)
        lp.exec_sid = sid
        note = {"at": time.time(), "role": role, "restarted": False}
        lp.state["resume_notice"] = note
        resume = {"fresh_body": text, "resume_note": note, "previous": previous}
    elif kind == "fresh":
        # The host cut the turn off before a session id was recorded. A fresh
        # conversation gets the original prompt; an older id must not be resumed.
        lp.exec_sid = None
        note = {"at": time.time(), "role": role, "restarted": True}
        lp.state["resume_notice"] = note
    # The ask's directory survives a host interruption, so resuming it cannot buy a third ask.
    closing_asked = previous is not None and ((previous / "final.md").exists()
                       or "-retry-hand-in" in previous.name or "-retry-foreground" in previous.name)
    if closing_asked:
        body = NO_CLOSING_ASK
        out = turns.free_dir(lp, f"{previous.name}-retry-hand-in")
    if role == "fixer" and "## Reviewer findings to fix\n" in text and lp.state.get("findings_file"):
        findings = Path(lp.state["findings_file"]).with_name(hand_in.FINDINGS_FILE)
        if findings.is_file():
            resume["findings"] = findings
    while True:
        # read once the attempt ends, however it ends -- a refused, parked or killed turn spent
        # tokens too -- off its own model and directory, which a handover below moves on from
        model, attempt = lp.executor, out
        try:
            code, summary, lp.exec_sid, dead = call_retrying(lp.cfg, lp.executor, body, lp.wt,
                                                             out, lp.role(role), lp.exec_sid,
                                                             lp.log, lp.turn_limit,
                                                             handover=handover, **resume)
        except worker.LoginExpired as expired:
            lp.exec_sid = expired.session or lp.exec_sid
            lp.save()           # the parked conversation is in run.json before the run parks
            raise
        except Killed as killed:
            lp.exec_sid = killed.session or lp.exec_sid
            lp.save()           # the killed conversation is in run.json before the run parks
            raise
        except turns.CannotRun as broken:
            # Another provider, the way a spent window goes; with nobody left, the run is
            # blocked on the harness's own line.  The turn never ran, so it left nothing
            # for the next model to be told about.
            if hand_executor(lp, "cannot run", broken.detail, dry) is None:
                raise
            body = text
            closing_asked = False
            out = turns.free_dir(lp, f"{name}-{lp.executor}")
            continue
        except turns.RanDry as refused:
            lp.exec_sid = refused.session
            refused.remember(lp.state)
            lp.save()           # the refused session is named in run.json before it is dropped
            before = lp.executor
            new = hand_executor(lp, refused.why, refused.detail, dry)
            if new is None:
                raise QuotaDry(f"{role} {before} ran dry on {refused.mark!r}: {refused.detail}; "
                               f"no other provider can execute; "
                               + ("retrying in ten minutes. " if lp.state.get("refusal_retry")
                                  else "resume when a meter refills. ") +
                               f"See {out}*/stderr.log")
            body = f"{HANDOVER.format(before=before)}\n\n{text}"
            closing_asked = False
            out = turns.free_dir(lp, f"{name}-{lp.executor}")
            continue
        except turns.TransientHandover as handed:
            # hand_executor already moved the role inside the callback; the new model
            # joins a round another started, in a fresh out dir on a fresh session.
            body = f"{HANDOVER.format(before=handed.before)}\n\n{text}"
            closing_asked = False
            out = turns.free_dir(lp, f"{name}-{lp.executor}")
            continue
        finally:
            history_role_tokens(lp.state.get("run_id"), "executor", attempt, lp.log,
                                lp.cfg, model)
            record_disputes(lp, attempt)
        if code != 0:
            lp.log(f"WARN {role} {killed_word(code) or f'exited {code}'}; "
                   f"see {out / 'stderr.log'}")
        lp.save()
        submitted = review_records(out, summary)
        if (not (submitted is not None and submitted.closing) and not closing_asked
                and not list(out.parent.glob(f"{out.name}-retry*foreground*"))):
            lp.log(f"{role} {lp.executor} gave no closing; asking once more")
            resume["previous"] = written_answer(out, summary).parent
            body = NO_CLOSING_ASK
            closing_asked = True
            out = turns.free_dir(lp, f"{resume['previous'].name}-retry-hand-in")
            continue
        return worker_result(lp, summary, out)


def suite_evidence(lp, cmds, identity):
    """Keep the checked tree: integration can carry the SHA without running the suite again."""
    suite = gitcall.declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
    return {"suite": suite, "tree_sha": identity.get("tree_sha")} if suite and suite in cmds else {}


def current_review(lp):
    """A successful review belongs to exactly the commit that was tested and reviewed."""
    if not review_pass(lp.state, lp.cfg):
        return False
    return lp.scratch or all(lp.state["review"].get(k) == v
                             for k, v in commit_identity(lp.wt).items())


def files_scope(lp):
    """A gate failure for paths outside the task's Git pathspecs, else an empty string."""
    specs = getattr(lp, "files", ())
    if not specs or lp.scratch or lp.state.get("review_pr"):
        return ""
    cmd = ["git", "-C", str(lp.wt), "diff", "--name-only", "--no-renames", "-z",
           f"{lp.base_sha}...HEAD"]
    paths = []
    for suffix in ([], ["--", *specs]):
        # git() strips whitespace, which can be part of the first path's name.
        code, out, err = tool_run(cmd + suffix)
        if code != 0:
            raise (Stopped if stopped(code, err) else config.Error)(
                f"files: git diff failed in {lp.wt}: {err.strip()}")
        paths.append(set(out.split("\0")) - {""})
    outside = sorted(paths[0] - paths[1])
    return "outside files: " + ", ".join(outside) if outside else ""


def rules_check(lp):
    """Refuse a branch's change to AGENTS.md that workers would not get as written: a link, a
    Git filter, more than a harness reads of it, or a front matter line ak does not read.
    A branch that leaves the file alone, or deletes it, passes."""
    if lp.scratch or not git(lp.wt, "diff", "--name-only", "--no-renames",
                             f"{lp.base_sha}...HEAD", "--", "AGENTS.md"):
        return ""
    entry = git(lp.wt, "ls-tree", "HEAD", "--", "AGENTS.md")
    if not entry:
        return ""       # the branch deleted it
    if entry.startswith("120000 "):
        # following it would mean redoing how Linux opens a path, inside Git's trees
        return ("AGENTS.md is a link, which ak does not follow, so workers would get no rules "
                "from it: make AGENTS.md the file itself.")
    if not git(lp.wt, "check-attr", "filter", "--", "AGENTS.md").endswith(("unspecified", "unset")):
        return "AGENTS.md must not go through a Git filter: ak reads its front matter as committed."
    ceiling = config.instruction_ceiling()
    try:
        held = gitcall.rules_bytes(lp.wt, "HEAD")
    except Stopped:
        raise
    except config.Error as exc:
        unknown = (f"its size against the {ceiling[0]} bytes {ceiling[1]} reads of it is unknown"
                   if ceiling else "ak cannot check it")
        return f"AGENTS.md could not be read as a checkout holds it, so {unknown}: {exc}"
    if ceiling and len(held) > ceiling[0]:
        return (f"AGENTS.md is {len(held)} bytes, past the {ceiling[0]} bytes {ceiling[1]} "
                "reads of it: tighten it.")
    text = held.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    unread = unknown_front_lines(text.strip())
    if not unread:
        return ""
    return (f"AGENTS.md front matter has lines ak does not read: "
            f"{', '.join(f'`{line}`' for line in unread)} (it reads {', '.join(FRONT_KEYS)}): "
            "remove them, or fix the misspelled name.")


def unknown_front_lines(text):
    """The front matter lines of AGENTS.md text whose name ak never reads, as written."""
    match = gitcall.FRONT.match(text)
    if not match:
        return []
    return [line.strip() for line in match.group(1).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
            and line.partition(":")[0].strip() not in FRONT_KEYS]


def needs_base_proof(lp):
    """A run launched under the rule owes one until a check fails on base, as its record
    says; one launched before it owes none -- a process change applies to the next launch.
    A fix run with no check of the reviewer's says it proves its regression.sh instead
    (`regression_fails_before`), a repair's that it is proven at landing, and a scratch run's
    record that it has no base."""
    return lp.state.get("base_proof") == "owed"


def own_checks(lp):
    """What judges this change each round: the task's per-round checks as the gate runs them
    -- `with_suite` has already moved any line that is the declared suite to landing -- less
    a suite split into shards (`AK_SHARD`), which is the repository's, not the change's."""
    return [cmd for cmd in lp.every if not gate.names_shard(cmd)]


def fails_on_base(lp):
    """Why no check of the task's own was shown to fail on the old code, or "" once one was:
    a check that finishes failing on base with the branch's tests laid over, and passes on base
    with every file the branch changed laid over, proves it (`base_proof` turns `proven`).

    It never fails a round, by the owner's rule (7 Oct): ak proves the failing test wherever
    it can and records why when it cannot, as no path tells every project's tests from its
    code -- Go's testdata, Django's tests.py, Rust's tests inside a code file.  Each replay
    runs alike -- one runner, the gate's environment, one order, the suite left out -- in a
    checkout of its own made from git alone (`replay_checkout`), so only the branch's files
    between them can turn a check: whatever else sets a replay apart, from the round's own
    gate or from a real commit, sets both apart, and what one replay's checks write reaches
    neither the other nor the run's checkout.  What goes over base is the branch's
    test-shaped paths, never a file a check merely names, or a check reading the changed file
    would pass on base too.  The replay with every change runs only once a check did not pass
    on base, and a check finishes failing as a reviewer's proof does.  A proof is kept across
    rounds and resumes.  Scratch runs have no base, and a PR review owes none: its own checks
    are its plan's lines, which fail on the default branch when written.
    """
    cmds = own_checks(lp)
    if not cmds:
        return "the task has no check of its own that runs each round"
    head = git(lp.wt, "rev-parse", "HEAD")
    base = lp.base_sha
    changed = [p for p in git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                              f"{base}...{head}").split("\0") if p]
    tests = changed_test_paths(lp, head, named=False)
    if len(tests) == len(changed):
        return "the branch changes nothing but tests"

    def replay(paths, log_name):
        """Each check's exit as the gate's runner saw it, in order."""
        log_path = lp.run_dir / log_name
        with replay_checkout(lp, head, paths) as checkout:
            marks = []
            _, text = gate.run_done_when(cmds, checkout, log_path, set(), lp.done_when_limit,
                                         lp.log, silence=lp.turn_limit, run_dir=lp.run_dir,
                                         marks=marks)
        laid = f", with {len(paths)} files of {head} laid over" if paths else ""
        log_path.write_text(f"Commit: {base}{laid}\n\n{text}")
        return marks + [None] * (len(cmds) - len(marks))      # none past a kill ran

    lp.log(f"--- base proof: the task's own checks on {base[:12]}")
    on_base = replay(tests, "base.log")
    if all(code == 0 for code in on_base):
        return (f"every check passes on base {base[:12]} with the branch's tests laid over: none "
                "shows the change, or its test lives where ak does not look for one")
    # the control: the same replay with the branch's changes, so only they turn a check
    lp.log(f"--- base proof: the same checks with {head[:12]}'s changes")
    on_head = replay(changed, "head.log")
    # a check finishes failing as a reviewer's proof does (`hand_in.proof_failed`)
    if any(after == 0 and before is not None and hand_in.proof_failed({"returncode": before})
           for before, after in zip(on_base, on_head)):
        lp.state["base_proof"] = "proven"
        lp.save()
        return ""
    if any(after != 0 for after in on_head):
        return ("a check fails in a checkout made from git alone even with the branch's changes: "
                "it needs what git does not hold, such as an installed dependency")
    unfinished = [command for command, code in zip(cmds, on_base) if code != 0]
    return f"`{unfinished[0]}` did not finish on base {base[:12]}"


@contextmanager
def replay_checkout(lp, head, paths):
    """A checkout of its own for one replay of the base proof, made from git alone and removed
    after with whatever its checks started: a clone sharing the run's objects, at base with
    `paths` of `head` laid over, committed the same way for every replay (one author, base's
    date, one message, no hooks or signature, no git author of the host's needed).  It has
    its own config and refs, nothing the run's checkout holds outside git reaches it, and
    nothing its checks write there reaches another replay or the run's checkout."""
    with tempfile.TemporaryDirectory(dir=lp.run_dir) as tmp:
        checkout = Path(tmp) / "checkout"
        git(lp.wt, "clone", "--quiet", "--shared", "--no-checkout", str(lp.wt), str(checkout))
        try:
            git(checkout, "checkout", "--quiet", "--detach", lp.base_sha)
            # what the branch deleted goes first, so a file or submodule it put where a
            # folder was takes that place; the paths come from a file, as a branch can change
            # more of them than one command line holds
            deleted = set(git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                              "--diff-filter=D", f"{lp.base_sha}...{head}").split("\0"))
            for part, command in (([p for p in paths if p in deleted],
                                   ("rm", "--quiet", "-r", "--ignore-unmatch")),
                                  ([p for p in paths if p not in deleted],
                                   ("restore", f"--source={head}", "--staged", "--worktree"))):
                if part:
                    listed = Path(tmp) / "paths"
                    listed.write_bytes(b"\0".join(os.fsencode(p) for p in part))
                    git(checkout, *command, f"--pathspec-from-file={listed}",
                        "--pathspec-file-nul", env={"GIT_LITERAL_PATHSPECS": "1"})
            when = git(checkout, "show", "-s", "--format=%cI", "HEAD")
            git(checkout, "-c", f"core.hooksPath={os.devnull}", "commit", "--quiet",
                "--no-gpg-sign", "--allow-empty", "-m", f"files of {head} over {lp.base_sha}",
                env={f"GIT_{who}_{what}": value for who in ("AUTHOR", "COMMITTER")
                     for what, value in (("NAME", "agentkit"), ("EMAIL", "agentkit@localhost"),
                                         ("DATE", when))})
            yield checkout
        finally:
            worker.kill_marked(gitcall.run_child_env().get(worker.RUN_MARKER), log=lp.log)


def regression_fails_before(lp):
    """Require the run's regression to fail on base with only its changed checks overlaid.

    A branch that changes only checks fixes a defect in a check itself; overlaying them
    would make base the branch, so its regression runs on base as it is.
    Keep a successful probe across rounds and resumes; a passing script must be fixed
    before it can earn that record. The probe's edits belong to neither commit.
    """
    script = regression_script(lp.run_dir)
    if not script.is_file() or lp.state.get("regression_checked"):
        return ""
    if lp.scratch:
        return "regression.sh cannot be checked without a base commit"
    head = git(lp.wt, "rev-parse", "HEAD")
    base = lp.base_sha
    changed = [p for p in git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                              f"{base}...{head}").split("\0") if p]
    only_tests = changed_test_paths(lp, head) == changed
    proof = proof_on(lp, f"bash {shlex.quote(str(script))}", lp.run_dir / "regression-base.log",
                     base, tests_from=None if only_tests else head)
    if proof["killed"] or proof["returncode"] < 0:
        return f"regression.sh did not finish on base {base}: it does not show the defect"
    if proof["returncode"] == 0:
        return f"regression.sh passes on base {base}: it does not show the defect"
    lp.state["regression_checked"] = True
    lp.save()
    return ""


def verify_work(lp, cmds=None):
    """Pin done-when to a commit before running commands, including leftover executor edits.

    Runs `cmds`, or the run's per-round commands when none are given. Checks deferred
    to landing run through `final_check`.
    """
    if cmds is None:
        cmds = lp.every
    lp.step("done-when")
    if not lp.scratch and not lp.state.get("review_pr"):
        if lp.state.get("repo"):
            # ak's commit step runs the lease scan itself: a diff that cannot merge with an
            # older live run's is parked here, before anything of it is reviewed, and the
            # save below raises the stop the scan recorded (`leases.park`)
            from . import leases
            leases.scan_safely(Path(lp.state["repo"]), lp.log)
            lp.save()
        commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
    checks = (files_scope(lp), rules_check(lp))
    lp.validation = {} if lp.scratch else commit_identity(lp.wt)
    clean = lp.scratch or lp.state.get("review_pr") or git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
    ok, text = gate.run_done_when(cmds, lp.wt, lp.round_dir / "donewhen.log", lp.artifacts,
                                  lp.done_when_limit, lp.log, silence=lp.turn_limit,
                                  run_dir=lp.run_dir)
    if not lp.scratch and not lp.state.get("review_pr") and (
            not clean or commit_identity(lp.wt) != lp.validation or
            git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0):
        ok = False
        text += "\n\nCheckout changed during done-when; these commands do not verify the pinned commit."
    for failure in checks:
        if failure:
            ok = False
            text += "\n\n" + failure
    if ok:
        failure = regression_fails_before(lp)
        if failure:
            ok = False
            text += f"\n\n$ regression.sh must fail on base\n[exit 1]\n{failure}"
    if ok and needs_base_proof(lp):
        # recorded, never a failure: the owner's rule (7 Oct)
        lp.state["base_proof_note"] = fails_on_base(lp) or None
        lp.save()
        text += "\n\n" + base_proof_line(lp.state)
    if lp.validation:
        text = (f"Commit: {lp.validation['head_sha']}\nTree: {lp.validation['tree_sha']}\n\n"
                + text)
        (lp.round_dir / "donewhen.log").write_text(text)
    return ok, text


def passed_review_head(state):
    """The last reviewed head whose task checks passed, before landing fixes."""
    reviewed = state.get("review") or {}
    passed_head = ((state.get("review_pending") or {}).get("passed_head_sha")
                   or reviewed.get("passed_head_sha"))
    if not passed_head and reviewed.get("verdict") == "PASS" and reviewed.get("done_when"):
        passed_head = reviewed.get("rebased_from") or reviewed.get("head_sha")
    return passed_head or next((entry.get("passed_head_sha") or entry.get("head_sha")
        for entry in reversed(state.get("round_summaries") or [])
        if entry.get("verdict") == "PASS" and entry.get("done_when") and entry.get("head_sha")), None)


def pending_review(lp, reason):
    """Invalidate before delivery; landing review spends no round, only fixing findings does."""
    entries = lp.state["round_summaries"]
    passed_head = passed_review_head(lp.state)
    lp.state.update(verdict=None, review=None,
                    review_pending={"round": lp.rnd, "record": False,
                                    "summary": entries[-1]["summary"] if entries else "",
                                    "reason": reason,
                                    **({"passed_head_sha": passed_head} if passed_head else {})})
    lp.save()


def resume_review(lp, verified=None):
    pending = lp.state["review_pending"]
    identity = {} if lp.scratch else commit_identity(lp.wt)
    pending.update(identity)
    lp.save()
    allowed = allowed_rounds(lp)
    if pending["round"] > allowed:
        work = f"for commit {identity['head_sha']} (tree {identity['tree_sha']}) " if identity else ""
        # a larger budget is only for asking up to what the change has left: past it the next
        # step is the orchestrator's, and naming a `--rounds` that is refused would send it nowhere
        onward = (f"resume with ak run resume {lp.run_dir.name} --rounds {pending['round']}"
                  if pending["round"] <= lineage_cap(lp.state, lp.run_dir)
                  else "split or redesign the task")
        reason = (f"{pending.get('reason', 'unfinished review')}; done-when and review are pending "
                  f"{work}at round {pending['round']}, but the round budget ({allowed}) is spent; "
                  f"{onward}")
        note(lp, reason, failed=True)
        raise Exhausted(reason)
    lp.rnd = pending["round"]
    lp.round_dir.mkdir(parents=True, exist_ok=True)
    if verified is None:
        ok, dw_log = verify_work(lp)
    else:
        ok, dw_log = verified
        if lp.scratch:
            lp.validation = {}
        (lp.round_dir / "donewhen.log").write_text(dw_log)
    # recorded, never judged: what preceded this round ran in another process, so whether a
    # fixer turn came before it is not known here -- but the next round has to be able to
    # compare against it
    same_failure(lp, ok, dw_log, compare=False)
    return review(lp, pending["summary"], ok, dw_log,
                  pending.get("reason", "Resume the unfinished review."),
                  **({"record": False} if pending.get("record") is False else {}))


def restore_review_checkout(lp, stage):
    """Tests can regenerate tracked files; preserve their diff, then review the pinned commit."""
    head = lp.state["head_sha"]
    if git(lp.wt, "rev-parse", "HEAD") != head:
        raise config.Error(f"review checkout HEAD changed during {stage}; cannot review the pinned PR head")
    rc, why = git_out(lp.wt, "diff", "--quiet", head)
    if rc == 1:
        path = lp.run_dir / f"{stage}-changes.patch"
        path.write_text(git(lp.wt, "diff", "--binary", head))
        git(lp.wt, "restore", f"--source={head}", "--staged", "--worktree", "--", ".")
        lp.log(f"WARN {stage} changed tracked files; saved {path} and restored the PR head")
    elif rc != 0:
        raise config.Error(f"cannot inspect the review checkout after {stage}: {why}")


def same_failure(lp, ok, dw_log, gate="every", compare=True):
    """Record what this gate left failing, and end the run when a fix round changed nothing.

    Called at the end of every round, after its fixer turn.  A round that changes neither which
    commands fail nor what they say about it has established something about the task rather
    than about the code: the check tests the wrong thing, or the task asks for something it
    also forbids.  A third attempt would buy the same answer for another model turn, so the run
    stops there and the orchestrator is told which commands stood still.

    `gate` keeps each set of commands to its own history: the per-round commands and
    the `# once` ones are different gates, so one passing must not wipe what the other
    keeps saying, and the two can never be compared with each other anyway.
    `compare=False` records without judging, for a round resumed from another process,
    where nothing here knows whether a fixer preceded it.

    The first sight of a gate is only recorded, never compared: one failure is not the same
    failure twice.  A gate that passed records no failure, so a later one is new again.
    """
    failure = [] if ok else failing_checks(dw_log)
    history = lp.state.get("done_when_failure")
    if not isinstance(history, dict):
        history = {}            # a record written before each gate kept its own history
    before, seen = history.get(gate), gate in history
    lp.state["done_when_failure"] = {**history, gate: failure}
    lp.save()
    if not compare or not seen or not failure or before != failure:
        return
    listed = "\n".join(f"- `{cmd}` \u2014 {line}" if line else f"- `{cmd}`"
                       for cmd, line in failure)
    raise Blocked(BLOCKED_SAME, f"## Blocked\n\n{BLOCKED_SAME}\n\n"
                                f"The checks that failed identically twice:\n\n{listed}")


def review(lp, summary, ok, dw_log, preface="", record=True):
    """Commit what the executor left, hand the work to the reviewer, record the round's verdict.

    A repo run is judged on its diff.  A scratch run has no commits at all -- what it produced
    is the files it left in the workspace, so that listing is what the reviewer is given.

    The reviewer judges that work against the done-when output the loop already ran on the
    commit under review; it is told so, with the commit and the exit counts, and not to run
    the commands again.  A run that lands defers its suite and `# once` commands to landing,
    and the reviewer is told their absence from the input is by design.

    `record` is off for landing re-review and the merge pipeline's fixer rounds: they are not task rounds
    and must not spend one, so no summary of them enters the rounds' own history.
    The verdict is recorded either way, because delivery is decided
    on it.
    """
    passed_head = passed_review_head(lp.state)
    # where this review began on its reviewer's session, kept from its first entry across
    # parks; a pending record that holds none was written before any turn of it ran
    pending = lp.state.get("review_pending") or {}
    since = pending["since"] if "since" in pending else str(
        turns.review_turn(lp.dir("reviewer").parent, lp.review_sid) or "")
    # the commit the last review judged (`delta_from`, written by every review) and its findings,
    # what a later round replays, kept on the pending record so no dying attempt overwrites them
    delta_from = lp.state.get("delta_from")
    earlier = earlier_findings(lp)
    lp.state.update(verdict=None, review=None,
                    review_pending={"round": lp.rnd, "summary": summary, "since": since,
                                    "earlier": earlier,
                                    **({"passed_head_sha": passed_head} if passed_head else {})})
    if not record:
        lp.state["review_pending"]["record"] = False
    if hasattr(lp, "step"):
        lp.step("reviewer")
    else:
        lp.state.update(step="reviewer", step_at=time.time())
        lp.save()
    checks, delta, replayed, listed = "", None, [], None
    if lp.scratch:
        work = whole = f"## Workspace ({lp.wt})\n```\n{gitcall.listing(lp.wt)}\n```"
    else:
        head = "HEAD"
        if lp.state.get("review_pr"):
            head = lp.state["head_sha"]
            restore_review_checkout(lp, "tests")
        else:
            commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
        diff = capped(lp, git(lp.wt, "diff", f"{lp.base_sha}...{head}", check=False))
        work = whole = f"## Diff ({lp.base}...HEAD in {lp.wt})\n```diff\n{diff}\n```"
        at = git(lp.wt, "rev-parse", head)
        # a later round judges what changed since the last review, where that review handed
        # in findings for a fix to answer: after a FAIL on the checks alone, and in a landing
        # re-review (`record` off: the repair that brought it here is nobody's fix round),
        # the whole change is judged again
        delta = reviewed_before(lp, delta_from, at) if record and earlier else None
        if record and delta_from and earlier:
            # a later round, on a new commit or the same again: ak re-proves the earlier findings.
            # One at a site the fixer disputed (a dispute names a site) is the reviewer's to weigh,
            # and a quote is no failing proof: both are listed, not replayed
            disputed = {(row["path"], row["line"]) for row in dispute_rows(lp)}
            proven = [row for row in earlier if "run" in (row.get("evidence") or {})
                      and (row["path"], row["line"]) not in disputed]
            left = [(row, "disputed by the fixer: hand it in again to uphold it"
                     if (row["path"], row["line"]) in disputed
                     else "a quote, which ak cannot re-prove: hand it in again if it still stands")
                    for row in earlier if row not in proven]
            replayed = replay_findings(lp, proven, at)
            # each earlier finding is listed, and handed to the reviewer's turn, where it
            # stands on this commit (`placed`): the one site a hand-in upholds it at
            standing = {id(row): placed(lp, row, delta, at)[0] for row in earlier}
            listed = lp.round_dir / "earlier.json"
            listed.parent.mkdir(parents=True, exist_ok=True)
            listed.write_text(json.dumps([{**row, "line": standing[id(row)]} for row in earlier]))
            shown = [({**row, "line": standing[id(row)]}, now, failing) for row, now, failing in replayed]
            told = [({**row, "line": standing[id(row)]}, why) for row, why in left]
            if delta:
                changed = capped(lp, git(lp.wt, "diff", delta, head, check=False))
                work = (f"## Fix delta ({delta[:12]}...HEAD in {lp.wt}; what changed since the "
                        f"last review)\n```diff\n{changed}\n```\n\n{replay_section(shown, told, delta)}")
            else:
                work = f"{whole}\n\n{replay_section(shown, told, None)}"
        paths = changed_test_paths(lp, head)
        if paths:
            # Leave room for full names, including git's quoted non-ASCII paths.
            width = max(len(p.encode()) * 4 + 2 for p in paths)
            stat = git(lp.wt, "diff", f"--stat={width + 80},{width}", "--no-renames",
                       f"{lp.base_sha}...{head}", "--", *(f":(literal){p}" for p in paths))
            checks = ("## Checks the executor changed\n```\n"
                      + "\n".join(stat.splitlines()[:-1]) + "\n```\n\n")
    identity = {} if lp.scratch else commit_identity(lp.wt)
    disputes = review_disputes(lp, identity.get("head_sha"))
    validation = getattr(lp, "validation", identity if lp.state.get("review_pr") else {})
    # A hand-built stand-in for the loop (as in test_v4c) carries no commands; the real
    # Loop always does, and only then are markers attributed to their commands.
    passed, total = done_when_counts(dw_log, getattr(lp, "cmds", None))
    if lp.scratch:
        heading = f"## Done-when output (run by the loop; {passed} of {total} commands exited 0)"
    else:
        heading = (f"## Done-when output (run by the loop on commit "
                   f"{identity.get('head_sha', '')[:12]}; {passed} of {total} commands exited 0)")
    deferred = ""
    if getattr(lp, "once", ()):
        deferred = ("\n".join(f"runs once at landing on the commit to be merged: {cmd}"
                               for cmd in lp.once)
                    + "\nThese run at landing; their absence here is by design "
                      "and is never a finding.")
    flaky = ""
    if re.search(r"^flaky: ", dw_log or "", re.M):
        flaky = ("A `flaky:` record is ak's own rule, not a weakened check: a done-when command "
                 "that fails runs once more at once, and it passes if that re-run does.")
    lp.log(f"--- round {lp.rnd}: reviewer {lp.reviewer}")

    def body_with(section):
        text = (f"{lp.body}\n\n{section}\n\n"
                + (disputes.text + "\n" if disputes.disputes else "")
                + f"## Executor summary\n{summary}\n\n{heading}\n"
                + (f"{deferred}\n" if deferred else "")
                + (f"{flaky}\n" if flaky else "")
                + f"```\n{dw_log}\n```")
        if preface:
            text = f"{preface}\n\n{text}"
        return checks + text
    rbody = body_with(work)
    # a conversation that resumes holds the whole change already; one that cannot gets it too
    rbody_whole = body_with(f"{whole}\n\n{work}") if delta else rbody
    # A review cut off mid-turn is continued where it was, fallback model and all: the
    # attempt after a fallback wrote under `reviewer-<model>`, and asking `reviewer` for
    # it would start the review over in a directory beside the one holding its session.
    # The round is read off `dir`, which is what free_dir writes through.
    rd = lp.dir("reviewer").parent
    name = turns.open_review(rd)[0] or "reviewer"
    def fall_back(reason, out, allow_self=True, ending=Exhausted):
        """The path a dry, twice-silent or twice-transient reviewer takes: next spare, else Exhausted."""
        # Recheck at the point of fallback, including spares from saved/legacy callers, and
        # against the meters as they read now: a spare whose own provider has run dry is none.
        try:
            providers = collect_usage(lp.cfg)
        except config.Error as exc:
            providers = {}      # meters nobody could read withhold no spare from a dead review
            lp.log(f"WARN could not read the meters before falling back: {exc}")
        order = ready_order(lp.cfg, providers, run_reviewers(lp.cfg, lp.state), lp.log,
                            role="reviewer", repo=lp.state.get("repo"))
        own = lp.state.get("own_orchestrator") if lp.state.get("own_pr") else None
        exec_for_rule = own or lp.executor
        writers = head_writers(lp.state)        # everyone who wrote part of the head
        spares = reviewer_order(lp.cfg, writers,
                                [n for n in order if n in lp.spares and n != lp.reviewer])
        if not allow_self:
            # A flake waits unless another model can review: only a reviewer that cannot
            # come back settles for the executor's own model.  The filter is local, so a
            # later fallback with a real reason still finds it.
            offered = [n for n in spares
                       if not any(same_model(lp.cfg, wrote, n) for wrote in writers)]
        else:
            offered = spares
        if not offered:
            raise ending(f"reviewer {lp.reviewer} {reason} and no eligible reviewer is left "
                            f"to review; waiting for review. See {out}*/stderr.log")
        lp.reviewer, lp.review_sid = offered.pop(0), None
        lp.spares = [n for n in spares if n != lp.reviewer]
        lp.save()
        # said only where it is true: a spare may share the executor's company
        theirs, spare = review_providers(lp.cfg, exec_for_rule, lp.reviewer)
        lp.log(f"WARN reviewer fell back to {lp.reviewer}"
               f"{' on another provider' if theirs not in (None, spare) else ''}")
        return f"reviewer-{lp.reviewer}"
    ask = None      # where the answer that gave no verdict is, for the call asking once more
    while True:
        if not lp.executor and not lp.state.get("review_pr"):
            raise config.Error("task review requires a recorded executor")
        exec_provider, review_provider = review_providers(lp.cfg, lp.executor, lp.reviewer)
        # The open attempt is read before free_dir creates the next directory.
        turn_kind, turn_sid = turns.open_turn(rd, name)
        out = turns.free_dir(lp, name)
        body = rbody if lp.review_sid else rbody_whole
        asked_body, note, resume = body, None, {}
        if ask:
            asked_body, resume, ask = NO_VERDICT_ASK, {"fresh_body": rbody_whole, "previous": ask}, None
        elif turn_kind == "resume":
            asked_body = turns.host_ended_prompt(lp.state)
            lp.review_sid = turn_sid
            note = {"at": time.time(), "role": "reviewer", "restarted": False}
            lp.state["resume_notice"] = note
            resume = {"fresh_body": rbody_whole, "resume_note": note, "previous": turns.latest_turn(rd, name)}
        elif turn_kind == "fresh":
            asked_body = rbody_whole
            lp.review_sid = None
            note = {"at": time.time(), "role": "reviewer", "restarted": True}
            lp.state["resume_notice"] = note
        else:
            # a conversation that cannot resume after all starts fresh on the whole change
            resume = {"previous": turns.review_turn(rd, lp.review_sid, since), "fresh_body": rbody_whole}
        why, ending = "died on API/transport errors", Exhausted
        model = lp.reviewer     # a fallback below moves on from it before its tokens are read
        reviewed = config.model(lp.cfg, model)
        review_harness, review_model = reviewed["harness"], reviewed["model"]

        def handover(detail, out=out):
            try:
                return fall_back(detail, out, allow_self=False)
            except Exhausted:
                return None
        try:
            code, text, lp.review_sid, dead = call_retrying(lp.cfg, lp.reviewer, asked_body,
                                                            lp.wt, out, lp.role("reviewer"),
                                                            lp.review_sid, lp.log,
                                                            lp.turn_limit,
                                                            handover=handover, findings=listed,
                                                            **resume)
        except worker.LoginExpired as expired:
            lp.review_sid = expired.session or lp.review_sid
            lp.save()           # the parked conversation is in run.json before the run parks
            raise
        except Killed as killed:
            lp.review_sid = killed.session or lp.review_sid
            lp.save()           # the killed conversation is in run.json before the run parks
            raise
        except turns.CannotRun as broken:
            # The spares road, as for a spent window; with no spare left, the run is blocked
            # on the harness's own line rather than waiting for a meter it is not short of.
            try:
                name = fall_back(broken.detail, out)
            except Exhausted:
                raise broken from None
            continue
        except turns.TransientHandover as handed:
            # fall_back already moved the role inside the callback; the spare reviews
            # in a fresh out dir on a fresh session.
            name = handed.new
            continue
        except turns.RanDry as dry:
            # A spent window is the other way a reviewer stops without judging the diff, so it
            # takes the same road out: the spares, checked against the executor and config.
            dry.remember(lp.state)
            code, text, lp.review_sid, dead, why = dry.code, dry.text, dry.session, True, dry.detail
            ending = dry.ending
        finally:
            history_role_tokens(lp.state.get("run_id"), "reviewer", out, lp.log, lp.cfg, model)
        if code != 0:
            lp.log(f"WARN reviewer {killed_word(code) or f'exited {code}'}; "
                   f"see {out / 'stderr.log'}")
        if dead:
            record_findings(lp, out, text)
            lp.save()
            name = fall_back(why, out, ending=ending)
            continue
        submitted = review_records(out, text)
        if submitted is not None and submitted.done:
            break
        # A missing verdict is a reviewer that has not answered, never an answer: ask the
        # same session once more, same round, no backoff, through the same call as the
        # review itself, so a window spent on the ask is a spent window and waits for its
        # refill.  When the turn already spent its one extra call finishing background
        # work in the foreground, that call already carried the verdict ask, so a second
        # silence means the reviewer is gone: no round is recorded, same as a dead reviewer.
        if asked_body == NO_VERDICT_ASK or list(lp.round_dir.glob(f"{out.name}*foreground*")):
            record_findings(lp, out, text)
            lp.save()
            name = fall_back("gave no verdict twice", out)
            continue
        lp.log(f"reviewer {lp.reviewer} gave no verdict; asking once more")
        ask = written_answer(out, text).parent

    checkout_changed = not lp.scratch and (
        identity != validation or commit_identity(lp.wt) != identity
        or (not lp.state.get("review_pr") and git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0))
    submitted = weigh_review(lp, submitted, identity.get("head_sha"), since=delta, replayed=replayed)
    upheld = {(row["path"], row["line"]) for row in submitted.findings}
    for row in disputes.disputes:
        # a dispute's finding is upheld wherever the fix left its line: moved, at the anchor
        # of its removal, or among the lines the fix put in its place
        lines = moved_lines(lp, row["path"], row["line"], delta, identity.get("head_sha"))[0]
        if not any((row["path"], at) in upheld for at in lines):
            dropped = lp.state.setdefault("disputes", [])
            text_dispute = "Dropped: " + hand_in.item_text(row)
            if text_dispute not in dropped:
                dropped.append(text_dispute)
    lp.state.pop("dispute_files", None)
    verdict = submitted.verdict
    overridden = None       # why the loop failed what the reviewer passed, for the hand-back
    if code != 0 and verdict == "PASS":
        verdict = "FAIL"
        overridden = f"the reviewer said PASS but {killed_word(code) or f'exited {code}'}"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    if ok is False and verdict == "PASS":
        verdict = "FAIL"
        # the check that failed, by name: the reviewer's text says PASS, and it is what is read
        checks = [line for line in (dw_log or "").splitlines() if LOOP_NOTE.match(line)]
        overridden = "; ".join(["the reviewer said PASS while done-when is failing", *checks])
        lp.log(f"WARN {overridden}; overriding to FAIL")
    if checkout_changed or (not lp.scratch and (
            commit_identity(lp.wt) != identity or (not lp.state.get("review_pr") and
                                                   git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0))):
        verdict = "FAIL"
        overridden = "the checkout changed after verification"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    record_findings(lp, out, text, submitted=submitted)
    lp.state["notes"] = submitted.notes
    # kept whatever the verdict, every round's, with the commit each was proven on for its plan
    # line; each defect once, whichever round proved it: the same defect handed in again on a
    # later head differs only in its proof, which names that head, and the first one is kept
    known = set((lp.state.get("followup_defects") or {}).values())
    fresh = []
    for item, defect in submitted.followup_defects.items():
        if defect not in known:
            known.add(defect)
            fresh.append(item)
    lp.state["followups"] = (lp.state.get("followups") or []) + fresh
    for key, found in (("followup_checks", submitted.followup_checks),
                       ("followup_commits", submitted.followup_commits),
                       ("followup_defects", submitted.followup_defects)):
        lp.state[key] = {**(lp.state.get(key) or {}), **{item: found[item] for item in fresh if item in found}}
    if verdict == "PASS":
        record_flakes(lp.state, dw_log)
        # A landing re-review with a pending suite keeps the task's probe base.
        if not getattr(lp, "once", ()) or (record and not lp.state.get("landing")):
            passed_head = validation.get("head_sha")
    passed = {"passed_head_sha": passed_head} if passed_head else {}
    if record:
        lp.state["round_summaries"].append(
            {"round": lp.rnd, "verdict": verdict, "done_when": ok,
             "finding_count": len(submitted.findings),
             "summary": summary.strip()[-4000:], **validation, **passed})
    lp.log(f"round {lp.rnd} verdict: {verdict}")
    lp.state["verdict"] = verdict
    lp.state["review"] = {"executor": lp.executor, "executor_provider": exec_provider,
                          "reviewer": lp.reviewer, "reviewer_provider": review_provider,
                          "returncode": code, "verdict": verdict, "done_when": ok, **validation, **passed,
                          **({"overridden": overridden} if overridden else {})}
    lp.state.pop("review_pending", None)
    if validation.get("head_sha"):
        lp.state["delta_from"] = validation["head_sha"]     # every review, recorded or not
    lp.save()
    own = hand_in.Review([row for row in submitted.records if not row.get("replayed")])   # ak's replays are no reviewer's catch
    history.record_review(lp.state.get("run_id"), str(out),
                          harness=review_harness, model=review_model,
                          blocking=len(own.findings), followup=len(own.preexisting),
                          note=len(own.notes), log=lp.log)
    return verdict


def rounds(lp, execv=None):
    """Executor -> done-when -> reviewer, until PASS or the round budget is spent.

    Only a recorded successful review by an eligible model can skip straight to delivery.
    An unfinished review resumes on the saved work without spending another executor turn.
    """
    invalidate_saved_pass(lp.state, lp.cfg, lp.log)
    lp.rounds = lp.state["rounds"]
    lp.save()
    if (lp.state.get("waiting_on") or {}).get("line"):
        return     # the lander's verdict resumes delivery, never a task round
    pending = lp.state.get("review_pending")
    if (pending and "record" not in pending and pending.get("round") == lp.rnd + 1
            and pending.get("reason", "").startswith("Re-review after the ")):
        # Older landing receipts reserved the next round before record=False existed.
        pending.update(round=lp.rnd, record=False)
        lp.save()
    if pending and pending.get("record") is False:
        # A landing gate may be waiting on a changed target, not another task
        # round. Bring that target in before verifying or reviewing the fixes.
        upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
        if not integrate(lp, upstream) and lp.state.get("merge_failed"):
            # An unreachable target needs the tick's error retry, not a task verdict.
            raise config.Error(lp.state["merge_note"])
        return
    if review_pass(lp.state, lp.cfg) and not current_review(lp):
        # A changed checkout needs a task review, not landing's target integration on resume.
        entries = lp.state["round_summaries"]
        lp.state.update(verdict=None, review=None,
                        review_pending={"round": lp.rnd + 1,
                                        "summary": entries[-1]["summary"] if entries else "",
                                        "reason": "The saved reviewed commit changed; "
                                                  "verify the current checkout.",
                                        "passed_head_sha": passed_review_head(lp.state)})
        lp.save()
    if current_review(lp):
        lp.log(f"already passed at round {lp.rnd}/{lp.rounds}; going straight to the merge")
        return
    pending = lp.state.get("review_pending")
    if pending:
        # a review finished on a resume is the round's verdict
        if resume_review(lp) == "PASS":
            return
    while round_allowed(lp):
        pickup_new_code(lp, execv=execv)
        lp.rnd += 1
        cut = continuation(lp)
        if cut in ("reviewer", "done-when"):
            # The worker already answered. A done-when that was cut off runs again;
            # a review that was the open step is continued, not preceded by another
            # executor turn.
            source = turns.saved_worker_answer(lp.round_dir)
            summary = worker_result(lp, turns.read_answer(source) or "", source.parent) if source else ""
            settled = settled_gate(lp) if cut == "reviewer" else None
            if settled is None:
                if cut == "done-when":
                    lp.log(f"--- round {lp.rnd}/{lp.rounds}: continuing done-when")
                ok, dw_log = verify_work(lp)
                lp.log(f"done-when: {'all passed' if ok else 'FAILED'}")
            else:
                ok, dw_log = settled
                lp.log(f"--- round {lp.rnd}/{lp.rounds}: continuing the review")
            if cut != "reviewer" and not ok:
                lp.log(f"--- round {lp.rnd}: fixer {lp.executor} (done-when failed)")
                fix = (f"{lp.context}\n\n## The done-when commands failed. "
                       f"Fix the root cause.\n```\n{dw_log}\n```")
                summary = (f"{summary}\n\n### After done-when fix\n"
                           f"{execute(lp, 'fixer', fix, 'fixer')}")
                ok, dw_log = verify_work(lp)
                lp.log(f"done-when after fix: {'all passed' if ok else 'still FAILING'}")
        else:
            worker_name = turns.open_worker(lp)[0] if cut == "worker" else None
            if worker_name and worker_name != "executor":
                lp.log(f"--- round {lp.rnd}/{lp.rounds}: continuing {worker_name}")
                log_path = lp.round_dir / "donewhen.log"
                dw = log_path.read_text(errors="replace") if log_path.is_file() else ""
                summary = execute(
                    lp, "fixer",
                    f"{lp.context}\n\n## The done-when commands failed. Fix the root cause.\n```\n{dw}\n```",
                    worker_name)
            else:
                lp.log(f"--- round {lp.rnd}/{lp.rounds}: executor {lp.executor}")
                if lp.rnd == 1:
                    summary = execute(lp, "executor", lp.context, "executor")
                else:
                    fixer_body = (f"{lp.context}\n\n## Reviewer findings to fix\n"
                                  f"{without_followups(lp.findings)}")
                    summary = execute(lp, "fixer", fixer_body, "executor")
            ok, dw_log = verify_work(lp)
            lp.log(f"done-when: {'all passed' if ok else 'FAILED'}")
            if not ok:
                lp.log(f"--- round {lp.rnd}: fixer {lp.executor} (done-when failed)")
                fix = (f"{lp.context}\n\n## The done-when commands failed. "
                       f"Fix the root cause.\n```\n{dw_log}\n```")
                summary = f"{summary}\n\n### After done-when fix\n{execute(lp, 'fixer', fix, 'fixer')}"
                ok, dw_log = verify_work(lp)
                lp.log(f"done-when after fix: {'all passed' if ok else 'still FAILING'}")
        same_failure(lp, ok, dw_log)
        if review(lp, summary, ok, dw_log, "Re-review after fixes." if lp.rnd > 1 else "") == "PASS":
            return


# --- the merge pipeline: PASS -> origin -> a PR -> its checks -> merged -----


def note(lp, reason, failed=False):
    """Why the branch is not merged.  `failed` means the run itself did not do its job."""
    reason = " ".join(reason.split())   # result.md gives it one line, however git wrapped it
    lp.state["merge_note"] = reason
    lp.state["merge_failed"] = failed
    lp.log(("ERROR " if failed else "WARN ") + f"not merged: {reason}")
    lp.write()
    return False


def park_waiting(lp, reason, ref, sha=None):
    """Park the run `waiting` on the next merge to `ref`, with the reason.

    Not an ending and never a FAIL: the work passed review and only the world stands in
    its way, and the world keeps moving.  The record carries the whole of the wait -- the
    reason on `merge_note` and on `error`, the ref to watch and the sha a fetch reads now
    -- so the tick picks the run up after the next merge to `ref` and retries it there
    rather than anybody losing the passed work behind a note.  A run parked on a red target
    also names the run repairing it, and retries when that one lets go of the tip
    (`repair_open`).
    """
    note(lp, reason, failed=False)
    waiting_on = dict(lp.state.get("waiting_on") or {})
    if waiting_on.get("line"):
        lp.state.update(state="waiting", error=reason)
        lp.write()
        return False
    waiting_on = {"ref": ref}
    if sha:
        waiting_on["sha"] = sha
    repair = getattr(lp, "repair", None)
    if repair:
        waiting_on["repair"] = repair
    lp.state.update(state="waiting", error=reason, waiting_on=waiting_on)
    lp.state.pop("recovery_pending", None)  # the wait is the tick's now
    lp.write()
    lp.log(f"--- merge: parked waiting; retried after the next merge to {ref}"
           + (f" or when {repair} ends" if repair else ""))
    return False


def in_progress(wt, how):
    """Is that `git rebase`/`git merge` still sitting in the worktree, unfinished?"""
    names = ("MERGE_HEAD",) if how == "merge" else ("rebase-merge", "rebase-apply")
    for name in names:
        path = Path(git(wt, "rev-parse", "--git-path", name))
        if not path.is_absolute():
            path = Path(wt) / path
        if path.exists():
            return True
    return False


def integrated(wt, rev):
    """Does the branch really carry `rev` now, whether by rebase or by merge?

    `rev` is the pinned commit the integration started from, never the moving branch name:
    the worktree shares its `.git` with checkouts other runs pull in, so `origin/main`
    can move under the run at any moment.  `git rebase --abort` also makes the rebase
    state directory disappear, so its absence alone says nothing: what makes either
    finished is the pinned commit being an ancestor of HEAD.
    """
    rc, _ = git_out(wt, "merge-base", "--is-ancestor", rev, "HEAD")
    return rc == 0


def patch_id(wt, base_sha):
    """The stable id of `base...HEAD`, or None for an empty diff or any git failure."""
    try:
        rc, diff = git_out(wt, "diff", f"{base_sha}...HEAD")
    except Stopped:
        raise
    except Exception:
        return None
    try:
        if rc != 0 or not diff.strip():
            return None
        proc = subprocess.run(["git", "-C", str(wt), "patch-id", "--stable"],
                              input=diff, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=TOOL_CAP, env=tool_env())
        if proc.returncode != 0:
            return None
        out = (proc.stdout or "").strip()
        return out.split()[0] if out else None
    except Exception:
        return None


def how_to_integrate(lp):
    """`merge` when the task asks for a merge commit or the branch already carries one.

    Rebasing such a branch replays each side of its merges as a flat run of commits: the
    history the run built is gone, and every commit it holds is rewritten.  A `git merge`
    brings origin in without touching what is already there.  Everything else rebases, so the
    common case still arrives at the PR as a straight line on top of the target.
    """
    if lp.state["merge_method"] == "merge":
        return "merge"
    merges = git(lp.wt, "rev-list", "--merges", f"{lp.base_sha}..HEAD", check=False)
    return "merge" if merges else "rebase"


def set_base(lp, tip):
    """Keep the integrated tip for the diff and suite, even if another fetch moves the ref."""
    tip = git(lp.wt, "rev-parse", f"{tip}^{{commit}}")
    lp.state.update(base_sha=tip, target_sha=tip)
    lp.write()


def abort_integration(lp, how):
    """Put the branch back, keeping any earlier landing review.

    A task review describes the abandoned integration and goes with it. A non-task
    review can predate it: the restored HEAD still holds unreviewed landing fixes,
    so recovery must keep that pending review at the current round. The invalidated
    verdict stays invalidated.
    """
    git_out(lp.wt, how, "--abort")
    if (lp.state.get("review_pending") or {}).get("record") is not False:
        lp.state.pop("review_pending", None)
    lp.write()


CONFLICT_ROUNDS = 3      # the merge pipeline's own fixer rounds per conflict or failing re-run


def fix_after_failed_review(lp, upstream, how):
    """A review failed after the merge-time rebase or a final-check fix, with rounds to spend.

    One fixer round carries its findings like any failed review -- all of them, exactly
    as the round loop hands them over -- then done-when runs and the reviewer judges
    again, until a review passes or the round budget is spent.  True when the merge may
    go on; False at the budget, and only then does the caller record why nothing merged:
    the loop never ends a run FAIL with rounds unspent.

    The whole review is carried even when its findings are prose rather than a list, or
    none at all; a done-when that failed it comes with its output, so a PASS the gate
    overrode is fixed on what the gate said.
    """
    if (lp.state.get("waiting_on") or {}).get("line"):
        return False
    what = f"the {how} of {upstream}"
    while round_allowed(lp):
        fix = f"{lp.context}\n\n## Reviewer findings to fix\n{without_followups(lp.findings)}"
        if (lp.state.get("review") or {}).get("done_when") is False:
            # the output the review was given, still in the round directory it ran in
            log_path = lp.round_dir / "donewhen.log"
            dw_log = log_path.read_text(errors="replace") if log_path.is_file() else ""
            fix += (f"\n\n## The done-when commands failed. Fix the root cause.\n```\n"
                    f"{dw_log}\n```")
        lp.rnd += 1
        lp.log(f"--- round {lp.rnd}/{lp.rounds}: fixer {lp.executor} (findings after {what})")
        summary = execute(lp, "fixer", fix, "executor")
        ok, dw_log = verify_work(lp)
        lp.log(f"done-when after the fix: {'all passed' if ok else 'FAILED'}")
        same_failure(lp, ok, dw_log)
        if review(lp, summary, ok, dw_log, f"Re-review after fixes for {what}.") == "PASS":
            return True
    return False


def landing_fixer(lp, text, name):
    """Give any landing fixer the line's red output and remember its completed turn."""
    wait = lp.state.get("waiting_on") or {}
    failure = wait.get("fix") if wait.get("line") else None
    if failure and name != "final-fixer":
        # An unrelated conflict or light check must not hide the lander's failure.
        output = Path(failure["log"]).read_text(errors="replace")
        text += (f"\n\n## The final check failed. Fix the root cause as well.\n```\n"
                 f"{failing_blocks(output)}\n```")
    summary = execute(lp, "fixer", text, name)
    if failure:
        # Save the actual fixer with its summary before a check or review can stop.
        lp.state["waiting_on"]["fixed"] = True
        lp.state["review_pending"]["summary"] = summary
        lp.save()
    return summary


def resolve_conflicts(lp, upstream, out, how, tip=None):
    """Hand a conflicted rebase or merge back to the executor, then re-test and re-review it.

    True once the branch carries the pinned `tip` and still passes.  False parks the run
    `waiting` with the reason: a conflict is the world moving, never a verdict on work
    that passed review, so a conflict fixer round spends no task round and never ends the
    run FAIL however the round budget stands.  Up to `CONFLICT_ROUNDS` of them work one
    conflicted rebase or merge, the unfinished ones on the same stopped `git`, and the
    re-review that fails is a failed review like any other -- a fixer round on its
    findings, within the round budget it may spend, and once that is spent a review FAIL
    handed back with them, never a wait that could only end in the same one.

    `upstream` names the branch for messages; every check uses `tip`, never the moving name
    again.  A re-test that fails on the target's tip but passes on the last reviewed
    head's target base parks `waiting`, spending no round.  An unchanged base needs
    only the tip probe.
    """
    tip = tip or upstream
    conflicts = [p for p in git(lp.wt, "diff", "--name-only", "--diff-filter=U",
                                check=False).splitlines() if p]
    what = f"the {how} of {upstream}"
    lp.log(f"WARN {what} conflicted in {len(conflicts)} file(s)")
    finish_it = ("`git commit` to finish the merge" if how == "merge"
                 else "`git rebase --continue` until the rebase is finished")
    text = (f"{lp.context}\n\n## Resolve the {how} conflict\n"
            f"`git {how} {upstream}` is in progress in {lp.wt} and has stopped on conflicts. "
            f"Resolve every one keeping both sides' intent -- never drop the other side's work -- "
            f"then `git add` the files and {finish_it}. "
            f"Re-run the done-when commands afterwards.\n\n### Conflicted files\n"
            + "\n".join(f"- {p}" for p in conflicts) + f"\n\n```\n{out[-OUT_CAP:]}\n```")
    summary, landed = "", False
    for attempt in range(1, CONFLICT_ROUNDS + 1):
        lp.log(f"--- merge: conflict round {attempt}/{CONFLICT_ROUNDS}: "
               f"fixer {lp.executor} ({how} conflict)")
        try:
            summary = landing_fixer(lp, text, f"{how}-fixer")
        except (Dead, Blocked, Exhausted, Killed, worker.LoginExpired) as exc:
            pending = lp.state.get("review_pending")
            if isinstance(exc, (Exhausted, Killed, worker.LoginExpired)) and pending:
                # A stopped conflict fixer retries landing even at the task round budget.
                pending.update(round=lp.rnd, record=False)
            # whatever stops here, the retry starts from a clean tree: a rebase or merge
            # left in progress behind it would be a conflict round nobody asked for
            abort_integration(lp, how)
            raise
        if not in_progress(lp.wt, how):
            landed = integrated(lp.wt, tip)
            break
        if attempt < CONFLICT_ROUNDS:
            lp.log(f"WARN the fixer did not finish {what}; another conflict round works it")
    if not landed:
        # only an unfinished rebase or merge is aborted, and only then is it said to be:
        # a fixer that finished the `git` but left the tip out is reported the same way
        abort_integration(lp, how)
        lp.save()
        return park_waiting(lp, f"the fixer did not finish {what}; it was aborted",
                            upstream, tip)
    set_base(lp, tip)
    # Keep the passed head for target probes; a provider wait also resumes as a
    # conflict round, outside the task budget.
    lp.state["review_pending"] = {**(lp.state.get("review_pending") or {}),
                                  "round": lp.rnd, "summary": summary,
                                  "reason": f"Re-review after {what}.", "record": False}
    lp.save()
    ok, dw_log = verify_work(lp)
    lp.log(f"done-when after the {how}: {'all passed' if ok else 'FAILED'}")
    said = "" if ok else target_fails(lp, upstream, dw_log)
    if said:
        return park_waiting(lp, f"{upstream} itself fails: {said}", upstream, tip)
    # as after the final check: the rounds' history is the rounds' to write, and a gate that
    # passed before the merge began leaves this one nothing to be the same as -- and a
    # conflict round is no task round, so nothing of it enters that history either
    if review(lp, summary, ok, dw_log, f"Re-review after the {how} of {upstream}.",
              record=False) != "PASS":
        if not fix_after_failed_review(lp, upstream, how):
            return note(lp, f"done-when or review after {what} did not pass")
    return True


def abort_stopped_integration(lp, how):
    """Put the branch back after a merge or rebase that was killed, before the run stops.

    A killed `git merge`/`git rebase` can leave MERGE_HEAD or a rebase state directory behind;
    the retry starts from a clean tree, so the abort runs under the cap like every other call.
    An abort that itself stops -- or that leaves the merge/rebase state behind, as one blocked
    by a leftover `.git/index.lock` does -- is logged and left, never claimed clean: the run
    still stops with the original remedy, and the resume reaps a worktree it can inspect.
    A no-op abort (nothing in progress is already the clean tree) still reports back on head.
    """
    try:
        rc, out = git_out(lp.wt, how, "--abort")
    except Stopped as exc:
        lp.log(f"WARN could not abort the stopped {how} of {lp.state['branch']}: {exc}")
        return
    try:
        dirty = rc != 0 and in_progress(lp.wt, how)
    except config.Error as exc:
        # the abort failed and the state cannot even be read: never claim the branch is back
        lp.log(f"WARN could not abort the stopped {how} of {lp.state['branch']}: {exc}; "
               f"the retry starts from whatever the {how} left behind")
        return
    if dirty:
        lp.log(f"WARN could not abort the stopped {how} of {lp.state['branch']}: {out[-200:]}; "
               f"the retry starts from whatever the {how} left behind")
        return
    lp.log(f"--- merge: aborted the stopped {how}; {lp.state['branch']} back on its head")


def target_disjoint_from_branch(wt, base, head_before, tip):
    """Whether the target's moves since `base` touch none of the branch's files.

    Both sides are read off `base`: the branch's files from `base..head_before`,
    the target's from `base..tip`.  Disjoint means a clean rebase changed only the
    parent, so the round's checks still verify the rebased commit.  Anything git
    cannot compare is overlapping: the checks run again.
    """
    sides = []
    for end in (head_before, tip):
        # `git()` strips whitespace, and with it the space a first name can start with
        code, out, _ = tool_run(["git", "-C", str(wt), "diff", "--no-renames",
                                 "--name-only", "-z", base, end])
        if code != 0:
            return False
        sides.append(set(out.split("\0")) - {""})
    return not (sides[0] & sides[1])


def integrate(lp, upstream):
    """Integrate one pinned target tip, resolving conflicts and rechecking changed work.

    A rebase, unless `how_to_integrate` says this branch's history has to survive.
    Checks use the pinned commit; delivery detects later target changes. A re-check
    red on the target and green on the old base parks without a fixer round.
    A branch with no diff ends PASS as already on the target.

    A stopped fetch, merge or rebase propagates after aborting integration, so the
    run stays retryable rather than spending a conflict round on a tool failure.
    """
    # --prune: a merged PR's branch, deleted on origin, otherwise leaves its tracking ref
    # behind, and push's lease holds a later run that reuses the name to that dead head
    rc, out = fetch(lp.wt, "origin", "--prune")
    if rc != 0:
        return note(lp, f"git fetch origin failed: {out[-400:]}", failed=True)
    if not git(lp.wt, "rev-parse", "--verify", "--quiet", f"{upstream}^{{commit}}",
               check=False):
        return note(lp, f"{upstream} does not exist on origin; nothing to merge into",
                    failed=True)
    tip = git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
    how = how_to_integrate(lp)
    try:
        pre_identity = commit_identity(lp.wt)
    except Stopped:
        raise
    except config.Error:
        pre_identity = None
    saved = dict(lp.state["review"]) if isinstance(lp.state.get("review"), dict) else None
    saved_verdict = lp.state.get("verdict")
    try:
        was_pass = review_pass(lp.state, lp.cfg)
    except Stopped:
        raise
    except Exception:
        was_pass = False
    old_head = pre_identity["head_sha"] if pre_identity else None
    landing_review = (lp.state.get("review_pending") or {}).get("record") is False
    # Persist invalidation before git rewrites HEAD: interruption must not leave a saved PASS.
    if not integrated(lp.wt, tip):
        if landing_review:
            lp.state.update(verdict=None, review=None)
            lp.save()
        else:
            pending_review(lp, f"Re-review after the {how} of {upstream}.")
    try:
        if how == "merge":
            lp.log(f"--- merge: merging {upstream} ({tip[:12]}) into {lp.state['branch']}")
            # check 19 in tests/smoke.sh pins the bare line below; the SHA line above
            # records the pinned tip being integrated.
            lp.log(f"--- merge: merging {upstream} into {lp.state['branch']}")
            rc, out = git_out(lp.wt, "merge", "--no-edit", tip)
        else:
            lp.log(f"--- merge: rebasing {lp.state['branch']} onto {upstream} ({tip[:12]})")
            rc, out = git_out(lp.wt, "rebase", tip)
    except Stopped:
        abort_stopped_integration(lp, how)
        raise
    if rc != 0:
        with released_gate_turn():
            resolved = resolve_conflicts(lp, upstream, out, how, tip)
        if not resolved:
            return False
        # the conflict round re-tested this commit and the review passed on it
        lp.checked_every_sha = git(lp.wt, "rev-parse", "HEAD")
    else:
        old_base = lp.state.get("base_sha")
        set_base(lp, tip)
        if current_review(lp) and not landing_review:
            lp.log("--- merge: unchanged commit; reusing done-when and review evidence")
        else:
            # a passed review survives a clean integration whatever it leaves, an empty
            # diff included: the done-when runs again on the new commit, and only its
            # failure or a commit it changed sends the work back to the reviewer --
            # unless the target moved only outside the branch's files, which lands on
            # the round's checks without re-running them
            carried = lp.state.get("final_check")
            carried_here = (isinstance(carried, dict)
                            and carried.get("outcome") == "passed"
                            and carried.get("sha") == old_head)
            if (not landing_review and was_pass and saved is not None and pre_identity is not None
                    and saved.get("head_sha") == pre_identity.get("head_sha")
                    and saved.get("tree_sha") == pre_identity.get("tree_sha")
                    and old_base and old_head and carried_here
                    and target_disjoint_from_branch(lp.wt, old_base, old_head, tip)):
                new_identity = commit_identity(lp.wt)
                lp.log(f"--- merge: clean {how} of {upstream}; target moved outside "
                       "this branch's files, reusing done-when and review evidence")
                lp.state["review"] = {**saved, "head_sha": new_identity["head_sha"],
                                      "tree_sha": new_identity["tree_sha"],
                                      "passed_head_sha": passed_review_head(lp.state),
                                      "rebased_from": old_head,
                                      "patch_id": patch_id(lp.wt, tip)}
                lp.state["verdict"] = saved_verdict
                lp.state.pop("review_pending", None)
                lp.save()
                lp.checked_every_sha = new_identity["head_sha"]
            elif (landing_review or (was_pass and saved is not None and pre_identity is not None
                    and saved.get("head_sha") == pre_identity.get("head_sha")
                    and saved.get("tree_sha") == pre_identity.get("tree_sha"))):
                try:
                    post_identity = commit_identity(lp.wt)
                except Stopped:
                    raise
                except config.Error:
                    post_identity = None
                if post_identity is None:
                    if not lp.state.get("review_pending"):
                        pending_review(lp, f"Re-review after the {how} of {upstream}.")
                    with released_gate_turn():
                        passed = (resume_review(lp) == "PASS"
                                  or fix_after_failed_review(lp, upstream, how))
                    if not passed:
                        return note(lp, f"done-when or review after the {how} of {upstream} "
                                        "did not pass")
                    lp.checked_every_sha = git(lp.wt, "rev-parse", "HEAD")
                else:
                    pending = lp.state.get("review_pending")
                    pending_round = pending["round"] if pending else lp.rnd
                    old_rnd = lp.rnd
                    lp.rnd = pending_round
                    lp.round_dir.mkdir(parents=True, exist_ok=True)
                    ok, dw_log = verify_work(lp)
                    lp.log(f"done-when after the {how}: {'all passed' if ok else 'FAILED'}")
                    if ok:
                        new_identity = commit_identity(lp.wt)
                        if new_identity != post_identity or landing_review:
                            if not lp.state.get("review_pending"):
                                pending_review(lp, f"Re-review after the {how} of {upstream}.")
                            with released_gate_turn():
                                passed = (resume_review(lp, verified=(ok, dw_log)) == "PASS"
                                          or fix_after_failed_review(lp, upstream, how))
                            if not passed:
                                return note(lp, f"done-when or review after the {how} of {upstream} "
                                                "did not pass")
                            lp.checked_every_sha = git(lp.wt, "rev-parse", "HEAD")
                        else:
                            lp.log(f"--- merge: clean {how} of {upstream}; "
                                   "done-when passed again, review kept")
                            lp.state["review"] = {**saved, "head_sha": new_identity["head_sha"],
                                                  "tree_sha": new_identity["tree_sha"],
                                                  "passed_head_sha": passed_review_head(lp.state),
                                                  "rebased_from": old_head,
                                                  "patch_id": patch_id(lp.wt, tip)}
                            lp.state["verdict"] = saved_verdict
                            record_flakes(lp.state, dw_log)
                            lp.state.pop("review_pending", None)
                            lp.save()
                            lp.rnd = old_rnd
                            lp.checked_every_sha = new_identity["head_sha"]
                    else:
                        # The target moved under work that already passed: fix the
                        # gate before reviewing it, without spending task rounds.
                        lp.rnd = old_rnd
                        reason = f"Re-review after the {how} of {upstream}."
                        lp.state["review_pending"] = {"round": lp.rnd, "summary": "",
                                                      "reason": reason, "record": False,
                                                      "passed_head_sha": passed_review_head(lp.state)}
                        lp.save()
                        for attempt in range(CONFLICT_ROUNDS + 1):
                            said = target_fails(lp, upstream, dw_log)
                            if said:
                                return park_waiting(
                                    lp, f"{upstream} itself fails: {said}", upstream, tip)
                            if attempt == CONFLICT_ROUNDS:
                                return park_waiting(
                                    lp, f"done-when after the {how} still fails after "
                                        f"{CONFLICT_ROUNDS} fixer rounds: {first_failure(dw_log)}",
                                    upstream, tip)
                            lp.log(f"--- merge: re-run round {attempt + 1}/{CONFLICT_ROUNDS}: "
                                   f"fixer {lp.executor} (done-when after the {how})")
                            fix = (f"{lp.context}\n\n## The done-when commands failed. "
                                   f"Fix the root cause.\n```\n{failing_blocks(dw_log)}\n```")
                            with released_gate_turn():
                                summary = landing_fixer(lp, fix, "rerun-fixer")
                                lp.state["review_pending"]["summary"] = summary
                                lp.save()
                                lp.round_dir.mkdir(parents=True, exist_ok=True)
                                ok, dw_log = verify_work(lp)
                                lp.log(f"done-when after the fix: {'all passed' if ok else 'FAILED'}")
                                if ok:
                                    passed = (review(lp, summary, ok, dw_log, reason,
                                                     record=False) == "PASS"
                                              or fix_after_failed_review(lp, upstream, how))
                                    if not passed:
                                        return note(lp, f"done-when or review after the {how} "
                                                        f"of {upstream} did not pass")
                                    break
                        lp.checked_every_sha = git(lp.wt, "rev-parse", "HEAD")
            else:
                if not lp.state.get("review_pending"):
                    pending_review(lp, f"Re-review after the {how} of {upstream}.")
                with released_gate_turn():
                    passed = (resume_review(lp) == "PASS"
                              or fix_after_failed_review(lp, upstream, how))
                if not passed:
                    return note(lp, f"done-when or review after the {how} of {upstream} "
                                    "did not pass")
                lp.checked_every_sha = git(lp.wt, "rev-parse", "HEAD")
    if (not (lp.state.get("waiting_on") or {}).get("line")
            and git_out(lp.wt, "diff", "--quiet", tip, "HEAD")[0] == 0):
        lp.state["on_target"] = True
        return note(lp, f"its work is already on {upstream.removeprefix('origin/')}")
    return True


def push(lp):
    require_review_pass(lp)
    branch = lp.state["branch"]
    head = git(lp.wt, "rev-parse", "HEAD", check=False)
    if lp.state.get("merge_method") == "rebase":
        # Rebase merges preserve the branch's messages, ignoring a merge commit body.
        # Change only the message: staged or untracked files cannot become checked code.
        old = git(lp.wt, "show", "-s", "--format=%B", head)
        message = re.sub(r"(?m)^Suite-Passed-Tree:.*\n?", "", old).rstrip()
        body = merge_body(lp, head)
        if body:
            message = add_suite_trailer(lp, message, body[-1])
        if message != old.rstrip():
            git(lp.wt, "-c", f"core.hooksPath={os.devnull}", "commit", "--amend", "--only",
                "-m", message)
            head = git(lp.wt, "rev-parse", "HEAD")
            lp.state["review"]["head_sha"] = head
            if body:
                lp.state["final_check"]["sha"] = head
            lp.write()
    # origin as integrate's pruning fetch saw it: a name another run pushed before that fetch
    # is refused here, unless it holds a commit this run pushed -- or set out to, since origin
    # may take a push that stops before it is recorded, and the retry may have rebased since
    seen = git(lp.wt, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}",
               check=False)
    ours = lp.state.setdefault("pushed", [])
    if seen and seen not in (lp.state.get("delivery_sha"), *ours):
        return note(lp, f"origin already has {branch} at {seen[:12]} and this run did not push "
                        "it; the branch was taken by another run", failed=True)
    ours.append(head)
    lp.write()
    # --force-with-lease from the start: a rebased branch is a rewrite, and a resumed or
    # retried run finds its own earlier push already on origin.  Pinned to what was seen, so
    # a fetch in another worktree since cannot move the lease onto another run's commit
    rc, out = git_out(lp.wt, "push", f"--force-with-lease={branch}:{seen}", "-u", "origin", branch)
    if rc != 0:
        # a name this run never pushed, already on origin: another run took it while this one
        # worked, and the lease git refuses to break is the only thing that says so
        if re.search(r"stale info|rejected", out, re.I):
            return note(lp, f"origin already has {branch} and this run did not push it; the "
                            f"branch was taken by another run: {out[-400:]}", failed=True)
        return note(lp, f"pushing {branch} to origin failed: {out[-400:]}", failed=True)
    lp.log(f"--- merge: pushed {branch} to origin")
    lp.state["delivery_sha"] = head
    lp.write()
    return True


def github_body(text, run_id):
    """Keep publication within GitHub's limit; the run retains the complete records."""
    data = text.encode("utf-8")
    if len(data) <= GITHUB_BODY_CAP:
        return text
    note = f"\n\n[body truncated; complete findings and summaries are in agentkit run {run_id}]\n"
    return data[:GITHUB_BODY_CAP - len(note.encode("utf-8"))].decode("utf-8", "ignore") + note


def pr_body(state):
    last = state["round_summaries"][-1]["summary"].strip() if state["round_summaries"] else ""
    lines = [last, "", "---", "",
             f"- verdict: {state['verdict']}",
             f"- rounds: {len(state['round_summaries'])} of {state['rounds']}",
             f"- executor: {state['executor']}, reviewer: {state['reviewer']}",
             f"- run: {state['run_id']}"]
    if base_proof_line(state):
        lines.append(f"- {base_proof_line(state)}")
    if state.get("followups"):
        lines += ["", "## Follow-ups", "",
                  *("- " + item.replace("\n", "\n  ") for item in state["followups"])]
    if state.get("notes"):
        lines += ["", "## Notes", "",
                  *("- " + item.replace("\n", "\n  ") for item in state["notes"])]
    return github_body("\n".join(lines + [""]), state["run_id"])


def refresh_pr_body(lp):
    """A later passing review replaces the list on the already-open PR too."""
    path = lp.run_dir / "pr-body.md"
    body = pr_body(lp.state)
    if path.is_file() and path.read_text() == body:
        return True
    pending = lp.run_dir / "pr-body-update.md"
    pending.write_text(body)
    # through the REST API: `gh pr edit` asks GraphQL for Projects (classic) too, and since
    # GitHub retired them some gh releases (2.46) fail that ask and change nothing
    parts = pr_parts(lp.state["pr"])
    if parts is None:
        return note(lp, f"cannot update the description of {lp.state['pr']}: not a PR URL",
                    failed=True)
    api, owner, repo, number = parts
    rc, out = gitcall.gh(lp.wt, *api, "-X", "PATCH", f"repos/{owner}/{repo}/pulls/{number}",
                 "-F", f"body=@{pending}")
    if rc != 0:
        if stopped(rc, out):
            raise Stopped(out)
        return note(lp, f"updating the PR description failed: {out[-400:]}", failed=True)
    pending.replace(path)      # only a confirmed update may be skipped on a delivery retry
    return True


def open_pr(lp, target_branch):
    """The PR's URL, opening it first unless this branch already has one."""
    if lp.state.get("pr"):
        return lp.state["pr"] if refresh_pr_body(lp) else None
    path = lp.run_dir / "pr-body.md"
    path.write_text(pr_body(lp.state))
    rc, out = gitcall.gh(lp.wt, "pr", "create", "--base", target_branch, "--head", lp.state["branch"],
                 "--title", lp.state["title"], "--body-file", str(path))
    # gh names the existing PR in the error it refuses a duplicate with, so one regex covers both
    found = PR_URL.search(out)
    view = None
    if not found:
        # the create may still have happened server-side: the view says so, or stops too
        vrc, view = gitcall.gh(lp.wt, "pr", "view", lp.state["branch"], "--json", "url", "-q", ".url")
        found = None if stopped(vrc, view) else PR_URL.search(view)
    if not found:
        if stopped(rc, out) or (view is not None and stopped(vrc, view)):
            raise Stopped(out if stopped(rc, out) else view)
        note(lp, f"gh pr create failed: {out[-400:]}", failed=True)
        return None
    lp.state["pr"] = found.group(0)
    lp.write()
    lp.log(f"--- merge: PR {lp.state['pr']}" + (" (already open)" if rc != 0 else ""))
    return lp.state["pr"]


def poll_cap(deadline):
    """One poll of the checks wait: capped like any other call, never shrunk to fit the hour.

    Shrinking the last poll below a real round trip manufactures a stop out of a healthy gh:
    the loop sleeps to exactly the deadline before re-polling, so a clamped budget always
    expires on a `gh` that was still answering, and the deadline branch below -- which names
    the checks that never finished -- never runs.  The hour cap is enforced by that post-poll
    deadline test instead.
    """
    return TOOL_CAP


def pr_parts(url):
    """(`gh api` and the host it needs, owner, repository, number) of the PR at `url`, or None
    for a URL that is not one PR on an https host."""
    pr = urlsplit(url)
    match = re.fullmatch(r"/([^/\s]+)/([^/\s]+)/pull/(\d+)/?", pr.path)
    if not match or pr.scheme != "https" or not pr.hostname or pr.username or pr.query or pr.fragment:
        return None
    api = ("api",) if pr.netloc == "github.com" else ("api", "--hostname", pr.netloc)
    return (api, *match.groups())


def checks(lp, url):
    """Wait for the target's required names, including checks that have not registered yet."""
    parts = pr_parts(url)
    if parts is None:
        return False, f"cannot read required checks for {url}"
    api, owner, repo, _ = parts
    target = lp.target.removeprefix("origin/")
    endpoint = f"repos/{owner}/{repo}/rules/branches/{quote(target, safe='')}"
    rules, why = gh_json(lp.run_dir, *api, "--paginate", endpoint + "?per_page=100")
    required = {}
    try:
        if not isinstance(rules, list) or any(not isinstance(page, list) for page in rules):
            raise ValueError(why or "invalid branch rules response")
        for page in rules:
            for rule in page:
                if rule["type"] == "required_status_checks":
                    for check in rule["parameters"]["required_status_checks"]:
                        name = check["context"]
                        if not isinstance(name, str) or not name:
                            raise ValueError("required check has no name")
                        required.setdefault(name, set()).add(check.get("integration_id") or None)
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"cannot read required checks for {target}: {exc}"
    # Branch rules cover rulesets only. Read the matching classic protection rule through
    # GraphQL, which does not require the REST protection endpoint's administration access.
    classic, why = gh_json(lp.run_dir, *api, "graphql", "-f", f"query={CLASSIC_CHECKS_QUERY}",
                           "-f", f"owner={owner}", "-f", f"name={repo}",
                           "-f", f"branch=refs/heads/{target}")
    try:
        if not isinstance(classic, dict) or classic.get("errors"):
            raise ValueError(why or "invalid classic protection response")
        protection = classic["data"]["repository"]["ref"]["branchProtectionRule"]
        if protection is not None and protection["requiresStatusChecks"]:
            for check in protection["requiredStatusChecks"]:
                name = check["context"]
                if not isinstance(name, str) or not name:
                    raise ValueError("required check has no name")
                app = check["app"]
                required.setdefault(name, set()).add(app["databaseId"] if app else None)
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"cannot read classic required checks for {target}: {exc}"
    if not required:
        lp.log(f"checks: {target} requires no status checks")
        return True, ""
    lp.log(f"--- checks: {target} requires {', '.join(sorted(required))}")
    head = lp.state.get("delivery_sha") or lp.state.get("head_sha")
    if not head:
        return False, "cannot verify required checks without the PR head SHA"
    deadline = time.monotonic() + CHECKS_CAP
    rerun = {}      # a check GitHub cancelled ran nothing: asked again until GitHub takes it
    while True:
        # The server's gh supports REST pagination but not `pr checks --json`. Read the
        # recorded commit directly, including all check-run and legacy status pages.
        data, why = gh_json(lp.run_dir, *api, "--paginate",
                            f"repos/{owner}/{repo}/commits/{head}/check-runs?filter=latest&per_page=100",
                            timeout=poll_cap(deadline))
        try:
            if not isinstance(data, list):
                raise ValueError(why or "invalid check-runs response")
            runs = [check for page in data for check in page["check_runs"]]
            latest = {}
            for check in runs:
                key = (check["name"], check["app"]["id"])
                if key not in latest or check["id"] > latest[key]["id"]:
                    latest[key] = check
            states, missing_apps = {}, set()
            for name, apps in required.items():
                matches = [check for (context, app), check in latest.items()
                           if context == name and (None in apps or app in apps)]
                states[name] = ["pending" if check["status"] != "completed" else
                                "pass" if check["conclusion"] in ("success", "neutral", "skipped")
                                else "pending" if check["conclusion"] == "cancelled"
                                else "fail" for check in matches]
                for check in matches:
                    if (check["conclusion"] == "cancelled" and rerun.get(check["id"]) != 0
                            and check["app"].get("slug") == "github-actions"):
                        # GitHub refuses a job's rerun while its workflow still runs: next poll
                        rc, out = gitcall.gh(lp.run_dir, *api, "-X", "POST",
                                     f"repos/{owner}/{repo}/actions/jobs/{check['id']}/rerun")
                        if stopped(rc, out):
                            raise Stopped(out)
                        if rc == 0 or check["id"] not in rerun:
                            lp.log(f"checks: GitHub cancelled {name}; asked it to run again"
                                   + ("" if rc == 0 else f", refused for now: {out.strip()[-200:]}"))
                        rerun[check["id"]] = rc
                if not (apps - {None}).issubset({check["app"]["id"] for check in matches}):
                    missing_apps.add(name)
                    states[name] = []  # a same-named check from another app cannot satisfy it
        except (KeyError, TypeError, ValueError) as exc:
            return False, f"cannot read required check runs: {exc}"
        latest_status = {}
        if any(None in apps for apps in required.values()):
            data, why = gh_json(lp.run_dir, *api, "--paginate",
                                f"repos/{owner}/{repo}/commits/{head}/statuses?per_page=100",
                                timeout=poll_cap(deadline))
            try:
                if not isinstance(data, list) or any(not isinstance(page, list) for page in data):
                    raise ValueError(why or "invalid statuses response")
                latest_status = {}
                for page in data:
                    for status in page:
                        name = status["context"]
                        if name not in latest_status or status["id"] > latest_status[name]["id"]:
                            latest_status[name] = status
                for name, status in latest_status.items():
                    if name in required and None in required[name] and name not in missing_apps:
                        states[name].append("pass" if status["state"] == "success" else
                                            "fail" if status["state"] in ("failure", "error") else "pending")
            except (KeyError, TypeError, ValueError) as exc:
                return False, f"cannot read required commit statuses: {exc}"
        failed = sorted(name for name, buckets in states.items()
                        if "fail" in buckets)
        if failed:
            why = f"required checks failed: {', '.join(failed)}"
            if (lp.state.get("waiting_on") or {}).get("line"):
                # Keep the check's output and details URL for the landing fixer.
                why += "\n\n" + json.dumps({
                    "check_runs": [check for check in latest.values() if check["name"] in failed],
                    "statuses": [status for name, status in latest_status.items() if name in failed]},
                    indent=2)
            return False, why
        missing = sorted(name for name, buckets in states.items() if not buckets)
        pending = sorted(name for name, buckets in states.items()
                         if any(bucket not in ("pass", "skipping") for bucket in buckets))
        if not missing and not pending:
            lp.log("checks: required checks green")
            return True, ""
        if time.monotonic() >= deadline:
            reasons = []
            if missing:
                reasons.append(f"required checks never registered: {', '.join(missing)}")
            if pending:
                reasons.append(f"required checks did not finish: {', '.join(pending)}")
            return False, "; ".join(reasons)
        time.sleep(min(CHECKS_POLL, max(0, deadline - time.monotonic())))


def wait_checks(lp, url):
    """Sit on the PR's checks until they are green.  False leaves the PR open, and says why."""
    green, why = checks(lp, url)
    if green:
        return True
    wait = lp.state.get("waiting_on") or {}
    if wait.get("line") and why.startswith("required checks failed:"):
        path = lp.run_dir / "pr-checks.log"
        path.write_text(f"{why}\nPR: {url}\n")
        lp.state["waiting_on"] = {**wait, "fix": {"line": why.splitlines()[0], "log": str(path)}}
        lp.write()
        return False
    return note(lp, f"{why}; the PR is open at {url}", failed=True)


def rights(lp):
    """(upstream repo, this account's permission on it), or (None, None) when gh cannot say.

    A gh that ran out of time, or that was refused the login prompt it wanted, said nothing at
    all -- which is not the same as saying it does not know.  Pushing on the strength of it
    would deliver on an assumption, so that ends the delivery with its remedy instead.
    """
    rc, out = gitcall.gh(lp.wt, "repo", "view", "--json", "nameWithOwner,viewerPermission")
    if stopped(rc, out):
        raise Stopped(out)
    try:
        data = json.loads(out) if rc == 0 else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data.get("nameWithOwner"):
        lp.log(f"WARN gh repo view could not say whether this account may push: {out[-200:]}")
        return None, None
    return data["nameWithOwner"], data.get("viewerPermission")


def fork_and_pr(lp, target_branch, upstream_repo, permission):
    """No push rights on origin: push the branch to a fork and open the PR upstream from there.

    The run ends `waiting for the maintainer` -- a PASS, not merged, and not a failure: merging
    is somebody else's decision now, and `ak watch` follows what they decide.
    """
    require_review_pass(lp)
    branch = lp.state["branch"]
    lp.log(f"--- merge: {permission or 'no'} permission on {upstream_repo}; pushing to a fork")
    if FORK_REMOTE not in git(lp.wt, "remote", check=False).split():
        # --remote-name keeps `origin` pointing upstream, which is what the diff and the PR are
        # against; an existing fork is reused, gh only adds the remote for it
        rc, out = gitcall.gh(lp.wt, "repo", "fork", "--remote", "--remote-name", FORK_REMOTE)
        if rc != 0:
            if stopped(rc, out):
                raise Stopped(out)
            return note(lp, f"gh repo fork failed: {out[-400:]}", failed=True)
    rc, out = git_out(lp.wt, "push", "--force-with-lease", "-u", FORK_REMOTE, branch)
    if rc != 0:
        return note(lp, f"pushing {branch} to the fork failed: {out[-400:]}", failed=True)
    lp.log(f"--- merge: pushed {branch} to {FORK_REMOTE}")
    if not lp.state.get("pr"):
        rc, me = gitcall.gh(lp.run_dir, "api", "user", "-q", ".login")
        # classify before reducing to the last line: the remedy tool_run appends is the last
        # line, and it matches none of PROMPTED's patterns, so a refused prompt checked after
        # the reduction would never read as the stop it is
        if stopped(rc, me):
            raise Stopped(me)
        me = me.strip().splitlines()[-1] if me.strip() else ""
        if rc != 0 or not me:
            return note(lp, f"gh api user could not say whose fork this is: {me[-200:]}",
                        failed=True)
        path = lp.run_dir / "pr-body.md"
        path.write_text(pr_body(lp.state))
        rc, out = gitcall.gh(lp.wt, "pr", "create", "--repo", upstream_repo, "--base", target_branch,
                     "--head", f"{me}:{branch}", "--title", lp.state["title"],
                     "--body-file", str(path))
        found = PR_URL.search(out)
        if not found:
            if stopped(rc, out):
                raise Stopped(out)
            return note(lp, f"gh pr create on {upstream_repo} failed: {out[-400:]}", failed=True)
        lp.state["pr"] = found.group(0)
        lp.log(f"--- merge: PR {lp.state['pr']}" + (" (already open)" if rc != 0 else ""))
    elif not refresh_pr_body(lp):
        return False
    lp.state["foreign"] = True
    return note(lp, "waiting for the maintainer")


def add_suite_trailer(lp, message, trailer):
    # Keep existing attribution in the trailer block Git and GitHub recognize.
    path = lp.run_dir / "merge-body.txt"
    path.write_text(message)
    return git(lp.wt, "interpret-trailers", "--no-divider", "--where", "end",
               "--if-exists", "replace", "--trailer", trailer, str(path))


def merge_body(lp, head, url=None):
    checked = lp.state.get("final_check") or {}
    suite = gitcall.declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
    if (suite and checked.get("suite") == suite and checked.get("outcome") == "passed"
            and checked.get("sha") == head and checked.get("tree_sha")
            and checked.get("tested", checked["tree_sha"]) == checked["tree_sha"]
            and checked["tree_sha"] == git(lp.wt, "rev-parse", f"{head}^{{tree}}")):
        body = f"Suite-Passed-Tree: {checked['tree_sha']}"
        if url:
            # An explicit body replaces GitHub's defaults, including co-author credit.
            parts = pr_parts(url)
            if parts is None:
                lp.log(f"WARN cannot read the merge commit body for {url}; merging without suite trailer")
                return []
            api, owner, name, number = parts
            try:
                default, why = gh_json(
                    lp.run_dir, *api, "graphql", "-f",
                    "query=query($owner:String!,$name:String!,$number:Int!,$method:PullRequestMergeMethod!){"
                    "repository(owner:$owner,name:$name){pullRequest(number:$number){"
                    "viewerMergeBodyText(mergeType:$method)}}}",
                    "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={number}",
                    "-f", f"method={(lp.state.get('merge_method') or 'squash').upper()}",
                    "-q", ".data.repository.pullRequest.viewerMergeBodyText | tojson")
            except Stopped as exc:
                # Only the CI shortcut needs this read; the reviewed head stays pinned.
                default, why = None, str(exc)
            if not isinstance(default, str):
                lp.log(f"WARN could not read the merge commit body for {url}: "
                       f"{why or 'GitHub returned no body text'}; merging without suite trailer")
                return []
            body = add_suite_trailer(lp, default, body)
        return ["--body", body]
    return []


def merged(lp, url, method):
    """Record the PR as merged, with what proving it live stands on; True, for the merge step
    to return."""
    lp.state.update(merged=True, **watch.merge_record(lp.wt, lp.state.get("delivery_sha")))
    lp.write()
    lp.log(f"--- merge: merged {url} with --{method}, remote branch deleted")
    return True


def is_delivery(lp, info, upstream):
    """Is this PR view still this run's delivery: the reviewed head, aimed at `upstream`?"""
    return (info.get("headRefOid") == lp.state["delivery_sha"]
            and info.get("baseRefName") == upstream.removeprefix("origin/"))


def merged_anyway(lp, url, upstream):
    """Did GitHub merge this delivery whatever `gh pr merge` answered?  Records it when it did.

    A 5xx or a stopped call may have merged it, and `--delete-branch` exits non-zero on a
    merge that went through when the repository deleted the head branch first (`Reference
    does not exist`).  Only `state` says MERGED -- mergeStateStatus carries mergeability
    (BEHIND/BLOCKED/CLEAN and the rest), never the outcome -- and only a merge of the
    delivery into its target is this run's work: a head another writer replaced, or a PR
    retargeted and merged elsewhere, is not.
    """
    src, view = gitcall.gh(lp.run_dir, "pr", "view", url, "--json", "state,headRefOid,baseRefName")
    if stopped(src, view):
        raise Stopped(view)
    try:
        info = json.loads(view) if src == 0 else {}
    except ValueError:
        info = {}
    return (info.get("state") == "MERGED" and is_delivery(lp, info, upstream)
            and merged(lp, url, lp.state["merge_method"]))


def do_merge(lp, url, upstream):
    """Merge the PR, integrating once more if origin moved under it while the checks ran.

    `gh pr merge` answering `Base branch was modified` is a race with a merge to the
    target between the push and this call, not an ending: the answer is re-fetched, the
    PR is re-checked to still be mergeable, and the merge is tried again -- three times,
    with a growing wait -- and only then does the run park `waiting` with the reason,
    retried after the next merge to the target.  GitHub answering with a 5xx of its own
    takes the same road, and a merge it went through with anyway counts as merged; so does
    `Head branch was modified` straight after the delivery's own push, which the re-check
    ends only when the PR head really is another commit.  After `Pull Request is not
    mergeable`, GitHub is asked again while it reports the PR's state UNKNOWN, up to
    MERGE_RETRIES times, and a PR it then calls CLEAN is tried once more.  Work
    that passed review is never thrown away over one lost race or one bad answer.
    """
    method = lp.state["merge_method"]
    why, raced = "", 0
    for attempt in (1, 2):
        ready, lost = True, False
        while True:
            require_review_pass(lp)
            if lp.state["review"].get("head_sha") != lp.state["delivery_sha"]:
                return note(lp, "the delivery SHA is not the tested and reviewed commit", failed=True)
            if ready:
                if (lp.state.get("waiting_on") or {}).get("line"):
                    fetch(lp.wt, "origin", "--prune", check=True)
                    if not integrated(lp.wt, upstream):
                        return rejoin_line(lp, upstream, "the PR's target moved")
                body = [] if method == "rebase" else merge_body(lp, lp.state["delivery_sha"], url)
                rc, out = gitcall.gh(lp.run_dir, "pr", "merge", url, MERGE_METHODS[method], "--delete-branch",
                             "--match-head-commit", lp.state["delivery_sha"], *body)
            if rc == 0 or stopped(rc, out):
                break
            if BASE_BRANCH_MODIFIED.search(out or ""):
                cause = "the base branch was modified under the merge"
            elif HEAD_BRANCH_MODIFIED.search(out or ""):
                cause = "GitHub had not yet taken the pushed head"
            elif GITHUB_5XX.search(out or ""):
                cause = "GitHub failed the merge call"
            else:
                break
            if raced >= MERGE_RETRIES:
                lost = True
                break
            raced += 1
            delay = transient_delay(raced)
            lp.log(f"WARN {cause}; re-fetching, re-checking and retrying in {delay}s "
                   f"({raced}/{MERGE_RETRIES})")
            step = history.close_step(lp.state.get("run_id"), log=lp.log)   # a wait, not work
            time.sleep(delay)
            history.open_step(lp.state.get("run_id"), step, log=lp.log)
            frc, fetched = fetch(lp.wt, "origin")
            if frc != 0:
                return note(lp, f"git fetch origin failed: {fetched[-400:]}", failed=True)
            vrc, view = gitcall.gh(lp.run_dir, "pr", "view", url, "--json",
                           "state,mergeable,headRefOid,baseRefName")
            if stopped(vrc, view):
                raise Stopped(view)
            if vrc != 0:
                return note(lp, f"could not re-check the PR: {view[-400:]}", failed=True)
            try:
                info = json.loads(view)
            except ValueError:
                return note(lp, f"could not read the PR: {view[-400:]}", failed=True)
            if not is_delivery(lp, info, upstream):
                return note(lp, "PR head or target changed since PASS; a new run is required",
                            failed=True)
            seen, mergeable = info.get("state"), info.get("mergeable")
            if seen == "MERGED":
                return merged(lp, url, method)
            if seen != "OPEN":
                return note(lp, "PR is closed without a merge", failed=True)
            # A moving target can change both the patch and its checks. Reuse the same
            # integration path as a BEHIND retry before authorizing the new head.
            head = lp.state["delivery_sha"]
            if (lp.state.get("waiting_on") or {}).get("line"):
                if not integrated(lp.wt, upstream):
                    return rejoin_line(lp, upstream, "the PR's target moved")
            elif not integrate(lp, upstream):
                return False
            if git(lp.wt, "rev-parse", "HEAD") != head:
                if not final_check(lp, upstream) or not push(lp) or not wait_checks(lp, url):
                    return False
                if not refresh_pr_body(lp):
                    return False
                ready = True
            else:
                # GitHub may still be computing mergeability. An unconfirmed answer
                # uses the remaining retries to re-check before authorizing a merge.
                ready = mergeable == "MERGEABLE"
        if rc == 0:
            return merged(lp, url, method)
        if lost:
            # the last attempt's 5xx may have merged too, and no re-check followed it
            if merged_anyway(lp, url, upstream):
                return True
            return park_waiting(
                lp, f"gh pr merge --{method} failed after {MERGE_RETRIES} retries: {cause}; "
                    f"the PR is open at {url}", upstream,
                git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False) or None)
        refused = bool(NOT_MERGEABLE.search(out or ""))
        for polled in range(MERGE_RETRIES + 1):
            if polled:
                time.sleep(CHECKS_POLL)     # GitHub still working out a head pushed just now
            vrc, why = gitcall.gh(lp.run_dir, "pr", "view", url, "--json", "mergeStateStatus",
                          "-q", ".mergeStateStatus")
            if not refused or vrc != 0 or why != "UNKNOWN":
                break
        if stopped(rc, out) or stopped(vrc, why):
            # a merge that stopped may still have gone through server-side
            if merged_anyway(lp, url, upstream):
                return True
            raise Stopped(out if stopped(rc, out) else why)
        if attempt == 2 or why not in ("BEHIND", "DIRTY", "CLEAN"):
            break
        if why == "CLEAN":
            if not refused:
                break
            lp.log("WARN GitHub called the PR not mergeable, then CLEAN: it had not yet worked "
                   "out the head just pushed; retrying the merge")
            continue
        lp.log(f"WARN the PR is {why}; taking {upstream} in once more and retrying the merge")
        if (lp.state.get("waiting_on") or {}).get("line"):
            return rejoin_line(lp, upstream, f"the PR is {why}")
        # the retry pushes a new head, so its checks are a new run: wait them out again rather
        # than merging on the strength of the ones that passed for the commit just replaced --
        # and its `# once` commands too, which have only ever run on that commit
        if (not integrate(lp, upstream) or not final_check(lp, upstream) or not push(lp)
                or not wait_checks(lp, url)):
            return False
        if not refresh_pr_body(lp):
            return False
    if merged_anyway(lp, url, upstream):
        return True
    return note(lp, f"gh pr merge --{method} failed"
                    f"{f' with the PR {why}' if why else ''}; the PR is open at {url}: {out[-400:]}",
                failed=True)


def require_review_pass(lp):
    if not review_pass(lp.state, lp.cfg):
        raise Exhausted("delivery requires a successful reviewer allowed by the model policy; "
                        "resume the run to obtain review")
    if not current_review(lp):
        raise Exhausted("delivery requires done-when and review of the current commit; "
                        "resume the run to obtain review")


def _branch_only_path(wt, cmd, head, tip):
    """The first path `cmd` names that the branch head has and the target tip lacks, else None.

    A landing check naming a file the branch adds can never survive its probe: the file is
    not on the target, so the probe fails there for want of the file rather than for anything
    the branch broke, and the run parks waiting for a target fix that will never come.
    File-test operands keep their probe: absence is what those commands test, not a
    missing prerequisite.  Paths are checked against the commits without changing the tree.
    """
    import glob

    # Keep quoting until comments and operators have been recognised: bash allows a
    # literal # inside a word, and quoted glob characters do not expand.
    tokens = re.findall(r'''(?:[^\s;&|()<>\\'"]+|\\.|'[^']*'|"(?:\\.|[^"\\])*")+'''
                        r'''|&&|\|\||[;&|()<>]|\S''', cmd)
    cwd, command, previous = "", "", ""
    directories = []
    for raw in tokens:
        if raw.startswith("#"):
            break
        if raw in (";", "&&", "||", "|", "&", "(", ")"):
            if raw == "(":
                directories.append(cwd)
            elif raw == ")" and directories:
                cwd = directories.pop()
            command = previous = ""
            continue
        try:
            token = shlex.split(raw)[0]
        except (ValueError, IndexError):
            return None
        if not command:
            command = token
            previous = token
            if "/" not in token:
                continue
        file_test = (command in ("test", "[", "[[") and previous in (
            "-a", "-b", "-c", "-d", "-e", "-f", "-g", "-h", "-k", "-L", "-N",
            "-O", "-G", "-p", "-r", "-s", "-S", "-t", "-u", "-w", "-x"))
        previous = token
        if file_test:
            continue
        word = token.split("::", 1)[0]      # a pytest node id names the file before the ::
        word = os.path.normpath(os.path.join(cwd, word))
        if word.startswith("/") or word == ".." or word.startswith("../"):
            continue
        paths = [word]
        unquoted = re.sub(r'''\\.|'[^']*'|"(?:\\.|[^"\\])*"''', "", raw)
        if any(ch in unquoted for ch in "*?["):
            paths = sorted(glob.glob(word, root_dir=wt))
        for path in paths:
            if git_out(wt, "cat-file", "-e", f"{head}:{path}")[0] != 0:
                continue
            if git_out(wt, "cat-file", "-e", f"{tip}:{path}")[0] != 0:
                return path
        if command == "cd" and token not in ("cd", "--", "-L", "-P"):
            cwd = word
    return None


def target_fails(lp, upstream, dw_log):
    """What the first failing landing command says on a red target tip with a green old
    base; "" when it needs the branch.  An unchanged base needs only the tip probe.

    Runs land in parallel, and one whose target moved only under other files lands on its
    earlier checks without running them on the combined commit -- so the target can be red
    while every run in flight passed alone.  A landing check failing on that red tip is not
    the branch's to fix only if it passes on the target commit the branch last passed on:
    the merge-base of its last reviewed head and the tip.  After a failed tip probe, that
    old base is probed too unless it is the tip.  Failure on both means the command needs
    the branch, so the fixer runs.  The failure is the tip probe's own, in `first_failure`'s
    words: a suite can fail on the target at another check than it did on the branch.

    Nobody else repairs a red target: the first run to find it starts one repair run on it,
    ahead of the queue, and every run parked on the same red waits for that run to let go of
    it (`repair_open`) as well as for the next merge (`lp.repair`, which `park_waiting`
    records).  The repair run itself is never probed on the command it repairs: its fixer
    rounds are the repair.

    A command naming a path the branch head has and the tip lacks is never probed: on the
    target the missing file alone would fail it, so the fixer rounds run as today and the
    log names the file the target lacks.

    "" when the check names no failing command, when the tree is dirty, and when the tip
    or old base cannot be resolved or checked out: those run the fixer
    rounds as today.  A stop propagates, after the worktree is put back on the branch head,
    clean.  A probe of a `# once` command takes a heavy-suite turn; any other probe runs
    light, as the check it repeats did.
    """
    if (lp.state.get("waiting_on") or {}).get("line"):
        return ""     # a line member fixes its own red, without assigning it to another run
    failed = failing_checks(dw_log)
    if not failed:
        return ""
    cmd = failed[0][0]
    if cmd == (lp.state.get("repair") or {}).get("command"):
        return ""
    try:
        tip = lp.state.get("target_sha") or git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
        head = git(lp.wt, "rev-parse", "HEAD")
    except Stopped:
        raise
    except config.Error:
        return ""
    if git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0:
        return ""
    missing = _branch_only_path(lp.wt, cmd, head, tip)
    if missing is not None:
        lp.log(f"--- merge: `{cmd}` names {missing}, which {upstream} lacks; "
               "no probe, the fixer runs")
        return ""
    branch = git(lp.wt, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    run_record.stop_check(lp.run_dir)
    before = set(dirty_paths(lp.wt))
    probe_log = lp.run_dir / "target-probe.log"
    heavy_probe = cmd in (getattr(lp, "once", None) or [])

    def probe(sha, where):
        label = f"`{cmd}` on {where}"
        gitcall.save_probe_checkout(lp, head, branch, before, label)
        try:
            rc, _ = git_out(lp.wt, "checkout", "--quiet", "--detach", sha)
            if rc != 0:
                return None
            lp.log(f"--- merge: `{cmd}` failed; probing it once on {where} ({sha[:12]})")
            with gate.gate_turn(lp.run_dir, probe_log, lp.log, cmd, lp.wt) if heavy_probe else nullcontext():
                began = time.monotonic()    # from the turn, not the wait
                while True:
                    with probe_log.open("ab") as progress:
                        progress.write(f"$ {cmd} (on {where} {sha})\n".encode())
                        progress.flush()
                        start = progress.tell()
                        code, _, killed = gate.run_suite(
                            cmd, lp.done_when_limit, silence=lp.turn_limit,
                            activity=probe_log, output=progress, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, cwd=str(lp.wt), run_dir=lp.run_dir,
                            log=lp.log)
                    # busy is no answer: the turn goes back until the suite runs
                    if (not heavy_probe or code != gate.SUITE_BUSY or killed
                            or time.monotonic() - began > lp.done_when_limit):
                        break
                    began += gate.busy_turn(lp.run_dir, probe_log, lp.log)
            turns.memory_cap_note(lp.run_dir, lp.log)
            # as after a gate: a command that exited may still have left processes behind
            worker.kill_marked(gitcall.run_child_env().get(worker.RUN_MARKER), log=lp.log)
            with probe_log.open("rb") as said:
                said.seek(start)
                output = said.read().decode(errors="replace")
            return code, output, killed
        finally:
            gitcall.restore_probe_checkout(lp, head, branch, before, label)

    result = probe(tip, upstream)
    if result is None:
        return ""
    code, output, killed = result
    if not (killed or code != 0):
        return ""
    passed_head = passed_review_head(lp.state)
    if not passed_head:
        return ""
    try:
        old_base = git(lp.wt, "merge-base", passed_head, tip)
    except Stopped:
        raise
    except config.Error:
        return ""
    if old_base != tip:
        previous = probe(old_base, "old base")
        if previous is None:
            return ""
        if previous[2] or previous[0] != 0:
            lp.log(f"--- merge: `{cmd}` fails on {old_base[:12]} too: needs this branch")
            return ""
    try:
        lp.repair = start_followups(lp.state, lp.run_dir, lp.log, lp.cfg, repair={
            "command": cmd, "check": f"{cmd}  # once" if heavy_probe else cmd, "sha": tip,
            "text": red_target_text(cmd, upstream, tip, output)})
    except run_record.StopRequested:
        raise
    except Exception as exc:  # noqa: BLE001 - the park matters, not its repair
        lp.log(f"WARN no repair of {upstream} could start: {exc}")
    return first_failure(f"$ {cmd}\n[exit {code}]\n{output}")


def fix_final_check(lp, upstream, text):
    """Repair failing landing output and re-review, without recording a task round."""
    fix = (f"{lp.context}\n\n## The final check failed. Fix the root cause.\n```\n"
           f"{failing_blocks(text)}\n```")
    lp.state["review_pending"] = {"round": lp.rnd, "summary": "",
                                  "reason": "Re-review after the final check.",
                                  "passed_head_sha": passed_review_head(lp.state),
                                  "record": False}
    lp.save()
    with released_gate_turn():
        summary = landing_fixer(lp, fix, "final-fixer")
        lp.state["review_pending"]["summary"] = summary
        lp.save()
        ok, dw_log = verify_work(lp)
        lp.log(f"done-when after the final check: {'all passed' if ok else 'FAILED'}")
        if (review(lp, summary, ok, dw_log, "Re-review after the final check.", record=False)
                != "PASS" and not fix_after_failed_review(lp, upstream, "final check")):
            return note(lp, "done-when or review after the final check did not pass")
    return True


def final_check(lp, upstream):
    """Run every-commands plus once-commands on the commit about to be pushed.

    True when the commit may be pushed.  The declared suite runs only here, at
    landing, and a passed landing check on this same commit is reused on resume.
    Without a `# once` line there is nothing to do.  When integration
    already ran the every-commands on this commit and they passed, only the
    once-commands run here: each command runs once on that commit.  The
    every-commands run light, without a turn; only the once-commands take a
    heavy-suite turn.  The run is pinned the way `verify_work` pins one: the
    commit and tree are recorded, and a checkout that changes during the check
    fails it.  The output goes to `<run dir>/final-check.log`.

    A failed check is handled like a rebase conflict.  The work already passed review,
    and what fails this late is as often the world -- a login, a scope, a service -- as
    the work, so a final-check fixer round spends no task round and the check never ends
    the run FAIL.  Up to `CONFLICT_ROUNDS` of them work from the failing output; each is
    verified and re-reviewed, then integration and this check run again.  A re-review
    that does not pass is a failed review like any other -- a fixer round on its
    findings, within the round budget it may spend, and once that is spent a review FAIL
    handed back with them.  Still failing after the last one, the run parks `waiting`
    with the check's first failing line, retried after the next merge to `upstream`.
    A command red on the target's tip and green on the old base parks without a
    fixer round.  When those commits are the same, only the tip is probed.
    """
    if not lp.state.get("target_sha"):
        lp.state["target_sha"] = git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False) or None
    try:
        now = git(lp.wt, "rev-parse", "HEAD")
    except (Stopped, config.Error):
        now = None
    record = lp.state.get("final_check") or {}
    if (now and record.get("outcome") == "passed" and record.get("where") == "landing"
            and record.get("sha") == now
            and record.get("suite") == gitcall.declared_suite(lp.wt, lp.target,
                                                       ref=lp.state.get("target_sha"))):
        try:
            reviewed = current_review(lp)
        except (Stopped, config.Error):
            reviewed = False
        if reviewed:
            lp.log(f"final check: already passed at landing on {now[:12]}; landing on it")
            return True
    fixed = 0       # the fixer rounds this run has spent on these commands here
    while True:
        sha = git(lp.wt, "rev-parse", "HEAD")
        suite = gitcall.declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
        # A rebase or fixer can change the declaration loaded into lp.once. Rebuild
        # it from the task so only the inherited suite is replaced, including for probes.
        task = lp.run_dir / "task.md"
        if task.is_file():
            _, body, _ = taskfile.parse_task(task)
            _, lp.once = taskfile.done_when_groups(body, task)
        if suite and suite not in lp.once:
            lp.once.append(suite)
        if not lp.once:
            return True
        if getattr(lp, "checked_every_sha", None) == sha:
            # integration already ran the task checks on this commit and they passed;
            # running them again would check nothing new
            cmds_every, cmds_once = [], list(lp.once)
        else:
            cmds_every, cmds_once = list(lp.every), list(lp.once)
        lp.log(f"--- merge: final check: {len(cmds_every) + len(cmds_once)} commands "
               f"({len(lp.once)} once) on {sha[:12]}")
        identity = commit_identity(lp.wt)
        clean = git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
        log_path = lp.run_dir / "final-check.log"
        began = time.monotonic()
        if cmds_every:
            ok_every, text_every = gate.run_done_when(
                cmds_every, lp.wt, log_path, lp.artifacts, lp.done_when_limit, lp.log,
                silence=lp.turn_limit, run_dir=lp.run_dir, heavy=False)
        else:
            ok_every, text_every = True, ""
        left = lp.done_when_limit - (time.monotonic() - began)
        ok_once, text_once = gate.run_done_when(
            cmds_once, lp.wt, log_path, lp.artifacts, max(0, left), lp.log,
            silence=lp.turn_limit, run_dir=lp.run_dir, heavy=True) if cmds_once else (True, "")
        gate.split_suite_run(lp, suite)
        ok = ok_every and ok_once
        text = "\n\n".join(part.strip() for part in (text_every, text_once) if part.strip())
        if (not clean or commit_identity(lp.wt) != identity
                or git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0):
            ok = False
            text += ("\n\nCheckout changed during the final check; "
                     "these commands do not verify the pinned commit.")
        text = (f"Commit: {identity['head_sha']}\nTree: {identity['tree_sha']}\n\n" + text)
        (lp.run_dir / "final-check.log").write_text(text)
        # the once-commands keep a history of their own across the rounds and this
        # re-run: a fixer round that leaves them failing exactly as they were is the
        # same task defect any other gate's would be.  Judged only once a fixer has
        # actually had a turn at them here: a resume walks back in on the signature
        # its last attempt left, and nothing has been asked to fix anything since.
        try:
            same_failure(lp, ok, text, gate="once", compare=fixed > 0)
        except Blocked as exc:
            # the hand-back names what kept failing, not only that something did
            raise Blocked(f"{exc}; the final check still fails on {first_failure(text)}",
                          exc.section) from None
        if ok:
            lp.log("final check: all passed")
            evidence = suite_evidence(lp, cmds_once, identity)
            lp.state["final_check"] = {"outcome": "passed", "sha": sha, "where": "landing",
                                       **evidence}
            if current_review(lp):
                lp.state["review"]["passed_head_sha"] = sha
            record_flakes(lp.state, text)
            lp.write()
            return True
        failing = first_failure(text)
        lp.log("final check: FAILED")
        lp.state["final_check"] = {"outcome": "failed", "sha": sha, "where": "landing",
                                   "line": failing}
        lp.write()
        said = target_fails(lp, upstream, text)
        if said:
            return park_waiting(
                lp, f"{upstream} itself fails: {said}", upstream,
                lp.state.get("target_sha"))
        if fixed >= CONFLICT_ROUNDS:
            return park_waiting(
                lp, f"the final check still fails after {CONFLICT_ROUNDS} fixer rounds: "
                    f"{failing}", upstream,
                lp.state.get("target_sha"))
        fixed += 1
        lp.log(f"--- merge: final check round {fixed}/{CONFLICT_ROUNDS}: "
               f"fixer {lp.executor} (final check)")
        if not fix_final_check(lp, upstream, text) or not integrate(lp, upstream):
            return False


def join_line(lp, upstream, deliver):
    """Leave a passed run's place on disk; a fresh process consumes the lander's verdict."""
    if (lp.state.get("waiting_on") or {}).get("line"):
        return land_from_line(lp, upstream, deliver)
    require_review_pass(lp)
    lp.state.update(state="waiting", waiting_on={"line": turn_path(lp, upstream).name,
                                               "joined": time.time()},
                    error="waiting for the lander", finished_at=None)
    lp.state.pop("recovery_pending", None)
    lp.write()
    return False


def release_line(run_dir, log):
    """Finish this attempt's cleanup before the lander can wake a new record owner."""
    with run_record.recovery_lock(run_dir):
        state = run_record.read_state(run_dir) or {}
        if (state.get("state") != "waiting" or state.get("pid") != os.getpid()
                or not (state.get("waiting_on") or {}).get("line")):
            return
        stop_run_tree(state, log)
        state.update(pid=None, process_identity=None)
        run_record.save_state(run_dir, state)
    landing.start_line(config.RUNS / state["waiting_on"]["line"], log)


def rejoin_line(lp, upstream, reason):
    """A rejoining run keeps its place, repaired work included: checked again soon, it meets
    the target it was fixed against, not one moved by every landing a lap at the back takes."""
    wait = lp.state["waiting_on"]
    lp.log(f"rejoins the line: {reason}")
    lp.state.update(state="waiting", error=reason, merge_failed=False, merge_note=reason,
                    waiting_on={"line": turn_path(lp, upstream).name, "joined": wait["joined"]})
    lp.state.pop("recovery_pending", None)
    lp.write()
    return False


def land_from_line(lp, upstream, deliver):
    """Consume the lander's verdict in this run; only delivery holds the plain merge flock."""
    wait = lp.state["waiting_on"]
    if landing.green_delivery(wait):
        turn = turn_path(lp, upstream)
        try:
            with merge_lock(lp, upstream):
                fetch(lp.wt, "origin", "--prune", check=True)
                tip = git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
                how = how_to_integrate(lp)
                args = ("merge", "--no-edit", tip) if how == "merge" else ("rebase", tip)
                saved = dict(lp.state["review"])
                try:
                    code, _ = git_out(lp.wt, *args)
                except Stopped:
                    abort_stopped_integration(lp, how)
                    raise
                if code:
                    abort_integration(lp, how)
                    reason = (f"its {how} onto {upstream} at {tip[:12]} stopped on a conflict; "
                              "the lander checks it again")
                    return rejoin_line(lp, upstream, reason)
                set_base(lp, tip)
                identity = commit_identity(lp.wt)
                lp.state["review"] = {**saved, **identity,
                                      "passed_head_sha": passed_review_head(lp.state),
                                      "rebased_from": saved["head_sha"]}
                lp.write()
                if identity["tree_sha"] != wait["land"]:
                    # Its tree alone on the tip is not the stack the lander passed: a change
                    # stacked ahead of it has not landed yet, or the target moved.
                    reason = (f"on {upstream} at {tip[:12]} its tree is {identity['tree_sha'][:12]}, "
                              f"not the {wait['land'][:12]} the lander checked: a change stacked "
                              f"ahead of it has not landed yet, or {upstream} moved")
                    return rejoin_line(lp, upstream, reason)
                if git_out(lp.wt, "diff", "--quiet", tip, "HEAD")[0] == 0:
                    lp.state.update(on_target=True)
                    lp.state.pop("waiting_on", None)
                    lp.state.pop("landing_reds", None)
                    return note(lp, f"its work is already on {upstream.removeprefix('origin/')}")
                if saved.get("skipped") and not text_only_pr(lp.wt, tip, "HEAD"):
                    # work not on the target yet: the target may have carried the wording onto
                    # files that need review (a rename, say)
                    path = lp.run_dir / "review-needed.log"
                    path.write_text("Rebased onto the target, this wording PR now changes files "
                                    "that need review; push the rebased branch and it is reviewed.\n")
                    return fail_pr_landing(lp, {"line": path.read_text().strip(), "log": str(path)},
                                           landing=False)
                lp.state["final_check"] = {"outcome": "passed", "where": "landing",
                                           "sha": identity["head_sha"],
                                           "tree_sha": identity["tree_sha"],
                                           "tested": wait.get("tested") or (
                                               landing.passed(turn, wait["land"]) or {}).get(
                                                   "tested", identity["tree_sha"]),
                                           "suite": gitcall.declared_suite(lp.wt, lp.target, ref=tip)}
                lp.write()
                result = deliver()
                if "fix" not in lp.state.get("waiting_on", {}):
                    if result:
                        lp.state.pop("waiting_on", None)
                        lp.state.pop("landing_reds", None)
                        lp.write()
                    return result
        finally:
            # Departures and changed-target rejoins were written under this flock.
            landing.start_line(turn, lp.log)
        wait = lp.state["waiting_on"]
    if "fix" not in wait:
        return rejoin_line(lp, upstream, "waiting for the lander")
    failure = wait["fix"]
    if lp.state.get("review_pr"):
        # a head the seat pushed past its review is new work, reviewed as a round: no landing red
        return fail_pr_landing(lp, failure, landing=not failure.get("moved"))
    if not wait.get("fixing"):
        lp.state["landing_reds"] = lp.state.get("landing_reds", 0) + 1
        lp.state["waiting_on"] = {**wait, "fixing": True}
        lp.write()
    if lp.state["landing_reds"] > CONFLICT_ROUNDS:
        lp.state.pop("waiting_on", None)
        # The count bounds one landing; a person who resumes the ended run starts a new one.
        lp.state.pop("landing_reds", None)
        return note(lp, f"landing failed four times: {failure['line']}; see {failure['log']}",
                    failed=True)
    if not integrate(lp, upstream):
        if lp.state.get("merge_failed"):
            raise config.Error(lp.state["merge_note"])
        lp.state["state"] = "running"
        if not lp.state.get("review_pending") or resume_review(lp) != "PASS":
            lp.state.pop("waiting_on", None)
            lp.write()
            return False
    if not lp.state["waiting_on"].get("fixed"):
        text = Path(failure["log"]).read_text(errors="replace")
        if not fix_final_check(lp, upstream, text):
            lp.state.pop("waiting_on", None)
            lp.write()
            return False
    return rejoin_line(lp, upstream, "landing fixes passed review")


def land(lp, upstream, verify, deliver, execv=None):
    """Consume a line verdict, or verify once before taking the delivery lock.

    Only delivery holds the repository lock; checks and fixers run outside it.
    """
    if (lp.state.get("waiting_on") or {}).get("line"):
        return land_from_line(lp, upstream, deliver)
    pickup_new_code(lp, execv=execv)
    gate.clear_landing_wait(lp.run_dir)
    lp.state["landing"] = True
    lp.write()
    try:
        if not verify():
            return False
        with merge_lock(lp, upstream):
            fetch(lp.wt, "origin", "--prune", check=True)
            tip = git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
            if tip != lp.base_sha:
                return park_waiting(lp, f"{upstream} changed since verification",
                                    upstream, lp.base_sha)
            return deliver()
    finally:
        lp.state.pop("landing", None)
        gate.clear_landing_wait(lp.run_dir)
        try:
            lp.write()
        except (OSError, run_record.StopRequested):
            pass            # the landing is over however the record ends


@contextmanager
def merge_lock(lp, upstream):
    """Serialize deliveries to one repository and target; the kernel releases a dead holder."""
    config.RUNS.mkdir(parents=True, exist_ok=True)
    held = getattr(_PICKUP_HELD, "count", 0)
    _PICKUP_HELD.count = held + 1
    try:
        turn = turn_path(lp, upstream)
        with turn.open("a") as lock:
            try:
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        # Another delivery can spend an hour on PR checks; its waiter is not stalled.
                        lp.state["delivery_wait"] = os.getpid()
                        lp.write()
                        fcntl.flock(lock, fcntl.LOCK_EX)
                    members = landing.line(turn) if landing.green_delivery(
                        lp.state.get("waiting_on") or {}) else []
                    if (not members or members[0][0] == lp.run_dir
                            or not landing.green_delivery(members[0][1]["waiting_on"])):
                        break
                    # Flock does not order contenders; a checked suffix needs its prefix delivered.
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    lp.state["delivery_wait"] = os.getpid()
                    lp.write()
                    run_record.stop_check(lp.run_dir)
                    time.sleep(gate.SLOT_POLL)
            finally:
                if lp.state.pop("delivery_wait", None) is not None:
                    lp.write()
            yield
    finally:
        _PICKUP_HELD.count = held


def turn_path(lp, upstream):
    """The delivery lock for `lp`'s repository and target."""
    url = git(lp.wt, "remote", "get-url", "origin", check=False) or str(lp.state.get("repo"))
    return merge_lock_path(url, upstream)


def remote_key(url):
    """`host/owner/repo` for a clone URL, however it spells the repository.

    `git@github.com:acme/widget.git`, `ssh://git@github.com:22/acme/widget` and
    `https://github.com/Acme/widget` are one repository: the host and the path are what is
    kept, without a user, a port, a trailing `.git`, or the case GitHub ignores.  A local
    path is itself.
    """
    scp = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(?!//)(.+)", url)
    parts = urlsplit(url)
    host, path = (scp[1], scp[2]) if scp else (parts.hostname, parts.path)
    return f"{host}/{path.strip('/').removesuffix('.git')}".lower() if host else url


def merge_lock_path(url, upstream):
    """The delivery lock for one repository and target, however a clone spells it."""
    digest = hashlib.sha256(f"{remote_key(url)}\n{upstream}".encode()).hexdigest()
    return config.RUNS / f".merge-{digest}.lock"


def merge(lp):
    """A passed writable run joins the line; a wake delivers its checked tree, a fork its PR.

    Never a model's call.

    Everything here is about `target` -- the branch the PR merges into -- and not about `base`,
    which is only where the run's branch was cut from.  They are the same branch unless the
    task said otherwise.
    """
    if not (lp.state.get("waiting_on") or {}).get("line"):
        require_review_pass(lp)
    lp.state.update(merged=False, merge_failed=False, merge_note=None, on_target=False)
    lp.step("merge")
    branch = lp.state["branch"]
    # merging is the job, so nothing here is a shrug: a run that cannot merge failed to deliver
    # and says so with exit 1.  `--no-merge` is how a run opts out of the job in the first place.
    if shutil.which("gh") is None:
        return note(lp, "no `gh` on PATH; push and open the PR yourself", failed=True)
    if "origin" not in git(lp.wt, "remote", check=False).split():
        return note(lp, f"{lp.state['repo']} has no `origin` remote to merge into", failed=True)
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
    target_branch = upstream.split("/", 1)[1]
    if branch == target_branch:
        return note(lp, f"this run works directly on {branch}, which is the branch it would merge "
                        "into, so there is no PR to open", failed=True)

    upstream_repo, permission = rights(lp)
    if upstream_repo and permission not in PUSH_RIGHTS:
        return land(lp, upstream, lambda: integrate(lp, upstream) and final_check(lp, upstream),
                    lambda: fork_and_pr(lp, target_branch, upstream_repo, permission))

    def deliver():
        require_review_pass(lp)
        lp.step("merge")        # integration may have spent rounds of its own on the way here
        if not push(lp):
            return False
        url = open_pr(lp, target_branch)
        if not url or not wait_checks(lp, url):
            return False
        return do_merge(lp, url, upstream)
    return join_line(lp, upstream, deliver)


def finish_blocked(run_dir, state, exc, log, cfg):
    """The task cannot be done as written: a final state of its own, because there is no
    verdict on work here and nothing a resume could spend.  The orchestrator that wrote
    the task hears why and writes a new one."""
    log(f"BLOCKED {exc}")
    state.update({"state": "blocked", "verdict": "BLOCKED", "error": str(exc),
                  "blocked": exc.section, "finished_at": time.time()})
    state.pop("quota_dry", None)
    run_record.save_state(run_dir, state)
    record_result(run_dir, state, log, cfg)
    worktrees.settle_run(state, run_dir, log)
    return state


def end_on_dependency(cfg, run_dir, state, log, why):
    """End a run cut from a dependency's passed tip, blocked, with the branch to relaunch from.

    `why` is `stands_on_dependency`'s.  An interrupted executor's uncommitted edits go onto
    that branch first.  A checkout off it -- a rebase or merge stopped part way -- or still
    holding work no commit took is kept with that work (`checkout_kept`), and the ending
    says where, so the hand-back's cleanup leaves it for the seat.  So is one git could not
    read or commit in time: the run still ends, and nothing in the checkout is lost.
    """
    wt = Path(state.get("worktree") or "")
    if not state.get("scratch") and state.get("worktree") and wt.is_dir():
        branch = state.get("branch")
        try:
            if (git(wt, "symbolic-ref", "--quiet", "HEAD", check=False) != f"refs/heads/{branch}"
                    or in_progress(wt, "rebase") or in_progress(wt, "merge")):
                why += (f"; its checkout {wt} stopped part way off {branch} (a rebase or merge) "
                        f"and is kept with that work")
                state["checkout_kept"] = True
            else:
                commit_leftovers(wt, log, set(), state)
                if any(not leftover_junk(path) for path in dirty_paths(wt)):
                    why += (f"; its uncommitted work could not be committed, so its checkout "
                            f"{wt} is kept")
                    state["checkout_kept"] = True
        except (config.Error, OSError) as exc:
            why += f"; git could not put its checkout's work on {branch} ({exc}), so {wt} is kept"
            state["checkout_kept"] = True
    return finish_blocked(run_dir, state, Blocked(why, f"## Blocked\n\n{why}"), log, cfg)


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
    if gc.disk_pressure():
        gc.gc(log)     # before this run adds a worktree of its own
    if prior:
        state = stamp_origin(prior)
        state.update(state="running", **run_record.process_owner(), finished_at=None, error=None,
                     reported=False, task_words=sized_words, task_points=sized_points,
                     task_checks=sized_checks)
        clear_delivery(state)
        state.setdefault("stalls", [])
        repo = Path(state["repo"]) if state.get("repo") else None
        wt = Path(state["worktree"])
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
        if scratch:
            # nothing to branch from: the run gets a workspace of its own, and whatever it
            # leaves there is the deliverable
            if (meta.get("from") or "").strip():
                raise config.Error(f"{task_path}: from: needs a repository; "
                                   "a scratch run has no branch to start from")
            base = target = base_sha = branch = None
            from_branch, change = "", None
            wt = config.WORK / run_dir.name
            wt.mkdir(parents=True, exist_ok=True)
        else:
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
            from_branch = (meta.get("from") or "").strip()
            change = None
            if from_branch:
                # the change continues on that branch: the run the branch belongs to names it,
                # and the rounds earlier runs spent on it are spent
                change = change_on(from_branch, repo, exclude=run_dir)
                n_rounds, why = round_budget(n_rounds, change=change, exclude=run_dir,
                                             what=f"branch {from_branch}")
                if why:
                    raise config.Error(f"{task_path}: {why}")
            if from_branch and opts["--no-worktree"]:
                raise config.Error(f"{task_path}: from: needs a worktree; "
                                   "drop --no-worktree so the run gets its own checkout")
            if opts["--no-worktree"]:
                wt, branch = repo, git(repo, "rev-parse", "--abbrev-ref", "HEAD")
                from_branch = ""
                log(f"no worktree: working directly in {wt} on {branch}")
            elif from_branch:
                # A relaunch from a stopped or blocked run's committed work: the new
                # checkout starts where that branch left off before taking in `target`.
                if not git(repo, "rev-parse", "--verify", "--quiet",
                           f"refs/heads/{from_branch}", check=False):
                    raise config.Error(f"{task_path}: from: {from_branch!r} "
                                       "is not a local branch")
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
    # who takes over when the reviewer dies on its provider rather than on the diff
    spares = [n for n in order if n != reviewer]
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
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, "", spares)
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
    if gate.turn_held() or getattr(_PICKUP_HELD, "count", 0):
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


def seat_refusal(opts, flags):
    """Why a seat's launch is refused: a seat names no model, no place in the queue and no
    second run of a change under way, since ak picks the models by budget, decides what goes
    first and refuses the rival itself.  A seat is a recorded session (`config.session_records`);
    a shell naming none is no seat, and outside a seat the flags stand.  So do a queued child's,
    which `spawn_bg` starts under the seat's name: they are ak's own pick (a job's rerun on the
    next executor) or the seat's launch, judged at its parsing."""
    if not from_seat():
        return None
    given = ([flag for flag in ("--exec", "--review") if opts.get(flag)]
             + [flag for flag in ("--anyway", "--first") if flags.get(flag)])
    if given:
        return (f"{', '.join(given)}: not a seat's; ak picks the models by budget, decides what "
                "goes first and refuses a second run of a change under way, so launch without")
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
    state = gate.wait_for_slot(run_dir)
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

    CPU and I/O weight stay below the seats' 100, and the memory cap is applied
    as both MemoryMax and MemorySwapMax: the same number, so a leak cannot trade
    one for the other and keep going.  OOMPolicy=continue, where the manager takes
    it, has the kernel end only the process that grew, not the whole scope: the
    loop, its harness session and its worktree go on, and `memory_cap_note` says
    so.  The properties are what `systemd-run -p` takes; the cap is what the
    receipt records, so the reason can still name the number after the process
    that knew it is gone. A lander supplies its recorded suite need as `cap_mb`,
    and its own CPU weight: among the runs only, so the seats keep theirs.
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
    """Launch the task.md in that new run directory as the tick does for a seat, the one `state`
    was launched from: `origin` on its receipt says why (`seat_launch`), with the seat's lists
    now, the given run's only for a seat with no record of its own -- checked against the
    config now, as that run's may predate a model it names -- and `opts` over the defaults."""
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
    spawn_bg(directory, [str(directory / "task.md")])


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
            pid = orch.start_in_slice(
                child, unit, env, log_path,
                log=note_in(log_path), target_slice=orch.run_slice_name(),
                properties=properties,
                nice=True, placement=placement)
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
        refused(run_dir, exc, log, cfg)
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
    refuse_unready(cfg, providers, opts["--review"])
    if exec_for_rule:
        review_providers(cfg, exec_for_rule, opts["--review"])
    return opts["--review"]


def refused(run_dir, exc, log, cfg):
    """A launch its parent refuses ends as a refused preflight does: recorded and told."""
    state = mark_state(run_dir, "error", str(exc), log)
    record_result(run_dir, state, log, cfg)
    announce_safely(state, run_dir, log, cfg)


def prepare(run_dir, opts, log, cfg=None, job_id=None, task_file=None, receipt=None):
    capture_launch(run_dir, opts, job_id, cfg, task_file, receipt)
    try:
        preflight(run_dir, opts, log)
    except Stopped as exc:
        # Repository discovery never answered: nothing was done, so relaunch is the recovery --
        # but the stop is still reported everywhere a finished run would report it.  The state
        # stays `error`, the remedy is in the log and the result, and the re-raise is what the
        # foreground parent prints.
        state = mark_state(run_dir, "error", str(exc), log)
        record_result(run_dir, state, log, cfg)
        announce_safely(state, run_dir, log, cfg)
        raise
    except (config.Error, OSError) as exc:
        # The launch receipt is already visible to `r`; a rejected preflight must not leave
        # it queued forever, or lose the seat it belonged to before the check began.  It is
        # an ending like any other, so a result is written and the seat that launched it
        # hears why -- a hand-back naming a result.md nothing wrote is no hand-back.
        state = mark_state(run_dir, "error", str(exc), log)
        record_result(run_dir, state, log, cfg)
        announce_safely(state, run_dir, log, cfg)
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
        try:
            launched_cfg = config.load()
            is_own, orch = own_pr_orchestrator(
                launched_cfg, state.get("launched_session"), info["author"])
        except Exception:  # noqa: BLE001 - unknown login is never the seat's own PR
            is_own, orch = False, None
        state["own_pr"] = is_own
        state["own_orchestrator"] = orch if is_own else None
        run_record.save_state(run_dir, state)
        if is_own and not orch:
            raise config.Error(f"no session record names the writer of this PR; "
                               f"review of the seat's own PR needs its orchestrator")
        if is_own:
            # the budget is the pull request's: earlier runs' rounds on it are spent
            why = own_pr_budget(url, run_dir)[1]
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
        refusal = taskfile.checks_refusal(every)
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
              body, cmds, f"Repo checkout: {state['worktree']}\n\n{body}", [])
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


def gh_json(cwd, *args, timeout=None):
    """The parsed JSON a gh command prints, or None with the reason why not.

    A stop is never an empty answer: a timeout, or a prompt it was refused, raises Stopped,
    so no caller can deliver on the strength of a gh that said nothing at all.
    """
    rc, out = gitcall.gh(cwd, *args, timeout=timeout)
    if stopped(rc, out):
        raise Stopped(out)
    if rc != 0:
        return None, out[:400] or "gh timed out"
    try:
        return (config.json_pages(out) if "--paginate" in args else json.loads(out)), ""
    except ValueError as exc:
        return None, f"gh printed no JSON ({exc}): {out[-200:]}"


def pr_size_refusal(number, lines, carried=0):
    """One sentence when a pull request adds more lines than a first review takes at once
    (`task.MAX_PR_LINES`), else None: `lines` as `diff_lines` counts the added ones, less
    `carried`, the ones `carried_lines` found moved unchanged from lines the diff deletes --
    what a reviewer reads; nothing deleted counts."""
    if lines - carried <= taskfile.MAX_PR_LINES:
        return None
    moved = f", {carried} of them moved unchanged from lines it deletes" if carried else ""
    return (f"PR #{number} adds {lines} lines{moved} (generated files aside; deletions never "
            f"count): a first review takes at most {taskfile.MAX_PR_LINES}; split it")


def pr_view(url):
    data, why = gh_json(config.RUNS, "pr", "view", url, "--json",
                        "number,title,body,author,baseRefName,headRefOid,url,state,isDraft")
    if not isinstance(data, dict):
        raise config.Error(f"gh pr view {url} failed: {why}")
    author = data.get("author") or {}
    data["author"] = author.get("login") or "?"
    return data


PR_READ_LAG = 2.0       # seconds between reads of a PR whose head GitHub does not show yet
PR_READ_TRIES = 5       # reads after the first, before the last one is taken as it stands


def pr_view_past(url, info, stale):
    """`info`, the PR as just read, or read again PR_READ_TRIES times PR_READ_LAG apart while
    it is open on `stale`, the head before this run's own push: the last read stands, for
    the caller to judge as it would."""
    for _ in range(PR_READ_TRIES):
        if info.get("state") != "OPEN" or info.get("headRefOid") != stale:
            break
        time.sleep(PR_READ_LAG)
        info = pr_view(url)
    return info


def text_only_pr(repo, base, head):
    """Does every change between `base` and `head` touch only a prose or translation file?

    Both sides of a rename count: moving code into a prose filename still needs review.
    AGENTS.md is executable configuration: its front matter supplies shell commands.  Only a
    regular file counts: a submodule's commit or a link names code elsewhere, and a local
    `diff.ignoreSubmodules` hides nothing here.  A file is binary when its committed bytes hold
    a NUL, whatever `.gitattributes` tells the diff.  Names are read byte for byte, so each is
    looked up as the file it is, never a lookalike.  An AGENTS.md at any depth that is a link
    makes its target executable configuration too, so then nothing skips review.
    """
    raw = ("--no-renames", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", "-z")
    try:
        trees = [gitcall.git_bytes(repo, "ls-tree", "-r", "-z", ref) for ref in (base, head)]
        if any(meta.split(" ", 1)[0] not in ("100644", "100755")
               for tree in trees for meta, _, name in (entry.partition("\t")
                                                       for entry in tree.split("\0") if entry)
               if Path(name).name.upper() == "AGENTS.MD"):
            return False        # an AGENTS.md anywhere that is a link or a submodule
        entries = gitcall.git_bytes(repo, "diff", "--raw", *raw, base, head, "--").split("\0")
        modes = [entry.split()[:2] for entry in entries[0::2] if entry.startswith(":")]
        entries = gitcall.git_bytes(repo, "diff", "--numstat", *raw, base, head, "--").split("\0")
    except (config.Error, Stopped):
        return False        # a diff nobody could read cannot be shown to be wording
    files = [entry.split("\t", 2) for entry in entries if entry]
    extensions = {".md", ".markdown", ".rst", ".adoc", ".po", ".pot", ".xlf", ".xliff",
                  ".strings", ".stringsdict", ".srt", ".vtt"}
    names = {"README", "LICENSE", "COPYING", "NOTICE", "AUTHORS", "CHANGELOG"}
    return (bool(files) and len(modes) == len(files)
            and all(mode.lstrip(":") in ("000000", "100644", "100755")
                    for pair in modes for mode in pair)
            and all(len(row) == 3 and row[0].isdigit() and row[1].isdigit()
                    and Path(row[2]).name.upper() != "AGENTS.MD"
                    and (Path(row[2]).suffix.lower() in extensions
                         or Path(row[2]).name.upper() in names
                         or Path(row[2]).suffix.lower() in (".txt", ".text")
                         and Path(row[2]).stem.upper() in names) for row in files)
            and all(text_blob(repo, ref, row[2]) for pair, row in zip(modes, files)
                    for mode, ref in zip(pair, (base, head)) if mode.lstrip(":") != "000000"))


def text_blob(repo, ref, path):
    """Do the bytes `path` names at `ref` read back, with no NUL among them?"""
    try:
        return "\0" not in gitcall.git_bytes(repo, "cat-file", "blob", f"{ref}:{path}")
    except (config.Error, Stopped):
        return False


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
    if not session_name or not author or author == "?":
        return False, None
    try:
        viewer = viewer_login()
    except Exception:  # noqa: BLE001 - unknown login is never the seat's own PR
        return False, None
    if not viewer or author.lower() != viewer.lower():
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

    The seat's own PR always comments: GitHub rejects a changes-requested review
    from the account that authored the PR, which would turn a FAIL into an error.
    """
    head = lp.state["head_sha"]
    current, why = gh_json(lp.run_dir, "pr", "view", url, "--json", "headRefOid,state")
    lp.state["review_posted"] = False
    lp.state.pop("review_stale", None)
    lp.state.pop("review_error", None)
    if not isinstance(current, dict) or not current.get("headRefOid"):
        lp.state["review_error"] = f"cannot verify the PR head: {why}"
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
    how = "COMMENT" if verdict == "PASS" or lp.state.get("own_pr") else "REQUEST_CHANGES"
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


def fail_pr_landing(lp, failure, landing=True):
    """The PR's writer fixes a red landing tree, just as it fixes review findings.

    A `landing` red -- the line's check, a required check, a rebase the tip conflicts with --
    gets the run's fixer turn on the PR branch and a re-review that spends no round, however
    the round budget stands (`landing_fix`, read by `review_pr_round`), up to CONFLICT_ROUNDS
    times for one landing, as a task run's landing fixer gets.  A PR whose head moved past its
    review, in the line or under its delivery, or that closed (`landing` off) is reviewed as a
    round, as any new head is, while rounds are left.
    """
    text = saved_findings(lp.run_dir, lp.state) + "\n\n## Landing failed\n" + Path(failure["log"]).read_text()
    path = lp.run_dir / "landing-findings.md"
    path.write_text(text)
    lp.findings = text
    lp.state.update(verdict="FAIL", findings=text[-8000:], findings_file=str(path),
                    final_check={"outcome": "failed", "where": "landing", "line": failure["line"]})
    lp.state["review"] = {**lp.state["review"], "verdict": "FAIL", "overridden": failure["line"]}
    # the round's delivery is settled in this same write: a resume after it reviews the next head
    lp.state.pop("waiting_on", None)
    lp.state.pop("own_pr_round_pending", None)
    lp.state.pop("landing_fix", None)
    reds = lp.state.get("landing_reds", 0)
    if landing:
        reds = lp.state["landing_reds"] = reds + 1
    if lp.state.get("own_pr") and (reds <= CONFLICT_ROUNDS if landing else lp.rnd < lp.rounds):
        lp.state.update(state="running", finished_at=None, own_pr_wait=lp.state["head_sha"])
        if landing:
            lp.state["landing_fix"] = True
    else:
        if landing:
            lp.state["merge_note"] = f"landing failed {reds} times: {failure['line']}"
        # the count bounds one landing; a person who resumes the ended run starts a new one
        lp.state.pop("landing_reds", None)
        lp.state.update(state="fail", finished_at=time.time())
    lp.write()
    return False


def own_pr_heads(state):
    """The PR heads that are this run's own: the head it reviewed and the one it pushed."""
    return state.get("head_sha"), state.get("delivery_sha")


def merge_own_pr(lp, url):
    """Join the same line as task runs; deliver only the lander's tested PR tree."""
    if lp.state.get("own_pr") and not lp.state.get("own_orchestrator"):
        return note(lp, "no recorded writer for this PR; refusing the automatic merge",
                    failed=True)
    upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"

    def deliver():
        current = pr_head(lp, url)
        remote = current["head"]
        expected = own_pr_heads(lp.state)
        ours = (remote["sha"] in expected
                and (current.get("base") or {}).get("ref") == upstream.removeprefix("origin/"))
        if current.get("merged") and ours:
            lp.state.update(merged=True, **watch.merge_record(lp.wt, remote["sha"]))
            lp.write()
            return True
        if current.get("state") != "open" or not ours:
            path = lp.run_dir / "pr-changed.log"
            path.write_text("The PR head or target changed, or the PR closed, since review.\n")
            lp.state["review_stale"] = True
            return fail_pr_landing(lp, {"line": path.read_text().strip(), "log": str(path)},
                                   landing=False)
        pinned = git(lp.wt, "rev-parse", "HEAD")
        # Keep the intended push before calling Git: a killed push may have gone through.
        lp.state["delivery_sha"] = pinned
        lp.write()
        if remote["sha"] != pinned:
            push_pr_branch(lp, remote, remote["sha"])
        lp.state["head_sha"] = pinned
        lp.write()
        return wait_checks(lp, url) and do_merge(lp, url, upstream)

    return join_line(lp, upstream, deliver)


def own_pr_fix(state):
    """(round, turn name) of the fix a seat's own PR's next head comes from, which its review
    shares: the next round's `executor`, or a landing red's (`landing_fix`) in the round whose
    PASS it repairs, under a name for each red, so neither that round's fixer nor an earlier
    red's stands for it, and the next round still starts in a directory of its own."""
    done = len(state.get("round_summaries") or [])
    if state.get("landing_fix"):
        return done, f"landing-{state['landing_reds']}-fixer"
    return done + 1, "executor"


def pr_context(state, body):
    """What a worker on a PR review's checkout is told first: where it is and on what branch."""
    number = PR_PARTS.match(state["review_pr"]).group(3)
    return (f"Repo checkout: {state['worktree']}\nBranch: {state['branch']} (PR #{number} head, "
            f"based on origin/{state['target']})\n\n{body}")


def pr_head(lp, url):
    """The pull request as GitHub describes it now, its head named, or an error: what a push
    to its branch and a merge of it stand on."""
    api, owner, repo, number = pr_parts(url)
    current, why = gh_json(lp.run_dir, *api, f"repos/{owner}/{repo}/pulls/{number}")
    if not isinstance(current, dict) or not (current.get("head") or {}).get("sha"):
        raise config.Error(f"cannot read the PR: {why}")
    return current


def push_pr_branch(lp, remote, lease):
    """The checkout's HEAD onto the PR branch GitHub describes (`remote`, the PR's head), over
    `lease` and nothing else: a push made by hand meanwhile is never overwritten."""
    branch, source = remote.get("ref"), (remote.get("repo") or {}).get("clone_url")
    if not branch or not source:
        raise config.Error("cannot locate the PR branch to push to")
    rc, out = git_out(lp.wt, "push", f"--force-with-lease=refs/heads/{branch}:{lease}",
                      "--", source, f"HEAD:refs/heads/{branch}")
    if rc:
        raise config.Error(f"pushing to the PR branch failed: {out[-400:]}")


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

    current = pr_head(lp, url)
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
                # reviewer reads it (`fixer_words`), resumed after a cut or not
                execute(lp, "fixer", fix, name or turn)
            except Blocked as exc:
                pr_review_blocked(lp, exc)
                return False
        commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
        head = git(lp.wt, "rev-parse", "HEAD")
        # the PR as it stands after the fix, whatever the fix left: a closed PR or a head
        # pushed meanwhile ends the run, never a review of what the fixer did not see
        current = pr_head(lp, url)
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
    return Loop(cfg, run_dir, state, opts, log, Path(state["worktree"]), body, cmds, body, [])


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
    pushed = prior.get("delivery_sha")
    if prior.get("own_pr") and pushed and pushed != prior.get("head_sha"):
        # GitHub's read may lag the fix this run just pushed: never take the head this run
        # reviewed for the PR having moved under it
        info = pr_view_past(url, info, prior.get("head_sha"))
    if info.get("state") != "OPEN":
        raise config.Error(f"{url} is {info.get('state', '?')}, not open")
    if "own_pr" in prior:
        # The writer was captured at launch, in preflight or the first attempt: a
        # session record rewritten since must not replace it, or the reviewer's
        # independence check would judge another model than the one that wrote this.
        is_own = bool(prior.get("own_pr"))
        orchestrator = prior.get("own_orchestrator")
        if is_own and orchestrator:
            try:
                config.model(cfg, orchestrator)
            except (config.Error, OSError, ValueError, KeyError, TypeError):
                orchestrator = None
    else:
        is_own, orchestrator = own_pr_orchestrator(cfg, session_at_launch, info["author"])
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
        # off the record as it stands now, under its lock: `prior` was read before the wait on
        # GitHub, and a whole save of it would put the old record over a watcher's write since
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
                         "started_at": prior.get("started_at") or time.time(), "review_posted": False})
    # `own_pr_wait` stays until the new head's checkout is written down below: a fetch that
    # fails or a process that dies before then still lets the next attempt move to that head
    if advancing:
        receipt["review_session"] = None
    run_record.save_state(run_dir, receipt)
    owner, name, number = PR_PARTS.match(url).groups()
    repo = checkout_for(f"{owner}/{name}", log)
    if gc.disk_pressure():
        gc.gc(log)
    base, head = info["baseRefName"], info["headRefOid"]
    fetch(repo, "origin", f"pull/{number}/head", base, check=True)
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
        wrote = (f"The {session_at_launch} seat's orchestrator {orchestrator} wrote this diff; "
                 "review it as that model's work.")
    else:
        wrote = "Nobody from agentkit executed anything here; the diff is the author's."
    body = (f"# {title}\n\n## Goal\nJudge {url} by {info['author']} against this repository: "
            f"its AGENTS.md, README, tests and conventions, and the intent the PR states. {wrote}\n\n"
            f"## The PR says\n{(info.get('body') or '(no description)').strip()}\n\n"
            + planned + done_when_block(cmds))
    (run_dir / "task.md").write_text(f"---\nrepo: {repo}\nrounds: {n_rounds}\n---\n{body}")
    state = stamp_origin({**(run_record.read_state(run_dir) or {}), "run_id": run_dir.name,
             "title": title, "task": str(run_dir / "task.md"),
             "launched_session": session_at_launch, "repo": str(repo), "scratch": False,
             "review_pr": url, "pr": url, "head_sha": head, "author": info["author"],
             "own_pr": is_own, "own_orchestrator": orchestrator if is_own else None,
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

    if is_own and text_only_pr(repo, base_sha, head):
        # The seat's own wording needs no reviewer: it joins the line like a passed review,
        # where the repository's suite and CI still check it.
        summary = "Text and translation files only; review skipped."
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
        lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, body, [])
        lp.rnd += 1
        return settle_pr_round(lp, url, info)
    if is_own and not summaries and not rounds_spent_elsewhere(pr=url, exclude=run_dir)[0]:
        # the PR's first review, in this run or any, takes at most MAX_PR_LINES at once, the
        # lines it moves unchanged aside: past it, the run ends blocked with the reason before
        # any reviewer is picked, and the PR is split; a later round reviews whatever the fix left
        why = pr_size_refusal(number, diff_lines(repo, base_sha, head, added_only=True),
                              carried_lines(repo, base_sha, head))
        if why:
            lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, body, [])
            return pr_review_blocked(lp, Blocked(why, f"## Blocked\n\n{why}"))
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
        refuse_unready(cfg, providers, opts["--review"])
        if is_own:
            review_providers(cfg, orchestrator, opts["--review"])
        reviewer = opts["--review"]
    elif preset_rev or order:
        reviewer = preset_rev or order[0]
    else:
        raise QuotaDry("every worker has a gate meter at 100% used")
    spares = [n for n in order if n != reviewer]
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
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, pr_context(state, body), spares)
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
        said = fixer_words(lp.round_dir, turn)      # the fixer's own words on the head it left
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
            state.pop("landing_fix", None)      # this verdict is the landing fix's
            lp.write()
            write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
            return state
        green, why = checks(lp, url)
        current, _ = gh_json(run_dir, "pr", "view", url, "--json", "headRefOid,state")
        if (green and isinstance(current, dict) and current.get("headRefOid") == head
                and current.get("state") == "OPEN"):
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
            prepare(run_dir, opts, logger(run_dir), cfg)
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
                refused(run_dir, exc, logger(run_dir), cfg)
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
        landing.check_line(config.RUNS / argv[1], print)
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
        if needs_recovery(receipt):
            name = receipt.get("run_id") or Path(resumed).name
            raise config.Error(f"this launch was interrupted; ak run resume {name} to recover it")
        # a stale variable inherited from some other run: start our own instead of stealing it
        print(f"ak run: ignoring {config.RUN_DIR_ENV}={resumed}: not a queued run",
              file=sys.stderr)
        resumed = None
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
            prepare(run_dir, opts, logger(run_dir), cfg, task_file=task_path)
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
