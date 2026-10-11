"""A round's steps.

The loop's own state, a worker's result and the disputes it records, the
verification of the work (its checks, the rules, the base proof and the replay
of a regression), the reviewer's checkout, the same failure seen twice, the
target's own failure, and what an integration needs: its base, its patch id,
its parks and its aborts.
"""

import copy
import os
import re
import shlex
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from . import config, gitcall, hand_in, handback, history, prompts, record as run_record, task as taskfile, transitions, turns, worker


# The front matter lines ak reads; any other name (a typo of `tests:` included) is read by nothing.
FRONT_KEYS = ("tests", "health", "cleanup", "users", "features")


BLOCKED_SAME = ("the same checks fail the same way after a fix round: "
                "the task or its checks are wrong")


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
        self.findings = prompts.saved_findings(run_dir, state)
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
                           session=transitions.launched_session(self.state), log=self.log)

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
        handback.redress_seat(transitions.launched_session(self.state))


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
    if turns.regression_script(lp.run_dir).is_file() and not lp.state.get("regression_checked"):
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
    passed, total = prompts.done_when_counts(text, lp.every)
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
            or prompts.review_files(lp.run_dir, lp.rnd)):
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
    answer = prompts.written_answer(out, summary).parent
    submitted = hand_in.read(answer / hand_in.FILE)
    closing = submitted.closing if submitted is not None else None
    if closing:
        if closing["kind"] == "blocked":
            raise turns.Blocked(closing["why"], f"## Blocked\n\n{closing['why']}")
        if (closing["kind"] == "not-needed" and lp.state.get("followup")
                and not lp.state.get("round_summaries")):
            raise turns.NotNeeded(closing["why"])
    # A closing reply may be only an acknowledgement; retain the work prose on restart too.
    name = re.split(r"-retry-(?:hand-in|foreground)", answer.name, maxsplit=1)[0]
    work = turns.read_answer(answer.with_name(name) / "final.md")
    if work and work != summary:
        summary = f"{work}\n\n{summary}"
    return summary


def suite_evidence(lp, cmds, identity):
    """Keep the checked tree: integration can carry the SHA without running the suite again."""
    suite = gitcall.declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
    return {"suite": suite, "tree_sha": identity.get("tree_sha")} if suite and suite in cmds else {}


def current_review(lp):
    """A successful review belongs to exactly the commit that was tested and reviewed."""
    if not transitions.review_pass(lp.state, lp.cfg):
        return False
    return lp.scratch or all(lp.state["review"].get(k) == v
                             for k, v in gitcall.commit_identity(lp.wt).items())


def files_scope(lp):
    """A gate failure for paths outside the task's Git pathspecs, else an empty string."""
    specs = getattr(lp, "files", ())
    if not specs or lp.scratch or lp.state.get("review_pr"):
        return ""
    cmd = ["git", "-C", str(lp.wt), "diff", "--name-only", "--no-renames", "-z",
           f"{lp.base_sha}...HEAD"]
    paths = []
    for suffix in ([], ["--", *specs]):
        # gitcall.git() strips whitespace, which can be part of the first path's name.
        code, out, err = gitcall.tool_run(cmd + suffix)
        if code != 0:
            raise (gitcall.Stopped if gitcall.stopped(code, err) else config.Error)(
                f"files: git diff failed in {lp.wt}: {err.strip()}")
        paths.append(set(out.split("\0")) - {""})
    outside = sorted(paths[0] - paths[1])
    return "outside files: " + ", ".join(outside) if outside else ""


def rules_check(lp):
    """Refuse a branch's change to AGENTS.md that workers would not get as written: a link, a
    Git filter, more than a harness reads of it, or a front matter line ak does not read.
    A branch that leaves the file alone, or deletes it, passes."""
    if lp.scratch or not gitcall.git(lp.wt, "diff", "--name-only", "--no-renames",
                             f"{lp.base_sha}...HEAD", "--", "AGENTS.md"):
        return ""
    entry = gitcall.git(lp.wt, "ls-tree", "HEAD", "--", "AGENTS.md")
    if not entry:
        return ""       # the branch deleted it
    if entry.startswith("120000 "):
        # following it would mean redoing how Linux opens a path, inside Git's trees
        return ("AGENTS.md is a link, which ak does not follow, so workers would get no rules "
                "from it: make AGENTS.md the file itself.")
    if not gitcall.git(lp.wt, "check-attr", "filter", "--", "AGENTS.md").endswith(("unspecified", "unset")):
        return "AGENTS.md must not go through a Git filter: ak reads its front matter as committed."
    ceiling = config.instruction_ceiling()
    try:
        held = gitcall.rules_bytes(lp.wt, "HEAD")
    except gitcall.Stopped:
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
    from . import gate  # here, not at the top: gate imports watch, which imports gc, which imports run
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
    from . import gate  # here, not at the top: gate imports watch, which imports gc, which imports run
    cmds = own_checks(lp)
    if not cmds:
        return "the task has no check of its own that runs each round"
    head = gitcall.git(lp.wt, "rev-parse", "HEAD")
    base = lp.base_sha
    changed = [p for p in gitcall.git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                              f"{base}...{head}").split("\0") if p]
    tests = prompts.changed_test_paths(lp, head, named=False)
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
        gitcall.git(lp.wt, "clone", "--quiet", "--shared", "--no-checkout", str(lp.wt), str(checkout))
        try:
            gitcall.git(checkout, "checkout", "--quiet", "--detach", lp.base_sha)
            # what the branch deleted goes first, so a file or submodule it put where a
            # folder was takes that place; the paths come from a file, as a branch can change
            # more of them than one command line holds
            deleted = set(gitcall.git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                              "--diff-filter=D", f"{lp.base_sha}...{head}").split("\0"))
            for part, command in (([p for p in paths if p in deleted],
                                   ("rm", "--quiet", "-r", "--ignore-unmatch")),
                                  ([p for p in paths if p not in deleted],
                                   ("restore", f"--source={head}", "--staged", "--worktree"))):
                if part:
                    listed = Path(tmp) / "paths"
                    listed.write_bytes(b"\0".join(os.fsencode(p) for p in part))
                    gitcall.git(checkout, *command, f"--pathspec-from-file={listed}",
                        "--pathspec-file-nul", env={"GIT_LITERAL_PATHSPECS": "1"})
            when = gitcall.git(checkout, "show", "-s", "--format=%cI", "HEAD")
            gitcall.git(checkout, "-c", f"core.hooksPath={os.devnull}", "commit", "--quiet",
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
    script = turns.regression_script(lp.run_dir)
    if not script.is_file() or lp.state.get("regression_checked"):
        return ""
    if lp.scratch:
        return "regression.sh cannot be checked without a base commit"
    head = gitcall.git(lp.wt, "rev-parse", "HEAD")
    base = lp.base_sha
    changed = [p for p in gitcall.git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                              f"{base}...{head}").split("\0") if p]
    only_tests = prompts.changed_test_paths(lp, head) == changed
    proof = prompts.proof_on(lp, f"bash {shlex.quote(str(script))}", lp.run_dir / "regression-base.log",
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
    from . import gate  # here, not at the top: gate imports watch, which imports gc, which imports run
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
        gitcall.commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
    checks = (files_scope(lp), rules_check(lp))
    lp.validation = {} if lp.scratch else gitcall.commit_identity(lp.wt)
    clean = lp.scratch or lp.state.get("review_pr") or gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
    ok, text = gate.run_done_when(cmds, lp.wt, lp.round_dir / "donewhen.log", lp.artifacts,
                                  lp.done_when_limit, lp.log, silence=lp.turn_limit,
                                  run_dir=lp.run_dir)
    if not lp.scratch and not lp.state.get("review_pr") and (
            not clean or gitcall.commit_identity(lp.wt) != lp.validation or
            gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0):
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
        text += "\n\n" + prompts.base_proof_line(lp.state)
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


def restore_review_checkout(lp, stage):
    """Tests can regenerate tracked files; preserve their diff, then review the pinned commit."""
    head = lp.state["head_sha"]
    if gitcall.git(lp.wt, "rev-parse", "HEAD") != head:
        raise config.Error(f"review checkout HEAD changed during {stage}; cannot review the pinned PR head")
    rc, why = gitcall.git_out(lp.wt, "diff", "--quiet", head)
    if rc == 1:
        path = lp.run_dir / f"{stage}-changes.patch"
        path.write_text(gitcall.git(lp.wt, "diff", "--binary", head))
        gitcall.git(lp.wt, "restore", f"--source={head}", "--staged", "--worktree", "--", ".")
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
    failure = [] if ok else prompts.failing_checks(dw_log)
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
    raise turns.Blocked(BLOCKED_SAME, f"## Blocked\n\n{BLOCKED_SAME}\n\n"
                                f"The checks that failed identically twice:\n\n{listed}")


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
        path = Path(gitcall.git(wt, "rev-parse", "--git-path", name))
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
    rc, _ = gitcall.git_out(wt, "merge-base", "--is-ancestor", rev, "HEAD")
    return rc == 0


def patch_id(wt, base_sha):
    """The stable id of `base...HEAD`, or None for an empty diff or any git failure."""
    try:
        rc, diff = gitcall.git_out(wt, "diff", f"{base_sha}...HEAD")
    except gitcall.Stopped:
        raise
    except Exception:
        return None
    try:
        if rc != 0 or not diff.strip():
            return None
        proc = subprocess.run(["git", "-C", str(wt), "patch-id", "--stable"],
                              input=diff, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=gitcall.TOOL_CAP, env=gitcall.tool_env())
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
    merges = gitcall.git(lp.wt, "rev-list", "--merges", f"{lp.base_sha}..HEAD", check=False)
    return "merge" if merges else "rebase"


def set_base(lp, tip):
    """Keep the integrated tip for the diff and suite, even if another fetch moves the ref."""
    tip = gitcall.git(lp.wt, "rev-parse", f"{tip}^{{commit}}")
    lp.state.update(base_sha=tip, target_sha=tip)
    lp.write()


def abort_integration(lp, how):
    """Put the branch back, keeping any earlier landing review.

    A task review describes the abandoned integration and goes with it. A non-task
    review can predate it: the restored HEAD still holds unreviewed landing fixes,
    so recovery must keep that pending review at the current round. The invalidated
    verdict stays invalidated.
    """
    gitcall.git_out(lp.wt, how, "--abort")
    if (lp.state.get("review_pending") or {}).get("record") is not False:
        lp.state.pop("review_pending", None)
    lp.write()


CONFLICT_ROUNDS = 3      # the merge pipeline's own fixer rounds per conflict or failing re-run


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
        rc, out = gitcall.git_out(lp.wt, how, "--abort")
    except gitcall.Stopped as exc:
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
        # `gitcall.git()` strips whitespace, and with it the space a first name can start with
        code, out, _ = gitcall.tool_run(["git", "-C", str(wt), "diff", "--no-renames",
                                 "--name-only", "-z", base, end])
        if code != 0:
            return False
        sides.append(set(out.split("\0")) - {""})
    return not (sides[0] & sides[1])


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
            if gitcall.git_out(wt, "cat-file", "-e", f"{head}:{path}")[0] != 0:
                continue
            if gitcall.git_out(wt, "cat-file", "-e", f"{tip}:{path}")[0] != 0:
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
    from . import gate  # here, not at the top: gate imports watch, which imports gc, which imports run
    if (lp.state.get("waiting_on") or {}).get("line"):
        return ""     # a line member fixes its own red, without assigning it to another run
    failed = prompts.failing_checks(dw_log)
    if not failed:
        return ""
    cmd = failed[0][0]
    if cmd == (lp.state.get("repair") or {}).get("command"):
        return ""
    try:
        tip = lp.state.get("target_sha") or gitcall.git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
        head = gitcall.git(lp.wt, "rev-parse", "HEAD")
    except gitcall.Stopped:
        raise
    except config.Error:
        return ""
    if gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0:
        return ""
    missing = _branch_only_path(lp.wt, cmd, head, tip)
    if missing is not None:
        lp.log(f"--- merge: `{cmd}` names {missing}, which {upstream} lacks; "
               "no probe, the fixer runs")
        return ""
    branch = gitcall.git(lp.wt, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    run_record.stop_check(lp.run_dir)
    before = set(gitcall.dirty_paths(lp.wt))
    probe_log = lp.run_dir / "target-probe.log"
    heavy_probe = cmd in (getattr(lp, "once", None) or [])

    def probe(sha, where):
        label = f"`{cmd}` on {where}"
        gitcall.save_probe_checkout(lp, head, branch, before, label)
        try:
            rc, _ = gitcall.git_out(lp.wt, "checkout", "--quiet", "--detach", sha)
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
        old_base = gitcall.git(lp.wt, "merge-base", passed_head, tip)
    except gitcall.Stopped:
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
        lp.repair = handback.start_followups(lp.state, lp.run_dir, lp.log, lp.cfg, repair={
            "command": cmd, "check": f"{cmd}  # once" if heavy_probe else cmd, "sha": tip,
            "text": prompts.red_target_text(cmd, upstream, tip, output)})
    except run_record.StopRequested:
        raise
    except Exception as exc:  # noqa: BLE001 - the park matters, not its repair
        lp.log(f"WARN no repair of {upstream} could start: {exc}")
    return prompts.first_failure(f"$ {cmd}\n[exit {code}]\n{output}")
