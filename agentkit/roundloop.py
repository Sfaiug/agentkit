"""A task's rounds.

The loop over them and each round's steps: the loop's own state, the
executor's turn and the result its worker hands in, the verification of the
work (its checks, the rules, the base proof and the replay of a regression),
the reviewer's turn and the checkout it keeps, the same failure seen twice,
the target's own failure, the integration (its base, its patch id, its
conflicts, its parks and its aborts, the fix after a failed review) and the
final check.
"""

import copy
import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from . import (config, gitcall, hand_in, handback, history, prompts, record as run_record,
               staffing, task as taskfile, transitions, turns, worker)


# The front matter lines ak reads; any other name (a typo of `tests:` included) is read by nothing.
# `content:` names, as space-separated path prefixes, the project's own product text (its pages,
# its knowledge base): words that are the product, not notes about the code.
FRONT_KEYS = ("tests", "health", "cleanup", "users", "features", "suite_image", "content")


# The words an AGENTS.md body may grow to: what the project is, and the few facts no code can
# hold.  A floor, not a target: past it a body only shrinks, so what a branch would add there
# moves into the test, check or comment that holds it by itself, and no file ever needs a cleanup.
BODY_WORDS = 300


# Prose is where a branch would put facts no check holds.  Past AGENTS.md (`BODY_WORDS`) and a
# root README of `README_WORDS` (what the project is and how to start it), a prose file only
# shrinks and a new one holds nothing, so no guide, map or notes file ever regrows; the product
# text the base's `content:` names grows freely.
PROSE = (".md", ".markdown", ".mdx", ".rst", ".adoc")
README_WORDS = 300


# An answer key: a black-box test of the program from outside, which a port to another language
# answers to.  Once a base holds one, every change to its Python brings one (`keyless_python`).
KEY = re.compile(r"tests/test_key_[^/]*\.py")


BLOCKED_SAME = ("the same checks fail the same way after a fix round: "
                "the task or its checks are wrong")


class Loop:
    """One run's moving parts, shared by the round loop and the merge pipeline.

    The merge pipeline runs rounds of its own -- a conflicted rebase is fixed, re-tested and
    re-reviewed like any other finding -- so everything a round needs lives here instead of in
    `loop()`'s locals.  `rnd` is the number of rounds already spent, which is where a resumed
    run picks up.
    """

    def __init__(self, cfg, run_dir, state, opts, log, wt, body, cmds, context):
        self.cfg = config.at_efforts(cfg, state)    # each turn at the efforts it launched with
        self.run_dir, self.state, self.opts, self.log = run_dir, state, opts, log
        path = run_dir / "task.md"
        self.files = taskfile.task_files(path) if path.is_file() else []
        self.wt, self.body, self.cmds, self.context = wt, body, cmds, context
        # the per-round commands and the ones that run at landing; without a
        # `# once` line the two are the list and the empty one
        self.every, self.once = taskfile.group_commands(cmds)
        self.base, self.rounds = state["base"], state["rounds"]
        # where the PR goes, which is not always where the branch came from
        self.target = state.get("target") or state["base"]
        self.executor, self.reviewer = state["executor"], state["reviewer"]
        self.exec_sid, self.review_sid = state.get("exec_session"), state.get("review_session")
        self.findings = prompts.saved_findings(run_dir, state)
        self.artifacts = set(state.get("artifacts", ()))
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

    # The task's `files:` scope closes what every worker is first told, however late the body or
    # the context is set: a fresh run writes its context only once the loop exists.
    @property
    def scope(self):
        return "\n\nfiles: " + ", ".join(self.files) if self.files else ""

    body = property(lambda self: self._body + self.scope,
                    lambda self, text: setattr(self, "_body", text))
    context = property(lambda self: self._context + self.scope,
                       lambda self, text: setattr(self, "_context", text))

    def role(self, name):
        """The preamble this run's workers get: a scratch run has no commits to talk about.

        A seat's own PR is reviewed as a task is: its writer is named in the task, and its
        suite runs once at landing, which only the task reviewer's preamble says.
        """
        if self.scratch:
            return f"{name}-scratch"
        if name == "reviewer" and self.state.get("review_pr") and not self.state.get("own_pr"):
            return "reviewer-pr"
        return name

    @property
    def base_sha(self):
        return self.state["base_sha"]

    @property
    def upstream(self):
        """`origin/<target>`, the branch the work lands on, or None for a scratch run."""
        if self.target:
            return self.target if self.target.startswith("origin/") else f"origin/{self.target}"
        return None

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
                           executor_effort=self.state.get("executor_effort"),
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
    if lp.state.get("step") == "done-when" or round_suite(lp):
        return None     # the round's suite passes on more than exits: it runs again
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
    """Refuse a branch that grows prose past what it may hold (`prose_grown`), changes Python
    with no answer key (`keyless_python`), or changes AGENTS.md so workers would not get it as
    written: a link, a Git filter, more than a harness reads of it, or a front matter line ak
    does not read; or grows its body past `BODY_WORDS` and past what the base holds.  A branch
    that leaves the file alone, or deletes it, passes that part."""
    if lp.scratch:
        return ""
    failure = prose_grown(lp) or keyless_python(lp)
    if failure:
        return failure
    if not gitcall.git(lp.wt, "diff", "--name-only", "--no-renames", f"{lp.base_sha}...HEAD", "--", "AGENTS.md"):
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
    words = len(gitcall.agents_body(lp.wt, "HEAD").split())
    before = len(gitcall.agents_body(lp.wt, lp.base_sha).split())
    if words > max(BODY_WORDS, before):
        return (f"AGENTS.md's body grows from {before} to {words} words; past {BODY_WORDS} it "
                "only shrinks. Move what this adds into a test, a check or a comment at the code "
                "it is about.")
    text = held.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    unread = unknown_front_lines(text.strip())
    if not unread:
        return ""
    return (f"AGENTS.md front matter has lines ak does not read: "
            f"{', '.join(f'`{line}`' for line in unread)} (it reads {', '.join(FRONT_KEYS)}): "
            "remove them, or fix the misspelled name.")


def prose_grown(lp):
    """The refusal for the first prose file (`PROSE`) the branch grows past what it may hold, or "".

    Measured against the base, whose `content:` is the one that counts: a branch cannot widen
    its own exemption.  A rename is a new file, so no file grows by moving.
    """
    content = (gitcall.declared_at(lp.wt, lp.base_sha, "content") or "").split()
    # a link turned file (T) grows too, and names keep every byte, leading spaces included
    changed = gitcall.git_bytes(lp.wt, "diff", "--name-only", "--no-renames", "--diff-filter=AMT", "-z",
                                f"{lp.base_sha}...HEAD")
    for path in filter(None, changed.split("\0")):
        if (not path.lower().endswith(PROSE) or path == "AGENTS.md"
                or any(path.startswith(prefix) for prefix in content)):
            continue
        before, words = (len(gitcall.git(lp.wt, "cat-file", "-p", f"{ref}:{path}", check=False).split())
                         for ref in (lp.base_sha, "HEAD"))
        floor = README_WORDS if path == "README.md" else 0
        if words > max(floor, before):
            return (f"{path} grows from {before} to {words} words; prose outside the project's "
                    f"`content:` {f'past {floor} words ' if floor else ''}only shrinks. Move what "
                    "this adds into a test, a check or a comment at the code it is about; words that are "
                    "the product itself need the base's `content:` to name them first.")
    return ""


def keyless_python(lp):
    """The refusal for a branch that changes Python outside tests/ with no answer key (`KEY`), or "".

    In force where the base holds a key: the base's keys count, so a branch deleting its own frees
    nothing.  Decided from git's change records alone: every record but a deletion or a pure move
    (R100) writes its file, and a pure move from another kind of name makes a new key or .py file.
    """
    # `git` replaces only bytes that are not UTF-8, never "/" or ASCII: a key's name keeps its shape
    held = gitcall.git(lp.wt, "ls-tree", "-z", "--name-only", lp.base_sha, "--", "tests/")
    if not any(KEY.fullmatch(name) for name in held.split("\0")):
        return ""
    fields = iter(gitcall.git_bytes(lp.wt, "diff", "--name-status", "--find-renames", "-z",
                                    f"{lp.base_sha}...HEAD").split("\0"))
    python, keyed = [], False
    for status in fields:
        if not status:
            break       # the NUL ending the last record
        old = new = next(fields)
        if status[0] == "R":
            new = next(fields)
        writes = status not in ("D", "R100")
        if KEY.fullmatch(new):
            keyed |= writes or not KEY.fullmatch(old)
        elif (writes or not old.endswith(".py")) and new.endswith(".py") and not new.startswith("tests/"):
            python.append(new)
    if keyed or not python:
        return ""
    return (f"Python changed with no answer key: {', '.join(python)}. A change to a .py file "
            "outside tests/ adds, edits or moves in a tests/test_key_*.py in the same change: a "
            "black-box test of what it does.")


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
    from . import gate  # here, not at the top: it reaches run
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
    from . import gate  # here, not at the top: it reaches run
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
    from . import gate  # here, not at the top: it reaches run
    if cmds is None:
        cmds = lp.every
    lp.step("done-when")
    check = gate.run_done_when
    if not lp.scratch and not lp.state.get("review_pr"):
        if lp.state.get("repo"):
            # ak's commit step runs the lease scan itself: a diff that cannot merge with an
            # older live run's is parked here, before anything of it is reviewed, and the
            # save below raises the stop the scan recorded (`leases.park`)
            from . import leases
            leases.scan_safely(Path(lp.state["repo"]), lp.log)
            lp.save()
        gitcall.commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
        check = gate.run_round      # the tree at HEAD is the checkout's: the helper may run it
    follow_target(lp)
    checks = (files_scope(lp), rules_check(lp))
    lp.validation = {} if lp.scratch else gitcall.commit_identity(lp.wt)
    clean = lp.scratch or lp.state.get("review_pr") or gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
    ok, text = check(cmds, lp.wt, lp.round_dir / "donewhen.log", lp.artifacts,
                     lp.done_when_limit, lp.log, silence=lp.turn_limit, run_dir=lp.run_dir)
    suite_ok, suite_text = affected_suite(lp)
    if suite_text:
        ok &= suite_ok
        text = f"{suite_text}\n\n{text}"
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


def round_suite(lp, ref=None):
    """The target's `tests:` suite, at `ref` or else as last fetched, where this run lands and
    it names `AK_CHANGED`, which opts it into every round (`affected_suite`); else None.  Read
    off the target each time, as a sibling can change the line mid-run."""
    from . import gate  # here, not at the top: gate reaches run
    landing = lp.upstream and not lp.state.get("no_merge")
    suite = landing and gitcall.declared_suite(lp.wt, lp.target, ref=ref)
    return suite if suite and gate.names_changed(suite) else None


def affected_suite(lp):
    """(whether it passed, what it said) of the round's suite (`round_suite`), which every
    round runs besides the task's own checks; (True, "") where there is none.

    The suite narrows itself to the tests the change can affect, from the file `AK_CHANGED`
    names: the paths the change edits relative to the target, one per line.  It runs on HEAD
    merged onto the target as just fetched, so a sibling merged since meets the change here
    rather than in the landing line, in a clone of its own, on the heavy-suite turns and shares
    a landing check takes.  A sibling that conflicts with the change is landing's to bring in,
    in conflict rounds outside the task budget (`integrate`): the round then judges its own
    work, merged onto the target it last integrated with.  The suite is the line of the target
    the change meets, whose tree holds what it runs.  A red whose failing tests (`AK_FAILED`)
    all fail again on that target alone (`AK_ONLY`) is the target's, not the change's: it
    passes, and says which.
    """
    from . import gate, leases  # here, not at the top: gate reaches run
    if not round_suite(lp):
        return True, ""
    if gitcall.fetch(lp.wt, "origin", lp.upstream.removeprefix("origin/"))[0]:
        lp.log(f"WARN cannot fetch {lp.upstream}: the suite meets it as last fetched")
    tip = gitcall.git(lp.wt, "rev-parse", f"{lp.upstream}^{{commit}}")
    head = gitcall.git(lp.wt, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory(dir=lp.run_dir) as tmp:
        checkout, changed = Path(tmp) / "checkout", Path(tmp) / "changed"

        def moved(sha):
            """Whether a run left the checkout off `sha` or edited what it tracks: then its
            verdict is not that commit's, as `land._check` holds for the landing suite."""
            return (gitcall.git(checkout, "rev-parse", "HEAD") != sha
                    or gitcall.git_out(checkout, "diff", "--quiet", "HEAD")[0] != 0)

        gitcall.git(lp.wt, "clone", "--quiet", "--shared", "--no-checkout", str(lp.wt), str(checkout))
        code, tree = gitcall.git_out(checkout, "merge-tree", "--write-tree", "--name-only", tip, head)
        if code:
            last = lp.state.get("target_sha") or lp.base_sha
            lp.log(f"done-when: {lp.upstream} moved to {tip[:12]} with a change conflicting with "
                   f"this one, which landing brings in; the round meets {last[:12]}")
            tip = last
            code, tree = gitcall.git_out(checkout, "merge-tree", "--write-tree", "--name-only",
                                         tip, head)
        suite = round_suite(lp, tip)
        if not suite:
            return True, ""
        where = f"{head[:12]} merged onto {lp.upstream} at {tip[:12]}"
        if code:
            return False, f"$ {suite}\n[not run: {where} does not merge cleanly]\n{tree}"
        merged = gitcall.git(checkout, "commit-tree", tree.splitlines()[0], "-p", tip, "-p", head,
                             "-m", where, env=leases.STAMP)
        gitcall.git(checkout, "checkout", "--quiet", "--detach", merged)
        paths = [p for p in gitcall.git(checkout, "diff", "--name-only", "-z", "--no-renames",
                                        tip, merged).split("\0") if p]
        changed.write_text("".join(f"{path}\n" for path in paths))
        pieces, confirmed = {}, {}
        ok, text = gate.run_done_when([suite], checkout, lp.round_dir / "suite.log", set(),
                                      lp.done_when_limit, lp.log, silence=lp.turn_limit,
                                      run_dir=lp.run_dir, heavy=True, pieces=pieces,
                                      confirmed=confirmed, changed=changed)
        text = f"The `tests:` suite on {where}, AK_CHANGED listing its {len(paths)} paths:\n\n{text}"
        if moved(merged):
            return False, f"{text}\n\nCheckout changed during the suite; it does not verify {where}."
        named = confirmed.get(suite, {})
        reds = [share for share, code in pieces.get(suite, {}).items() if code != 0] or ["1/1"]
        failed = sorted({test for share in reds for test in named.get(share) or ()})
        if ok or not all(named.get(share) for share in reds):
            return ok, text
        gitcall.git(checkout, "checkout", "--quiet", "--force", "--detach", tip)
        gitcall.git(checkout, "clean", "-fdqx")
        again = {}
        gate.run_done_when([suite], checkout, lp.round_dir / "suite-target.log", set(),
                           lp.done_when_limit, lp.log, silence=lp.turn_limit, run_dir=lp.run_dir,
                           heavy=True, shard="1/1", only=failed, confirmed=again)
        if moved(tip):
            return False, text
    theirs = [test for test in failed if test in (again.get(suite) or {}).get("1/1", ())]
    if not theirs:
        return False, text
    said = f"failing on {lp.upstream} at {tip[:12]} alone too, the target's own: {' '.join(theirs)}"
    lp.log(f"done-when: the suite's tests {said}")
    return theirs == failed, f"{text}\n\nTests {said}"


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
    """Tests can regenerate tracked files; preserve their diff, then review the pinned commit.

    A run killed after its own rebase resumes on the commit it made (`pinned_head`)."""
    head = pinned_head(lp.state)
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


def follow_target(lp):
    """Move the run's base to the newest target commit its branch took in, before any check reads
    the work: a worker that rebased onto a newer tip, or merged it in, would otherwise hand
    in the target's moves since the launch as its own lines, to the file and prose checks, the
    first review's size and the reviewer's diff (a 73-line change counted 655).  A target git cannot
    read, or a fork point not past the base, keeps it."""
    if lp.scratch or not lp.upstream:
        return
    code, fork = gitcall.git_out(lp.wt, "merge-base", "HEAD", lp.upstream)
    fork = fork.strip()
    if code != 0 or not fork or fork == lp.base_sha:
        return
    if gitcall.git_out(lp.wt, "merge-base", "--is-ancestor", lp.base_sha, fork)[0] == 0:
        lp.log(f"base: the branch took in {lp.upstream} up to {fork[:12]}")
        set_base(lp, fork)


def set_base(lp, tip):
    """Keep the integrated tip for the diff and suite, even if another fetch moves the ref."""
    tip = gitcall.git(lp.wt, "rev-parse", f"{tip}^{{commit}}")
    lp.state.update(base_sha=tip, target_sha=tip)
    lp.write()
    pin_checkout(lp)


def pin_checkout(lp):
    """A review run reviews the commit its own rebase, merge or landing fixer left, until the
    PR head moves (`pinned_head`); a rebase or merge still stopped has made nothing yet."""
    if lp.state.get("review_pr") and not (in_progress(lp.wt, "rebase") or in_progress(lp.wt, "merge")):
        lp.state["integrated"] = {"from": lp.state["head_sha"],
                                  "to": gitcall.git(lp.wt, "rev-parse", "HEAD")}
        lp.write()


def pinned_head(state):
    """The commit a review run judges: the PR head, or what its own landing made of it."""
    review = state.get("review") or {}
    integrated = state.get("integrated") or (
        # a receipt from before `integrated` kept its rebase in the review that passed
        {"from": review.get("passed_head_sha"), "to": review.get("head_sha")}
        if review.get("verdict") == "PASS" else {})
    return integrated["to"] if integrated.get("from") == state["head_sha"] else state["head_sha"]


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
    from . import gate  # here, not at the top: it reaches run
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
            "text": prompts.red_target_text(cmd, upstream, tip, output, lp.run_dir)})
    except run_record.StopRequested:
        raise
    except Exception as exc:  # noqa: BLE001 - the park matters, not its repair
        lp.log(f"WARN no repair of {upstream} could start: {exc}")
    return prompts.first_failure(f"$ {cmd}\n[exit {code}]\n{output}")


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
        return staffing.hand_executor(lp, "transient", detail, dry)
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
        body = turns.NO_CLOSING_ASK
        out = turns.free_dir(lp, f"{previous.name}-retry-hand-in")
    if role == "fixer" and "## Reviewer findings to fix\n" in text and lp.state.get("findings_file"):
        findings = Path(lp.state["findings_file"]).with_name(hand_in.FINDINGS_FILE)
        if findings.is_file():
            resume["findings"] = findings
    while True:
        # read once the attempt ends, however it ends -- a refused, parked or killed turn spent
        # tokens too -- off its own model and directory, which a handover below moves on from
        model, attempt = lp.executor, out
        # the effort this turn runs at (worker.py reads the same), on the record before the
        # worker runs: a later save -- a review's, a landing's, or a resume's after the host cut
        # the loop off once the turn had closed (`continuation`) -- records what the executor
        # ran at, not the config since
        lp.state["executor_effort"] = config.worker_effort(lp.cfg, model, "executor")
        lp.save()
        try:
            code, summary, lp.exec_sid, dead = turns.call_retrying(lp.cfg, lp.executor, body, lp.wt,
                                                             out, lp.role(role), lp.exec_sid,
                                                             lp.log, lp.turn_limit,
                                                             handover=handover, **resume)
        except worker.LoginExpired as expired:
            lp.exec_sid = expired.session or lp.exec_sid
            lp.save()           # the parked conversation is in run.json before the run parks
            raise
        except turns.Killed as killed:
            lp.exec_sid = killed.session or lp.exec_sid
            lp.save()           # the killed conversation is in run.json before the run parks
            raise
        except turns.CannotRun as broken:
            # Another provider, the way a spent window goes; with nobody left, the run is
            # blocked on the harness's own line.  The turn never ran, so it left nothing
            # for the next model to be told about.
            if staffing.hand_executor(lp, "cannot run", broken.detail, dry) is None:
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
            new = staffing.hand_executor(lp, refused.why, refused.detail, dry)
            if new is None:
                raise turns.QuotaDry(f"{role} {before} ran dry on {refused.mark!r}: {refused.detail}; "
                               f"no other provider can execute; "
                               + ("retrying in ten minutes. " if lp.state.get("refusal_retry")
                                  else "resume when a meter refills. ") +
                               f"See {out}*/stderr.log")
            body = f"{prompts.HANDOVER.format(before=before)}\n\n{text}"
            closing_asked = False
            out = turns.free_dir(lp, f"{name}-{lp.executor}")
            continue
        except turns.TransientHandover as handed:
            # hand_executor already moved the role inside the callback; the new model
            # joins a round another started, in a fresh out dir on a fresh session.
            body = f"{prompts.HANDOVER.format(before=handed.before)}\n\n{text}"
            closing_asked = False
            out = turns.free_dir(lp, f"{name}-{lp.executor}")
            continue
        finally:
            transitions.history_role_tokens(lp.state.get("run_id"), "executor", attempt, lp.log,
                                lp.cfg, model)
            record_disputes(lp, attempt)
        if code != 0:
            lp.log(f"WARN {role} {turns.killed_word(code) or f'exited {code}'}; "
                   f"see {out / 'stderr.log'}")
        lp.save()
        submitted = prompts.review_records(out, summary)
        if (not (submitted is not None and submitted.closing) and not closing_asked
                and not list(out.parent.glob(f"{out.name}-retry*foreground*"))):
            lp.log(f"{role} {lp.executor} gave no closing; asking once more")
            resume["previous"] = prompts.written_answer(out, summary).parent
            body = turns.NO_CLOSING_ASK
            closing_asked = True
            out = turns.free_dir(lp, f"{resume['previous'].name}-retry-hand-in")
            continue
        return worker_result(lp, summary, out)


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
    `summary` is the author's own account of its work: it is recorded, never handed to the
    reviewer, whom it would prime.  The verdict is recorded either way, because delivery is decided
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
    earlier = prompts.earlier_findings(lp)
    # who could not finish this round's review, and whether a reviewer took it over from
    # outside it (`staffing.replace_reviewer`), kept across parks as `since` is: none is
    # asked again in this round, and a new round starts with nobody failed or handed
    this_round = pending.get("round") == lp.rnd
    failed = pending.get("failed", []) if this_round else []
    handed = this_round and pending.get("handed", False)
    lp.state.update(verdict=None, review=None,
                    review_pending={"round": lp.rnd, "summary": summary, "since": since,
                                    "earlier": earlier, "failed": failed,
                                    **({"handed": True} if handed else {}),
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
            head = pinned_head(lp.state)
            restore_review_checkout(lp, "tests")
        else:
            gitcall.commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
        diff = prompts.capped(lp, gitcall.git(lp.wt, "diff", f"{lp.base_sha}...{head}", check=False))
        work = whole = f"## Diff ({lp.base}...HEAD in {lp.wt})\n```diff\n{diff}\n```"
        at = gitcall.git(lp.wt, "rev-parse", head)
        # a later round judges what changed since the last review, where that review handed
        # in findings for a fix to answer: after a FAIL on the checks alone, and in a landing
        # re-review (`record` off: the repair that brought it here is nobody's fix round),
        # the whole change is judged again
        delta = prompts.reviewed_before(lp, delta_from, at) if record and earlier else None
        if record and delta_from and earlier:
            # a later round, on a new commit or the same again: ak re-proves the earlier findings.
            # One at a site the fixer disputed (a dispute names a site) is the reviewer's to weigh,
            # and a quote is no failing proof: both are listed, not replayed
            disputed = {(row["path"], row["line"]) for row in prompts.dispute_rows(lp)}
            proven = [row for row in earlier if "run" in (row.get("evidence") or {})
                      and (row["path"], row["line"]) not in disputed]
            left = [(row, "disputed by the fixer: hand it in again to uphold it"
                     if (row["path"], row["line"]) in disputed
                     else "a quote, which ak cannot re-prove: hand it in again if it still stands")
                    for row in earlier if row not in proven]
            replayed = prompts.replay_findings(lp, proven, at)
            # each earlier finding is listed, and handed to the reviewer's turn, where it
            # stands on this commit (`placed`): the one site a hand-in upholds it at
            standing = {id(row): prompts.placed(lp, row, delta, at)[0] for row in earlier}
            listed = lp.round_dir / "earlier.json"
            listed.parent.mkdir(parents=True, exist_ok=True)
            listed.write_text(json.dumps([{**row, "line": standing[id(row)]} for row in earlier]))
            shown = [({**row, "line": standing[id(row)]}, now, failing) for row, now, failing in replayed]
            told = [({**row, "line": standing[id(row)]}, why) for row, why in left]
            if delta:
                changed = prompts.capped(lp, gitcall.git(lp.wt, "diff", delta, head, check=False))
                work = (f"## Fix delta ({delta[:12]}...HEAD in {lp.wt}; what changed since the "
                        f"last review)\n```diff\n{changed}\n```\n\n{prompts.replay_section(shown, told, delta)}")
            else:
                work = f"{whole}\n\n{prompts.replay_section(shown, told, None)}"
        paths = prompts.changed_test_paths(lp, head)
        if paths:
            # Leave room for full names, including git's quoted non-ASCII paths.
            width = max(len(p.encode()) * 4 + 2 for p in paths)
            stat = gitcall.git(lp.wt, "diff", f"--stat={width + 80},{width}", "--no-renames",
                       f"{lp.base_sha}...{head}", "--", *(f":(literal){p}" for p in paths))
            checks = ("## Checks the executor changed\n```\n"
                      + "\n".join(stat.splitlines()[:-1]) + "\n```\n\n")
    identity = {} if lp.scratch else gitcall.commit_identity(lp.wt)
    disputes = prompts.review_disputes(lp, identity.get("head_sha"))
    validation = getattr(lp, "validation", identity if lp.state.get("review_pr") else {})
    # A hand-built stand-in for the loop (as in test_v4c) carries no commands; the real
    # Loop always does, and only then are markers attributed to their commands.
    passed, total = prompts.done_when_counts(dw_log, getattr(lp, "cmds", None))
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
                + f"{heading}\n"
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
    # A reviewer that took the review over writes in its own, so the attempt it continues
    # is only ever one it ran itself, never its predecessor's conversation.
    # The round is read off `dir`, which is what free_dir writes through.
    rd = lp.dir("reviewer").parent
    name = f"reviewer-{lp.reviewer}" if handed else turns.open_review(rd)[0] or "reviewer"

    def ready_reviewers():
        """The run's marked reviewers with room, as the meters read now, in pick order; only
        those that already failed this round stay out."""
        failed = lp.state["review_pending"].get("failed", [])
        try:
            providers = staffing.collect_usage(lp.cfg)
        except config.Error as exc:
            providers = {}      # meters nobody could read withhold no reviewer from a dead review
            lp.log(f"WARN could not read the meters: {exc}")
        return [n for n in staffing.ready_order(lp.cfg, providers, staffing.run_reviewers(lp.cfg, lp.state),
                                                lp.log, role="reviewer", repo=lp.state.get("repo"))
                if n not in failed]

    def independent(names):
        """Of `names`, those that wrote no part of the head under review (`head_writers`)."""
        writers = staffing.head_writers(lp.state)
        return [n for n in names if not any(staffing.same_model(lp.cfg, wrote, n) for wrote in writers)]

    if not independent([lp.reviewer]):
        # a writer reviews its own work only while no other marked reviewer has room: a
        # self-review picked in a shortage, at launch or on a resume, ends with the shortage
        offered = independent(ready_reviewers())
        if offered:
            lp.log(f"reviewer {offered[0]} has room: {lp.reviewer} does not review its own work")
            lp.reviewer, lp.review_sid = offered[0], None
            name = f"reviewer-{lp.reviewer}"
            lp.save()

    def fall_back(reason, out, allow_self=True, ending=turns.Exhausted):
        """The path a dry, twice-silent or twice-transient reviewer takes: next one, else Exhausted.

        The next one is read afresh from the run's marked reviewers and the meters as they
        read now, so a reviewer passed over while its meter was spent is picked once it has
        refilled; only those that already failed this round stay out of it."""
        failed = lp.state["review_pending"].setdefault("failed", [])
        if lp.reviewer not in failed:
            failed.append(lp.reviewer)
        # everyone who wrote part of the head reviews last
        offered = staffing.reviewer_order(lp.cfg, staffing.head_writers(lp.state), ready_reviewers())
        if not allow_self:
            # A flake waits unless another model can review: only a reviewer that cannot
            # come back settles for the executor's own model.
            offered = independent(offered)
        own = lp.state.get("own_orchestrator") if lp.state.get("own_pr") else None
        exec_for_rule = own or lp.executor
        if not offered:
            raise ending(f"reviewer {lp.reviewer} {reason} and no eligible reviewer is left "
                            f"to review; waiting for review. See {out}*/stderr.log")
        lp.reviewer, lp.review_sid = offered[0], None
        lp.save()
        transitions.review_providers(lp.cfg, exec_for_rule, lp.reviewer)
        lp.log(f"WARN reviewer fell back to {lp.reviewer}")
        return f"reviewer-{lp.reviewer}"
    ask = None      # where the answer that gave no verdict is, for the call asking once more
    while True:
        if not lp.executor and not lp.state.get("review_pr"):
            raise config.Error("task review requires a recorded executor")
        exec_provider, review_provider = transitions.review_providers(lp.cfg, lp.executor, lp.reviewer)
        # The open attempt is read before free_dir creates the next directory.
        turn_kind, turn_sid = turns.open_turn(rd, name)
        out = turns.free_dir(lp, name)
        body = rbody if lp.review_sid else rbody_whole
        asked_body, note, resume = body, None, {}
        if ask:
            asked_body, resume, ask = turns.NO_VERDICT_ASK, {"fresh_body": rbody_whole, "previous": ask}, None
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
        why, ending = "died on API/transport errors", turns.Exhausted
        model = lp.reviewer     # a fallback below moves on from it before its tokens are read
        reviewed = config.model(lp.cfg, model)
        review_harness, review_model = reviewed["harness"], reviewed["model"]

        def handover(detail, out=out):
            try:
                return fall_back(detail, out, allow_self=False)
            except turns.Exhausted:
                return None
        try:
            code, text, lp.review_sid, dead = turns.call_retrying(lp.cfg, lp.reviewer, asked_body,
                                                            lp.wt, out, lp.role("reviewer"),
                                                            lp.review_sid, lp.log,
                                                            lp.turn_limit,
                                                            handover=handover, findings=listed,
                                                            base=lp.state.get("target_sha") or lp.upstream,
                                                            **resume)
        except worker.LoginExpired as expired:
            lp.review_sid = expired.session or lp.review_sid
            lp.save()           # the parked conversation is in run.json before the run parks
            raise
        except turns.Killed as killed:
            lp.review_sid = killed.session or lp.review_sid
            lp.save()           # the killed conversation is in run.json before the run parks
            raise
        except turns.CannotRun as broken:
            # The fallback road, as for a spent window; with no reviewer left, the run is blocked
            # on the harness's own line rather than waiting for a meter it is not short of.
            try:
                name = fall_back(broken.detail, out)
            except turns.Exhausted:
                raise broken from None
            continue
        except turns.TransientHandover as handed:
            # fall_back already moved the role inside the callback; the next one reviews
            # in a fresh out dir on a fresh session.
            name = handed.new
            continue
        except turns.RanDry as dry:
            # A spent window is the other way a reviewer stops without judging the diff, so it
            # takes the same road out: the next marked reviewer, read as the meters stand now.
            dry.remember(lp.state)
            code, text, lp.review_sid, dead, why = dry.code, dry.text, dry.session, True, dry.detail
            ending = dry.ending
        finally:
            transitions.history_role_tokens(lp.state.get("run_id"), "reviewer", out, lp.log, lp.cfg, model)
        if code != 0:
            lp.log(f"WARN reviewer {turns.killed_word(code) or f'exited {code}'}; "
                   f"see {out / 'stderr.log'}")
        if dead:
            prompts.record_findings(lp, out, text)
            lp.save()
            name = fall_back(why, out, ending=ending)
            continue
        submitted = prompts.review_records(out, text)
        if submitted is not None and submitted.done:
            break
        # A missing verdict is a reviewer that has not answered, never an answer: ask the
        # same session once more, same round, no backoff, through the same call as the
        # review itself, so a window spent on the ask is a spent window and waits for its
        # refill.  When the turn already spent its one extra call finishing background
        # work in the foreground, that call already carried the verdict ask, so a second
        # silence means the reviewer is gone: no round is recorded, same as a dead reviewer.
        if asked_body == turns.NO_VERDICT_ASK or list(lp.round_dir.glob(f"{out.name}*foreground*")):
            prompts.record_findings(lp, out, text)
            lp.save()
            name = fall_back("gave no verdict twice", out)
            continue
        lp.log(f"reviewer {lp.reviewer} gave no verdict; asking once more")
        ask = prompts.written_answer(out, text).parent

    checkout_changed = not lp.scratch and (
        identity != validation or gitcall.commit_identity(lp.wt) != identity
        or (not lp.state.get("review_pr") and gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0))
    submitted = prompts.weigh_review(lp, submitted, identity.get("head_sha"), since=delta, replayed=replayed)
    upheld = {(row["path"], row["line"]) for row in submitted.findings}
    for row in disputes.disputes:
        # a dispute's finding is upheld wherever the fix left its line: moved, at the anchor
        # of its removal, or among the lines the fix put in its place
        lines = prompts.moved_lines(lp, row["path"], row["line"], delta, identity.get("head_sha"))[0]
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
        overridden = f"the reviewer said PASS but {turns.killed_word(code) or f'exited {code}'}"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    if ok is False and verdict == "PASS":
        verdict = "FAIL"
        # the check that failed, by name: the reviewer's text says PASS, and it is what is read
        checks = [line for line in (dw_log or "").splitlines() if prompts.LOOP_NOTE.match(line)]
        overridden = "; ".join(["the reviewer said PASS while done-when is failing", *checks])
        lp.log(f"WARN {overridden}; overriding to FAIL")
    if checkout_changed or (not lp.scratch and (
            gitcall.commit_identity(lp.wt) != identity or (not lp.state.get("review_pr") and
                                                   gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0))):
        verdict = "FAIL"
        overridden = "the checkout changed after verification"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    prompts.record_findings(lp, out, text, submitted=submitted)
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
        prompts.record_flakes(lp.state, dw_log)
        # A landing re-review with a pending suite keeps the task's probe base.
        if not getattr(lp, "once", ()) or (record and not lp.state.get("landing")):
            passed_head = validation.get("head_sha")
    passed = {"passed_head_sha": passed_head} if passed_head else {}
    if record:
        lp.state["round_summaries"].append(
            {"round": lp.rnd, "verdict": verdict, "done_when": ok,
             "finding_count": len(submitted.findings),
             "summary": summary.strip(), **validation, **passed})
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
                          note=len(own.notes), round=lp.rnd, verdict=verdict,
                          effort=config.role_effort(reviewed, "reviewer"), log=lp.log)
    return verdict


def landing_fixer(lp, text, name):
    """Give any landing fixer the line's red output and remember its completed turn."""
    wait = lp.state.get("waiting_on") or {}
    failure = wait.get("fix")
    if failure and name != "final-fixer":
        # An unrelated conflict or light check must not hide the lander's failure.
        output = Path(failure["log"]).read_text(errors="replace")
        text += (f"\n\n## The final check failed. Fix the root cause as well.\n```\n"
                 f"{prompts.failing_blocks(output, lp.run_dir)}\n```")
    summary = execute(lp, "fixer", text, name)
    pin_checkout(lp)
    if failure:
        # Save the actual fixer with its summary before a check or review can stop.
        lp.state["waiting_on"]["fixed"] = True
        lp.state["review_pending"]["summary"] = summary
        lp.save()
    return summary


@contextmanager
def released_gate_turn():
    """Let this thread's held gate turn go while slow work runs.

    A rebase conflict, a failing check and a re-review all end in a fixer or a reviewer,
    and a model turn held through them lands nothing for the runs queued behind.  The
    check takes a fresh turn after the fix.
    """
    from . import gate  # here, not at the top: it reaches run
    gate.release_turn()
    yield


def resume_review(lp, verified=None):
    pending = lp.state["review_pending"]
    identity = {} if lp.scratch else gitcall.commit_identity(lp.wt)
    pending.update(identity)
    lp.save()
    allowed = transitions.allowed_rounds(lp)
    if pending["round"] > allowed:
        work = f"for commit {identity['head_sha']} (tree {identity['tree_sha']}) " if identity else ""
        # a larger budget is only for asking up to what the change has left: past it the next
        # step is the orchestrator's, and naming a `--rounds` that is refused would send it nowhere
        onward = (f"resume with ak run resume {lp.run_dir.name} --rounds {pending['round']}"
                  if pending["round"] <= transitions.lineage_cap(lp.state, lp.run_dir)
                  else "split or redesign the task")
        reason = (f"{pending.get('reason', 'unfinished review')}; done-when and review are pending "
                  f"{work}at round {pending['round']}, but the round budget ({allowed}) is spent; "
                  f"{onward}")
        note(lp, reason, failed=True)
        raise turns.Exhausted(reason)
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
    first_review_ceiling(lp)
    return review(lp, pending["summary"], ok, dw_log,
                  pending.get("reason", "Resume the unfinished review."),
                  **({"record": False} if pending.get("record") is False else {}))


def rounds(lp, execv=None):
    """Executor -> done-when -> reviewer, until PASS or the round budget is spent.

    Only a recorded successful review by an eligible model can skip straight to delivery.
    An unfinished review resumes on the saved work without spending another executor turn.
    """
    from . import run  # here, not at the top: run imports roundloop
    transitions.invalidate_saved_pass(lp.state, lp.cfg, lp.log)
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
        if not integrate(lp, lp.upstream) and lp.state.get("merge_failed"):
            # An unreachable target needs the tick's error retry, not a task verdict.
            raise config.Error(lp.state["merge_note"])
        return
    if transitions.review_pass(lp.state, lp.cfg) and not current_review(lp):
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
    while transitions.round_allowed(lp):
        run.pickup_new_code(lp, execv=execv)
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
                    # A change past the ceiling is refused now, before its checks and their fixer.
                    first_review_ceiling(lp, record=False)
                else:
                    fixer_body = (f"{lp.context}\n\n## Reviewer findings to fix\n"
                                  f"{prompts.without_followups(lp.findings)}")
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
        first_review_ceiling(lp)
        if review(lp, summary, ok, dw_log, "Re-review after fixes." if lp.rnd > 1 else "") == "PASS":
            return


def first_review_ceiling(lp, record=True):
    """A task's change gets its first review only up to `task.MAX_PR_LINES` added lines:
    past it the run ends blocked with `split it`
    before the reviewer reads a line, and the branch it keeps holds the work for the pieces.
    Only the change's first review, a resumed one too: once a review of it, in this run or in
    one launched `from:` its branch, handed in a verdict, a later one reviews whatever the fix
    left.  A scratch run has no diff to count.  A first review that goes ahead records the lines
    it reads in the run's history row, whatever the run's ending, so the ceiling can be weighed
    against how often changes of each size end merged."""
    if (lp.scratch or lp.state.get("review_pr")
            or transitions.change_reviewed(change=transitions.change_of(lp.state))):
        return
    gitcall.commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
    follow_target(lp)
    lines = transitions.diff_lines(lp.wt, lp.base_sha, "HEAD", added_only=True)
    carried = transitions.carried_lines(lp.wt, lp.base_sha, "HEAD")
    why = transitions.first_review_refusal(f"The change on {lp.state.get('branch') or 'its branch'}",
                                           lines, carried)
    if why:
        raise turns.Blocked(why, f"## Blocked\n\n{why}")
    if record:
        history.first_review(lp.state.get("run_id"), lines - carried, log=lp.log)


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
    while transitions.round_allowed(lp):
        fix = f"{lp.context}\n\n## Reviewer findings to fix\n{prompts.without_followups(lp.findings)}"
        if (lp.state.get("review") or {}).get("done_when") is False:
            # the output the review was given, still in the round directory it ran in
            log_path = lp.round_dir / "donewhen.log"
            dw_log = log_path.read_text(errors="replace") if log_path.is_file() else ""
            fix += (f"\n\n## The done-when commands failed. Fix the root cause.\n```\n"
                    f"{dw_log}\n```")
        lp.rnd += 1
        lp.log(f"--- round {lp.rnd}/{lp.rounds}: fixer {lp.executor} (findings after {what})")
        summary = execute(lp, "fixer", fix, "executor")
        pin_checkout(lp)
        ok, dw_log = verify_work(lp)
        lp.log(f"done-when after the fix: {'all passed' if ok else 'FAILED'}")
        same_failure(lp, ok, dw_log)
        if review(lp, summary, ok, dw_log, f"Re-review after fixes for {what}.") == "PASS":
            return True
    return False


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
    conflicts = [p for p in gitcall.git(lp.wt, "diff", "--name-only", "--diff-filter=U",
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
            + "\n".join(f"- {p}" for p in conflicts)
            + f"\n\n```\n{turns.cut(out, lp.run_dir, f'{how}-conflict')}\n```")
    summary, landed = "", False
    if lp.state.get("own_pr"):
        # a seat's PR that passed its first review had no fixer yet: its conflict is its
        # writer's, as a finding is, and the re-review is picked against them
        lp.executor = lp.executor or lp.state["own_orchestrator"]
    for attempt in range(1, CONFLICT_ROUNDS + 1):
        lp.log(f"--- merge: conflict round {attempt}/{CONFLICT_ROUNDS}: "
               f"fixer {lp.executor} ({how} conflict)")
        try:
            summary = landing_fixer(lp, text, f"{how}-fixer")
        except (turns.Dead, turns.Blocked, turns.Exhausted, turns.Killed, worker.LoginExpired) as exc:
            pending = lp.state.get("review_pending")
            if isinstance(exc, (turns.Exhausted, turns.Killed, worker.LoginExpired)) and pending:
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
    rc, out = gitcall.fetch(lp.wt, "origin", "--prune")
    if rc != 0:
        return note(lp, f"git fetch origin failed: {out[-400:]}", failed=True)
    if not gitcall.git(lp.wt, "rev-parse", "--verify", "--quiet", f"{upstream}^{{commit}}",
               check=False):
        return note(lp, f"{upstream} does not exist on origin; nothing to merge into",
                    failed=True)
    tip = gitcall.git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
    how = how_to_integrate(lp)
    try:
        pre_identity = gitcall.commit_identity(lp.wt)
    except gitcall.Stopped:
        raise
    except config.Error:
        pre_identity = None
    saved = dict(lp.state["review"]) if isinstance(lp.state.get("review"), dict) else None
    saved_verdict = lp.state.get("verdict")
    try:
        was_pass = transitions.review_pass(lp.state, lp.cfg)
    except gitcall.Stopped:
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
            rc, out = gitcall.merge(lp.wt, tip)
        else:
            lp.log(f"--- merge: rebasing {lp.state['branch']} onto {upstream} ({tip[:12]})")
            rc, out = gitcall.git_out(lp.wt, "rebase", tip)
    except gitcall.Stopped:
        abort_stopped_integration(lp, how)
        raise
    if rc != 0:
        with released_gate_turn():
            resolved = resolve_conflicts(lp, upstream, out, how, tip)
        if not resolved:
            return False
        # the conflict round re-tested this commit and the review passed on it
        lp.checked_every_sha = gitcall.git(lp.wt, "rev-parse", "HEAD")
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
                new_identity = gitcall.commit_identity(lp.wt)
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
                    post_identity = gitcall.commit_identity(lp.wt)
                except gitcall.Stopped:
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
                    lp.checked_every_sha = gitcall.git(lp.wt, "rev-parse", "HEAD")
                else:
                    pending = lp.state.get("review_pending")
                    pending_round = pending["round"] if pending else lp.rnd
                    old_rnd = lp.rnd
                    lp.rnd = pending_round
                    lp.round_dir.mkdir(parents=True, exist_ok=True)
                    ok, dw_log = verify_work(lp)
                    lp.log(f"done-when after the {how}: {'all passed' if ok else 'FAILED'}")
                    if ok:
                        new_identity = gitcall.commit_identity(lp.wt)
                        if new_identity != post_identity or landing_review:
                            if not lp.state.get("review_pending"):
                                pending_review(lp, f"Re-review after the {how} of {upstream}.")
                            with released_gate_turn():
                                passed = (resume_review(lp, verified=(ok, dw_log)) == "PASS"
                                          or fix_after_failed_review(lp, upstream, how))
                            if not passed:
                                return note(lp, f"done-when or review after the {how} of {upstream} "
                                                "did not pass")
                            lp.checked_every_sha = gitcall.git(lp.wt, "rev-parse", "HEAD")
                        else:
                            lp.log(f"--- merge: clean {how} of {upstream}; "
                                   "done-when passed again, review kept")
                            lp.state["review"] = {**saved, "head_sha": new_identity["head_sha"],
                                                  "tree_sha": new_identity["tree_sha"],
                                                  "passed_head_sha": passed_review_head(lp.state),
                                                  "rebased_from": old_head,
                                                  "patch_id": patch_id(lp.wt, tip)}
                            lp.state["verdict"] = saved_verdict
                            prompts.record_flakes(lp.state, dw_log)
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
                                        f"{CONFLICT_ROUNDS} fixer rounds: {prompts.first_failure(dw_log)}",
                                    upstream, tip)
                            lp.log(f"--- merge: re-run round {attempt + 1}/{CONFLICT_ROUNDS}: "
                                   f"fixer {lp.executor} (done-when after the {how})")
                            fix = (f"{lp.context}\n\n## The done-when commands failed. "
                                   f"Fix the root cause.\n```\n{prompts.failing_blocks(dw_log, lp.run_dir)}\n```")
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
                        lp.checked_every_sha = gitcall.git(lp.wt, "rev-parse", "HEAD")
            else:
                if not lp.state.get("review_pending"):
                    pending_review(lp, f"Re-review after the {how} of {upstream}.")
                with released_gate_turn():
                    passed = (resume_review(lp) == "PASS"
                              or fix_after_failed_review(lp, upstream, how))
                if not passed:
                    return note(lp, f"done-when or review after the {how} of {upstream} "
                                    "did not pass")
                lp.checked_every_sha = gitcall.git(lp.wt, "rev-parse", "HEAD")
    if (not (lp.state.get("waiting_on") or {}).get("line")
            and gitcall.git_out(lp.wt, "diff", "--quiet", tip, "HEAD")[0] == 0):
        lp.state["on_target"] = True
        return note(lp, f"its work is already on {upstream.removeprefix('origin/')}")
    return True


def fix_final_check(lp, upstream, text):
    """Repair failing landing output and re-review, without recording a task round."""
    fix = (f"{lp.context}\n\n## The final check failed. Fix the root cause.\n```\n"
           f"{prompts.failing_blocks(text, lp.run_dir)}\n```")
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
    from . import gate  # here, not at the top: it reaches run
    if not lp.state.get("target_sha"):
        lp.state["target_sha"] = gitcall.git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False) or None
    try:
        now = gitcall.git(lp.wt, "rev-parse", "HEAD")
    except (gitcall.Stopped, config.Error):
        now = None
    record = lp.state.get("final_check") or {}
    if (now and record.get("outcome") == "passed" and record.get("where") == "landing"
            and record.get("sha") == now
            and record.get("suite") == gitcall.declared_suite(lp.wt, lp.target,
                                                       ref=lp.state.get("target_sha"))):
        try:
            reviewed = current_review(lp)
        except (gitcall.Stopped, config.Error):
            reviewed = False
        if reviewed:
            lp.log(f"final check: already passed at landing on {now[:12]}; landing on it")
            return True
    fixed = 0       # the fixer rounds this run has spent on these commands here
    while True:
        sha = gitcall.git(lp.wt, "rev-parse", "HEAD")
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
        identity = gitcall.commit_identity(lp.wt)
        clean = gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
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
        if (not clean or gitcall.commit_identity(lp.wt) != identity
                or gitcall.git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0):
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
        except turns.Blocked as exc:
            # the hand-back names what kept failing, not only that something did
            raise turns.Blocked(f"{exc}; the final check still fails on {prompts.first_failure(text)}",
                          exc.section) from None
        if ok:
            lp.log("final check: all passed")
            evidence = suite_evidence(lp, cmds_once, identity)
            lp.state["final_check"] = {"outcome": "passed", "sha": sha, "where": "landing",
                                       **evidence}
            if current_review(lp):
                lp.state["review"]["passed_head_sha"] = sha
            prompts.record_flakes(lp.state, text)
            lp.write()
            return True
        failing = prompts.first_failure(text)
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
