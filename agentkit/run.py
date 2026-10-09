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
from collections import Counter
from contextlib import ExitStack, contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import (box, command_help, config, gate, gc, hand_in, history, host, job as jobs,
               land as landing, notify, orch, record as run_record, retention, status,
               stop, task as taskfile, update, usage, watch, worker, worktrees)
from .harness import FAULT, LIMITED, SPENT, load as harness_plugin, says

DIFF_CAP = 300 * 1024
OUT_CAP = 20 * 1024
GITHUB_BODY_CAP = 60_000         # below GitHub's 65,536-character body limit, including UTF-8
# A transient answer is what a person answers by typing `continue`: the same worker session
# again, after 1, 5, 15, 30 and 60 minutes, then hourly, indefinitely.  The run stays
# `running` throughout, so its session reads `working`, and never ends in `error` for one.
TRANSIENT_BACKOFF = (60, 300, 900, 1800, 3600)
TRANSIENT_HOURLY = 3600
KILL_WINDOW = 60              # a second signal kill inside this many seconds parks the run
SWAP_POLL = 10                # seconds between looks at a harness swap a failed turn waits out
KILLED = {-15: "SIGTERM", -9: "SIGKILL"}   # worker exits by signal, as `subprocess` reports them
# When a refusal says to come back: Codex prints `Try again at Oct 12th, 2026 11:39 PM` in this
# machine's own timezone, and a 429 body carries the same moment as an ISO timestamp.  A clock
# time with no date is not read: on its own it could be minutes ago or a week off, and the
# meters answer that better than a guess would.
TRY_AGAIN_ISO = re.compile(r"try again (?:at|on)\s+"
                           r"(\d{4}-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d)?"
                           r"(?:Z|[+-]\d\d:?\d\d)?)", re.I)
TRY_AGAIN_NAMED = re.compile(r"try again (?:at|on)\s+([A-Za-z]{3,9})\.?\s+(\d{1,2})"
                             r"(?:st|nd|rd|th)?,?\s+(\d{4})(?:\s+at)?,?\s+(\d{1,2}):(\d{2})"
                             r"(?::\d{2})?\s*([AaPp])?\.?[Mm]?\.?", re.I)
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# The files in a worker's out dir that are the harness talking.  prompt.md is what it was told,
# and session_id is bookkeeping; neither is ever evidence of anything the harness said.
NOT_HARNESS = ("prompt.md", "session_id", hand_in.FILE, hand_in.REPORT, hand_in.FINDINGS_FILE)
ANSWER = "final.md"             # and this one arrives as `text`, already read by worker.call
ECHO = 40                       # a prompt is recognised quoted back by this many of its own
                                # first characters -- the role preamble, which is one line and
                                # which no refusal begins with
REFUSAL_CAP = 1000              # a refusal replaces the answer instead of following it, so it is
                                # short; past this many characters what is there is an answer
# A heading distinguishes an answer from the harness's short refusal.
ANSWERED = re.compile(r"^\s{0,3}#{1,6}\s", re.M)
# A record in a harness's event log is that harness reporting a failure when one of its own kind
# fields says so -- Codex ends a refused turn with `turn.failed`, Claude with a `result` whose
# subtype names an error -- or when it carries an error of its own.  Whatever a command or a tool
# printed is cut out of every record first, at any depth: that text is the work's own output,
# quoted inside the record, and a task that greps for the words a refusal uses is not one.
EVENT_KINDS = ("type", "subtype", "kind", "status", "state", "level")
EVENT_FAILED = re.compile(r"error|fail|abort", re.I)
EVENT_OUTPUT = ("aggregated_output", "output", "stdout", "stderr", "command", "content",
                "arguments", "tool_result", "input")
# what a test run, a build or an editor drops next to the work, and no reviewer should ever see
JUNK = ("__pycache__/", "*.pyc", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
        "node_modules/", ".DS_Store", "*.swp")
# what the suites leave inside the checkout when a test is killed mid-way: every sandbox
# tests/smoke.sh and the test_*.py files create there is named under this one prefix, which
# tests/test_leftover_staged_and_sandboxes.py holds every one of them to.  The leftover sweep
# never commits these and the loop removes them before the next turn, whatever the
# repository's .gitignore says.
SANDBOX_PREFIX = ".ak-test-"
# A fix run's check, in a folder of its own: the run directory is the loop's, read-only
# to its turns, and the executor writes this one.
REGRESSION = Path("regression", "regression.sh")


def regression_script(run_dir):
    """A fix run's check: in its folder, or beside the run for one started before it had one."""
    legacy = run_dir / REGRESSION.name
    return legacy if legacy.is_file() else run_dir / REGRESSION
MERGE_METHODS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}
CHECKS_CAP = 60 * 60            # a check suite still running after an hour is not going to finish
CHECKS_POLL = 10
TOOL_CAP = 120                  # seconds allowed for each git or gh attempt
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
# the line a fetch prints for a ref another process holds: the ref moved under it, or git's
# lock on it is held -- not a ref no retry can write, such as a stale name in its way; see
# `fetch`.  `.*`, not `[^']*`: a ref name or a checkout path may hold an apostrophe
REF_LOCKED = re.compile(r"error: cannot lock ref '.*': (?:is at \w+ but expected \w+|"
                        r"Unable to create '.*': File exists\.)")
# what git and gh say when the prompt they wanted was refused; each is a stop, never a wait
PROMPTED = re.compile(r"terminal prompts disabled|could not read (?:Username|Password)|"
                      r"prompts (?:are )?disabled|askpass", re.I)
LIST_CAP = 500                  # files a scratch run's reviewer is shown before it is told the count
PUSH_RIGHTS = ("ADMIN", "MAINTAIN", "WRITE")
FORK_REMOTE = "fork"            # the remote a run adds for its fork; `origin` stays the upstream
PR_PARTS = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")
CLASSIC_CHECKS_QUERY = (
    "query($owner:String!,$name:String!,$branch:String!){repository(owner:$owner,name:$name){"
    "ref(qualifiedName:$branch){branchProtectionRule{requiresStatusChecks "
    "requiredStatusChecks{context app{databaseId}}}}}}")
NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten")   # the hand-back spells the spent budget out
FRONT = re.compile(r"^---\n(.*?)\n---", re.S)
# The front matter lines ak reads; any other name (a typo of `tests:` included) is read by nothing.
FRONT_KEYS = ("tests", "health", "cleanup", "users", "features")
FOLLOWUPS = re.compile(r"^(#+)[ \t]*Follow-ups\b[^\n]*$", re.M | re.I)
NOTES = re.compile(r"^(#+)[ \t]*Notes\b[^\n]*$", re.M | re.I)
BLOCKED_SAME = ("the same checks fail the same way after a fix round: "
                "the task or its checks are wrong")
# What the loop itself adds to a done-when log, in its own words, after the commands have had
# their say: none is a command's output, and reading one as such would make a failure that
# never moved look new every round.  See `run_done_when`, `verify_work` and `final_check`.
LOOP_NOTE = re.compile(r"^(?:Checkout changed during |done-when: stopped after |outside files: "
                       r"|AGENTS\.md (?:is|could not be read|must not|front matter has) )")
# Where a suite, unittest, pytest or TAP names what failed: at the start of the line it says so
# on, long before the tally it ends with.  See `first_failure`.
FAILURE_LINE = re.compile(r"^(?:FAIL(?:ED)?|ERROR|not ok)\b")
QUEUED_GRACE = 30               # old launchers did not record the background child's identity
_RUN_CONTEXT = threading.local()  # job threads export their own depth and slot owner
_DELIVERY_HELD = threading.local()   # the delivery locks this thread is already inside
_PICKUP_START = None    # the installed agentkit this process started on, for in-flight pickup
_PICKUP_HELD = threading.local()   # delivery locks this thread holds or waits for
STALL_RESUME_GRACE = 600        # the tick stopped this loop and its resume is on the way; reap
                                # leaves the record alone until then, and the resume adopts it
RESUME_VISIBLE = 3600           # ak run status names a mid-turn resume in the age column for this long
TURN_ROLES = ("executor", "fixer", "reviewer")   # the steps that are a model's turn to continue


class Stopped(config.Error):
    """A git or gh that ran out of time or was refused the prompt it wanted.

    Not the same as a tool that answered `no`: nothing was learned, so nothing can be decided
    on it, and the run keeps its work for the command that picks it up once the tool works again.
    """


def tool_env():
    """What git and gh are given: this run's environment, with every prompt turned off and the
    seat's name dropped.

    A headless run has no terminal to answer on, so a credential prompt is not a question --
    it is a wait with nobody at the other end of it.

    ak's git and gh speak for no seat: a merge or a push ak runs is ak's own machinery, not a
    seat's hand, wherever it runs from (a background run, a seat's own `ak run merge`, a job).
    Dropping $AGENTKIT_SESSION keeps the tmux and gh shims' seatless premise true by construction
    -- they engage only on a seat's own by-hand call -- so ak's own merge is never refused.
    """
    env = {k: v for k, v in config.child_env().items() if k != config.SESSION_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    run_id = getattr(_RUN_CONTEXT, "state", {}).get("run_id")
    if run_id:
        # A git or gh the loop runs is the run's own: it carries the run's marker, so
        # detached or timeout-surviving descendants die with the run like any child.
        # An inherited marker already comes through child_env; this is the loop's own
        # context, which the loop never exports.
        env[worker.RUN_MARKER] = worker.run_marker(run_id)
    return env


def tool_run(cmd, cwd=None, timeout=None, env=None):
    """(exit code, stdout, stderr) for every git and gh call this module makes, in `tool_env`
    as `env` changes it (None drops a variable).

    Git's fetch, push and ls-remote, and gh get one timeout retry. Other calls stop so their
    callers can recover any unfinished checkout edits. The code is None on timeout;
    a refused prompt gets credential advice, no retry. The run's outcome names the next command.
    """
    timeout = TOOL_CAP if timeout is None else timeout
    # Repeating checkout edits can turn a timeout into an "already in progress" failure.
    args = cmd[3:] if len(cmd) > 1 and cmd[0] == "git" and cmd[1] == "-C" else cmd[1:]
    retry = cmd[0] == "gh" or (cmd[0] == "git" and args and args[0] in ("fetch", "push", "ls-remote"))
    for attempt in range(2):
        try:
            proc = subprocess.run(cmd, cwd=None if cwd is None else str(cwd), capture_output=True,
                                  encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                                  timeout=timeout,
                                  env={name: value for name, value in
                                       {**tool_env(), **(env or {})}.items() if value is not None})
            break
        except subprocess.TimeoutExpired:
            if attempt or not retry:
                tries = " on both attempts" if attempt else ""
                return None, "", (f"`{' '.join(cmd[:3])}` was killed after {timeout:g}s{tries}: "
                                  "the remote did not answer")
            time.sleep(1)
    err = proc.stderr
    if proc.returncode != 0 and PROMPTED.search(proc.stdout + err):
        err = (err.rstrip() + f"\n`{' '.join(cmd[:3])}` asked for a credential it may not ask for: "
               "check `gh auth status` and the remote's credentials by hand")
    return proc.returncode, proc.stdout, err


def stopped(code, text):
    """Did this call stop rather than answer -- out of time, or refused its prompt?"""
    return code is None or (code != 0 and bool(PROMPTED.search(text)))


def stall_minutes_for(run_dir, state):
    """The shared silence limit, preserving the one recorded when this run launched."""
    return state.get("silence_minutes", run_record.SILENCE_MINUTES)


def ignore_time_keys(run_dir, meta, log):
    """Warn once per retired key, including across preflight, launch and resume."""
    path = Path(run_dir) / "log.txt"
    logged = path.read_text(errors="replace") if path.exists() else ""
    for key in ("done_when_minutes", "turn_hours", "stall_minutes"):
        line = f"ignoring {key}: the loop watches for silence"
        if key in meta and line not in logged:
            log(line)


def stall_summary(state):
    """`stalled 2× (done-when: bash tests/smoke.sh), recovered` for a running run with stalls."""
    stalls = state.get("stalls") or []
    if state.get("state") != "running" or not stalls:
        return ""
    step = (stalls[-1].get("step") or "").strip()
    return f"stalled {len(stalls)}× ({step}), recovered" if step else f"stalled {len(stalls)}×, recovered"


def collect_usage(cfg):
    """The usage read every pick of a run starts from, its harnesses asked if they can run.

    A concurrent cache publisher must not abort a run that already owns a slot.
    """
    try:
        read = usage.collect(cfg)
    except FileNotFoundError as exc:
        cache = config.STATE / "usage.json"
        if (exc.filename != str(cache.with_suffix(".tmp")) or
                exc.filename2 != str(cache)):
            raise
        # collect uses a shared temporary filename. Another reader can publish it
        # first; re-read its snapshot through the normal freshness checks.
        # Retry once only: a persistent filesystem failure still propagates.
        read = usage.collect(cfg)
    return usage.readiness(cfg, read)


def handover_executor(state, cfg, reason, dry=(), log=None):
    """Hand a worker turn to the best pair on a provider that refused nothing yet.

    Returns the new executor, or None where none is eligible.  Both roles are re-picked
    as one pair (`best_pair`), so tier beats budget and the pair is always a legal one --
    a reviewer kept from before can be the very model now executing.  A refused provider
    never gets the work back (that is how a handover becomes a circle); its reviewers
    are considered only when no pair forms without them.  Records the move
    in `executor_history` with the reason (`stalled`, `dry`); an attempt that finds nobody
    records nothing, since the same worker carries on. `dry` is every provider that
    already refused this piece of work.
    Later re-picks follow the normal order; this preference applies only at handover.
    """
    current = state.get("executor")
    try:
        current_provider = config.model(cfg, current)["provider"] if current else None
    except config.Error:
        current_provider = None
    refused = set(dry)
    if current_provider is not None:
        refused.add(current_provider)
    new = reviewer = None
    try:
        providers = collect_usage(cfg)
        workers = run_workers(cfg, state)
        reviewers = run_reviewers(cfg, state)
        order = [n for n in ready_order(cfg, providers, workers, log, reviewers=reviewers)
                 if n != current and config.model(cfg, n)["provider"] not in refused]
        review_order = ready_order(cfg, providers, reviewers, role="reviewer")
        pair = best_pair(cfg, order, [n for n in review_order
                                     if config.model(cfg, n)["provider"] not in refused])
        if pair is None:
            pair = best_pair(cfg, order, review_order)
        if pair is not None:
            new, reviewer = pair
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    if new is None:
        return None
    state.setdefault("executor_history", []).append(
        {"at": time.time(), "from": current, "to": new, "reason": reason})
    state["executor"] = new
    state["exec_session"] = None
    if reviewer != state.get("reviewer"):
        state["reviewer"], state["review_session"] = reviewer, None
    return new


def park_stalled(run_dir, state, entry):
    """Park a thrice-stalled run in state `stalled`: resumable via `ak run resume <id>`."""
    run_dir = Path(run_dir)
    stalls = list(state.get("stalls") or [])
    stalls.append(entry)
    state.update(state="stalled", stalls=stalls, finished_at=None, stalled_notified=False,
                 error=f"stalled three times at {entry.get('step')}; parked: "
                       f"ak run resume {run_dir.name}")
    run_record.save_state(run_dir, state)
    try:
        _, body, _ = taskfile.parse_task(run_dir / "task.md")
        cmds = taskfile.done_when(body, run_dir / "task.md")
    except (OSError, config.Error):
        cmds = []
    try:
        write_result(run_dir, state, cmds)
    except (OSError, config.Error, ValueError, KeyError, TypeError):
        pass
    return state


def git(repo, *args, check=True, env=None):
    """The command's stdout, raising on failure unless `check` is off.

    `check=False` tolerates a git that said no, never one that never answered: a timeout, or a
    prompt it was refused, is not an empty result, and reading it as one is how a run loses the
    thing it was about to do.
    """
    code, out, err = tool_run(["git", "-C", str(repo), *args], env=env)
    halted = stopped(code, err)
    if (check or halted) and code != 0:
        raise (Stopped if halted else config.Error)(
            f"git {' '.join(args)} failed in {repo}: {err.strip()}")
    return out.strip()


def git_out(repo, *args, timeout=None, env=None):
    """(exit code, output) -- for the steps whose failure is a result to report, not an exception.

    A stop is never a result: a timeout, or a prompt it was refused, raises Stopped, so no
    caller can route it into conflict handling or read it as an ordinary non-zero exit.
    """
    code, out, err = tool_run(["git", "-C", str(repo), *args], timeout=timeout, env=env)
    if stopped(code, err):
        raise Stopped(f"git {' '.join(args)} stopped in {repo}: {(out + err).strip()}")
    return code, (out + err).strip()


def fetch(repo, *args, check=False, env=None):
    """`git fetch` as `git_out` answers it; `check` raises on a failure as `git` does.

    Every run's worktree shares one repository's refs, so two runs fetching at once race for
    the same remote-tracking ref and the loser's fetch fails on git's ref lock.  That lock
    already put the two in order: the loser goes again at once, until it goes through or
    TOOL_CAP, counted from its first try, is spent (a timed-out call still gets one retry),
    so a passed run is never handed back over another run's fetch.  Any other ref it could
    not write fails the fetch at once as before.
    """
    deadline = time.monotonic() + TOOL_CAP
    code, out = git_out(repo, "fetch", *args, env=env)
    while code != 0 and time.monotonic() < deadline and ref_held(out):
        try:
            code, out = git_out(repo, "fetch", *args, timeout=deadline - time.monotonic(),
                                env=env)
        except Stopped:
            if time.monotonic() < deadline:
                raise       # refused a prompt, which no retry answers
            break           # the limit ran out mid-try: the lock it kept losing is the answer
    if check and code != 0:
        raise config.Error(f"git fetch {' '.join(args)} failed in {repo}: {out}")
    return code, out


def ref_held(out):
    """Did this failed fetch fail only on refs another process holds?

    Every error it printed and every ref it rejected has to be one: a tag it would clobber
    or a stale name beside a lost race is a failure no retry clears.  A `-q` fetch prints no
    rejected ref, so no loop fetch is quiet.
    """
    failed = [line for line in out.splitlines()
              if line.startswith(("error:", "fatal:"))
              or line.strip().startswith("!") and not line.endswith("(unable to update local ref)")]
    return bool(failed) and all(REF_LOCKED.fullmatch(line) for line in failed)


def gh(cwd, *args, timeout=None):
    """(exit code, output); the code is None when the command ran out of time.

    The PR commands are handed the PR's own URL and run from the run directory rather than the
    worktree: outside a checkout `gh pr merge --delete-branch` has no local branch to switch
    away from, and deleting the branch out from under the run's own worktree is not what it means.
    """
    code, out, err = tool_run(["gh", *args], cwd=cwd, timeout=timeout)
    return code, (out + err).strip()


def project_env(repo):
    """What git's environment changes to work on the checkout at `repo` and nothing else, None
    for a variable it drops (`tool_run`).  GIT_DIR names the checkout's own `.git`, so git looks
    nowhere else: not in a parent directory's repository when that `.git` was moved away or is
    none (git fails instead), not where an inherited GIT_DIR points.  The other variables git
    keeps for one repository are dropped, as git drops them entering a submodule."""
    code, out, _err = tool_run(["git", "rev-parse", "--local-env-vars"])
    return {**dict.fromkeys(out.split() if code == 0 else []),
            "GIT_DIR": os.path.join(os.path.abspath(repo), ".git")}


def agents_body(repo, ref):
    """The body of the AGENTS.md committed at `ref` in `repo`, front matter removed: what each
    worker's prompt carries of its repository, and each seat's rulebook of its project.

    Read from git, never a checkout's file: the rules are what was merged, not what one checkout
    holds or one piece of work is changing.  "" where there is none, where it is a link -- its
    text is a path, not rules (`rules_check` refuses one) -- or where it cannot be read.
    """
    if not repo or not ref:
        return ""
    env = project_env(repo)
    try:
        listed = git(repo, "ls-tree", ref, "--", "AGENTS.md", check=False, env=env).split()
        # the blob the listing names, never `ref` read twice: a fetch between the two reads
        # could put a link where the listing saw a file
        text = (git(repo, "cat-file", "blob", listed[2], check=False, env=env)
                if listed and listed[0].startswith("100") else "")
    except Exception:
        return ""
    match = FRONT.match(text)
    return (text[match.end():] if match else text).strip()


def repo_rules(wt, ref):
    """The body of the repository's AGENTS.md at `ref` (`agents_body`), for every worker prompt.

    ak reads only its front matter itself, and a harness loads the body on its own terms
    (some never, some only beside no file of their own), so without this each brand
    worked to different rules.  Read at the base commit, never the checkout: the work
    under review cannot rewrite the rules it is judged by.
    """
    text = agents_body(wt, ref)
    if not text:
        return ""
    return ("\n\n## Repository AGENTS.md\n"
            "The repository's own instructions, as on the base commit. Where they differ "
            f"from the rest of this prompt, the rest of this prompt wins.\n\n{text}\n")


def first_command(cmd):
    """The shell line up to its first output plumbing: `2>&1`, `|`, `&&`, `||` or `;`.

    A task ends its done-when with the suite's bare command while the repository declares
    the same command with its log plumbing, and the two are the same run: this is the text
    before the first plumbing operator outside any quotes and outside any `$(...)`, so a
    pipe inside a substitution is the command's own argument, never the plumbing.
    """
    single = double = False
    escaped = False
    depth = 0
    i, end = 0, len(cmd)
    while i < end:
        ch = cmd[i]
        if escaped:
            escaped = False
        elif ch == "\\" and not single:
            escaped = True
        elif ch == "'" and not double:
            single = not single
        elif ch == '"' and not single:
            double = not double
        elif not single and not double:
            if ch == "$" and cmd[i + 1:i + 2] == "(":
                depth += 1
                i += 1
            elif ch == ")" and depth:
                depth -= 1
            elif not depth:
                if cmd.startswith("2>&1", i) or ch in "|;":
                    return cmd[:i]
                if ch == "&" and cmd[i + 1:i + 2] == "&":
                    return cmd[:i]
        i += 1
    return cmd


def declared_suite(wt, target=None, *, ref=None):
    """The target's `tests:` suite at a pinned ref or `origin/<target>`, else the checkout's.

    A change cannot loosen its own landing checks; its line applies after it merges.
    """
    if not ref and target:
        ref = target if target.startswith("origin/") else f"origin/{target}"
    suite = declared_at(wt, ref, "tests") if ref else None
    return suite or declared(wt, "tests")


def with_suite(cmds, wt, target=None, *, landing=True, ref=None):
    """Task checks, plus the declared `tests:` suite as a `# once` line when landing.

    A repository names its full suite once, in AGENTS.md, rather than every task writing it
    into every round: it runs once at landing on the commit to be merged.  A task line that is
    the same command is that line, so it runs once, not twice;
    so is a line that is the suite's bare first command, without its output plumbing,
    whitespace aside.  A line already marked `# once` keeps today's meaning: only one
    identical to the suite is that line. Without landing, keep every task check
    as an ordinary round check, without adding the declared suite.
    """
    if not landing:
        return [taskfile.split_once(cmd)[0] for cmd in cmds]
    suite = declared_suite(wt, target, ref=ref)
    if not suite:
        return cmds
    targets = {" ".join(suite.split())}
    first = " ".join(first_command(suite).split())
    if first:
        targets.add(first)
    kept = []
    for cmd in cmds:
        bare, once = taskfile.split_once(cmd)
        if once:
            if bare != suite:
                kept.append(cmd)
        elif " ".join(bare.split()) not in targets:
            kept.append(cmd)
    return kept + [f"{suite}  # once"]


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    return slug or "task"


def repo_line(meta, task_path):
    """The path a task's `repo:` names, `~` expanded, or None when it names none.

    `~name` for a user this host has no home for cannot be expanded, and pathlib says so with a
    RuntimeError nothing up the stack expects: it is the task's own error, named here.
    """
    named = meta.get("repo") or ""
    if named.lower() in ("", "none"):
        return None
    try:
        return Path(named).expanduser()
    except RuntimeError:
        raise config.Error(f"{task_path}: repo {named} names a home directory this host "
                           "does not have") from None


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


def default_base(repo, log):
    """The repository's default branch -- what `origin/HEAD` points at -- as `origin/<branch>`.

    Not the current branch: a run started while something else is checked out still belongs on,
    and merges into, the branch the repo calls default.
    """
    for attempt in (1, 2):
        head = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD",
                   check=False)
        if head:
            return head
        if attempt == 1:
            # a clone made before origin had a HEAD, or a remote added by hand: ask origin once
            git(repo, "remote", "set-head", "origin", "--auto", check=False)
    current = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    log(f"WARN {repo} has no origin/HEAD; basing this run on the current branch {current}")
    return current


def ready_order(cfg, providers, workers=None, log=None, **kwargs):
    """`usage.pick_order` over the workers whose harness can run a turn here.

    Every pick a run makes -- executor, reviewer, spare, handover, the fixer's -- comes
    through here.  A worker whose harness is not installed or not logged in is left out
    before any budget rule reads the list, so a subscription nobody can run keeps no payg
    provider out; `log`, on the one call of a pick that gives a role, says so in one line.
    """
    skip = {}
    if getattr(providers, "harnesses", None):
        skip = {name: usage.unready(cfg, name, providers) for name in config.offered(cfg)}
        skip = {name: why for name, why in skip.items() if why}
    if log and skip:
        listed = (config.reviewers(cfg) if kwargs.get("role") == "reviewer"
                  else config.workers(cfg)) if workers is None else workers
        for name in listed:
            if name in skip:
                log(f"skipped {name}: {skip[name]}")
    return usage.pick_order(cfg, providers, workers, skip=skip, **kwargs)


def refuse_unready(cfg, providers, name):
    """A model named outright whose harness cannot run here is refused, in one sentence.

    Not on an answer an install or revert of that harness overlapped: its command was missing
    then, so the swap is waited out and the harness asked again, as a failed turn's is.
    """
    why = usage.unready(cfg, name, providers)
    harness = config.model(cfg, name)["harness"]
    if why and update.swap_end(harness, providers.asked_at, time.time()):
        while (end := update.swap_end(harness, providers.asked_at, time.time()) or 0) > (
                now := time.time()):
            time.sleep(min(SWAP_POLL, end - now))
        why = usage.harness_unready(harness)
    if why:
        raise config.Error(f"{name} cannot run here: {why}")


def refuse_outside_group(cfg, name, group, role):
    if name:
        config.model(cfg, name)
        if group is not None and name not in group:
            raise config.Error(f"{name!r} is not a {role} of this run "
                               f"({role}s: {', '.join(group)})")


def pick_models(cfg, providers, want_exec, want_review, log, *, resuming=False, quiet=False,
                repo=None, workers=None, reviewers=None):
    """Pick each role within its launch list, refusing an explicit name outside that group."""
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    if reviewers is not None:
        refuse_outside_group(cfg, want_review, reviewers, "reviewer")
    order = ready_order(cfg, providers, workers, None if want_exec and want_review else log,
                        quiet=quiet, repo=repo, reviewers=reviewers)
    session = config.active_session(cfg)
    allowed = workers if workers is not None else (session["workers"] if session else None)
    if want_exec:
        config.model(cfg, want_exec)
        # Legacy callers without a bound list retain the default orchestrator on resume.
        admitted = (workers is None and session
                    and session["orchestrator"] == want_exec == cfg["defaults"]["orchestrator"]
                    and (resuming or want_exec in order))
        if allowed is not None and want_exec not in allowed and not admitted:
            where = f"session {session['name']!r}" if session else "this run"
            raise config.Error(f"{want_exec!r} is not a worker of {where}")
        refuse_unready(cfg, providers, want_exec)
    elif not order:
        raise QuotaDry("every worker has a gate meter at 100% used")
    executor = want_exec or order[0]
    if want_review:
        config.model(cfg, want_review)
        if reviewers is None and allowed is not None and want_review not in allowed:
            where = f"session {session['name']!r}" if session else "this run"
            raise config.Error(f"{want_review!r} is not a worker of {where}")
        refuse_unready(cfg, providers, want_review)
        reviewer = want_review
        if want_exec is None:
            # A named reviewer takes the best executor for it: tier first, then
            # budget, through the same pair choice every automatic pick uses.
            pair = best_pair(cfg, order, [reviewer])
            if pair is not None:
                executor = pair[0]
    else:
        review_order = ready_order(cfg, providers, reviewers if reviewers is not None else workers,
                                   role="reviewer", quiet=quiet, repo=repo)
        pair = best_pair(cfg, [want_exec] if want_exec else order, review_order)
        if pair is None:
            where = f" for executor {want_exec}" if want_exec else ""
            raise QuotaDry("no eligible reviewer: no worker with budget is left to review"
                           f"{where}; waiting for review")
        executor, reviewer = pair
    review_providers(cfg, executor, reviewer)
    return executor, reviewer


def pair_refusal(cfg, providers, workers, want_exec=None, want_review=None, reviewers=None):
    """The one sentence a launch is refused with when no worker can run, or None.

    Budgets are left out: a spent meter refills, and a run waiting on one is parked for a
    reason.  Nothing refills a harness that is not installed or not logged in, so a launch
    left with no runnable executor or reviewer is refused instead of parking on a review
    nobody can give.  One runnable worker is enough to launch: it reviews its own work,
    marked self-reviewed.  Legacy explicit names remain unbound; only automatic candidates
    fall back to the configured worker selection.
    """
    listed, review_list = config.role_groups(cfg, workers, reviewers)
    bound_exec = listed is not None
    bound_review = review_list is not None or bound_exec
    listed = config.workers(cfg) if listed is None else listed
    review_list = listed if review_list is None else review_list
    skipped = {name: usage.unready(cfg, name, providers) for name in [*listed, *review_list]}
    ready = [name for name in listed if not skipped[name]]
    reviews = [name for name in review_list if not skipped[name]]
    if want_exec:
        ready = [name for name in ready if name == want_exec] if bound_exec else [want_exec]
    if want_review:
        reviews = ([name for name in reviews if name == want_review]
                   if bound_review else [want_review])
    if any(reviewer_order(cfg, name, reviews) for name in ready):
        return None
    why = "; ".join(f"{name}: {reason}" for name, reason in skipped.items() if reason)
    missing = []
    if not ready:
        missing.append(f"workers {', '.join(listed)}")
    if not reviews:
        missing.append(f"reviewers {', '.join(review_list)}")
    if not missing:  # an unknown explicit name refuses below; name both lists
        missing = [f"workers {', '.join(listed)}",
                   f"reviewers {', '.join(review_list)}"]
    return (f"none of the {' and '.join(missing)} can run here"
            + (f" ({why})" if why else "")
            + "; log in to another harness or add another model to the groups")


def review_providers(cfg, executor, reviewer):
    """The (executor, reviewer) providers.  Any reviewer may review any executor --
    another company is only preferred, by reviewer_order, never required."""
    executed = config.model(cfg, executor) if executor else None
    reviewed = config.model(cfg, reviewer)
    return (executed["provider"] if executed else None), reviewed["provider"]


def same_model(cfg, first, second):
    """Whether two worker names are the same model: the same name, or the same provider
    and model id under another name -- the `sonnet-2` the `c` screen adds an already
    configured model as at another effort."""
    if not first or not second:
        return False
    if first == second:
        return True
    try:
        one, two = config.model(cfg, first), config.model(cfg, second)
    except config.Error:
        return False
    return one["provider"] == two["provider"] and one["model"] == two["model"]


def reviewer_order(cfg, executor, order):
    """Another company's models, then the executor's company's, then its own; budget order
    within each tier.  A model tends to miss the mistakes it makes, so its own review is
    the last choice -- but only a choice, never a refusal: one worker reviews itself."""
    try:
        executed = config.model(cfg, executor) if executor else None
    except config.Error:
        return []
    cross, same, own = [], [], []
    for name in order:
        try:
            reviewed = config.model(cfg, name)
        except config.Error:
            continue
        if executed is None or reviewed["provider"] != executed["provider"]:
            cross.append(name)
        elif name == executor or reviewed["model"] == executed["model"]:
            own.append(name)
        else:
            same.append(name)
    return cross + same + own


def pair_tier(cfg, executor, reviewer):
    """This pair's tier: 0 another company, 1 the executor's company, 2 its own model.

    None when either name is unknown: no pick weighs a pair it cannot name.
    """
    if same_model(cfg, executor, reviewer):
        return 2
    try:
        executed = config.model(cfg, executor)["provider"]
        reviewed = config.model(cfg, reviewer)["provider"]
    except config.Error:
        return None
    return 0 if executed != reviewed else 1


def best_pair(cfg, executors, reviewers, allow_self=True):
    """The pair every automatic pick takes: tier first, then executor budget, then reviewer.

    Both lists are already budget-ordered, so the first pair in tier order wins: a review
    by another company beats one by the executor's company, which beats the executor
    reviewing itself.  A first pick that stopped at the cheapest executor would keep a
    self-review while a cross-company pair is ready.  None when no pair forms -- or only
    a self-review when `allow_self` is off, which a flake waits out.
    """
    best, key = None, None
    for ei, executor in enumerate(executors or []):
        for ri, reviewer in enumerate(reviewers or []):
            tier = pair_tier(cfg, executor, reviewer)
            if tier is None or (tier == 2 and not allow_self):
                continue
            found = (tier, ei, ri)
            if key is None or found < key:
                key, best = found, (executor, reviewer)
    return best


def self_reviewed(state, cfg=None):
    """Whether the executor's own model reviews this run: the recorded review's pair
    where a round was reviewed, else the current one.  A seat's own PR has no executor,
    so its writer -- the seat's orchestrator -- counts as the executor.  `cfg` tells an
    alias (the same provider and model id under another name) from another model;
    without it only the same name counts."""
    evidence = state.get("review") if isinstance(state.get("review"), dict) else {}
    reviewer = evidence.get("reviewer") or state.get("reviewer")
    executor = evidence.get("executor")
    if executor is None:
        executor = state.get("own_orchestrator") if state.get("own_pr") else state.get("executor")
    if not reviewer or not executor or reviewer == executor:
        return bool(reviewer and reviewer == executor)
    return cfg is not None and same_model(cfg, executor, reviewer)


def review_pass(state, cfg):
    """A verdict alone (including a legacy PASS) is not evidence of a successful review."""
    evidence = state.get("review")
    if (state.get("review_pr") and state.get("own_pr") and isinstance(evidence, dict)
            and evidence.get("skipped")):
        # the seat's own wording, its review skipped for exactly the commit it was judged on
        return (state.get("verdict") == "PASS" and evidence.get("verdict") == "PASS"
                and all(evidence.get(key) for key in ("head_sha", "tree_sha")))
    if state.get("verdict") != "PASS" or not isinstance(evidence, dict):
        return False
    if state.get("repo") and not all(evidence.get(key) for key in ("head_sha", "tree_sha")):
        return False
    if (evidence.get("returncode") != 0 or evidence.get("verdict") != "PASS"
            # a reviewed PR whose repository declares no suite ran nothing: None, not True
            or not (evidence.get("done_when") is True
                    or (state.get("review_pr") and evidence.get("done_when", False) is None))
            or evidence.get("executor") != state.get("executor")
            or not evidence.get("reviewer") or evidence["reviewer"] != state.get("reviewer")
            or not evidence.get("reviewer_provider")):
        return False
    if not state.get("executor"):
        if not state.get("review_pr") or evidence.get("executor_provider") is not None:
            return False
    elif not evidence.get("executor_provider"):
        return False
    try:
        providers = review_providers(cfg, state.get("executor"), state["reviewer"])
    except config.Error:
        return False
    if providers != (evidence.get("executor_provider"), evidence["reviewer_provider"]):
        return False
    if state.get("own_pr"):
        own = state.get("own_orchestrator")
        if not own:
            return False
        try:
            review_providers(cfg, own, state["reviewer"])
        except config.Error:
            return False
    return True


def invalidate_saved_pass(state, cfg, log):
    """Recover old verdicts by reviewing the saved work, even if its task rounds are spent."""
    if state.get("verdict") != "PASS" or review_pass(state, cfg):
        return
    log("WARN saved PASS lacks eligible review or commit verification evidence; reviewing again")
    entries = state["round_summaries"]
    rnd = len(entries) + 1
    state.update(verdict=None, review=None,
                 review_pending={"round": rnd, "summary": entries[-1]["summary"] if entries else ""},
                 rounds=max(state["rounds"], rnd))


class Exhausted(Exception):
    pass


class QuotaDry(Exhausted):
    """Out of budget on every eligible provider: wait for a window, then resume."""


class Dead(Exception):
    """The executor outlived its retries: not a FAIL, because nothing was ever judged.

    Kept for the merge pipeline's older receipts; a transient answer never raises it now --
    the same session is resumed indefinitely instead, so there is nothing left to outlive.
    """


class Killed(Exception):
    """A worker turn killed by signal twice within a minute: a person must look.

    Not a death on the provider and not a FAIL -- nothing was executed and nothing was
    judged -- so the run parks as an interruption, resumable, reading `needs you` with the
    signal for a reason.  The session the killed turn left behind travels with it, so the
    resume continues it rather than opening a new one.
    """

    def __init__(self, message, session=None):
        super().__init__(message)
        self.session = session


class NotNeeded(Exception):
    """A follow-up's executor found no work left, before any checks or review."""


class Blocked(Exception):
    """The task cannot be done as written, so the run ends here and says why.

    Not a FAIL: a FAIL is a verdict on work, and there is no work to judge -- either a worker
    ended its turn saying the task contradicts itself, or two fixer rounds left the same
    checks failing the same way, which is the checks being wrong rather than the code.  There
    is nothing for another round or a reviewer to add, and nothing a resume could spend, so
    the orchestrator that wrote the task hears the sentence and writes a new one.  `section`
    is the `## Blocked` section result.md carries.
    """

    def __init__(self, reason, section):
        super().__init__(reason)
        self.section = section


class CannotRun(Blocked):
    """The harness never ran the turn, and its stderr line says why: see `cannot_run`.

    Not a provider fault, so never one of the transient waits -- no wait installs a harness,
    teaches it a flag or logs it in -- and not a FAIL, since nothing was judged.  The work
    goes to another provider first, the way a spent window's does; with nobody left to take
    it, the run is blocked on that line, which is what this is wherever nobody catches it.
    """

    def __init__(self, name, line):
        self.detail = f"cannot run: {line}"
        super().__init__(f"{name} {self.detail}", f"## Blocked\n\n{name} {self.detail}")


class RanDry(Exception):
    """This worker's provider refused it.

    Not a death and not a FAIL -- nothing was executed and nothing was judged -- so the work
    goes to another provider rather than being retried where it cannot run.  The refusal and
    the dead session travel with it, so the post-mortem still has both.
    """

    def __init__(self, name, mark, code, text, session, until, message, quota):
        super().__init__(f"{name} refused: {message}")
        self.name, self.mark, self.code, self.text = name, mark, code, text
        self.session, self.until = session, until
        self.message, self.quota = message, quota
        # and what a role parks with when no one else can take it: a window waits for its refill
        self.why, self.ending = ("ran dry", QuotaDry) if quota else ("refused", Exhausted)
        self.detail = f"refused: {message}"

    def remember(self, state):
        """Remember a short refusal retry, or clear one when a quota window is parked."""
        if self.quota:
            state.pop("refusal_retry", None)
        else:
            state["refusal_retry"] = {"model": self.name, "at": self.until}


class TransientHandover(Exception):
    """This worker failed on the provider twice in a row and another took the role.

    Not a death and not a FAIL -- nothing was executed and nothing was judged -- so the
    turn goes to the next worker the way a spent window's does, and the failed provider
    joins only that round's refused set.  The handover itself already happened inside
    `call_retrying`'s `handover` callback; this only unwinds to the turn loop so it can
    restart the role with the new worker, a fresh session and a fresh out dir.
    """

    def __init__(self, before, new, session, detail):
        super().__init__(f"{before} failed on the provider twice; handed to {new}: {detail}")
        self.before, self.new, self.session, self.detail = before, new, session, detail


def killed_word(code):
    """How a worker exit by signal reads: `killed (SIGTERM)`, never an exit code.

    None for any other exit: a worker that exited by code said what the code says.
    """
    if code is None or code >= 0:
        return None
    return f"killed ({KILLED.get(code, f'SIG{-code}')})"


def transient_delay(attempt):
    """How long the attempt-th transient retry waits: 1, 5, 15, 30, 60 minutes, then hourly."""
    if attempt <= len(TRANSIENT_BACKOFF):
        return TRANSIENT_BACKOFF[attempt - 1]
    return TRANSIENT_HOURLY


def transient(code, text):
    """Why this call looks like a provider failure rather than an answer, or None.

    Only a non-zero exit qualifies: a worker that exited 0 said what it meant to say, however
    much of an API error it quotes back while saying it.  A kill is not one either: it reads
    as the signal, through `killed_word`, and takes its own road.  An empty final.md gets
    here only once `cannot_run` has found no harness fault on stderr.  Anything else the
    harness said is for its own words to read (`Harness.failure`), and `call_retrying` asked
    them first; a final.md the model answered in says nothing here.
    """
    if code == 0 or killed_word(code):
        return None
    return f"exited {code} with an empty final.md" if not text.strip() else None


def cannot_run(code, text, stderr, out_dir=None, harness=None):
    """The stderr line saying this harness never ran the turn at all, or None.

    Only for a non-zero exit, not a kill, that left final.md empty: whatever answered is an
    answer, and a kill takes its own road.  The line holds one of the harness's `faults`
    words (`Harness.failure`), and no outage word stands anywhere beside it: that is waited
    out instead.
    `opencode.sh: opencode is not installed` is the case -- it was retried like a 500,
    hourly, for as long as nobody installed it.

    Exit 126 or 127 with an empty event stream never ran either: the shell refused the
    exec -- `Argument list too long` for a prompt over one argument's limit -- and no
    wait starts what cannot start, whatever else stderr says.  The role goes to the next
    worker, as a refused one does.
    """
    if code == 0 or killed_word(code) or text.strip():
        return None
    if code in (126, 127) and out_dir is not None and worker.said_nothing(out_dir):
        line = next((" ".join(line.split()) for line in stderr.splitlines() if line.strip()),
                     "")
        return line or f"exited {code} with an empty event stream"
    outcome, word = harness_plugin(harness).failure(stderr, ran=False)
    if outcome != FAULT:
        return None
    return next((" ".join(line.split()) for line in stderr.splitlines() if says(line, word)),
                None)


def transient_wait(out_dir, delay):
    """Sleep out one transient wait, with the run's record saying until when.

    The tick reads a run's silence off its newest write, and a wait writes nothing: the
    30-minute wait read as a 20-minute silence, the tick killed the loop, its resume began the
    waits again at one minute, and the third such stall parked a run whose provider was only
    down.  `transient_wait` on the record, with this loop's pid, is where `watch.stall_clock`
    starts that clock instead.  A turn with no run record above its round (a direct caller's)
    only sleeps.
    """
    run_dir = Path(out_dir).parent.parent
    if (run_dir / "run.json").is_file():
        try:
            with run_record.recovery_lock(run_dir):
                state = run_record.read_state(run_dir)
                if state and state.get("state") == "running":
                    state["transient_wait"] = {"until": time.time() + delay, "pid": os.getpid()}
                    run_record.save_state(run_dir, state)
        except OSError:
            pass            # an unwritten mark costs a stall rung, never the wait itself
    step = history.close_step(run_dir.name)     # the wait is no step's work
    time.sleep(delay)
    history.open_step(run_dir.name, step)


def shell_foreground_note():
    """Keep long commands attached to the turn that must report their result."""
    return ("Run long commands, tests included, in the foreground and wait for them; "
            "a turn that ends with a command still running in the background is not finished.")


FINISH_IN_FOREGROUND = ("The command you left in the background was stopped when your turn ended. "
                        "Run it in the foreground now, wait for it, and report.")
NO_VERDICT_ASK = ("Your previous turn ended without ak hand-in done. Review the diff now, "
                  "hand in any remaining findings or follow-ups with ak hand-in, then run "
                  "ak hand-in done. Earlier records have been carried into this turn. "
                  "Do not start commands you will not wait for in this turn.")
NO_CLOSING_ASK = ('Your previous turn ended without a closing hand-in. Close it now with '
                  'ak hand-in done, ak hand-in blocked "<why>" or ak hand-in not-needed "<why>" '
                  'as instructed. Earlier records have been carried into this turn. '
                  'Do not start commands you will not wait for in this turn.')


def turn_unfinished(out_dir):
    """Did this turn end with a command still running in the background -- unfinished, then.

    Either the harness says so on stderr (`Background tasks still running`, which Claude
    prints when it stops a turn over background work) or its event log's last
    `background_tasks_changed` event still lists a task -- Claude 2.1.263 streams those as
    `{"type": "system", "subtype": "background_tasks_changed", "tasks": [...]}`, and only the
    last one counts, so a list the turn emptied before ending is finished.  A missing or
    unreadable file is no signal: the turn counts as finished.
    """
    try:
        if "Background tasks still running" in (Path(out_dir) / "stderr.log").read_text(
                errors="replace"):
            return True
    except OSError:
        pass
    try:
        lines = (Path(out_dir) / "events.jsonl").read_text(errors="replace").splitlines()
    except OSError:
        return False
    last = None
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if (event.get("type") == "background_tasks_changed"
                or event.get("subtype") == "background_tasks_changed"):
            last = event
    if last is None:
        return False
    return bool(last.get("tasks", last.get("background_tasks")))


def tail(path, cap=OUT_CAP):
    """The last `cap` bytes of a file, as text; an event log can be far too big to read whole."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - cap))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def answered(text):
    """Did the worker answer here, or did the harness put a refusal where the answer belongs?

    A refusal takes the answer's place rather than following it: it is the whole of what the
    harness managed to say, and it is short. Legacy text answers carry a heading or length
    of their own; closing hand-in records establish an answer separately.
    """
    return len(text) > REFUSAL_CAP or bool(ANSWERED.search(text))


def without_output(node):
    """`node` with every command's and tool's output cut out of it, at any depth."""
    if isinstance(node, dict):
        return {k: without_output(v) for k, v in node.items() if k not in EVENT_OUTPUT}
    if isinstance(node, list):
        return [without_output(item) for item in node]
    return node


# Re-encoded, a control character in a record's text -- a line break, a tab -- reads as an
# escape (`\n`, `\t`, `\u000b`) that runs into the word after it, which then never stands on
# its own; so do characters outside ASCII unless they are written as they are.  With every
# control character and line separator a space and the rest written as is, the only escapes
# left are `\"` and `\\`, which end in neither a letter nor a digit, and a record stays one
# line wherever `str.splitlines` would break it.
ONE_LINE = {code: " " for code in (*range(0x20), *range(0x7f, 0xa0), 0x2028, 0x2029)}


def one_line(node):
    """`node` with every control character and line separator in its text a space, at any
    depth."""
    if isinstance(node, dict):
        return {k: one_line(v) for k, v in node.items()}
    if isinstance(node, list):
        return [one_line(item) for item in node]
    return node.translate(ONE_LINE) if isinstance(node, str) else node


def is_failure(node):
    """Does this record say of itself that it is a failure, at any depth?"""
    if isinstance(node, list):
        return any(is_failure(item) for item in node)
    if not isinstance(node, dict):
        return False
    for key, value in node.items():
        if key in ("error", "is_error") and value not in (None, False, "", [], {}):
            return True
        if key in EVENT_KINDS and isinstance(value, str) and EVENT_FAILED.search(value):
            return True
    return any(is_failure(value) for value in node.values())


def is_terminal(node, terminal):
    """Is this record the run's own terminal report, whatever its kind calls it?

    The kind is the harness's own: `[stall] terminal` in adapters/<harness>.toml names it,
    and it is read at any depth the way `is_failure` reads a failure.
    """
    if not terminal:
        return False
    if isinstance(node, list):
        return any(is_terminal(item, terminal) for item in node)
    if not isinstance(node, dict):
        return False
    for key, value in node.items():
        if key in EVENT_KINDS and value == terminal:
            return True
    return any(is_terminal(value, terminal) for value in node.values())


def record_text(node):
    """Every string a terminal record says, in one place, for the answer-shape test.

    Kind discriminators are not what it says: they name the record, and a long one of those
    must never read as an answer on its own.
    """
    if isinstance(node, dict):
        return "\n".join(record_text(value) for key, value in node.items()
                          if key not in EVENT_KINDS)
    if isinstance(node, list):
        return "\n".join(record_text(item) for item in node)
    return node if isinstance(node, str) else ""


def failures(chunk, terminal, terminal_only=False, handed_in=False):
    """The failure records of an event log, each minus the output of the work it quotes, its
    text's control characters read as spaces and the rest as written.

    The output goes first, so a command that failed while printing the words a refusal uses
    contributes its exit code and nothing else.  The run's terminal record is kept beside
    them, failure or not: with an empty final.md it is the only place a refusal can be, and
    the adapter may never have filled final.md at all.  A record that declares itself a
    failure is the harness speaking, whatever shape its text has; the answer-shape test
    decides only a terminal record that declares none, where an answer-shaped text is the
    worker's answer and never a refusal.  With ``terminal_only`` (the zero-exit path), only a
    terminal record's explicit failure or unanswered text is kept, so an earlier stream warning
    cannot discard an answer. Handed-in records establish an answer without a text-shape test;
    explicit terminal errors still speak. A line that is not a JSON record says nothing here.
    """
    records = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = without_output(json.loads(line))
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if terminal_only:
            terminal_record = is_terminal(record, terminal)
            failure = (terminal_record
                       and (is_failure(record)
                            or (not handed_in and not answered(record_text(record)))))
        else:
            failure = (is_failure(record)
                       or (is_terminal(record, terminal)
                           and not handed_in and not answered(record_text(record))))
        if failure:
            records.append(json.dumps(one_line(record), ensure_ascii=False))
    return records


def harness_said(out_dir, text, harness, failures_only=False):
    """What the harness itself said this attempt, with the work's own output kept out of it.

    Three sources, because a refusal lands in a different one on each harness.  The answer --
    Claude's and Muse's refusals arrive there -- but only where nothing answered, because a
    refusal replaces an answer instead of following one.  `stderr.log`, which is the harness's
    own diagnostics and not anywhere a command's output goes.  And the event log, where
    Codex's refusal arrived while final.md stayed empty: every failure record, and the run's
    terminal record -- `[stall] terminal` in adapters/<harness>.toml names its kind -- whether
    or not that kind names a failure, each stripped of what the work printed: a task that
    greps for the words a refusal uses, or a test that prints them, is the work talking and
    never the provider.  With ``failures_only`` (the exit-zero path), only a terminal refusal
    event or unanswered terminal record is read and stderr is ignored, because a harness may
    log a retried warning before a successful answer.  The prompt is not read at all, nor any
    line quoting it back.
    """
    out_dir = Path(out_dir)
    try:
        with (out_dir / "prompt.md").open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        first = ""
    # up to the first quote or backslash: past those an event log's own JSON escaping means the
    # prompt is no longer in it character for character, and the marker would never match
    echo = first.split('"')[0].split("\\")[0].strip()
    echo = echo if len(echo) >= ECHO else ""
    submitted = hand_in.read(out_dir / hand_in.FILE)
    # Successful turns with a record file use it even when the model forgot to hand in anything.
    # An unfinished, failed call may still contain a real provider error in its final text.
    handed_in = submitted is not None and (submitted.closing is not None or failures_only)
    if failures_only and not handed_in and answered(text):
        return ""
    terminal = watch.terminal(harness)
    parts = [] if failures_only or handed_in or answered(text) else [text]
    for path in sorted(out_dir.glob("*")):
        if path.name in NOT_HARNESS or path.name == ANSWER or not path.is_file():
            continue
        chunk = tail(path)
        if path.suffix == ".jsonl":
            parts += failures(chunk, terminal, terminal_only=failures_only, handed_in=handed_in)
        elif not failures_only:
            parts.append(chunk[-REFUSAL_CAP:])
    return "\n".join(line for part in parts for line in part.splitlines()
                      if line.strip() and not (echo and echo in line))


def ran_dry(code, said, harness, refusal=False):
    """The harness's own word for a spent provider window in this exit, or None.

    They come from the harness package's shared `[stall] quotas` beside the adapter's own,
    read off a seat's screen the same way, each a whole word (`Harness.failure`);
    a LIMITED one parks a worker's account as a SPENT one does.
    A non-zero exit is as required here as it is for `transient`, because a worker that exited
    0 said what it meant to say.  The scoped terminal refusal path may pass ``refusal`` for an
    exit-zero turn that never answered.
    """
    if code == 0 and not refusal:
        return None
    outcome, word = harness_plugin(harness).failure(said)
    return word if outcome in (SPENT, LIMITED) else None


def try_again_at(said):
    """The moment a refusal named as the one to come back at, as an epoch, or None."""
    match = TRY_AGAIN_ISO.search(said)
    if match:
        try:
            return datetime.fromisoformat(match.group(1).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    match = TRY_AGAIN_NAMED.search(said)
    if not match:
        return None
    month, day, year, hour, minute, half = match.groups()
    if month[:3].lower() not in MONTHS:
        return None
    hour, half = int(hour), (half or "").lower()
    if half == "p":
        hour = hour % 12 + 12
    elif half == "a":
        hour %= 12
    try:
        return datetime(int(year), MONTHS.index(month[:3].lower()) + 1, int(day), hour,
                        int(minute)).timestamp()
    except ValueError:
        return None


def resume_failed(out_dir, killed, text):
    """A resume the harness ended at once, with nothing streamed and nothing answered.

    A silence kill ran and was stopped; this one never started. The Codex session that
    exited before its first byte after a host freeze is the case, and retrying that id
    spends the transport attempts on a conversation that will not come back.
    """
    if killed or (text or "").strip():
        return False
    return worker.said_nothing(out_dir)


def note_turn_meters(cfg, name, out_dir, account):
    """The meters the turn in `out_dir` reported about the account it ran on are the reading.

    Best effort and never the turn's failure: a harness that says nothing leaves the
    endpoint's reading alone.
    """
    try:
        entry = config.model(cfg, name)
        meters = harness_plugin(entry["harness"]).turn_meters(out_dir)
    except (config.Error, OSError, ValueError, TypeError, AttributeError):
        return
    if not meters:
        return
    try:
        usage.record_turn_meters(cfg, entry["provider"], meters, account)
    except (config.Error, OSError, ValueError, TypeError, AttributeError, KeyError):
        pass


def call_retrying(cfg, name, body, workspace, out_dir, role, session, log, limit=None,
                  fresh_body=None, resume_note=None, handover=None, previous=None, findings=None):
    """worker.call, retried while the harness keeps dying on the provider instead of the task.

    Returns (code, text, session, dead): `dead` stays False -- a transient answer is resumed
    indefinitely now, so there is nothing left to give up on.  A retry resumes the session
    the dead attempt left behind, if any, and gets its own out dir, so the failed attempt's
    stderr.log survives for the post-mortem.  A resume that exits at once with no output is
    not one of those retries: that id is abandoned after the first such exit, and the role
    continues in a fresh conversation (`fresh_body` when the caller has the original prompt,
    otherwise the same one). The new session id replaces the old.

    A turn killed for emitting no event for `limit` seconds is one of those retries: nothing
    judged it, so it is retried on the same session rather than scored, with the same waits.

    Each turn's box ends its leftovers, without ending the suite or the loop's helpers.
    A turn that left processes or reports background work is unfinished:
    the same session is called once more, with no backoff, to run it in the
    foreground and report -- the same round, and not one of the transient waits.  That
    turn gets artifacts of its own (`<role>-retry-foreground`, beside the transient retries'
    `-retryN`, so `written_answer` still finds whose answer the round recorded): the first
    turn's diagnostics survive it, and only what the second turn itself wrote determines
    completion and retry behavior.  A second turn that ends the same way is carried on from
    with a WARN, as if it had been finished.

    Only an answer that names the account hands the round over.  A provider that lists
    `accounts` runs each call on the one with the most room left, and one that refuses for
    quota is marked spent on its own: the same worker goes again at once on the next account
    with room, on its own session.  A spent window otherwise leaves `RanDry` for the caller,
    whose job is another provider, not another try here: a usage-limit reset held is never
    spent for it, since only the owner spends one.
    An empty exit whose stderr says the harness never ran the turn leaves `CannotRun` the
    same way, at once: another provider, or a run blocked on that line.  Before either, a
    failed exit, not a kill, that an install or revert of its harness overlapped
    (`update.swap_end`) waits for that swap to end and starts again on its session: once per
    swap, since the retry begins after it ended.

    A worker exit by signal is neither: it reads as the signal, resumes once at once, and on
    a second kill inside a minute raises `Killed` for the run to park on.

    `handover`, when the turn loop gives one, is what a second transient failure in a row
    tries before its wait: called with the failure's detail, it moves the role to the next
    worker the way a spent window's moves and returns the new worker, or None when no other
    worker can take it.  A move raises `TransientHandover` at once, with no wait, so the
    loop restarts the role fresh; None waits out the growing waits on the same session, as
    without it, and tries only once -- the waits after that are the run's own.

    An executor or fixer of a fix run may also write the run's regression folder.
    """
    limit = 60 * run_record.SILENCE_MINUTES if limit is None else limit
    out_dir = Path(out_dir)
    run_dir = out_dir.parent.parent
    places = [place for place in [run_dir / REGRESSION.parent]
              if role in ("executor", "fixer") and place.is_dir()]
    note = shell_foreground_note()
    if note not in body:
        # the executor and fixer bodies already carry it in the context header; the reviewer
        # body is built from the task text, so it gets it here, said once either way
        body = f"{note}\n\n{body}"
    entry = config.model(cfg, name)
    # Mark only the worker child; the loop's orphaned-orchestrator fallback may still speak.
    # Every role (and retry) lives under <run>/round-N/<role> and inherits this audit log.
    env = {**run_child_env(), "AK_RUN_ROLE": "worker",
           "AK_RUN_LOG": str(run_dir / "log.txt")}
    if findings:
        env[hand_in.FINDINGS_ENV] = str(findings)
    attempt, calls, last_kill, account, span = 1, 0, None, None, None
    handover_tried = False
    last_dir, last_sid = Path(previous) if previous is not None else None, session

    def turn(text, target, session):
        """One call, with a login failure taken aside before it costs a wait.

        No call starts on a stopped run: the stop lands first and the sweep after
        it, so a retry that outlived the sweep would otherwise run a whole turn no
        record wants anymore.
        """
        nonlocal account, span, last_dir, last_sid
        run_record.stop_check(run_dir)
        account = usage.account(cfg, entry["provider"])[0]
        began = time.time()
        named = env if account is None else {**env, **config.account_env(account)}
        if session and session == last_sid and last_dir is not None:
            named = {**named, hand_in.CONTINUE: str(last_dir / hand_in.FILE)}
        try:
            with reviewer_checkout(workspace, target, log) if role in (
                    "reviewer", "reviewer-pr") else nullcontext(workspace) as cwd:
                result = worker.turn(cfg, name, text.replace(str(Path(workspace).resolve()), str(cwd)), cwd,
                                     target, role, session, env=named, limit=limit, log=log,
                                     places=places)
        except worker.LoginExpired as expired:
            log(f"{role} {name} cannot authenticate: {expired.why}; the run waits for that "
                "login rather than retrying into it")
            expired.session = expired.session or session
            raise
        else:
            span = (began, time.time())
        finally:
            memory_cap_note(run_dir, log)     # however the turn ended
        note_turn_meters(cfg, name, target, account)
        last_dir, last_sid = target, result[2] or session
        return result

    def swapped(code, killed, session):
        """Whether an install or revert of this harness overlapped the turn that just failed.

        Its command was missing then, which reads as a harness that cannot run, so the swap is
        waited out like a provider fault and the turn starts again on its session: once per
        swap, since that start comes after the swap ended.
        """
        if killed or not code or killed_word(code) or update.swap_end(
                entry["harness"], *span) is None:
            return False
        log(f"WARN {role} {name} exited {code} while {entry['harness']} was being swapped; "
            "starting again once that swap has ended"
            + (f", resuming session {session}" if session else ""))
        while (end := update.swap_end(entry["harness"], *span) or 0) > (now := time.time()):
            transient_wait(out_dir, min(SWAP_POLL, end - now))
        return True

    def next_account(until, message):
        """Park the account this turn ran on alone, and whether another of its provider has
        room: the turn goes there, on its own session, before any other model is asked."""
        usage.mark_exhausted(cfg, entry["provider"], until, account)
        spare, room = usage.account(cfg, entry["provider"])
        if room and spare != account:
            log(f"{role} {name} ran dry on account {account}: {message}; going on with account "
                f"{spare}" + (f", resuming session {session}" if session else ""))
        return room and spare != account

    while True:
        target = out_dir if not calls else out_dir.with_name(f"{out_dir.name}-retry{calls}")
        # Only the conversation the caller handed in is a resume. An id this ladder's own
        # first attempt left behind is a fresh turn's, and an empty exit on it is the
        # transport failure the three attempts are for, not a session that cannot be opened.
        asked = session if not calls else None
        code, text, sid, killed, unfinished = turn(body, target, session)
        if swapped(code, killed, sid or session):
            session, calls = sid or session, calls + 1
            continue
        if asked and resume_failed(target, killed, text):
            # One empty exit abandons the id. The role continues in a new conversation,
            # and the dead id is not retried and does not spend the transport attempts.
            log(f"resume of {asked} failed; fresh conversation")
            if isinstance(resume_note, dict):
                resume_note["restarted"] = True
                resume_note["at"] = time.time()
            if fresh_body is not None:
                body = fresh_body if note in fresh_body else f"{note}\n\n{fresh_body}"
            session = None
            calls += 1
            target = out_dir.with_name(f"{out_dir.name}-retry{calls}")
            code, text, sid, killed, unfinished = turn(body, target, None)
            session = sid or None
            calls += 1
            if swapped(code, killed, session):
                continue
        else:
            session, calls = sid or session, calls + 1
        # An ask for a missing closing or verdict is the turn's one extra call already.
        if (not killed and (unfinished or turn_unfinished(target))
                and "-retry-hand-in" not in out_dir.name and not body.endswith(NO_VERDICT_ASK)):
            log(f"{role} {name} ended its turn with a command still in the background; asking "
                "it to finish in the foreground")
            finish = target.with_name(f"{target.name}-retry-foreground")
            # Foreground recovery also asks for the closing, so neither role spends another ask.
            finish_body = (f"{FINISH_IN_FOREGROUND} "
                           f"{NO_VERDICT_ASK if role.startswith('reviewer') else NO_CLOSING_ASK}")
            code, text, sid, killed, unfinished = turn(finish_body, finish, session)
            session = sid or session
            if swapped(code, killed, session):
                continue
            if not killed and (unfinished or turn_unfinished(finish)):
                log(f"WARN {role} {name} ended its turn with a command still in the background "
                    "again; carrying on with what it reported")
            target = finish
        elif not killed and (unfinished or turn_unfinished(target)):
            log(f"WARN {role} {name} ended its turn with a command still in the background "
                "again; carrying on with what it reported")
        # A harness that never ran the turn says so on stderr, and that outranks the refusal
        # words below: a 404 for a model it does not have reads `API Error` like a 500, and
        # Codex's missing model suggests `try a different model` like its capacity refusal.
        # Not a wait: the caller hands the work over, or the run is blocked on this line.
        fault = None if killed else cannot_run(
            code, text, tail(target / "stderr.log"), target, entry["harness"])
        if fault:
            log(f"WARN {role} {name} cannot run: {fault}")
            raise CannotRun(name, fault)
        # Some adapters exit zero after streaming turn.failed; that event still refused
        # the turn. On a successful exit only failure events speak, never answer text.
        # A spent window, a refusal or an outage, each in the harness's own whole words.  A
        # kill by signal reads as the signal whatever else was said, unless the window is spent.
        said = harness_said(target, text, entry["harness"], failures_only=code == 0)
        outcome, mark = harness_plugin(entry["harness"]).failure(said)
        sig = killed_word(code) if not killed else None
        if outcome in (SPENT, LIMITED) or (outcome and not sig):
            quota = ran_dry(code, said, entry["harness"],
                            refusal=code == 0 and bool(said))
            lines = [line for line in said.splitlines() if says(line, mark)]
            message = lines[0] if lines else said or mark
            try:
                parsed = record_text(json.loads(message))
                if parsed:
                    message = parsed
            except (TypeError, ValueError):
                pass
            message = " ".join(message.split()) or mark
            if not quota:
                # A fault, not the account: the same session again, after the growing
                # wait, indefinitely -- what a person answers by typing `continue`.
                if handover is not None and attempt == 2 and not handover_tried:
                    handover_tried = True
                    detail = f"transient {mark!r}: {message} (twice in a row)"
                    new = handover(detail)
                    if new is not None:
                        raise TransientHandover(name, new, session, detail)
                    log(f"WARN {role} {name} {detail}; no other worker can take it")
                delay = transient_delay(attempt)
                log(f"WARN {role} {name} transient {mark!r}: {message} "
                    f"(attempt {attempt}); retrying in {delay}s"
                    + (f", resuming session {session}" if session else ""))
                attempt += 1
                transient_wait(out_dir, delay)
                continue
            if account is not None and next_account(try_again_at(said), message):
                continue
            requested = try_again_at(said)
            until = usage.mark_exhausted(cfg, entry["provider"], requested) or requested
            parked = (f"; nothing is picked on {entry['provider']} until "
                      + time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
            log(f"WARN {role} {name} refused: {message}{parked}")
            raise RanDry(name, quota, code, text, session, until, message, True)
        if sig:
            # The worker died by signal, not on the provider and not on the task: it
            # resumes once, at once, on the session it left behind.  A second kill
            # inside the minute is somebody -- or something -- killing it on purpose,
            # and the run parks for a person instead of retrying into it.
            now = time.time()
            if last_kill is not None and now - last_kill < KILL_WINDOW:
                raise Killed(f"{role} {name} {sig} twice within a minute; "
                             f"see {target}*/stderr.log", session)
            last_kill = now
            log(f"WARN {role} {name} {sig}; resuming once"
                + (f", resuming session {session}" if session else ""))
            continue
        why = (f"emitted no event for {orch.span(limit)} and was killed with everything it "
               f"spawned (session {session or 'not recorded'})" if killed else transient(code, text))
        if not why:
            # a quota word left only in the model's answer is the answer talking, not the
            # provider: it parks no account and hands nothing over
            return code, text, session, False
        if handover is not None and attempt == 2 and not handover_tried:
            handover_tried = True
            detail = f"{why} (twice in a row)"
            new = handover(detail)
            if new is not None:
                raise TransientHandover(name, new, session, detail)
            log(f"WARN {role} {name} {detail}; no other worker can take it")
        delay = transient_delay(attempt)
        log(f"WARN {role} {name} {why} (attempt {attempt}); retrying in {delay}s"
            + (f", resuming session {session}" if session else ""))
        attempt += 1
        transient_wait(out_dir, delay)


def dirty_paths(wt):
    """Every uncommitted path: tracked edits (staged or not) and untracked files, no ignored ones.

    Two plumbing calls rather than `status --porcelain`, whose output would have to be
    un-quoted and split off its status column; `-z` hands back the raw paths.
    """
    tracked = git(wt, "diff", "--name-only", "-z", "HEAD", check=False)
    untracked = git(wt, "ls-files", "--others", "--exclude-standard", "-z", check=False)
    return [p for p in f"{tracked}\0{untracked}".split("\0") if p]


def reset_checkout(wt, head, before, check=False):
    """Discard tracked changes and only paths created since the checkout was recorded."""
    git(wt, "reset", "--quiet", "--hard", head, check=check)
    new = sorted(set(dirty_paths(wt)) - set(before))
    if new:
        git(wt, "clean", "--quiet", "-fd", "--", *(f":(literal){p}" for p in new), check=check)


def writable_review_dirs(path, log):
    """Git does not record directory modes; the private copy must remain removable."""
    path = Path(path)
    if path.is_symlink():
        return
    try:
        mode = path.stat().st_mode
        if mode & 0o700 != 0o700:
            path.chmod(mode | 0o700)
            log(f"WARN made reviewer directory writable for cleanup: {path}")
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    writable_review_dirs(entry.path, log)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log(f"WARN skipped {path} during reviewer cleanup: {exc}")


@contextmanager
def reviewer_checkout(wt, out_dir, log):
    """Keep the reviewer's files and refs apart from the suite running in the task checkout."""
    wt = Path(wt).resolve()
    root = git(wt, "rev-parse", "--show-toplevel", check=False)
    if not root or Path(root).resolve() != wt:
        # Role-only callers can use a plain workspace inside some other repository.
        yield wt
        return
    checkout = Path(out_dir).parent / "review-checkout"
    checkout.parent.mkdir(parents=True, exist_ok=True)

    def copy_files(source, destination):
        destination.mkdir(exist_ok=True)
        with os.scandir(source) as entries:
            for entry in entries:
                if source == wt and (entry.name == ".git" or entry.name.startswith(SANDBOX_PREFIX)):
                    continue
                target = destination / entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        copy_files(Path(entry.path), target)
                    elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                        shutil.copy2(entry.path, target, follow_symlinks=False)
                    else:
                        log(f"WARN skipped {entry.path} in review checkout: not a regular file or link")
                except FileNotFoundError:
                    # The live suite can remove listed files or directories before copying.
                    pass
                except OSError as exc:
                    log(f"WARN skipped {entry.path} in review checkout: {exc}")

    def remove_checkout():
        if checkout.exists():
            writable_review_dirs(checkout, log)
            shutil.rmtree(checkout)

    with ExitStack() as stack:
        remove_checkout()
        stack.callback(remove_checkout)
        # A mirror keeps the source's base refs but owns its refs and index; a linked
        # worktree would still let a reviewer move the task branch through shared refs.
        git(wt, "clone", "--quiet", "--shared", "--mirror", str(wt), str(checkout / ".git"))
        # Keep the copied refs without a mirror push destination back into the source.
        git(checkout, "config", "--remove-section", "remote.origin")
        git(checkout, "config", "core.bare", "false")
        git(checkout, "read-tree", git(wt, "write-tree"))
        copy_files(wt, checkout)
        for key in ("user.name", "user.email"):
            value = git(wt, "config", "--get", key, check=False)
            if value:
                git(checkout, "config", key, value)
        exclude = Path(git(wt, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = wt / exclude
        if exclude.is_file():
            shutil.copyfile(exclude, checkout / ".git/info/exclude")
        with reviewer_changes(checkout, out_dir, log):
            yield checkout


@contextmanager
def reviewer_changes(wt, out_dir, log):
    """A review turn's changes survive only in its round's patch, including on a failed turn."""
    writable_review_dirs(wt, log)
    head = git(wt, "rev-parse", "HEAD")
    branch = git(wt, "symbolic-ref", "--quiet", "HEAD", check=False)
    before = set(dirty_paths(wt))
    staged = git(wt, "write-tree")
    # A private index records untracked files too, without staging artifacts for the next
    # executor. Its tree also puts back existing dirty paths a reviewer edited or committed.
    with tempfile.TemporaryDirectory() as tmp:
        index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(wt, "read-tree", head, env=index)
        skipped = []

        def snapshot():
            try:
                git(wt, "add", "--ignore-errors", "-A", "--", ".", env=index)
            except Stopped:
                raise
            except config.Error as exc:
                skipped.append(str(exc))
                log(f"WARN skipped unreadable reviewer paths: {exc}")
            return git(wt, "write-tree", env=index)

        tree = snapshot()
        try:
            yield
        finally:
            writable_review_dirs(wt, log)
            after = git(wt, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
            branch_after = git(wt, "symbolic-ref", "--quiet", "HEAD", check=False)
            # A conflicted index has no tree, but its staged diff and entries remain readable.
            index_diff = git(wt, "diff", "--cached", "--binary", staged)
            tree_after = snapshot()
            if skipped or index_diff or (after, branch_after, tree_after) != (head, branch, tree):
                path = Path(out_dir).parent / "reviewer-changes.patch"
                paths, patches = set(dirty_paths(wt)) - before, set()
                with path.open("a") as saved:
                    saved.write(f"# {Path(out_dir).name}: HEAD {head} -> {after or 'unborn HEAD'}\n")
                    for error in skipped:
                        saved.write("# skipped: " + error.replace("\n", "\n# ") + "\n")
                    if branch_after != branch:
                        saved.write(f"# checkout: {branch or 'detached HEAD'} -> "
                                    f"{branch_after or 'detached HEAD'}\n")
                    def save_diff(label, *args):
                        diff = git(wt, "diff", "--binary", *args)
                        paths.update(p for p in git(wt, "diff", "--name-only", "-z",
                                                   *args).split("\0") if p)
                        diff = re.sub(r"^\* Unmerged path ", "# Unmerged path ", diff, flags=re.M)
                        if diff and diff not in patches:
                            saved.write(f"# {label}\n{diff}\n")
                            patches.add(diff)

                    save_diff("checkout", tree, tree_after)
                    if after:
                        save_diff("commits", head, after)
                    save_diff("index", "--cached", staged)
                    unmerged = git(wt, "ls-files", "--unmerged")
                    if unmerged:
                        saved.write("# unmerged index\n# " + unmerged.replace("\n", "\n# ") + "\n")
                        # Unmerged blobs can differ from the worktree, especially binary files.
                        entries = [entry.split("\t", 1) for entry in git(
                            wt, "ls-files", "--unmerged", "-z").split("\0") if entry]
                        empty = git(wt, "mktree")
                        for stage in ("1", "2", "3"):
                            git(wt, "read-tree", "--empty", env=index)
                            for info, name in entries:
                                mode, blob, entry_stage = info.split()
                                if entry_stage == stage:
                                    git(wt, "update-index", "--add", "--cacheinfo", mode, blob,
                                        name, env=index)
                            save_diff(f"unmerged stage {stage}", empty,
                                      git(wt, "write-tree", env=index))
                if branch:
                    git(wt, "symbolic-ref", "HEAD", branch)
                else:
                    git(wt, "update-ref", "--no-deref", "HEAD", head)
                reset_checkout(wt, head, before, check=True)
                if before:
                    git(wt, "restore", f"--source={tree}", "--worktree", "--", ".")
                git(wt, "read-tree", staged)
                undone = ", ".join(sorted(paths)) or ("unreadable paths" if skipped else "")
                if after != head:
                    moved = f"commit {after[:12]}" if after else "unborn HEAD"
                    undone = f"{moved} back to {head[:12]}" + (f"; {undone}" if undone else "")
                if branch_after != branch:
                    undone = f"checkout back to {branch or 'detached HEAD'}" + (f"; {undone}" if undone else "")
                log(f"WARN undid reviewer changes: {undone}; saved {path}")


def main_checkout(repo):
    """The main checkout of the repository at `repo`: itself, or what a linked worktree was added from.

    A run launched from inside a linked worktree without `repo:` records that worktree, and a
    gate keyed on it would take a second set of turns for the same repository.  A path git
    cannot read as a checkout -- gone, never one, or a git that never answered -- keys on
    itself: a turn's key is not worth stopping the run over.
    """
    code, out, _ = tool_run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"])
    common = out.strip() if code == 0 else ""
    return (Path(repo) / common).resolve().parent if common else Path(repo)


@contextmanager
def released_gate_turn():
    """Let this thread's held gate turn go while slow work runs.

    A rebase conflict, a failing check and a re-review all end in a fixer or a reviewer,
    and a model turn held through them lands nothing for the runs queued behind.  The
    check takes a fresh turn after the fix.
    """
    gate.release_turn()
    yield


def leftover_junk(path):
    """Match names, not targets: a dependency symlink is junk even when Git ignores only directories."""
    parts = path.rstrip("/").split("/")
    return (parts[0].startswith(SANDBOX_PREFIX)
            or any(part in (run_record.RECOVERY_LOCK, "delivery.lock", "node_modules", "venv", ".venv")
                   for part in parts))


def commit_leftovers(wt, log, artifacts, state):
    """Commit whatever the executor left uncommitted, so the reviewer sees a real diff.

    The commit carries the run's title: a lone commit's headline becomes its squash merge's
    subject on the target, where changelogs read it.

    The reviewer only ever reads `base...HEAD`.  An executor that wrote the whole change and
    forgot to commit would otherwise be reviewed on an empty diff -- and a review of nothing
    is worse than no review, because it produces a verdict.

    Everything the done-when commands generated is left alone.  Committing that instead earns
    a FAIL on junk the next round's commands recreate, so the fixer can never get out of it.

    Test sandboxes, run locks and dependency trees are left alone too, including symlinks,
    whatever the repository's .gitignore says.  Anything `git check-ignore` would ignore
    stays out as well.  Ignored junk is listed back for the count below, since
    `dirty_paths` never sees it.

    The done-when only verifies a checkout clean at HEAD, so nothing left out may stay
    staged: a staged `venv` would fail every round as a changed checkout.  It is unstaged,
    and a staged deletion of junk (`git rm --cached venv`) is committed with the rest.  The
    commit is built in an index of its own: `git commit -- venv` would add the link back
    from the worktree, and the real index keeps whatever else the executor staged.
    """
    paths = [p for p in dirty_paths(wt) if p not in artifacts]
    real, sandbox = [], []
    for path in paths:
        if leftover_junk(path):
            sandbox.append(path)
        elif git_out(wt, "check-ignore", "-q", "--", path)[0] == 0:
            sandbox.append(path)
        else:
            real.append(path)
    status = git(wt, "diff", "--cached", "--name-status", "--no-renames", "-z", "HEAD",
                 check=False).split("\0")
    staged = dict(zip(status[1::2], status[::2]))
    junk = {p for p in sandbox if p in staged}
    gone = sorted(p for p in junk if staged[p] == "D")
    unstage = sorted(junk - set(gone))
    sandbox = sorted(set(sandbox) | set(ignored_sandbox_paths(wt, artifacts)))
    if sandbox:
        log(f"left {len(sandbox)} untracked sandbox files uncommitted: "
            f"{', '.join(sandbox[:3])}")
    try:
        if unstage:
            git(wt, "reset", "-q", "--", *unstage)
            log(f"unstaged {len(unstage)} sandbox files the executor staged: "
                f"{', '.join(unstage[:3])}")
        if not real and not gone:
            return
        if real:
            git(wt, "add", "--", *real)
        with tempfile.TemporaryDirectory() as tmp:
            index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            git(wt, "read-tree", "HEAD", env=index)
            if real:
                git(wt, "add", "--", *real, env=index)
            if gone:
                git(wt, "rm", "-q", "--cached", "--", *gone, env=index)
            git(wt, "commit", "-m", state["title"], env=index)
    except Stopped:
        # a git that stopped verifies nothing: the round ends on the stop, never on a review
        # of a diff the loop did not pin
        raise
    except config.Error as exc:
        log(f"WARN could not commit the executor's uncommitted changes: {exc}")
        return
    log("WARN committed uncommitted executor changes: " + ", ".join(real + gone))


def ignored_sandbox_paths(wt, artifacts):
    """Ignored sandbox files, run locks and dependencies: invisible to `dirty_paths`, still uncommitted.

    Once the repository's .gitignore names the suite's sandbox prefix, a killed test's
    sandbox never reaches the leftover sweep's classifier -- and without this listing its
    `left N ...` log line would never fire in a real checkout.  Collapsed directory
    entries are expanded to the files inside them, so the count is files, not sandboxes.
    """
    out = git(wt, "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
              check=False)
    found = []
    for entry in out.split("\0"):
        if not entry or entry in artifacts:
            continue
        if not leftover_junk(entry):
            continue
        if not entry.endswith("/"):
            found.append(entry)
            continue
        try:
            members = sorted((Path(wt) / entry).rglob("*"))
        except OSError:
            continue
        found.extend(str(member.relative_to(wt)) for member in members
                     if not member.is_dir()
                     and str(member.relative_to(wt)) not in artifacts)
    return found


def sweep_sandboxes(wt, log):
    """Remove killed-test sandboxes from the worktree before a turn starts.

    A test killed mid-way leaves its sandbox behind, and the next turn's executor would
    otherwise find stub binaries and fake adapters sitting in its checkout.  Only top-level
    names under the suite sandbox prefix are touched; anything else is the work's own.
    """
    try:
        names = sorted(path.name for path in Path(wt).iterdir()
                       if path.name.startswith(SANDBOX_PREFIX))
    except OSError as exc:
        log(f"WARN could not list test sandboxes in {wt}: {exc}")
        return
    removed = []
    for name in names:
        try:
            path = Path(wt) / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as exc:
            log(f"WARN could not remove test sandbox {name}: {exc}")
            continue
        removed.append(name)
    if removed:
        log(f"removed test sandboxes left by a killed test: {', '.join(removed)}")


def exclude_junk(wt, log):
    """Hide the usual build junk from git in `wt`, so no run can commit it.

    The executor runs the test suite itself, long before the loop's own done-when snapshot,
    so its `__pycache__` is already there when the leftover sweep looks -- and a sweep that
    commits it hands the reviewer droppings to fail the round on.

    `git rev-parse --git-path info/exclude` names the *shared* exclude file even inside a
    linked worktree: git keeps `info/` in the common dir, so `.git/worktrees/<id>/info/exclude`
    can be written but is never read (checked on git 2.39.5).  The file therefore belongs to
    the repo rather than to this run, and is treated the way `--no-worktree` demands either
    way: only the patterns it is missing are appended, and nothing is ever rewritten.

    Failing to write it ends the run.  The guarantee is that junk never reaches a commit, and
    a run that carried on with git still seeing `__pycache__` would break it the first time
    the sweep looked -- before any model call, so nothing is wasted by stopping here.
    """
    try:
        path = Path(git(wt, "rev-parse", "--git-path", "info/exclude"))
        if not path.is_absolute():
            path = Path(wt) / path
        text = path.read_text(errors="replace") if path.exists() else ""
        missing = [pat for pat in JUNK if pat not in text.splitlines()]
        if not missing:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(("" if not text or text.endswith("\n") else "\n")
                     + "# agentkit: build junk a run must never commit\n"
                     + "".join(f"{pat}\n" for pat in missing))
    except Stopped:
        # a git that stopped is not a git that said no: it takes the same path as every other
        # stopped tool -- `exhausted`, remedy in log and result, resumable -- never `error`
        raise
    except (config.Error, OSError) as exc:
        raise config.Error(f"cannot exclude build junk in {wt}: {exc}; without that git would "
                           "hand the executor's own __pycache__ to the leftover sweep")
    log(f"excluded build junk in {path}: {', '.join(missing)}")


def listing(work):
    """Every file in the workspace with its size: what a scratch run has instead of a diff."""
    root = Path(work)
    try:
        paths = sorted(p for p in root.rglob("*") if not p.is_dir())
    except OSError as exc:
        return f"(cannot read {root}: {exc})"
    rows = []
    for path in paths[:LIST_CAP]:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0        # a dangling symlink is still a file the reviewer should see
        rows.append(f"{size:>10}  {path.relative_to(root)}")
    if len(paths) > LIST_CAP:
        rows.append(f"... and {len(paths) - LIST_CAP} more files")
    return "\n".join(rows) or "(the workspace is empty)"


def links(work):
    """Every file in the workspace as a link to it, uncapped: result.md's deliverables.

    Whatever the name, the link reaches the file: the destination is percent-encoded, the
    few characters that would end the text early are escaped, and a control character is
    shown encoded, since a line break would end the link.
    """
    root = Path(work)
    try:
        paths = sorted(p for p in root.rglob("*") if not p.is_dir())
    except OSError as exc:
        return f"(cannot read {root}: {exc})"
    rows = []
    for path in paths:
        text = "".join("\\" + c if c in "\\[]`<" else c if c.isprintable()
                       else quote(c, errors="surrogateescape")
                       for c in str(path.relative_to(root)))
        rows.append(f"- [{text}]({quote(os.fsencode(path))})")
    return "\n".join(rows) or "(the workspace is empty)"


# The reason ak locks a checkout it makes under ~/.agentkit/wt while git makes it.  Git writes
# a reason as given, in every language, so a maker killed before it unlocks leaves a checkout
# gc knows holds nothing yet.
MAKING = "ak is making this checkout"


def add_worktree(repo, path, *args, mark=None):
    """(exit code, output) of `git worktree add` making `path`, locked as `MAKING` until git
    has made it and, given `mark`, that file is in the checkout's own git directory."""
    code, out = git_out(repo, "worktree", "add", "--lock", "--reason", MAKING, str(path), *args)
    if code == 0:
        if mark:
            (Path(git(path, "rev-parse", "--absolute-git-dir")) / mark).touch()
        code, out = git_out(repo, "worktree", "unlock", str(path))
    return code, out


def make_worktree(repo, run_id, slug, base):
    # The name has to be free on the remote too: two runs that picked the same one locally both
    # push it, and the second is rejected with `stale info` after its work has passed -- a PASS
    # that cannot be delivered.  One ls-remote answers for all of them, bounded so an
    # unreachable origin cannot hold the run: no `origin`, no network, a credential prompt, a
    # timeout or any other error means the empty set and local-only naming, exactly as before,
    # because naming is not worth failing a run over.
    taken = set()
    try:
        code, out, _ = tool_run(["git", "-C", str(repo), "ls-remote", "--heads", "origin",
                                 f"refs/heads/ak/{slug}*"], timeout=60)
        if code == 0:
            for line in out.splitlines():
                _, _, ref = line.partition("\t")
                if ref.startswith("refs/heads/"):
                    taken.add(ref[len("refs/heads/"):])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    branch, suffix = f"ak/{slug}", 1
    while branch in taken or git(repo, "rev-parse", "--verify", "--quiet",
                                 f"refs/heads/{branch}", check=False):
        suffix += 1
        branch = f"ak/{slug}-{suffix}"
    wt = config.WT / run_id
    code, out = add_worktree(repo, wt, "-b", branch, base)
    if code:
        raise config.Error(f"git worktree add {wt} failed in {repo}: {out}")
    return wt, branch


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
            restore_probe_checkout(self, **probe)

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


HANDOVER = ("## Another model started this round\n"
            "{before} began this round and its provider's window ran out mid-way, so the work is "
            "yours from here. The checkout is the same one it was working in and may carry "
            "uncommitted edits of its own: read them, keep what is right, and finish the task "
            "below as if it were round one.")


def started_round(run_dir, state):
    """The last round anything actually ran in: its round directory is the record of it.

    A round that was cut short leaves no summary but does leave the directory its executor
    wrote in, so the model that held it is credited with it rather than with nothing.
    """
    started = [int(path.name[len("round-"):]) for path in run_dir.glob("round-*")
               if path.name[len("round-"):].isdigit()]
    return max([*started, len(state.get("round_summaries") or [])], default=0)


def note_handover(state, before, why, rnd, to=None, reason="dry"):
    """Record in run.json which model held which rounds, and why the work changed hands.

    Two models that shared a round both held it: a handover mid-round is what this is, so the
    outgoing model's rounds start at the round it took over in -- the last round its own
    predecessor held -- and not at the one after it.  Anything else loses the round of whoever
    took over second, and of every model after that.

    The model taking over starts a fresh session: the context the old one built lives on a
    provider that is spent, and there is nothing there to resume.

    Every entry this function writes names the move both ways -- `from`/`to`/`reason` for
    the handover the tick records, `model`/`rounds`/`why` for the rounds each model held.
    The tick's own entries carry only the first half, so both readers fall back to it: the
    status line reads `from` where `model` is missing and `reason` where `why` is, and the
    rounds here start at the round being handed over, crediting the outgoing model with
    only the round it plainly held rather than every round since the run began.
    """
    history = state.setdefault("executor_history", [])
    last = history[-1] if history else None
    if last is not None and last.get("rounds"):
        took_over = last["rounds"][-1]
    elif last is not None:
        took_over = rnd
    else:
        took_over = 1
    history.append({"from": before, "to": before if to is None else to, "reason": reason,
                    "model": before, "rounds": list(range(took_over, rnd + 1)), "why": why})
    state["exec_session"] = None


def next_executor(cfg, providers, dry, reviewer, log, repo=None, workers=None, reviewers=None,
                  allow_self=True):
    """(executor, reviewer) for work whose provider has run dry, or Exhausted when none is left.

    Both roles are re-picked as one pair (`best_pair`), so tier beats budget: a cross-company
    review beats a same-company one, which beats a self-review.  Keeping the current reviewer
    instead would force a dearer executor on the run -- on 2026-09-22 a Grok refusal kept
    reviewer Muse and pushed execution onto Claude, though executor Muse with reviewer Claude
    was legal and cheaper.

    `dry` is every provider that has already refused this piece of work, not just the last one:
    a refusal the meters cannot see is still a refusal, and handing the work back to a provider
    that has just turned it down is how a handover becomes a circle.  `workers`, when given,
    is the run's bound list: nothing outside it is ever picked.  `allow_self` False keeps a
    flaky provider's handover off a self-review pair: the flake usually answers after a wait,
    so only a provider that cannot run the work settles for one.
    """
    workers, reviewers = config.role_groups(cfg, workers, reviewers)
    order = [n for n in ready_order(cfg, providers, workers, log, repo=repo, reviewers=reviewers)
             if config.model(cfg, n)["provider"] not in dry]
    review_order = [n for n in ready_order(cfg, providers,
                                          reviewers if reviewers is not None else workers,
                                          role="reviewer", repo=repo)
                    if config.model(cfg, n)["provider"] not in dry]
    pair = best_pair(cfg, order, review_order, allow_self=allow_self)
    if pair is not None:
        return pair
    raise QuotaDry(f"nothing is left to execute with a legal reviewer: "
                   f"{', '.join(sorted(dry))} ran dry; resume when a meter refills")


def hand_executor(lp, why, detail, dry):
    """Give this round's work to a model on a provider that refused nothing yet.

    The work keeps its identity: the same worktree, the same branch, the same round number and
    the same round budget.  Only the model changes, and it changes in run.json too, so what
    `ak run status` shows and what the result reads is who really did which round.

    Returns the new executor, or None where none is eligible.  An attempt that finds nobody
    records nothing: the same worker carries on, and run.json would otherwise show a handover
    that never happened.  `dry` is every provider that already refused this piece of work, not
    just the last one -- handing the work back to one of those is how a handover becomes a
    circle -- so the caller's set grows here and stays grown for the rest of the round.
    """
    before = lp.executor
    workers = run_workers(lp.cfg, lp.state)
    reviewers = run_reviewers(lp.cfg, lp.state)
    try:
        dry.add(config.model(lp.cfg, before)["provider"])
    except config.Error:
        pass
    try:
        providers = collect_usage(lp.cfg)
        # Only "transient" may still answer where it is: a flake waits out the backoff
        # unless another model can take the role with an independent review beside it.
        new, reviewer = next_executor(lp.cfg, providers, dry, lp.reviewer, lp.log,
                                      lp.state.get("repo"), workers, reviewers,
                                      allow_self=why != "transient")
    except (Exhausted, config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        new = None
    rnd = started_round(lp.run_dir, lp.state)
    if new is None:
        return None
    note_handover(lp.state, before, why, rnd, to=new, reason="dry")
    lp.executor, lp.exec_sid = new, None
    previous = lp.reviewer
    if reviewer != previous:
        lp.reviewer, lp.review_sid = reviewer, None
    lp.spares = [n for n in ready_order(lp.cfg, providers, reviewers, role="reviewer",
                                        repo=lp.state.get("repo"))
                 if n != reviewer and config.model(lp.cfg, n)["provider"] not in dry]
    lp.save()
    if why == "refused":
        message = detail.removeprefix("refused: ")
        lp.log(f"{before} refused: {message}; handing over to {new}")
    else:
        lp.log(f"handing executor to {new}: {before} {detail}")
    if reviewer != previous:
        lp.log(f"reviewer re-picked for executor {new}: {previous} -> {reviewer}")
    return new


def free_dir(lp, name):
    """`round-N/<name>`, or the next `-attempt<n>` beside it: no attempt overwrites another.

    A resumed round, a reviewer falling back, an executor handed over mid-round -- each writes
    where the one before it did, and the diagnostics of a call that failed are exactly what the
    post-mortem needs.
    """
    out, attempt = lp.dir(name), 1
    while out.exists():
        attempt += 1
        out = lp.dir(f"{name}-attempt{attempt}")
    return out


def role_base(dirname):
    """The role directory name without an `-attemptN` suffix."""
    match = re.fullmatch(r"(.+)-attempt(\d+)", dirname)
    return match.group(1) if match else dirname


def attempt_dirs(round_dir, name):
    """Out dirs for one role, the first attempt first."""
    found = []
    base = Path(round_dir) / name
    if base.is_dir():
        found.append((1, base))
    for path in Path(round_dir).glob(f"{name}-attempt*"):
        if not path.is_dir():
            continue
        suffix = path.name[len(name) + len("-attempt"):]
        if suffix.isdigit():
            found.append((int(suffix), path))
    found.sort()
    return [path for _, path in found]


def session_of(directory):
    """A conversation id recorded for this turn, from the file or the event stream."""
    directory = Path(directory)
    try:
        text = (directory / "session_id").read_text(errors="replace").strip()
    except OSError:
        text = ""
    if text:
        return text
    return worker.recovered_session(directory) or None


def latest_turn(round_dir, name):
    """The last call, including retries a host interruption may have left unfinished."""
    dirs = attempt_dirs(round_dir, name)
    if not dirs:
        return None
    out = dirs[-1]
    return max([out, *out.parent.glob(f"{out.name}-retry*")],
               key=lambda path: (path.stat().st_mtime_ns, path.name))


def open_turn(round_dir, name):
    """`(resume|fresh, session)` when this role's latest attempt never finished.

    A missing `final.md` is a turn the host cut off. An executor answer without a
    closing still needs its one extra ask. A recorded session is resumed; without one
    a fresh turn is needed. A finished attempt is `(None, None)`.
    """
    latest = latest_turn(round_dir, name)
    if latest is None:
        return None, None
    if (latest / "final.md").exists():
        submitted = hand_in.read(latest / hand_in.FILE)
        if (name.startswith("reviewer") or submitted is not None and submitted.closing
                or "-retry-hand-in" in latest.name or "-retry-foreground" in latest.name):
            return None, None
    sid = session_of(latest)
    if sid:
        return "resume", sid
    return "fresh", None


def finished_answer(round_dir, name):
    """The latest attempt's `final.md`, or None when that file was never written."""
    dirs = attempt_dirs(round_dir, name)
    if not dirs:
        return None
    return read_answer(dirs[-1] / "final.md")


def host_ended_prompt(state):
    """The one sentence a resumed harness session is handed.

    The conversation already holds the task. This says the checkout was not tidied
    and the turn is the same one, so the model does not start the work over.
    """
    when = None
    deaths = state.get("deaths") or []
    if deaths and isinstance(deaths[-1], dict):
        when = deaths[-1].get("at")
    if not isinstance(when, (int, float)) or isinstance(when, bool):
        when = state.get("interrupted_at")
    if not isinstance(when, (int, float)) or isinstance(when, bool):
        when = time.time()
    clock = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
    return (f"Your process was ended by the host at {clock}, not by you; "
            "the worktree is exactly as you left it. Continue this turn and finish it; "
            "do not start over.")


def latest_worker_turn(round_dir):
    """The latest executor/fixer attempt supersedes earlier attempts, even when it closed."""
    rd = Path(round_dir)
    if not rd.is_dir():
        return None
    turns = [latest_turn(rd, role_base(path.name)) for path in rd.iterdir()
             if path.is_dir() and "-retry" not in path.name
             and not path.name.startswith("reviewer")
             and re.match(r"(?:executor|(?:.+-)?fixer)(?:-|$)", path.name)]
    return max(turns, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)


def open_worker(lp):
    """`(name, kind, session)` of the open executor/fixer attempt, or three Nones."""
    latest = latest_worker_turn(lp.round_dir)
    if latest is None:
        return None, None, None
    name = role_base(latest.name.split("-retry", 1)[0])
    kind, sid = open_turn(lp.round_dir, name)
    return (name, kind, sid) if kind else (None, None, None)


def open_review(round_dir):
    """`(name, kind, session)` of the open reviewer attempt, or three Nones.

    A review that fell back to another model writes under `reviewer-<model>`, so the
    attempt to continue is the newest reviewer directory of any name, not `reviewer`
    alone: a fallback cut off mid-turn would otherwise start its review over. Retries
    belong to that same attempt, including a foreground finish ended by the host.
    """
    rd = Path(round_dir)
    if not rd.is_dir():
        return None, None, None
    best = None
    for path in rd.glob("reviewer*"):
        if not path.is_dir() or "-retry" in path.name or "foreground" in path.name:
            continue
        base = role_base(path.name)
        kind, sid = open_turn(rd, base)
        if not kind:
            continue
        latest = latest_turn(rd, base)
        try:
            mtime = latest.stat().st_mtime
        except OSError:
            mtime = 0
        if best is None or mtime >= best[0]:
            best = (mtime, base, kind, sid)
    return (None, None, None) if best is None else (best[1], best[2], best[3])


def review_turn(round_dir, session, since=""):
    """The round's latest reviewer turn on `session`, unless it is the one named `since`.

    A review is pending until its verdict is saved, not until its reviewer says `done`, and
    its pending record keeps where its session stood when it began.  Parked before the
    verdict (a spent window, an expired login, a stop while its proofs replay), it goes on in
    a conversation that has handed in what it found already: the next turn starts from the
    records of the latest turn since, or its `done` alone would pass the work.  A turn from
    before belongs to a review whose verdict is on the record, and hands on nothing.
    """
    turns = [path for path in Path(round_dir).glob("reviewer*")
             if session and path.is_dir() and session_of(path) == session]
    latest = max(turns, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)
    return None if latest is None or str(latest) == since else latest


def saved_worker_answer(round_dir):
    """The executor or fixer answer file already written for this round."""
    latest = latest_worker_turn(round_dir)
    answer = latest / "final.md" if latest is not None else None
    return answer if answer is not None and answer.is_file() else None


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
    if (lp.state.get("step") == "reviewer" or open_review(rd)[1]
            or review_files(lp.run_dir, lp.rnd)):
        return "reviewer"
    if open_worker(lp)[0]:
        return "worker"
    if lp.state.get("step") == "done-when" or saved_worker_answer(rd) is not None:
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
    work = read_answer(answer.with_name(name) / "final.md")
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
        sweep_sandboxes(lp.wt, lp.log)
    # Read the open attempt before free_dir creates the next one, or the empty new
    # directory would look like a turn that recorded no session.  Off `dir`, which is
    # what free_dir writes through, so the round is read exactly where it is written.
    rd = lp.dir(name).parent
    kind, sid = open_turn(rd, name) if rd.is_dir() else (None, None)
    previous = latest_turn(rd, name) if kind else None
    if previous is not None:
        record_disputes(lp, previous)
    out, body, dry = free_dir(lp, name), text, set()

    def handover(detail):
        return hand_executor(lp, "transient", detail, dry)
    # Only a turn whose body was replaced by the handover has a conversation that can be
    # refused, and only that turn hands the original prompt and the notice down.
    resume = {}
    note = None
    if kind == "resume":
        body = host_ended_prompt(lp.state)
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
        out = free_dir(lp, f"{previous.name}-retry-hand-in")
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
        except CannotRun as broken:
            # Another provider, the way a spent window goes; with nobody left, the run is
            # blocked on the harness's own line.  The turn never ran, so it left nothing
            # for the next model to be told about.
            if hand_executor(lp, "cannot run", broken.detail, dry) is None:
                raise
            body = text
            closing_asked = False
            out = free_dir(lp, f"{name}-{lp.executor}")
            continue
        except RanDry as refused:
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
            out = free_dir(lp, f"{name}-{lp.executor}")
            continue
        except TransientHandover as handed:
            # hand_executor already moved the role inside the callback; the new model
            # joins a round another started, in a fresh out dir on a fresh session.
            body = f"{HANDOVER.format(before=handed.before)}\n\n{text}"
            closing_asked = False
            out = free_dir(lp, f"{name}-{lp.executor}")
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
            out = free_dir(lp, f"{resume['previous'].name}-retry-hand-in")
            continue
        return worker_result(lp, summary, out)


def commit_identity(wt):
    return {"head_sha": git(wt, "rev-parse", "HEAD"),
            "tree_sha": git(wt, "rev-parse", "HEAD^{tree}")}


def plan_context(seat):
    """The seat's open plan lines (`plan.open_lines`), for the review of its own PR: the
    outcomes the user agreed to, each with the check that proves it and the project it is
    on.  A review launched from no seat has no plan."""
    from . import plan
    open_lines = plan.open_lines(seat) if seat else []
    if not open_lines:
        return ""
    return ("## The plan this PR serves\nThe session's open plan lines, the outcomes the user "
            "agreed to, each naming the project it is on:\n" + "\n".join(open_lines) + "\nAn "
            "outcome on this repository that this PR claims to deliver but misses is a finding "
            "whose proof is that line's check, run with `--run`.\n\n")


def suite_evidence(lp, cmds, identity):
    """Keep the checked tree: integration can carry the SHA without running the suite again."""
    suite = declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
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


def rules_bytes(repo, rev):
    """The bytes of AGENTS.md at `rev` as a checkout holds it, Git's line-end conversion and
    filters applied: what a harness reads, not the stored blob, and read as bytes, since a text
    read would fold CRLF to LF.  None where `rev` has no AGENTS.md file -- none, or a link,
    whose text is a path -- and config.Error, with what git said, where it cannot be read."""
    entry = git(repo, "ls-tree", rev, "--", "AGENTS.md")
    if not entry or entry.startswith("120000 "):
        return None
    try:
        read = subprocess.run(["git", "-C", str(repo), "cat-file", "--filters", f"{rev}:AGENTS.md"],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=TOOL_CAP,
                              env=tool_env())
    except subprocess.TimeoutExpired as exc:
        raise Stopped(f"git cat-file --filters {rev}:AGENTS.md was killed after {TOOL_CAP:g}s "
                      f"in {repo}") from exc
    if read.returncode != 0:
        raise config.Error(read.stderr.decode("utf-8", "replace").strip())
    return read.stdout


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
        held = rules_bytes(lp.wt, "HEAD")
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
    match = FRONT.match(text)
    if not match:
        return []
    return [line.strip() for line in match.group(1).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
            and line.partition(":")[0].strip() not in FRONT_KEYS]


def needs_base_proof(lp):
    """A run launched under the rule owes one until a check fails on base, as its record
    says; one launched before it owes none -- a process change applies to the next launch.
    A fix run's receipt says it proves its regression.sh instead (`regression_fails_before`),
    a repair's that it is proven at landing, and a scratch run's record that it has no base."""
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


def base_proof_line(state):
    """What a run's result and PR say of its proof, or "" for a run that owes none."""
    if state.get("base_proof") == "proven":
        return "base proof: a check fails on the old code and passes with this change"
    if state.get("base_proof") == "owed":
        return f"base proof: none shown ({state.get('base_proof_note') or 'not tried yet'})"
    return ""


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
            worker.kill_marked(run_child_env().get(worker.RUN_MARKER), log=lp.log)


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
    if pending["round"] > lp.rounds:
        work = f"for commit {identity['head_sha']} (tree {identity['tree_sha']}) " if identity else ""
        # a larger budget is only for asking up to the rule: past it the next step is the
        # orchestrator's, and naming a `--rounds` that is refused would send it nowhere
        onward = (f"resume with ak run resume {lp.run_dir.name} --rounds {pending['round']}"
                  if pending["round"] <= taskfile.TASK_MAX_ROUNDS else "split or re-scope the task")
        reason = (f"{pending.get('reason', 'unfinished review')}; done-when and review are pending "
                  f"{work}at round {pending['round']}, but the round budget ({lp.rounds}) is spent; "
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


def read_answer(path):
    """One worker answer from disk, or None when it is not there to be read."""
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def review_files(run_dir, rnd):
    """Every reviewer answer one round left, oldest first; the last is the one it recorded.

    A round writes under `reviewer`, `reviewer-attemptN` when an unfinished review resumed,
    `reviewer-<model>` when the reviewer fell back to another model, and `-retryN` beside
    any of those when the harness died on the provider rather than on the diff.
    """
    found = []
    for directory in Path(run_dir).joinpath(f"round-{rnd}").glob("reviewer*"):
        try:
            path = directory / hand_in.REPORT
            if not path.exists():
                path = directory / "final.md"
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue                    # no answer under it, or it went while we were looking
    return [path for _, path in sorted(found)]


def written_answer(out, text):
    """The file the answer just returned was read from.

    `call_retrying` gives every retry a directory of its own and returns only the text, so
    `out` itself holds a provider error whenever a retry is what finally answered -- naming it
    would hand the next fixer that error instead of the review.  Matched on the content, which
    is what makes the answer and the file the same thing.
    """
    out = Path(out)
    directories = sorted([out, *out.parent.glob(f"{out.name}-retry*")],
                         key=lambda path: (path.stat().st_mtime_ns if path.exists() else 0, path.name),
                         reverse=True)
    for directory in directories:
        if read_answer(directory / "final.md") == text:
            return directory / "final.md"
    for directory in directories:
        if (directory / hand_in.FILE).exists():
            return directory / "final.md"
    return out / "final.md"


def review_records(out, text):
    return hand_in.read(written_answer(out, text).parent / hand_in.FILE)


def record_findings(lp, out, text, submitted=None):
    """What the reviewer said, and where the whole of it is.

    Written together everywhere, because a `findings_file` left pointing at another answer
    would hand the next fixer the wrong review -- worse than the tail it replaces.
    """
    source = written_answer(out, text)
    if submitted is None:
        submitted = hand_in.read(source.parent / hand_in.FILE) or hand_in.Review([])
    text = submitted.text
    source = source.parent / hand_in.REPORT
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)
    source.with_name(hand_in.FINDINGS_FILE).write_text(json.dumps(submitted.findings))
    lp.findings = text
    lp.state["findings"] = text.strip()[-8000:]
    lp.state["findings_file"] = str(source)
    lp.state["review_records"] = submitted.records


def overridden_section(state):
    """Why the loop failed what the reviewer passed, to lead wherever that review is shown.

    It lives in the round's review record, never in the reviewer's text, whose kept tail
    a long report would push it out of.
    """
    review = state.get("review")
    why = review.get("overridden") if isinstance(review, dict) else None
    return f"## Overridden to FAIL\n{why}\n\n" if why else ""


def saved_findings(run_dir, state):
    """The last reviewer's whole text, for the fixer that has to work through it.

    `run.json` keeps a bounded tail of it, which is all a result page or a menu row needs;
    the round directory keeps the answer itself.  A resumed round must not be handed less than
    the round it continues would have been, so the file wins wherever it is still there --
    including for a run saved before the loop recorded which file that is, whose answers are
    still on disk: the tail was cut off the end of one of them, and that one is it.  Without
    a `run_dir` only the named file is read.
    """
    tail = (state.get("findings") or "").strip()
    named = read_answer(state.get("findings_file")) if state.get("findings_file") else None
    if named is not None and (not tail or named.strip().endswith(tail)):
        return named
    for rnd in (range(len(state.get("round_summaries") or []), 0, -1)
                if tail and run_dir is not None else ()):
        for path in reversed(review_files(run_dir, rnd)):
            whole = read_answer(path)
            if whole is not None and whole.strip().endswith(tail):
                return whole
    return state.get("findings") or ""


def without_followups(text):
    """The reviewer's answer as its fixer gets it, without follow-ups or unproven notes.

    Follow-ups predate the task and start runs of their own once this one merges; handed to
    a fixer told to address every finding below, they become out-of-scope work. Each section
    ends at the next heading of the same level or higher.
    """
    for pattern in (FOLLOWUPS, NOTES):
        heading = pattern.search(text or "")
        if heading:
            section = text[heading.end():]
            end = re.search(rf"^#{{1,{len(heading.group(1))}}}[ \t]", section, re.M)
            text = text[:heading.start()] + (section[end.start():] if end else "")
    return text


def record_flakes(state, text):
    """Keep each gate's flaky evidence with the current review, including checks after PASS."""
    for record in text.split("\n\n"):
        if record.startswith("flaky: ") and record not in state.get("followups", []):
            state.setdefault("followups", []).append(record)


def followup_place(text):
    """The review's site, independent of its wording or Markdown decoration."""
    site = re.search(r"([^\s`*]+):(\d+)\b", text)
    if site:
        return f"{site[1].removeprefix('./')}:{int(site[2])}"
    return text.splitlines()[0].strip()


def followup_open(state):
    """Whether this fix run is still on its way: running, about to, or resuming itself."""
    return (state.get("state") == "running"
            or (state.get("state") == "queued"
                and (run_record.process_active(state) or state.get("slot_waiting")))
            or (state.get("state") in ("waiting", "waiting_login", "exhausted", "error")
                and going(state))
            or (state.get("state") == "interrupted" and state.get("deaths")
                and tick_resumes(state)))


def repair_open(state, tip):
    """Whether this repair run holds its command on the target at `tip`.

    The one answer to both "does this red get a repair" and "do its waiters retry": one
    repair per command per tip.  On its way it does, on any tip.  Ended, it holds the tip
    its launch recorded from the probe that found it failing (`repair_tip`) -- never one
    read off its branch later, which a rebase or an aborted integration moves -- unless it
    merged, which moved the target, or found the command passing there (`not needed`).
    Failed, passed unmerged or blocked, another run of it on that tip would only repeat it;
    a target that moved past it is a new red.
    """
    return followup_open(state) or (
        state.get("state") in run_record.ENDED and state.get("state") != "not_needed"
        and not state.get("merged") and state.get("repair_tip") == tip)


def open_followup(state, text, repair=None, tip=None, split=None):
    """The open run already fixing `text`, or None.

    A follow-up is the same site in the same repository from the same seat.  A `repair` is
    the same repository, target and command from any seat, open at the target's `tip`: the
    target is everybody's. A suite split holds its line forever, and its repository while open.
    """
    for directory in run_record.run_dirs():
        other = run_record.read_state(directory) or {}
        if split:
            if (other.get("repo") == state.get("repo") and other.get("split_suite")
                    and (other["split_suite"] == split or followup_open(other))):
                return directory.name
            continue
        if (other.get("run_id") != state.get("run_id") and other.get("followup")
                and other.get("repo") == state.get("repo")
                and other.get("repair") == repair
                and (repair_open(other, tip) if repair else
                     launched_session(other) == launched_session(state)
                     and other["followup"]["place"] == followup_place(text)
                     and followup_open(other))):
            return directory.name
    return None


def start_followups(state, run_dir, log, cfg=None, repair=None, split=None):
    """A merge hands its follow-ups on, once, under the same lock that closes the seat.

    A review follow-up becomes a line in the seat's own plan, checked by its failing command:
    the seat builds it with the context it already has.  Anything else on the list (a flaky
    check's evidence) starts an ordinary run.  The receipt is written once the list is handed
    on: a process cut off before that hands it on again, and each item finds what the cut-off
    one already did -- its open plan line, the fix run it started.  A fix run waits for its slot
    from its first record on, so one the cut left before its launch is a slot wait the tick
    resumes.  There is no collector or backlog: this ending alone gets to hand on its list.

    A target failing a check on its own tip starts one the same way, before any merge:
    `repair` is what `target_fails` saw -- the `command`, its done-when `check` line, the
    tip's `sha`, and `text` naming the tip and what the command printed there -- and its
    run, launched ahead of the queue, makes the target pass that command again.  Its guard
    is an open repair of the same repository, target and command instead of a receipt.
    Returns the repair's run, started, already open, or left queued by a launch that
    raised, or None when none is.
    A slow suite's `split` starts the same way, with ak's task and check. Its cost record
    keeps the receipt even after run retention, whatever the run's ending.
    """
    session = launched_session(state)
    if (not (repair or split or state.get("merged") and state.get("followups")) or not session
            or not state.get("repo") or state.get("scratch")
            or (state.get("review_pr") and not state.get("own_pr"))):
        return None
    with watch.state_lock():
        if not (repair or split):
            current = run_record.read_state(run_dir) or state
            if "followup_runs" in current:
                state.update({key: current[key] for key in ("followup_runs", "followup_plan")
                              if key in current})
                return None
            if state.get("state") != "stopped":
                run_record.stop_check(run_dir)   # a stop that landed first ends the ending
        if watch.seat_closed(session):
            return None
        request = repair or split
        checks = {} if request else state.get("followup_checks") or {}
        items = [request["text"]] if request else state["followups"]
        planned = [item for item in items if item in checks]   # the seat's own, executors or not
        repo = main_checkout(Path(state["repo"])) if planned else None
        handed = {"followup_runs": [], "followup_plan": [
            plan_followup(session, repo, item, checks[item], state.get("base_sha"), log)
            for item in planned]}
        cfg = report_config(cfg)
        record = config.session_records().get(config.resolve_session(session), {})
        if record.get("workers") == []:
            return None if request else followups_handed(run_dir, state, handed)
        repo = repo or main_checkout(Path(state["repo"]))
        target = (state.get("target") or state["base"]).removeprefix("origin/")
        if split:
            previous = gate.read_suite_cost(Path(split["cost"])).get("split_run")
            if previous:
                return previous
        key = repair and {"target": target, "command": repair["command"]}
        for item in items:
            if item in planned:
                continue
            started = None if request else started_by(run_dir, item)
            if started:
                handed["followup_runs"].append(started)
                continue
            source = {**state, "repo": str(repo)}
            opened = open_followup(source, item, key, repair and repair["sha"],
                                   split and split["command"])
            if opened and request:
                return opened
            if opened:
                continue
            title = ("Split the slow test suite" if split else
                     f"Make {target} pass `{repair['command']}` again" if repair
                     else "Fix " + item.splitlines()[0])
            if len(title) > 256:  # GitHub rejects a longer PR title; the item stays whole below
                title = title[:255] + "…"
            name = f"{datetime.now():%Y%m%d-%H%M}-{slugify(title)}"
            directory = config.RUNS / name
            number = 1
            while directory.exists():
                number += 1
                directory = config.RUNS / f"{name}-{number}"
            try:
                directory.mkdir(parents=True)
                check = shlex.quote(str(directory / REGRESSION))
                task = (f"---\nrepo: {repo}\nbase: origin/{target}\ntarget: {target}\n---\n"
                        f"# {title}\n\n{item}\n\n")
                if split:
                    task += f"## Done when\n```bash\n{split['check']}\n```\n"
                elif repair:
                    task += (
                        "First fetch the target branch and run the command on its tip. If it "
                        'passes there now, run `ak hand-in not-needed "<why>"`, '
                        "with no edits or PR. Otherwise make the target pass it "
                        "again: fix the root cause, and show the command failing before the fix "
                        "and passing afterwards in your summary. If only the owner can decide, "
                        'run `ak hand-in blocked "<question>"`.\n\n'
                        f"## Done when\n```bash\n{repair['check']}\n```\n")
                else:
                    task += (
                        "First fetch the target branch and check that this defect still exists there. "
                        f"Inspect {config.RUNS}/*/run.json for another open run of session {session} "
                        f"fixing this site in {repo}; exclude this run ({directory.name}). "
                        "If the defect is gone or another open run is fixing it, run "
                        '`ak hand-in not-needed "<why>"`, with no edits or PR. '
                        "Otherwise fix it with a regression test: show it failing before the fix "
                        "and passing afterwards, and include both outputs in your summary. "
                        f"You may write {directory / REGRESSION} outside the checkout "
                        "to run that test from the checkout; "
                        "the loop runs it as a check. If only the owner can decide, run "
                        '`ak hand-in blocked "<question>"`.\n\n'
                        f"## Done when\n```bash\nbash {check}\n```\n")
                    (directory / REGRESSION.parent).mkdir()
                (directory / "task.md").write_text(task)
                (directory / "log.txt").touch()
                # A fix run is a new launch: the session's lists now, the discovering
                # run's only for a seat with no record of its own.  The record is checked
                # against the config now: the discovering run's may predate a model it names.
                try:
                    lists = config.load_session(config.load(), session, required=False) or state
                except config.Error:
                    lists = state
                receipt = {"followup": {"run": run_dir.name, "text": item,
                                        "place": followup_place(item)},
                           # a repair's only check is the target's own, run at landing: its
                           # before is the lander's run of it on the target tip, where it did
                           # not pass, and no round has a check of its own to replay on base
                           **({"repair": key, "repair_tip": repair["sha"],
                               "base_proof": "at landing"} if repair else {}),
                           **({"split_suite": split["command"]} if split else {}),
                           # a fix run is proven by its own regression.sh
                           # (`regression_fails_before`), not by its checks on base
                           **({} if repair or split else {"base_proof": "regression.sh"}),
                           "launched_session": session, "repo": str(repo),
                           **{role: list(lists[role]) for role in ("workers", "reviewers")
                              if isinstance(lists.get(role), list) and lists[role]},
                           **({"notify_sink": state["notify_sink"]}
                              if state.get("notify_sink") else {})}
                opts = {"--rounds": None, "--exec": None, "--review": None,
                        "--review-pr": None, "--no-worktree": False, "--no-merge": False,
                        "--bg": True, **({"--first": True} if request else {})}
                if split:
                    gate.write_suite_cost(Path(split["cost"]), {"split_run": directory.name})
                prepare(directory, opts, logger(directory), cfg, receipt=receipt)
                spawn_bg(directory, [str(directory / "task.md")])
            except run_record.StopRequested as exc:
                log(f"follow-up {directory.name} could not start: {exc}")
                return None if request else followups_handed(run_dir, state, handed)
            except (config.Error, OSError) as exc:
                log(f"follow-up {directory.name} could not start: {exc}")
                if split:
                    return directory.name
                if repair:
                    # a launch that raised can leave its receipt queued for a slot, and the
                    # tick starts that: it is the repair all the same
                    return directory.name if repair_open(run_record.read_state(directory) or {},
                                                         repair["sha"]) else None
                continue
            if request:
                return directory.name
            handed["followup_runs"].append(directory.name)
        if not request:
            return followups_handed(run_dir, state, handed)


def started_by(run_dir, item):
    """The fix run this ending already started for `item`, whatever became of it, or None: a
    handoff cut off before its receipt starts no item twice, not even one stopped since."""
    for directory in run_record.run_dirs():
        followup = (run_record.read_state(directory) or {}).get("followup") or {}
        if followup.get("run") == run_dir.name and followup.get("text") == item:
            return directory.name
    return None


def followups_handed(run_dir, state, handed):
    """Write the receipt that this ending's list is handed on: onto the record as it stands,
    so nothing written there meanwhile -- a stop, a delivery's mark -- is put back.  Read and
    written under `delivery_lock` too, taken inside the recovery lock as `reap` takes it: a
    delivery's mark lands before the read or after the write, never between them."""
    state.update(handed)
    with run_record.recovery_lock(run_dir), delivery_lock(run_dir), \
            run_record.record(run_dir) as current:
        current.update(handed)


def plan_followup(session, repo, item, check, proven, log):
    """Write one review follow-up into the seat's plan, unless an open line already holds its
    check in this project; the entry the run's ending names it by, or why the plan refused it."""
    from . import plan   # here, not at the top: a seat's small verb, this the loop
    outcome = "Fix " + item.splitlines()[0].replace("·", "-")
    try:
        plan.add(session, outcome, check, repo, proven=proven)
        entry = {"outcome": outcome}
    except (config.Error, OSError) as exc:
        entry = {"outcome": outcome, "refused": str(exc)}
    log(f"follow-up for {session}: {outcome}" + (f" (not planned: {entry['refused']})"
                                                if "refused" in entry else " (in its plan)"))
    return entry


def done_when_counts(dw_log, cmds):
    """(exited_zero, total) done-when commands, from the markers run_done_when writes.

    A marker only counts at the start of a blank-line-separated record, and only for the
    done-when command named on its `$ command` line.  Only `[exit 0]` is a pass: a signed
    status, `[killed at the limit]`, `[not run: the done-when limit was already spent]`
    and any marker text a later writer adds all count as failed, so nothing the loop
    reports ever vanishes from the reviewer's summary.  Whatever a command itself printed
    -- even a blank line plus a record-shaped `$ ...` / `[exit ...]` pair for a pending
    command -- never establishes provenance: when the records for one command disagree on
    the outcome, that command counts as failed.
    """
    marks = []
    for record in dw_log.split("\n\n"):
        match = re.match(r"\$ ([^\n]*)\n\[([^\]\n]*)\]", record)
        if match:
            marks.append((match.group(1), match.group(2) == "exit 0"))
    if cmds is None:
        return sum(ok for _, ok in marks), len(marks)
    hits = {}
    for cmd, ok in marks:
        hits.setdefault(cmd, []).append(ok)
    totals = {}
    for cmd in cmds:
        totals[cmd] = totals.get(cmd, 0) + 1
    passed = total = 0
    used = {}
    for cmd in cmds:
        outcomes, at = hits.get(cmd, []), used.get(cmd, 0)
        used[cmd] = at + 1
        if len(outcomes) == totals[cmd]:
            total += 1
            passed += outcomes[at]
        elif len(outcomes) > totals[cmd]:
            total += 1
            # printed records collide with the real one: fail closed, unless every
            # candidate agrees the command exited 0 -- then success is undisputed
            passed += all(outcomes)
        elif at < len(outcomes):
            total += 1  # a record went missing; trust the ones still there, in order
            passed += outcomes[at]
        # else: no record at all for this occurrence; nothing to count
    return passed, total


def failing_checks(dw_log):
    """Which done-when commands failed, and the last line each of them printed.

    What makes two failures the same failure: `run_done_when` writes one blank-line-separated
    record per command -- `$ <command>`, its marker, then its output -- and the last line is
    what the command finally said about itself.  Earlier lines carry run numbers, temporary
    paths and timings that differ every round, so comparing them would make every failure look
    new; the last line is the assertion or the exit message, which does not move unless
    something about the failure did.
    """
    found, failing = [], None
    for record in (dw_log or "").split("\n\n"):
        if record.startswith("flaky: "):
            continue
        match = re.match(r"\$ ([^\n]*)\n\[([^\]\n]*)\]", record)
        if match:
            # a marker counts only at the start of a record, as `done_when_counts` reads it;
            # a passing command's output is nobody's failure and a new record ends the last
            failing = None
            if match.group(2) != "exit 0":
                failing = [match.group(1), ""]
                found.append(failing)
            record = record[match.end():]
        if failing is None or LOOP_NOTE.match(record.lstrip()):
            continue    # the header, a passing command, or the loop talking about the gate
        # a blank line inside a command's own output split it into parts of its own: they are
        # all that command's, so the last line stays the last thing it said about itself
        printed = [line.strip() for line in record.splitlines() if line.strip()]
        if printed:
            failing[1] = printed[-1]
    return found


def first_failure(dw_log):
    """The first failing command and the line that says what failed: one line, for a person.

    Not the line `failing_checks` compares on.  That last line is what stays still between
    rounds, and a suite ends on its tally -- `acceptance: FAILED (see ...)` -- which says that
    something failed and never what.  This is the first line the failing command started
    with FAIL, FAILED, ERROR or `not ok`, else the last line it printed, else the command
    alone; a gate no command failed says what the loop said about it instead.
    """
    failing, named, last, note = None, None, None, None
    for record in (dw_log or "").split("\n\n"):
        if record.startswith("flaky: "):
            continue
        match = re.match(r"\$ ([^\n]*)\n\[([^\]\n]*)\]", record)
        if match:
            if failing is not None:
                break       # the next command's record: the first failing one said all it had
            if match.group(2) != "exit 0":
                failing = match.group(1)
            record = record[match.end():]
        for line in (line.strip() for line in record.splitlines()):
            if LOOP_NOTE.match(line):
                note = note or line
            elif failing is not None and line:
                named = named or (line if FAILURE_LINE.match(line) else None)
                last = line
    said = named or last or note or ""
    line = f"`{failing}` \u2014 {said}" if failing and said else f"`{failing}`" if failing else said
    return line if len(line) <= 200 else line[:199] + "\u2026"


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


def changed_test_paths(lp, head="HEAD", named=True):
    """The branch's changed tests: test-shaped paths, and with `named` every file a
    done-when command names."""
    # Include removed paths too: renaming a test out of discovery must remain visible.
    changed = git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                  f"{lp.base_sha}...{head}").split("\0")
    return [p for p in changed if p and (
        any(part in TEST_DIRS for part in Path(p).parts[:-1]) or test_named(p)
        or (named and any(p in cmd for cmd in getattr(lp, "cmds", []))))]


def test_named(path):
    return Path(path).name.startswith("test_") or any(Path(path).match(shape)
                                                       for shape in TEST_NAMES)


# Where tests live and what they are called, in the common languages' own conventions:
# Python's tests/ and test_*.py, Go's *_test.go, Ruby's spec/ and *_spec.rb, JavaScript's
# __tests__/, *.test.js and *.spec.js.
TEST_DIRS = ("tests", "test", "spec", "specs", "__tests__")
TEST_NAMES = ("*_test.*", "*_spec.*", "*.test.*", "*.spec.*")


def changed_line(lp, row, head, since=None):
    """Whether the finding's line is inside the diff to `head` from `since`: the base, or the
    commit the last review judged, for a later round."""
    diff = git(lp.wt, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
               "--unified=0", f"{since or lp.base_sha}...{head}", "--", f":(literal){row['path']}")
    for hunk in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(hunk[1]), int(hunk[2] or 1)
        # A pure removal leaves an anchor between the two surviving neighbouring lines.
        if (start <= row["line"] < start + count if count else row["line"] in (start, start + 1)):
            return True
    return False


def proof_on(lp, command, log_path, revision=None, tests_from=None):
    """Replay evidence with the regression probe's overlay and crash-safe checkout recovery."""
    run_record.stop_check(lp.run_dir)
    if not lp.scratch:
        head = git(lp.wt, "rev-parse", "HEAD")
        branch = git(lp.wt, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        before = set(dirty_paths(lp.wt))
        paths = changed_test_paths(lp, tests_from) if tests_from else []
        save_probe_checkout(lp, head, branch, before, f"proof on {revision}")
    try:
        if not lp.scratch:
            reset_checkout(lp.wt, head, before)
            git(lp.wt, "checkout", "--quiet", "--detach", revision)
            if paths:
                git(lp.wt, "restore", f"--source={tests_from}", "--staged", "--worktree", "--",
                    *(f":(literal){p}" for p in paths))
        run_record.stop_check(lp.run_dir)
        lp.log(f"--- review proof: checking {revision or 'workspace'}")
        env = gate.suite_env()
        env.pop(hand_in.ENV, None)
        env.pop(hand_in.CONTINUE, None)
        with tempfile.TemporaryDirectory(dir=lp.run_dir) as cache, log_path.open("w+b") as progress:
            # Same-size revisions can share a timestamp, making ignored bytecode look valid.
            env["PYTHONPYCACHEPREFIX"] = cache
            progress.write(f"$ {command} (on {revision or 'workspace'})\n".encode())
            progress.flush()
            start = progress.tell()
            try:
                code, _, killed = worker.boxed(
                    ["bash", "-c", command], lp.done_when_limit, silence=lp.turn_limit,
                    activity=log_path, output=progress, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, cwd=str(lp.wt), env=env)
            except (FileNotFoundError, PermissionError) as exc:
                code, killed = (127 if isinstance(exc, FileNotFoundError) else 126), False
                progress.write(str(exc).encode())
            output = hand_in.output_excerpt(progress, start)
            progress.write(f"\n[{'did not finish' if killed or code < 0 else f'exit {code}'}]\n".encode())
        memory_cap_note(lp.run_dir, lp.log)
        return {"returncode": code, "output": output, "killed": killed}
    finally:
        try:
            worker.kill_marked(run_child_env().get(worker.RUN_MARKER), log=lp.log)
        finally:
            if not lp.scratch:
                restore_probe_checkout(lp, head, branch, before, f"proof on {revision}")


def quoted_sites(lp, submitted, head):
    quotes = {index: row for index, row in enumerate(submitted.records, 1)
              if row["kind"] == "finding" and "quote" in row["evidence"]}
    if not quotes:
        return {}
    with ExitStack() as stack:
        checkout = lp.wt
        if not lp.scratch:
            # Reuse hand-in's filesystem rules without trusting the reviewer's files or refs.
            checkout = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=lp.run_dir)))
            git(lp.wt, "clone", "--quiet", "--shared", "--no-checkout", str(lp.wt), str(checkout))
            git(checkout, "checkout", "--quiet", "--detach", head)
            # Clone metadata is not part of the reviewed commit.
            shutil.rmtree(checkout / ".git")
        sites = {}
        for index, row in quotes.items():
            try:
                root, path, line = hand_in.checked_site(
                    f"{row['path']}:{row['line']}", checkout, row["evidence"]["quote"])
                sites[index] = {"path": str(path.relative_to(root)), "line": line}
            except (config.Error, OSError, ValueError, RuntimeError):
                sites[index] = None
        return sites


def before_at_base(lp, row):
    before = row.get("before", "").strip()
    if not before:
        return False
    named = re.match(r"(?:base\s+)?([^\s:]+)(?::|\s|$)", before)
    if named:
        commit = git(lp.wt, "rev-parse", "--verify", "--end-of-options",
                     f"{named[1]}^{{commit}}", check=False)
        if commit and git_out(lp.wt, "merge-base", "--is-ancestor", commit, lp.base_sha)[0] == 0:
            return True
    code, content = git_out(lp.wt, "show", f"{lp.base_sha}:{row['path']}")
    return code == 0 and before in content


def reviewed_before(lp, before, head):
    """The commit the last review of this run judged (`before`), when `head` is a later one:
    the delta from it is what a later round reviews.  None in round 1, in a scratch run, and
    for a review of that same commit again."""
    return before if before and not lp.scratch and before != head else None


def earlier_findings(lp):
    """The blocking findings the last review of this run handed in, as weighed then."""
    return [row for row in (lp.state.get("review_records") or [])
            if isinstance(row, dict) and row.get("kind") == "finding"]


def replay_findings(lp, rows, head):
    """Each earlier finding proven again on `head`: (the row, its evidence now, still failing).

    A `--run` proof is replayed on the head; a quote stands while its lines are still in the
    file there.  What ak can prove itself is never left to the reviewer to find again, and a
    finding whose proof still fails blocks whatever the reviewer hands in."""
    replayed = []
    if rows:
        lp.round_dir.mkdir(parents=True, exist_ok=True)   # the replay logs come before the turn
    for index, row in enumerate(rows, 1):
        evidence = row.get("evidence") or {}
        if "run" in evidence:
            command = evidence["run"]
            now = {"run": command, "commit": head,
                   **proof_on(lp, command, lp.round_dir / f"replay-{index}.log", head)}
            failing = hand_in.proof_failed(now)
        else:
            quote = evidence.get("quote") or ""
            text = git(lp.wt, "show", f"{head}:{row['path']}", check=False)
            failing = bool(quote) and quote in text
            now = evidence
        replayed.append((row, now, failing))
    return replayed


def replay_section(replayed, since):
    """What the reviewer is told of the earlier findings: ak's own replay, not a question."""
    lines = []
    for row, now, failing in replayed:
        how = (f"still fails ({'exit ' + str(now['returncode']) if 'run' in now else 'the quoted lines are still there'})"
               if failing else "fixed (the proof passes now)")
        lines.append(f"- {row['path']}:{row['line']} - {row['what']} - {how}")
    return (f"## Earlier findings, re-proven by ak on this commit\n"
            + ("\n".join(lines) if lines else "(none)")
            + "\nA finding still failing blocks whatever you hand in; one fixed needs no word. "
              f"A new finding blocks only inside the fix delta since {since[:12]}; "
              "outside it, it is kept as a note.")


def weigh_review(lp, submitted, head=None, since=None, replayed=()):
    """The reviewer's editable copy cannot decide what blocks the reviewed commit.

    In a later round (`since` names the commit the last review judged) a new finding blocks
    only inside the fix delta, and ak's own replay of the earlier findings (`replayed`) is
    weighed with the reviewer's: one still failing blocks whether or not the reviewer handed
    it in again, one fixed is a note."""
    if not any(row["kind"] in ("finding", "follow-up") for row in submitted.records) and not replayed:
        return submitted
    head = None if lp.scratch else head or git(lp.wt, "rev-parse", "HEAD")
    sites = quoted_sites(lp, submitted, head)
    records = []
    for index, row in enumerate(submitted.records, 1):
        if row["kind"] not in ("finding", "follow-up"):
            records.append(row)
            continue
        evidence = row["evidence"]
        kind = row["kind"]
        outside = False
        if kind == "follow-up":
            if not lp.scratch and "run" in evidence:
                command = evidence["run"]
                evidence = {"run": command, "commit": lp.base_sha, **proof_on(
                    lp, command, lp.round_dir / f"proof-{index}-base.log", lp.base_sha, head)}
        elif index in sites and sites[index] is None:
            kind = "note"
        elif "run" in evidence:
            command = evidence["run"]
            evidence = {"run": command, "commit": head or "workspace",
                        **proof_on(lp, command, lp.round_dir / f"proof-{index}-commit.log", head)}
            if not lp.scratch:
                evidence["base"] = {"sha": lp.base_sha, **proof_on(
                    lp, command, lp.round_dir / f"proof-{index}-base.log", lp.base_sha, head)}
            if not hand_in.proof_failed(evidence):
                kind = "note"
            elif since and not changed_line(lp, row, head, since):
                kind, outside = "note", True
            elif not lp.scratch and not changed_line(lp, row, head):
                base = evidence["base"]
                if hand_in.proof_failed(base):
                    kind = "follow-up"
                elif base["returncode"] != 0 or base["killed"]:
                    kind = "note"
        else:
            row = {**row, **sites[index]}
            if since and not changed_line(lp, row, head, since):
                kind, outside = "note", True
            elif not lp.scratch and not changed_line(lp, row, head):
                kind = "follow-up"
        row = {**row, "kind": kind, "evidence": evidence}
        if outside:
            row["outside"] = f"the fix delta since {since[:12]}; judged in an earlier round"
            lp.log(f"Kept as a note {row['path']}:{row['line']}: outside the fix delta")
        if kind == "follow-up":
            if "before" not in row:
                row["before"] = f"base {lp.base_sha}: " + (
                    "the proof fails there too" if "run" in evidence
                    else "quoted lines outside the change")
            reason = ("no base commit" if lp.scratch else
                      "needs a --run proof that fails on base" if "run" not in evidence else
                      "the command did not fail on base" if not hand_in.proof_failed(
                          evidence.get("base", evidence)) else
                      "--before names no commit in base's history or quote present at base" if not before_at_base(lp, row)
                      else "")
            if reason:
                row.update(kind="note", dropped=reason)
                lp.log(f"Dropped follow-up {row['path']}:{row['line']}: {reason}")
        records.append(row)
    if replayed:
        upheld = {(row["path"], row["line"]) for row in records if row["kind"] == "finding"}
        extra = []
        for row, now, failing in replayed:
            if failing and (row["path"], row["line"]) not in upheld:
                extra.append({**row, "kind": "finding", "evidence": now,
                              "replayed": "still failing; it blocks until its proof passes"})
                lp.log(f"Earlier finding {row['path']}:{row['line']} still fails on this commit")
            elif not failing:
                extra.append({**row, "kind": "note", "evidence": now,
                              "replayed": "fixed; its proof passes now"})
        closing = records.pop() if records and records[-1]["kind"] in hand_in.CLOSING else None
        records.extend(extra)
        if closing is not None:
            records.append(closing)
    return hand_in.Review(records)


def review_disputes(lp, head):
    """Keep the finding snapshot the fixer received; replay its dispute on the reviewed work."""
    rows = []
    for file in lp.state.get("dispute_files", []):
        submitted = hand_in.read(file)
        for row in submitted.disputes if submitted is not None else ():
            if row not in rows:
                rows.append(row)
    disputes = []
    for index, row in enumerate(rows, 1):
        evidence = row["evidence"]
        if "run" in evidence:
            command = evidence["run"]
            evidence = {"run": command, "commit": head or "workspace", **proof_on(
                lp, command, lp.round_dir / f"dispute-{index}.log", head)}
        disputes.append({**row, "evidence": evidence})
    return hand_in.Review(disputes)


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
        review_turn(lp.dir("reviewer").parent, lp.review_sid) or "")
    # the commit the last review judged, read before this review replaces that record and
    # kept on the pending record, so a resumed review still knows its delta
    last = lp.state.get("review") if isinstance(lp.state.get("review"), dict) else {}
    delta_from = last.get("head_sha") or pending.get("delta_from") or lp.state.pop("delta_from", None)
    lp.state.update(verdict=None, review=None,
                    review_pending={"round": lp.rnd, "summary": summary, "since": since,
                                    **({"passed_head_sha": passed_head} if passed_head else {}),
                                    **({"delta_from": delta_from} if delta_from else {})})
    if not record:
        lp.state["review_pending"]["record"] = False
    if hasattr(lp, "step"):
        lp.step("reviewer")
    else:
        lp.state.update(step="reviewer", step_at=time.time())
        lp.save()
    checks, since, replayed = "", None, []
    if lp.scratch:
        work = whole = f"## Workspace ({lp.wt})\n```\n{listing(lp.wt)}\n```"
    else:
        head = "HEAD"
        if lp.state.get("review_pr"):
            head = lp.state["head_sha"]
            restore_review_checkout(lp, "tests")
        else:
            commit_leftovers(lp.wt, lp.log, lp.artifacts, lp.state)
        diff = git(lp.wt, "diff", f"{lp.base_sha}...{head}", check=False)
        if len(diff) > DIFF_CAP:
            diff = diff[:DIFF_CAP] + f"\n\n[diff truncated at {DIFF_CAP} bytes; use git in {lp.wt} for the rest]"
        work = whole = f"## Diff ({lp.base}...HEAD in {lp.wt})\n```diff\n{diff}\n```"
        # a later round judges what changed since the last review, and ak re-proves the
        # earlier findings itself: the reviewer re-finds nothing
        at = git(lp.wt, "rev-parse", head)
        since = reviewed_before(lp, delta_from, at)
        if since:
            delta = git(lp.wt, "diff", f"{since}...{head}", check=False)
            if len(delta) > DIFF_CAP:
                delta = delta[:DIFF_CAP] + f"\n\n[diff truncated at {DIFF_CAP} bytes; use git in {lp.wt} for the rest]"
            replayed = replay_findings(lp, earlier_findings(lp), at)
            work = (f"## Fix delta ({since[:12]}...HEAD in {lp.wt}; what changed since the last "
                    f"review)\n```diff\n{delta}\n```\n\n{replay_section(replayed, since)}")
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
    rbody_whole = body_with(f"{whole}\n\n{work}") if since else rbody
    # A review cut off mid-turn is continued where it was, fallback model and all: the
    # attempt after a fallback wrote under `reviewer-<model>`, and asking `reviewer` for
    # it would start the review over in a directory beside the one holding its session.
    # The round is read off `dir`, which is what free_dir writes through.
    rd = lp.dir("reviewer").parent
    name = open_review(rd)[0] or "reviewer"
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
        spares = reviewer_order(lp.cfg, exec_for_rule,
                                [n for n in order if n in lp.spares and n != lp.reviewer])
        if not allow_self:
            # A flake waits unless another model can review: only a reviewer that cannot
            # come back settles for the executor's own model.  The filter is local, so a
            # later fallback with a real reason still finds it.
            offered = [n for n in spares
                       if not same_model(lp.cfg, exec_for_rule, n)]
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
        turn_kind, turn_sid = open_turn(rd, name)
        out = free_dir(lp, name)
        body = rbody if lp.review_sid else rbody_whole
        asked_body, note, resume = body, None, {}
        if ask:
            asked_body, resume, ask = NO_VERDICT_ASK, {"fresh_body": body, "previous": ask}, None
        elif turn_kind == "resume":
            asked_body = host_ended_prompt(lp.state)
            lp.review_sid = turn_sid
            note = {"at": time.time(), "role": "reviewer", "restarted": False}
            lp.state["resume_notice"] = note
            resume = {"fresh_body": body, "resume_note": note, "previous": latest_turn(rd, name)}
        elif turn_kind == "fresh":
            asked_body = rbody_whole
            lp.review_sid = None
            note = {"at": time.time(), "role": "reviewer", "restarted": True}
            lp.state["resume_notice"] = note
        else:
            resume = {"previous": review_turn(rd, lp.review_sid, since)}
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
                                                            handover=handover, **resume)
        except worker.LoginExpired as expired:
            lp.review_sid = expired.session or lp.review_sid
            lp.save()           # the parked conversation is in run.json before the run parks
            raise
        except Killed as killed:
            lp.review_sid = killed.session or lp.review_sid
            lp.save()           # the killed conversation is in run.json before the run parks
            raise
        except CannotRun as broken:
            # The spares road, as for a spent window; with no spare left, the run is blocked
            # on the harness's own line rather than waiting for a meter it is not short of.
            try:
                name = fall_back(broken.detail, out)
            except Exhausted:
                raise broken from None
            continue
        except TransientHandover as handed:
            # fall_back already moved the role inside the callback; the spare reviews
            # in a fresh out dir on a fresh session.
            name = handed.new
            continue
        except RanDry as dry:
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
    submitted = weigh_review(lp, submitted, identity.get("head_sha"), since=since, replayed=replayed)
    upheld = {(row["path"], row["line"]) for row in submitted.findings}
    for row in disputes.disputes:
        if (row["path"], row["line"]) not in upheld:
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
    lp.state["followups"] = submitted.followups if verdict == "PASS" else []
    lp.state["followup_checks"] = submitted.followup_checks if verdict == "PASS" else {}
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
    lp.save()
    history.record_review(lp.state.get("run_id"), str(out),
                          harness=review_harness, model=review_model,
                          blocking=len(submitted.findings), followup=len(submitted.followups),
                          note=len(submitted.notes), log=lp.log)
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
    while lp.rnd < lp.rounds:
        pickup_new_code(lp, execv=execv)
        lp.rnd += 1
        cut = continuation(lp)
        if cut in ("reviewer", "done-when"):
            # The worker already answered. A done-when that was cut off runs again;
            # a review that was the open step is continued, not preceded by another
            # executor turn.
            source = saved_worker_answer(lp.round_dir)
            summary = worker_result(lp, read_answer(source) or "", source.parent) if source else ""
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
            worker_name = open_worker(lp)[0] if cut == "worker" else None
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


def stands_on_dependency(state):
    """Why a record from before `after:` went cannot go on, or "" when it can.

    Its branch was to be cut from, or still stands on, a dependency's passed tip: the
    reviewed diff leaves that dependency's commits out, so landing would deliver them
    unreviewed, and replaying them after the dependency's squash conflicts.  Once
    integrated onto the target the branch stands on its own commits and goes on.
    """
    after = state.get("from_pass")
    if not isinstance(after, dict) or state.get("base_sha") not in (None, after.get("tip")):
        return ""
    dep, branch = after.get("task"), state.get("branch")
    if not branch:
        # never started: there is no branch to go on from, only the task to launch again
        return (f"this run was to start from {dep}'s passed work, which `after:` no longer "
                f"waits for; once that has merged, launch its task again")
    return (f"this branch stands on {dep}'s passed work, which `after:` no longer "
            f"waits for; once that has merged, relaunch with `from: {branch}`")


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
    while lp.rnd < lp.rounds:
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
    rc, out = gh(lp.wt, *api, "-X", "PATCH", f"repos/{owner}/{repo}/pulls/{number}",
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
    rc, out = gh(lp.wt, "pr", "create", "--base", target_branch, "--head", lp.state["branch"],
                 "--title", lp.state["title"], "--body-file", str(path))
    # gh names the existing PR in the error it refuses a duplicate with, so one regex covers both
    found = PR_URL.search(out)
    view = None
    if not found:
        # the create may still have happened server-side: the view says so, or stops too
        vrc, view = gh(lp.wt, "pr", "view", lp.state["branch"], "--json", "url", "-q", ".url")
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
                        rc, out = gh(lp.run_dir, *api, "-X", "POST",
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
    rc, out = gh(lp.wt, "repo", "view", "--json", "nameWithOwner,viewerPermission")
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
        rc, out = gh(lp.wt, "repo", "fork", "--remote", "--remote-name", FORK_REMOTE)
        if rc != 0:
            if stopped(rc, out):
                raise Stopped(out)
            return note(lp, f"gh repo fork failed: {out[-400:]}", failed=True)
    rc, out = git_out(lp.wt, "push", "--force-with-lease", "-u", FORK_REMOTE, branch)
    if rc != 0:
        return note(lp, f"pushing {branch} to the fork failed: {out[-400:]}", failed=True)
    lp.log(f"--- merge: pushed {branch} to {FORK_REMOTE}")
    if not lp.state.get("pr"):
        rc, me = gh(lp.run_dir, "api", "user", "-q", ".login")
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
        rc, out = gh(lp.wt, "pr", "create", "--repo", upstream_repo, "--base", target_branch,
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
    suite = declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
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
    """Record the PR as merged; True, for the merge step to return."""
    lp.state["merged"] = True
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
    src, view = gh(lp.run_dir, "pr", "view", url, "--json", "state,headRefOid,baseRefName")
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
                rc, out = gh(lp.run_dir, "pr", "merge", url, MERGE_METHODS[method], "--delete-branch",
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
            vrc, view = gh(lp.run_dir, "pr", "view", url, "--json",
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
            vrc, why = gh(lp.run_dir, "pr", "view", url, "--json", "mergeStateStatus",
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


def save_probe_checkout(lp, head, branch, before, label):
    """A hard exit skips finally: record recovery before Git can detach the checkout."""
    lp.state["probe_checkout"] = {"head": head, "branch": branch,
                                  "before": sorted(before), "label": label}
    lp.write()


def restore_probe_checkout(lp, head, branch, before, label):
    """Discard probe edits; keep recovery pending until the original checkout is restored."""
    stopped = None
    restored = False
    try:
        reset_checkout(lp.wt, "HEAD", before)
    except Stopped as exc:
        stopped = exc
    try:
        git(lp.wt, "checkout", "--quiet", branch or head, check=False)
        if git(lp.wt, "rev-parse", "HEAD", check=False) != head:
            git(lp.wt, "checkout", "--quiet", head, check=False)
        restored = (git(lp.wt, "rev-parse", "HEAD", check=False) == head
                    and (not branch or git(lp.wt, "symbolic-ref", "--quiet", "--short",
                                           "HEAD", check=False) == branch)
                    and git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
                    and not (set(dirty_paths(lp.wt)) - set(before)))
        if not restored:
            lp.log(f"WARN the probe of {label} did not restore {branch or head[:12]} "
                   "cleanly; checkout recovery is still pending")
    except Stopped as exc:
        stopped = stopped or exc
    if restored:
        lp.state.pop("probe_checkout", None)
        lp.write()
    if stopped is not None:
        raise stopped
    if not restored:
        raise config.Error(f"could not restore the checkout after the probe of {label}")


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
        save_probe_checkout(lp, head, branch, before, label)
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
            memory_cap_note(lp.run_dir, lp.log)
            # as after a gate: a command that exited may still have left processes behind
            worker.kill_marked(run_child_env().get(worker.RUN_MARKER), log=lp.log)
            with probe_log.open("rb") as said:
                said.seek(start)
                output = said.read().decode(errors="replace")
            return code, output, killed
        finally:
            restore_probe_checkout(lp, head, branch, before, label)

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


def failing_blocks(text, cap=OUT_CAP):
    """What a fixer reads of a failed check: its last `cap` characters, as before, and ahead of
    them every block that begins above that end and says what failed.

    A suite run in pieces prints each piece's failures where that piece ends, so the end alone
    can hold none of a red piece printed earlier: a landing fixer handed the last 20 KB never
    saw the red file 32 KB before it.  A block is a line that names a failure
    (`FAILURE_LINE`, at the start of the line) and the indented lines under it, taken whole
    even where the end begins inside it.  The end is kept whole too, so nothing the end alone
    showed is ever traded for a block.
    """
    if len(text) <= cap:
        return text
    above, blocks, block, at = len(text) - cap, [], None, 0
    for line in text.splitlines(keepends=True):
        began, at = at, at + len(line)
        line = line.rstrip("\r\n")
        if FAILURE_LINE.match(line):
            if began >= above:
                break       # this block and every later one lie whole in the end
            block = [line]
            blocks.append(block)
        elif block is not None and (not line or line[:1].isspace()):
            block.append(line)
        elif began >= above:
            break
        else:
            block = None
    named = "\n".join("\n".join(block).rstrip() for block in blocks)
    return f"{named}\n\n... the end of the output:\n{text[-cap:]}" if named else text[-cap:]


def red_target_text(cmd, upstream, tip, output):
    """What a red target's repair is told: the command, where it fails, and what it printed
    there, read as a fixer reads a failed check -- indented, so nothing it printed reads as a
    heading or a fence of the task."""
    printed = "\n".join("    " + line for line in failing_blocks(output).splitlines())
    return (f"`{cmd}` fails on {upstream} at {tip}, the target's own tip, whichever branch runs "
            f"it. What it printed there:\n\n{printed}")


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
            and record.get("suite") == declared_suite(lp.wt, lp.target,
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
        suite = declared_suite(lp.wt, lp.target, ref=lp.state.get("target_sha"))
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
                    return fail_pr_landing(lp, {"line": path.read_text().strip(), "log": str(path)})
                lp.state["final_check"] = {"outcome": "passed", "where": "landing",
                                           "sha": identity["head_sha"],
                                           "tree_sha": identity["tree_sha"],
                                           "tested": wait.get("tested") or (
                                               landing.passed(turn, wait["land"]) or {}).get(
                                                   "tested", identity["tree_sha"]),
                                           "suite": declared_suite(lp.wt, lp.target, ref=tip)}
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
        return fail_pr_landing(lp, failure)
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
            from_branch = ""
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
                log(f"WARN could not fetch {name} from origin; basing this run on the local "
                    f"{spelled}: {out.partition(chr(10))[0]}")
                ref = spelled
            # a branch name moves with the executor's commits, so pin the diff to the commit it names
            base_sha = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
            from_branch = (meta.get("from") or "").strip()
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
    if state.get("scratch"):
        where = (f"Workspace: {wt}\nThere is no git repository here: nothing to commit, no branch "
                 "and no PR. What you leave in the workspace is the deliverable.")
    else:
        target = state.get("target") or state["base"]
        where = (f"Repo checkout: {wt}\nBranch: {state['branch']} (based on {state['base']}"
                 + (f", to be merged into {target}" if target != state["base"] else "") + ")")
    if state.get("scratch"):
        cmds = [taskfile.split_once(cmd)[0] for cmd in cmds]
    else:
        cmds = with_suite(cmds, wt, target, landing=not state.get("no_merge"))
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


def history_start(state, log=None):
    """Publish the launch receipt without making SQLite part of run correctness.

    A test suite's run -- launched under the suites' notify sink, which run.json keeps -- is
    never recorded: every later write finds no row.  The row names the model the launching
    seat's orchestrator runs.
    """
    if state.get("notify_sink"):
        return
    session = launched_session(state)
    record = config.session_records().get(session) if session else None
    history.start_run(state.get("run_id"), repo=state.get("repo"),
                      executor=state.get("executor"), reviewer=state.get("reviewer"),
                      rounds_used=len(state.get("round_summaries") or []),
                      started_at=state.get("started_at"),
                      session=session, task_words=state.get("task_words"),
                      task_points=state.get("task_points"),
                      task_checks=state.get("task_checks"),
                      orchestrator=record.get("orchestrator") if record else None, log=log)


def changed_files(state):
    """Files the run changed against its base, or None when that cannot be read.

    Best effort for the history row: a scratch run has no base. A worktree that is
    gone -- collected on delivery, or never built -- is diffed from the record
    instead: the delivery sha, else the reviewed head, names the same tip the
    worktree's HEAD held, and the objects outlive the branch that pointed at them.
    """
    try:
        wt, base = state.get("worktree"), state.get("base_sha")
        if not wt or not base:
            return None
        if Path(wt).is_dir():
            out = git(Path(wt), "diff", "--name-only", "-z", "--no-renames",
                      f"{base}...HEAD", check=False)
        else:
            review = state.get("review")
            tip = state.get("delivery_sha") or (review.get("head_sha") if isinstance(review, dict)
                                                else None)
            repo = state.get("repo")
            if not tip or not repo:
                return None
            out = git(Path(repo), "diff", "--name-only", "-z", "--no-renames",
                      f"{base}...{tip}", check=False)
    except (config.Error, OSError, ValueError, TypeError, AttributeError):
        return None
    return [found for found in out.split("\0") if found]


def diff_lines(repo, base, head="HEAD"):
    """Added plus deleted text lines, excluding files Git marks linguist-generated.

    Deleted files read their attributes at the base; their directory's attributes may
    have been deleted too. NUL records preserve unusual filenames and rename pairs.
    """
    total = 0
    for selector, source in (("d", head), ("D", base)):
        parts = iter(git(repo, "diff", "--numstat", "-z", "--find-renames",
                         f"--diff-filter={selector}", f"{base}...{head}").split("\0"))
        changes = []
        for entry in parts:
            if not entry:
                continue
            added, deleted, name = entry.split("\t", 2)
            if not name:
                next(parts)  # the old name; surviving files use their new attributes
                name = next(parts)
            if added != "-":
                changes.append((name, int(added) + int(deleted)))
        if changes:
            # Older Git has no check-attr --source; a private index reads the same tree.
            with tempfile.TemporaryDirectory(dir=config.TMP) as tmp:
                index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
                git(repo, "read-tree", source, env=index)
                attrs = git(repo, "check-attr", "--cached", "-z", "linguist-generated",
                            "--", *(name for name, _ in changes), env=index).split("\0")[2::3]
            if len(attrs) != len(changes):
                raise config.Error("git did not report generated attributes for the PR diff")
            total += sum(lines for (_, lines), attr in zip(changes, attrs)
                         if attr.lower() not in ("set", "true"))
    return total


def history_finish(state, log=None):
    """Publish a terminal receipt and close the step this process was running, if any."""
    now = state.get("finished_at") or time.time()
    history.close_step(state.get("run_id"), now, log=log)
    files = changed_files(state)
    # git is read from the run's worktree while it exists, else from its repository
    wt = state.get("worktree")
    try:
        present = bool(wt) and Path(wt).is_dir()
    except (OSError, TypeError):
        present = False
    repo = wt if present else state.get("repo")
    size = None
    if state.get("merged") and state.get("base_sha"):
        try:
            review = state.get("review") or {}
            head = state.get("delivery_sha") or review.get("head_sha") or ("HEAD" if present else None)
            if repo and head:
                size = diff_lines(repo, state["base_sha"], head)
        except (config.Error, OSError, ValueError, TypeError, AttributeError, StopIteration):
            pass  # best-effort history must never change the merge's outcome
    # the AGENTS.md its workers were handed, measured as the ceiling measures it
    rules = None
    if repo and state.get("base_sha"):
        try:
            # no file, or a link, hands its workers no rules: 0, where a failed read stays unknown
            rules = len(rules_bytes(repo, state["base_sha"]) or b"")
        except (config.Error, OSError, ValueError, TypeError):
            pass
    history.finish_run(state.get("run_id"), repo=state.get("repo"),
                       executor=state.get("executor"), reviewer=state.get("reviewer"),
                       rounds_used=len(state.get("round_summaries") or []),
                       final_state=state.get("state"), verdict=state.get("verdict"),
                       started_at=state.get("started_at"), finished_at=now,
                       session=launched_session(state), peak_rss_mb=state.get("peak_rss_mb"),
                       task_files=json.dumps(files) if files is not None else None,
                       changed_lines=size, rules_bytes=rules, log=log)


def history_role_tokens(run_id, role, out, log=None, cfg=None, model=None):
    """Copy token counts from where the model's harness keeps them, when it reports them at all.

    None of the turns reporting leaves the column unknown, never zero.  A model the config
    cannot place is read the default way, from its event log.
    """
    try:
        harness = config.model(cfg, model)["harness"] if cfg is not None and model else None
    except (config.Error, KeyError, TypeError, AttributeError):
        harness = None
    out = Path(out)
    paths = [out, *sorted(out.parent.glob(f"{out.name}-retry*"))]
    values = [harness_plugin(harness).tokens(path) for path in paths]
    values = [value for value in values if value is not None]
    if not values:
        return
    history.add_tokens(run_id, role, sum(values), log=log)


def park_exhausted(state, exc):
    """Only a quota stop waits on a window, whether in a round or during delivery."""
    state["state"] = "exhausted"
    if exc:
        state["error"] = str(exc)
    if isinstance(exc, QuotaDry):
        state["quota_dry"] = True
    else:
        state.pop("quota_dry", None)
        state.pop("refusal_retry", None)


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


def failed_at_budget(state):
    """A FAIL that ran out of rounds rather than out of work, so more rounds carry it on.

    Deliberately not part of `needs_recovery`: nothing was interrupted here, so this is no
    recovery decision for the menu to raise, for the seat to be told about or for `announce`
    to swallow the finished-run notice over.  An explicit `--rounds` above the saved budget,
    and no higher than `taskfile.TASK_MAX_ROUNDS`, continues it and nothing else does -- see
    `cmd_resume`.
    """
    return (state.get("state") == "fail" and not state.get("review_pr")
            and bool(state.get("worktree")) and Path(state["worktree"]).is_dir()
            and len(state.get("round_summaries") or []) >= (state.get("rounds") or 0) > 0)


def _integration_fail_guards(state, run_dir=None):
    """What every FAIL resumed past the merge shares: it failed there, not in the rounds.

    A run the tick parked `waiting` off such a FAIL shares it too: the branch, base
    and budget still identify the saved work, and the merge note still names why.

    The branch, base and budget identify the saved work, `merge_note` names the delivery
    failure and the log carries it.  Judged or not, rounds left or not, is the caller's
    distinction -- see `integration_note` and `judged_in_integration`.
    """
    if state.get("state") not in ("fail", "waiting") or state.get("review_pr"):
        return False
    if not state.get("worktree") or not Path(state["worktree"]).is_dir():
        return False
    for key in ("branch", "base", "base_sha", "rounds"):
        if not state.get(key):
            return False
    if not state.get("merge_note"):
        return False
    if run_dir is not None:
        try:
            if "not merged:" not in (Path(run_dir) / "log.txt").read_text(errors="replace"):
                return False
        except OSError:
            return False
    return True


def integration_note(state, run_dir=None):
    """A FAIL whose last note came from integration rather than from the rounds.

    The branch is saved with rounds possibly left, but origin moved under it or the rebase
    could not land.  A last round that recorded a judged failure -- a `FAIL` verdict with a
    done-when value and the commit it judged -- is not one of these, however its delivery
    note reads: only the reviewer can clear that tree.  Nor is a last review that failed
    it without being a round -- after a conflict or a final-check fix -- whose older PASS
    of the same commit a resume would otherwise put back.  The old code's synthetic marker
    (`FAIL` with no done-when review and no commit) judged nothing, so it stays eligible.
    Budget is not consulted here: classifying the failure is independent of the budget
    needed to continue it -- see `failed_in_integration` and `cmd_resume`.
    """
    if not _integration_fail_guards(state, run_dir):
        return False
    summaries = state.get("round_summaries") or []
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    for last in (review, summaries[-1] if summaries else {}):
        if (last.get("verdict") == "FAIL" and last.get("done_when") is not None
                and ("head_sha" in last or "tree_sha" in last)):
            return False
    return True


def failed_in_integration(state, run_dir=None):
    """An integration FAIL with rounds left, so a resume needs no larger `--rounds`.

    Unlike `failed_at_budget` the run continues with the rounds it has left.
    """
    return (integration_note(state, run_dir)
            and len(state.get("round_summaries") or []) < (state.get("rounds") or 0))


def judged_in_integration(state, run_dir=None):
    """A judged FAIL after the rebase with rounds left: a fixer round carries it on.

    Unlike `failed_in_integration` the last round judged the tree -- a `FAIL` verdict with
    a done-when value and the commit it judged -- so the resume spends a fixer round on the
    reviewer's findings, then review, then the merge.  The delivery note still says the last
    word came from integration (`merge_note` set, `not merged:` in the log).  At its budget
    this is a `failed_at_budget` resume with `--rounds`, never this path.
    """
    if not _integration_fail_guards(state, run_dir):
        return False
    summaries = state.get("round_summaries") or []
    if len(summaries) >= (state.get("rounds") or 0):
        return False
    if not summaries:
        return False
    last = summaries[-1]
    return (last.get("verdict") == "FAIL" and last.get("done_when") is not None
            and ("head_sha" in last or "tree_sha" in last))


def continue_line(state, run_dir=None):
    """The way on from a FAIL at its round budget, an integration FAIL below it,
    a judged FAIL after the rebase with rounds left, a reviewer that never answered,
    or a run parked `stalled`."""
    if state.get("state") == "stalled" and state.get("run_id"):
        return f"continue: ak run resume {state['run_id']}"
    if not state.get("run_id"):
        return ""
    # Only the no-verdict stop names its resume here: a quota-dry stop inside
    # review leaves the same `review_pending` behind, but its row already says which
    # window it waits for and the tick resumes it by itself.
    if (state.get("state") == "exhausted" and state.get("review_pending")
            and "gave no verdict twice" in (state.get("error") or "")):
        return f"continue: ak run resume {state['run_id']}"
    if failed_at_budget(state) and state["rounds"] < taskfile.TASK_MAX_ROUNDS:
        # up to the budget and no further: past it the task is split or re-scoped instead
        return f"continue: ak run resume {state['run_id']} --rounds {taskfile.TASK_MAX_ROUNDS}"
    if failed_in_integration(state, run_dir):
        return f"continue: ak run resume {state['run_id']}"
    if judged_in_integration(state, run_dir):
        return f"continue: ak run resume {state['run_id']}"
    return ""


def report_config(cfg=None):
    """Live reports use the run's config; standalone reports tolerate a broken config file.

    Without readable model policy a report cannot establish PASS, but it must still leave
    the original failure and recovery instructions instead of failing while reporting it.
    """
    if cfg is not None:
        return cfg
    try:
        return config.load()
    except config.Error:
        return {"models": {}, "providers": {}}


def delivery(state, cfg=None):
    """The review verdict and the delivery outcome are separate facts.

    `not merged` is a repository run's answer and only a repository run's: a run with no repo
    has no branch to merge, and its workspace is where the work went, so it is `delivered`.
    """
    if state.get("state") == "not_needed":
        return f"not needed: {state['not_needed']}"
    if state.get("state") == "waiting":
        return f"WAITING: {state.get('merge_note') or state.get('error') or 'delivery pending'}"
    cfg = report_config(cfg)
    if not review_pass(state, cfg) or state.get("state") in (
            "error", "fail", "interrupted", "exhausted", "blocked", "waiting_login",
            "stopped"):
        return "FAIL"
    if state.get("scratch"):
        return "PASS, delivered"
    if state.get("merged"):
        return "PASS, merged"
    reason = state.get("merge_note")
    if not reason:
        reason = ("review only" if state.get("review_pr") else
                  "--no-merge" if state.get("no_merge") else "delivery did not finish")
    return f"PASS, not merged: {reason}"


def retry_command(state):
    """The one command that finishes a PASS whose delivery failed, or None.

    A run that reviewed its work and then could not push it is not over and not a new run's
    job: `ak run merge` picks up exactly where the delivery stopped.
    """
    if (state.get("state") != "pass" or not state.get("merge_failed") or state.get("scratch")
            or state.get("review_pr") or not state.get("repo")):
        return None
    return f"ak run merge {state['run_id']}"


def final_check_line(state, cmds):
    """The run's `final check:` result.md line: what the once-commands came to, and where."""
    record = state.get("final_check") or {}
    if record.get("outcome") in ("passed", "failed") and (
            record.get("sha") or record.get("where") in ("round", "landing")):
        sha = f" on {record['sha']}" if record.get("sha") else ""
        where = record.get("where")
        if where == "round":
            rnd = record.get("round")
            loc = f"in round {rnd}" if rnd else "in round"
            return f"final check: {record['outcome']} {loc}{sha}"
        if where == "landing":
            if record.get("tested") and record["tested"] != record.get("tree_sha"):
                return f"final check: {record['outcome']} at landing on tree {record['tested']}"
            return f"final check: {record['outcome']} at landing{sha}"
        if record.get("sha"):
            return f"final check: {record['outcome']} on {record['sha']}"
    if not taskfile.group_commands(cmds)[1]:
        return "final check: none (no once-commands)"
    return "final check: not run"


def result_done_when(cmds, state=None):
    """Commands as result.md shows them, including where each once-command ran."""
    record = (state.get("final_check") or {}) if isinstance(state, dict) else {}
    where = record.get("where") or ("landing" if record.get("outcome") else None)
    rnd = record.get("round")
    if where == "round":
        suffix = f"(once, in round {rnd})" if rnd else "(once, in round)"
    elif where == "landing":
        suffix = "(once, at landing)"
    else:
        suffix = "(once)"
    marked = []
    for cmd in cmds:
        bare, once = taskfile.split_once(cmd)
        if once and "(once" not in bare:
            cmd = f"{bare} {suffix}"
        marked.append(cmd)
    return marked


def save_result(run_dir, text=None, *, notices=()):
    """Publish a report or save its full notices without a rebuild losing them.

    Build the report before taking the delivery lock: while git reads its diff, the tick
    can deliver a notice. Read its saved section only at publication, under the same lock.
    """
    with delivery_lock(run_dir):
        result = run_dir / "result.md"
        try:
            saved = result.read_text()
        except FileNotFoundError:
            saved = ""
        heading = "\n## Seat notice\n\n"
        _, boundary, kept = saved.partition(heading)
        if text is None:
            missing = [part for part in notices if part and part not in kept]
            if missing:
                with result.open("a") as output:
                    output.write(heading + "\n\n".join(missing) + "\n")
        else:
            result.write_text(text + boundary + kept)


def write_result(run_dir, state, cmds, log=None, cfg=None):
    """The full result.md.  `log` carries a stop observed while reporting, if any.

    The state and exit code stay the delivery's -- a merged run is merged -- but nothing
    about a stop is silent: the diff-stat fallback names it, and its remedy is logged.
    """
    wt = Path(state["worktree"])
    # A blocked run heads its report with the word for it: nothing was delivered and nothing
    # was judged, so the delivery outcome would call FAIL on work that was never reviewed.
    outcome = ("BLOCKED" if state.get("state") == "blocked"
               else delivery(state, report_config(cfg)))
    parts = [f"# {outcome} — {state['title']}", "",
             f"VERDICT: {state['verdict']}",
             f"rounds: {len(state['round_summaries'])} of {state['rounds']}"]
    if state.get("scratch"):
        # no branch, no PR, no merge: the files are where this run's work went
        parts += [f"workspace: {wt}",
                  f"executor: {state['executor']}   reviewer: {state['reviewer']}",
                  "", "## Deliverables", links(wt)]
    else:
        try:
            stat = git(wt, "diff", "--stat", f"{state['base_sha']}...HEAD", check=False) or "(no changes)"
        except Stopped as exc:
            # the report never depends on git working -- and a stop is recorded, not swallowed:
            # the diff-stat section names it, and the remedy goes to the log with everything else
            stat = f"(cannot read the diff: {exc})"
            if log is not None:
                log(f"ERROR {exc}")
        except config.Error as exc:
            stat = f"(cannot read the diff: {exc})"   # the report never depends on git working
        parts += [f"branch: {state['branch']}",
                  f"pr: {state.get('pr') or '(none)'}",
                  f"merged: {'yes' if state.get('merged') else 'no'}"]
        if state.get("merge_note"):
            parts.append(f"merge: {state['merge_note']}")
        retry = retry_command(state)
        if retry:
            parts.append(f"retry delivery: {retry}")
        parts += [f"worktree: {state['worktree']}",
                  f"executor: {state['executor'] or '-'}   reviewer: {state['reviewer']}",
                  "", "## Diff stat", "```", stat, "```"]
    if state.get("blocked"):
        parts += ["", state["blocked"], ""]
    parts += ["", "## Done-when", "```", "\n".join(result_done_when(cmds, state)), "```", ""]
    parts += [final_check_line(state, cmds), ""]
    if base_proof_line(state):
        parts += [base_proof_line(state), ""]
    # A model's summary need not repeat a stop; a fix started from this result
    # still needs the diagnostic the gate recorded before ending the children.
    try:
        with (run_dir / "log.txt").open(errors="replace") as progress:
            stopped = [line.rstrip().split("] ", 1)[1] for line in progress
                       if re.match(r"^\[\d\d:\d\d:\d\d\] done-when: stopped ", line)]
    except OSError:
        stopped = []
    if stopped:
        parts += ["## Stopped checks", "", "```", *stopped, "```", ""]
    for entry in state["round_summaries"]:
        dw = {True: "done-when passed", False: "done-when failed"}.get(
            entry["done_when"], "done-when not run")
        parts += [f"## Round {entry['round']} ({entry['verdict']}, {dw})", "",
                  entry["summary"], ""]
    if state.get("error"):
        parts += ["## Why this run stopped", "", state["error"], ""]
    if state["verdict"] != "PASS" and overridden_section(state):
        parts += [overridden_section(state)]
    if state["verdict"] != "PASS" and state["findings"]:
        parts += ["## Reviewer findings", "", without_followups(state["findings"]), ""]
    if followup_report(state):
        parts += [followup_report(state), ""]
    if state.get("notes"):
        parts += ["## Notes", "", *("- " + item.replace("\n", "\n  ") for item in state["notes"]), ""]
    if state.get("disputes"):
        parts += ["## Disputes", "", *("- " + item.replace("\n", "\n  ") for item in state["disputes"]), ""]
    onward = continue_line(state, run_dir)
    if onward:
        parts += [onward, ""]
    save_result(run_dir, "\n".join(parts))


def run_for_pr(url):
    """(run_dir, state) of the run that opened that PR, or (None, None)."""
    for run_dir in run_record.run_dirs():
        state = run_record.read_state(run_dir)
        if state and state.get("pr") == url:
            return run_dir, state
    return None, None


def record_decision(run_dir, state, reason, merged=False):
    """Put what the maintainer decided on the run itself, where the menu and result.md read it.

    A PR of ours moving is news for the run that opened it, not for Discord: `waiting for the
    maintainer` becomes what they did, in the one line `ak run status` already shows.
    """
    state["merge_note"] = note = " ".join(reason.split())
    if merged:
        state["merged"] = True
    run_record.save_state(run_dir, state)
    if merged:
        history_finish(state)
        start_followups(state, run_dir, logger(run_dir))
    result = run_dir / "result.md"
    try:
        if state.get("worktree") and Path(state["worktree"]).is_dir():
            _, body, _ = taskfile.parse_task(run_dir / "task.md")
            write_result(run_dir, state, taskfile.done_when(body, run_dir / "task.md"))
        else:
            # The worktree is gone, so the diff stat cannot be produced again: keep the result
            # as it was written and add what has happened to it since.
            with delivery_lock(run_dir):
                if note not in result.read_text():
                    with result.open("a") as fh:
                        fh.write(f"\n## The maintainer decided\n\n{note}\n")
    except (config.Error, OSError, KeyError):
        pass          # the note is on the run; a result we cannot rewrite from here is not news
    return state


# --- telling the user, when nobody else will --------------------------------


def run_workers(cfg, state):
    """The executor list this run is bound to: its session's selection at launch.

    Every executor of the run -- first pick, every handover and every fixer -- is picked
    from this list and never widened.  `run.json` records what the session held when the run
    was launched, because the session record can be rewritten while the run lives and the
    process doing a later pick may speak for another seat or for none.  A receipt written
    before the field existed reads its launch session's selection now.  None means no
    selection was ever recorded anywhere, and the pick falls back as it always did.
    """
    workers = state.get("workers")
    if isinstance(workers, list) and workers:
        return list(workers)
    try:
        name = launched_session(state)
        selection = config.load_session(cfg, name, required=False) if name else None
    except config.Error:
        selection = None
    workers = (selection or {}).get("workers")
    return list(workers) if isinstance(workers, list) and workers else None


def run_reviewers(cfg, state):
    """Old receipts keep their shared list even if the session adds reviewers later."""
    if "reviewers" in state:
        return list(state["reviewers"])
    return run_workers(cfg, state)


def launched_session(state):
    """The seat this run was launched from, by its name now, or None: it was launched from none.

    `session` is what a run.json written before the field was renamed calls the same thing.
    """
    name = state.get("launched_session") or state.get("session")
    return config.resolve_session(name) if isinstance(name, str) and name else None


def run_project(state):
    """The checkout a run's work belongs to, or None when it belongs to none.

    A run belongs to the checkout its task's `repo:` names, else to its task folder's
    (`task_project`), never to one it merely inherits from where it was launched.  `project`
    is that answer, settled once by the process that launched the run (`preflight`), where a
    relative `repo:` still means something; so the run votes the same while it waits for a slot
    and once it works, whoever reads it from wherever.  A run launched before the field existed
    is read from its task: an absolute `repo:` is that checkout; a relative one is the checkout
    its record says it works in, once it has started, and no vote before, nobody else knowing
    what `.` meant; no `repo:` is its task folder's.  One with no task to read belongs to the
    repository it works on.
    """
    if "project" in state:
        return orch.checkout_of(state["project"])
    try:
        path = config.RUNS / state["run_id"] / "task.md"
        meta = taskfile.parse_task(path)[0]
    except (KeyError, TypeError, OSError, ValueError, config.Error):
        return task_project(state.get("repo"), state.get("task_file"))
    try:
        named = repo_line(meta, path)
    except config.Error:
        # a launch refuses such a line, so only a receipt from before that has one, and it
        # never got as far as a project: it has none rather than breaking everyone who reads it
        return None
    if named and not named.is_absolute():
        return orch.checkout_of(state.get("repo"))
    return task_project(named, state.get("task_file"))


def task_project(repo, task_file):
    """The checkout a task belongs to: the repository it works in, else its task folder's.

    A task with no repository belongs to the checkout its task file's folder is named for: an
    orchestrator files a project's tasks under ~/.agentkit/tasks/<project>/, whatever the task
    works in.
    """
    if repo:
        return orch.checkout_of(repo)
    if not isinstance(task_file, str) or not task_file:
        return None
    try:
        parts = Path(task_file).resolve().relative_to((config.HOME / "tasks").resolve()).parts
    except (OSError, ValueError):
        return None
    if len(parts) < 2:
        return None
    return next((checkout for checkout in orch.checkouts()
                 if checkout.name.lower() == parts[0].lower()), None)


def join_session_project(session, runs=None):
    """File a session under the project most of its runs belong to, again at each launch.

    A session filed by hand (`ak orch project`) keeps that project: its job can be one project
    while most of its runs land in another.  Any other session's launched runs vote, each for
    its `run_project` from the moment it is queued; a run belonging to no checkout has no vote
    (`session_vote`).  A tie or no votes keeps the filing.  Returns the project the session
    has after the count.

    `runs` are run records a draw or a tick has already read, and from them only a session
    that still has no project when its turn at the lock comes is filed: a launch's own count,
    taken from disk, is never overwritten by one read before that launch's run was there.
    """
    if not session:
        return None
    try:
        session = config.resolve_session(session)
    except config.Error:
        return None
    # One count at a time per session: a count taken before a later launch's run was on
    # disk must not be written after that launch's, or the minority wins until the next.
    with notify.session_lock(session) as session:
        record = config.session_records().get(session)
        if record is None:
            return None
        repo = record.get("repo")
        if not record.get("filed") and (runs is None or not repo):
            repo = session_vote(session, (run_record.read_state(directory) or {} for directory in run_record.run_dirs())
                                if runs is None else runs, repo)
            if repo != record.get("repo"):
                config.update_session(session, repo=repo)
        return repo


def session_vote(session, states, repo=None):
    """The project most of the runs `session` launched, among `states`, belong to.

    `repo` is the project the session has: a tie keeps it, else goes to the first by name,
    and a session none of whose runs votes keeps it too.
    """
    votes = Counter()
    for state in states:
        try:
            if launched_session(state) != session:
                continue
        except config.Error:
            continue
        checkout = run_project(state)
        if checkout is not None:
            votes[str(checkout)] += 1
    if not votes:
        return repo
    most = max(votes.values())
    if votes.get(repo) == most:
        return repo
    return min((voted for voted, count in votes.items() if count == most),
               key=lambda voted: (Path(voted).name, voted))


def stamp_origin(state):
    """Stamp this launch's test origin on a run state going to disk, if it has one.

    A run launched while the sink marker is set records the marker's value in
    run.json, so everything that later speaks for the run obeys the record --
    the launching seat may be long gone and the reaping process unmarked.
    A run.json without the record is the owner's run and behaves as today: an
    empty stamp writes nothing.
    """
    marker = (os.environ.get(notify.SINK_ENV) or "").strip()
    if marker:
        state.setdefault("notify_sink", marker)
    return state


@contextmanager
def speaking_for(state):
    """The destination anything said for this run goes to: its launch record.

    A run launched under the sink marker sends its notices to that sink or
    nowhere, never to the owner's webhook -- even when `ak watch` reaps it
    hours later with no marker in its own environment.  A run.json without the
    record leaves the environment alone, which is today's behaviour exactly.
    """
    marker = state.get("notify_sink") if isinstance(state, dict) else None
    if not marker:
        yield
        return
    previous = os.environ.get(notify.SINK_ENV)
    os.environ[notify.SINK_ENV] = marker
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(notify.SINK_ENV, None)
        else:
            os.environ[notify.SINK_ENV] = previous


def redress_seat(session):
    """Rewrite the bar of the seat that launched a run now, not at the next tick or draw.

    A run's step, round and ending are what the bar names, so each one is published the moment
    it happens, through the one writer the tick uses and from the facts already on record: no
    look at the seat's screen.  The writer waits on the seat's lock and on tmux, so the run
    hands it to a `run-shell -b` job on the seats' own server (`publish_seat`) and waits on
    neither.  The handoff times out after a second; the next tick or step repairs a missed
    update.  The job is the server's, not the run's: the run's exit, the stop of its scope and
    its marker sweep leave it be.  A seat tmux has lost, and a legacy one on the user's own
    server, is no target there, so nothing runs for it; nothing here ever raises into the run.

    Every open menu hears of it first, whatever tmux holds: the run touches the one file they
    watch (`config.runs_moved_path`), which takes no lock, so the seat's row moves with its bar
    though the seat's word stays as it was -- a legacy seat's and a gone seat's rows included.
    """
    if not session:
        return
    try:
        config.runs_moved_path().touch()
    except OSError:
        pass   # the next draw's own read, or the menu's timer, catches up
    publish = shlex.join([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                          "from agentkit import run; run.publish_seat(sys.argv[2])",
                          str(config.REPO), session])
    try:
        # silent and always 0: tmux shows a job's output, or its failure, in the seat's pane
        orch.tmux_out("run-shell", "-b", "-t", f"={session}:",
                      orch.tmux_text(f"{publish} >/dev/null 2>&1; true"),
                      socket=orch.socket_name(), timeout=1)
    except Exception:  # noqa: BLE001 - the bar is dressing; the run beneath it is what matters
        pass


def publish_seat(session):
    """`redress_seat`'s job: that seat's bar, if tmux still holds it on agentkit's own server."""
    seat = orch.find(session)
    if seat is not None and orch.on_own_server(seat):
        watch.announce_state(seat)


def seat_tallies(records, now=None):
    """What the runs each seat launched add up to: {seat: (running, needing him, merged)}.

    `running` is the runs still going of their own accord -- `going`, the same test the
    seat row's own reason counts, so `1 running` on the row and `1 running` in this tally can
    never disagree about a run parked on a window; the second figure is the endings still his
    -- menu.v5o_needs_look, again the test the row's reason reads; `merged` the merges of the
    last gc.GC_AGE.  From records already
    read, so the menu draws its rows and lists its runs from one pass over run.json, and
    read-only: nothing here reaps or writes.  A seat that launched nothing is not in the answer
    at all, and a record whose seat cannot be resolved counts for nobody.
    """
    from . import menu
    now = time.time() if now is None else now
    states = list(records)
    index = supersession_index(states)
    found = {}
    for state in states:
        try:
            seat = launched_session(state)
        except config.Error:
            continue
        if not seat:
            continue
        counts = found.setdefault(seat, [0, 0, 0])
        if going(state):
            counts[0] += 1
        elif menu.v5o_needs_look(state, None, index, now):
            counts[1] += 1
        elif state.get("merged"):
            finished = state.get("finished_at") or state.get("started_at")
            if isinstance(finished, (int, float)) and now - gc.GC_AGE <= finished <= now:
                counts[2] += 1
    return {seat: tuple(counts) for seat, counts in found.items()}


def notice_title(state):
    """The run's title for the notice, with every path token dropped.

    A word carrying `/` or `~` is a path, and a path on this line is the worst of both: long
    enough to push the rest off it, and useless on the phone that reads it.  result.md has the
    paths, and `ak run status` names result.md.
    """
    words = (state.get("title") or state.get("run_id") or "agentkit run").split()
    return " ".join(word for word in words if "/" not in word and "~" not in word)


@contextmanager
def launcher_world(session):
    """Look for that seat in either world that may hold it, and act in the one that found it.

    Yields whether anybody is in it.  Finding the seat and typing into it have to happen in
    the same environment: a lookup that only succeeded with the suite's redirect lifted would
    otherwise be followed by a send that puts the redirect back and aims at the wrong server.
    See `launcher_watched` for why the inherited lookup always goes first.  Read-only either
    way: no seat is made, killed or attached, and the environment is always put back.
    """
    if orch.watching(session):
        yield True
        return
    dropped = {}
    for key in (orch.SOCKET_ENV, "TMUX_TMPDIR"):
        if key in os.environ:
            dropped[key] = os.environ.pop(key)
    try:
        yield orch.watching(session)
    finally:
        os.environ.update(dropped)


def launcher_watched(session):
    """Whether the seat that launched this run is still up, in either world that may hold it.

    The run inherits its launcher's environment, and a suite running inside a live seat
    points the seat lookup at servers of the suite's own ($AGENTKIT_TMUX_SOCKET and
    $TMUX_TMPDIR, the isolation check 0 of tests/smoke.sh requires): asking only there
    mistakes a live launcher seat for a gone one, and a run nobody orphaned reports an
    orphan.  But $TMUX_TMPDIR is also legitimately set (orch.job_env keeps it precisely
    so a child reaches the same servers), so the inherited lookup -- which keeps it --
    always goes first and its answer stands: the redirect is lifted for a second lookup
    only when the first already missed, which is exactly the suite's shape.  Read-only
    either way: no seat is made, killed or attached.
    """
    with launcher_world(session) as live:
        return live


def handback_verdict(state, cfg=None):
    """The words a hand-back line may carry about how a run ended.

    `PASS merged`, `PASS not merged`, `DONE`, `FAIL`, `BLOCKED`, `ERROR` -- the delivery outcome, not
    the review verdict, because what the orchestrator decides next turns on where the work
    went and not on what the reviewer thought of it.
    """
    if state.get("state") == "not_needed":
        return "DONE"
    if state.get("state") == "blocked":
        return "BLOCKED"
    if state.get("state") == "error":
        return "ERROR"
    if not delivery(state, report_config(cfg)).startswith("PASS"):
        return "FAIL"
    return "PASS merged" if state.get("merged") else "PASS not merged"


def handback_reason(state, cfg=None):
    """The one line after the verdict: why it ended that way, in the run's own words."""
    if state.get("state") == "not_needed":
        return " ".join(delivery(state, cfg).split())
    if state.get("state") in ("blocked", "error", "waiting"):
        return " ".join((state.get("error") or "no reason was recorded").split())[:300]
    # A memory-cap death is the whole news: rounds and findings say nothing about a
    # run the kernel stopped before it could finish a turn.
    cap_line = " ".join((state.get("error") or "").split())
    if cap_line.startswith("killed: memory cap"):
        return cap_line[:300]
    if state.get("state") not in run_record.ENDED and needs_recovery(state):
        # an interruption, or a stop no window will lift: what stopped it is the whole news,
        # and rounds and findings say nothing about a run that never reached its verdict.  A
        # resumed attempt that did reach one is an ending, `recovery_pending` or not, and says
        # what every other ending says.  Its own full stop goes: the line puts one after it.
        return " ".join(recovery_reason(state).split()).rstrip(".")[:300]
    word = delivery(state, report_config(cfg))
    if word.startswith("PASS, not merged: "):
        reason = word[len("PASS, not merged: "):]
        retry = retry_command(state)
        return f"{reason}; retry delivery: {retry}" if retry else reason
    if word.startswith("PASS"):
        return state.get("pr") or word[len("PASS, "):]
    # a FAIL hands back what the next step turns on: the rounds it spent and why they did
    # not pass -- the findings themselves, or the check still failing
    spent = len(state.get("round_summaries") or [])
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    if review_failed(state):
        rows = hand_in.Review(state["review_records"]).findings
        said = " ".join("\n".join("- " + hand_in.item_text(row) for row in rows).split())
        if len(said) <= 600:
            return f"after {spent} rounds, open findings: {said}".rstrip(".")
        # a line cut short must not read as the whole list: a fix of what it shows alone
        # spends the next round on the rest, so it names the reviewer's whole report
        count = f"{len(rows)} open findings" if len(rows) != 1 else "1 open finding"
        where = state.get("findings_file")
        whole = f" (every one in full: {where})" if where else ""
        return f"after {spent} rounds, {count}, cut short here{whole}: {said[:600]}".rstrip(".")
    # else a PASS the loop overrode says why it did, and a check still failing names its line
    why = "; ".join(filter(None, (review.get("overridden"), failed_check(state))))
    if why:
        return f"after {spent} rounds, {why}".rstrip(".")
    return " ".join((state.get("merge_note") or state.get("error")
                     or "no reason was recorded").split())[:300].rstrip(".")


def review_failed(state):
    """Blocking records distinguish a reviewer FAIL from a PASS the loop overrode."""
    return hand_in.Review(state.get("review_records") or []).verdict == "FAIL"


def failed_check(state):
    """The check a FAIL whose review passed still has failing, as the hand-back says it.

    The final check first, by the line `first_failure` read off it, else by the one its gate
    recorded; then the round's own done-when.  None when no check is failing.
    """
    history = state.get("done_when_failure")
    history = history if isinstance(history, dict) else {}

    def first(gate):
        for cmd, said in history.get(gate) or []:
            return f"`{cmd}` \u2014 {said}" if said else f"`{cmd}`"
        return None

    record = state.get("final_check") if isinstance(state.get("final_check"), dict) else {}
    if record.get("outcome") == "failed":
        where = record.get("where")
        if where == "round":
            rnd = record.get("round")
            loc = f"in round {rnd}" if rnd else "in round"
            log = f"see round-{rnd}/once.log" if rnd else "see once.log"
            return (f"the final check failed {loc}: "
                    + (record.get("line") or first("once") or log))
        if where == "landing":
            return ("the final check failed at landing: "
                    + (record.get("line") or first("once") or "see final-check.log"))
        return ("the final check failed: "
                + (record.get("line") or first("once") or "see final-check.log"))
    if first("every"):
        return f"the done-when failed: {first('every')}"
    return None


def planned_followups(state):
    """The review follow-ups a merge handed to its seat, as the ending's sentence about them."""
    entries = state.get("followup_plan") or []
    planned = [entry["outcome"] for entry in entries if "refused" not in entry]
    refused = [f"{entry['outcome']} ({entry['refused']})" for entry in entries
               if "refused" in entry]
    return ((f"Review follow-ups now in your plan, yours to build: {'; '.join(planned)}. "
             "Each is checked by the reviewer's probe until `ak plan check N` puts your fix's "
             "own test in its place. " if planned else "")
            + (f"Review follow-ups your plan refused, yours to judge: {'; '.join(refused)}. "
               if refused else ""))


def followup_report(state):
    """Keep everything a compact seat notice refers to in the run's result."""
    parts = []
    if state.get("followups"):
        parts += ["## Follow-ups", "",
                  *("- " + item.replace("\n", "\n  ") for item in state["followups"]), ""]
    if state.get("followup_plan"):
        parts += ["## Follow-up plan", "", planned_followups(state).strip(), ""]
    if state.get("followup_runs"):
        parts += ["## Fix runs", "", *("- " + name for name in state["followup_runs"]), ""]
    return "\n".join(parts)


def seat_notice(line, state, run_dir, brief, action="Decide the next step."):
    """A run line that fits stays unchanged; otherwise its files carry the whole news.

    Use the same bound as `ak tell`, including its byte limit, after every addition to the
    line. Never type even the compact form unless that bound accepts it and its full notice
    and follow-ups have been saved in result.md, including for an older pending ending.
    """
    from . import plan, tell
    if not tell.too_long(line):
        return line

    def shown(path):
        try:
            return f"~/{path.relative_to(Path.home())}"
        except ValueError:
            return str(path)

    result = run_dir / "result.md"
    where = shown(result)
    report = result.name
    parts = [brief, f"Result: {where}."]
    entries = state.get("followup_plan") or []
    count = len(state.get("followups") or entries)
    if count:
        parts.append(f"{count} review follow-ups in full in {report}.")
    planned = sum("refused" not in entry for entry in entries)
    if planned:
        parts.append(f"{planned} in your plan: {shown(plan.path(launched_session(state)))}.")
    refused = len(entries) - planned
    if refused:
        parts.append(f"{refused} refused by your plan; reasons in {report}.")
    if state.get("followup_runs"):
        parts.append(f"{len(state['followup_runs'])} fix runs named in {report}.")
    parts.append(action)
    if line.endswith(watch.FRESH_NOTE):
        parts.append(watch.FRESH_NOTE.lstrip("; "))
    compact = " ".join(parts)
    refusal = tell.too_long(compact)
    if refusal:
        raise config.Error(refusal)
    save_result(run_dir, notices=(line, followup_report(state)))
    return compact


def handback_line(state, run_dir, cfg=None, *, review_round=None):
    """The one line a finished run types into the seat that launched it.

    `run <id> finished <verdict>: <why>. Result: <path>. Decide the next step.` -- an ending
    is the orchestrator's to act on, so it gets the three things a decision needs and nothing
    else: what happened, where the whole of it is written down, and that the next move is its
    own.  The owner is never the fallback for a run that did not work out.  A FAIL whose
    reviews spent the whole round budget says so and says to split: the task was too big, not
    the worker.  A FAIL a check left behind says no such thing: more rounds of the same task
    would not have passed it either.  A scratch run names its workspace too: the files
    there are what it delivered.
    """
    workspace = (f" Workspace: {state['worktree']}."
                 if state.get("scratch") and state.get("worktree") else "")
    ending = (f"review round {review_round}/{state['rounds']} FAIL" if review_round is not None
              else f"finished {handback_verdict(state, cfg)}")
    action = ("Fix the findings and push to this PR; this run reviews the new head."
              if review_round is not None else "Decide the next step.")
    line = (f"run {run_dir.name} {ending}: "
            f"{handback_reason(state, cfg)}. Result: {run_dir / 'result.md'}.{workspace} "
            + (f"Started fix runs: {', '.join(state['followup_runs'])}. "
               if state.get("followup_runs") else "") + planned_followups(state)
            + action)
    spent = len(state.get("round_summaries") or [])
    if (state.get("state") == "fail" and (state.get("rounds") or 0) > 0
            and spent >= (state.get("rounds") or 0) and review_failed(state)):
        word = NUMBER_WORDS[spent] if 0 <= spent < len(NUMBER_WORDS) else str(spent)
        split = f" {word} rounds spent: split or re-scope"
        line += split
        action += split
    return seat_notice(line, state, run_dir, f"run {run_dir.name} {ending}.", action)


def already_handed_back(state):
    """Whether this ending -- and not an earlier attempt's -- has already been handed back.

    `handed_back` is when the line was typed.  A run that reached its ending after that was a
    later attempt, whose own ending nobody has heard, whatever mark a resume failed to clear
    left behind: `clear_delivery` drops it on every new attempt, and this is the belt under
    that.  An undated mark from an older record is taken at its word.
    """
    said, ended = state.get("handed_back"), (state.get("finished_at")
                                             or state.get("interrupted_at"))
    if not isinstance(said, (int, float)) or isinstance(said, bool):
        return bool(said)
    if isinstance(ended, (int, float)) and not isinstance(ended, bool):
        return said >= ended
    return True


def owes_ending(state):
    """Whether this ending still has to be said, and nothing has said it.

    `handed_back` is the orchestrator having been told and `reported` is the ending having
    been given to the owner instead -- an orphan notice that landed, or the runs list handing
    a gone seat's ending over when he opened it.  An ending with neither has been heard by
    nobody -- a resumed attempt that ended carries no pending flag at all, because `reap`
    leaves an ending to `announce` -- so the tick keeps offering it until one of them is true.
    Which is why no pending flag is consulted here: one is how a delivery says it has not
    happened yet, and having happened is the only thing that stops the offer.

    An acknowledgement is not one of those.  Opening a run in `r` or naming it to `ak run
    status` marks it looked at, which settles it for the menu and for him -- but the owner is
    never the fallback for a run that did not work out, so him having glanced at it cannot be
    what the orchestrator was owed.  The hand-back still goes.

    A `stopped` run owes nothing at all: the stop was deliberate, so there is no ending
    to hand back and no card to send.

    An error the tick will retry owes nothing either: the retry is the next step, and
    saying "decide the next step" every hour for a run that resumes itself is the
    person being needed when they are not.  The stamp going away -- the worktree
    gone, the task unparsable -- is what starts the telling again.
    """
    if state.get("state") == "stopped":
        return False
    if going(state) and state.get("state") == "error":
        return False
    return (state.get("state") in run_record.ENDED and not already_handed_back(state)
            and not state.get("reported"))


def clear_delivery(state):
    """Forget what the last attempt's ending said: this one owes an ending of its own.

    A resume and a delivery retry both carry the old record forward, and its delivery marks
    with it.  Left there, a `handed_back` from the attempt before would make every later tick
    skip the new ending as already said; a `recovery_notified` would make the next
    interruption keep quiet because an earlier one had already spoken; and `reported` would
    fold the new ending out of the menu.  Every one of them is the last attempt's word.
    """
    for key in ("handed_back", "handback_pending", "handback_typed", "handback_note",
                "handback_wait_reason", "notification_pending", "recovery_notified"):
        state.pop(key, None)
    state["reported"] = False
    return state


@contextmanager
def delivery_lock(run_dir):
    """The one delivery an ending gets, held from deciding to say it until it is said.

    The loop that finished a run and the `ak watch` tick that found it unheard can both be
    holding a snapshot of the same ending.  Without this they both type the line and then
    write their own snapshot back, one of them over the other's marks, and the seat reads the
    ending twice.  Its own file, apart from the recovery lock: `reap` already holds that one while it
    calls down to here.

    Reentrant within a thread, and counted here because flock is not: `mark_delivery` takes it
    for every write it makes, and `hand_back` holds it across the whole decision the write is
    the end of.
    """
    held = getattr(_DELIVERY_HELD, "paths", None)
    if held is None:
        held = _DELIVERY_HELD.paths = set()
    mine = str(run_dir)
    if mine in held:
        yield
        return
    held.add(mine)
    try:
        with (Path(run_dir) / "delivery.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    finally:
        held.discard(mine)


def same_attempt(state, record):
    """Whether these two are the same attempt of a run, and not one either side of a resume.

    A resume keeps the directory and the id and carries the record forward: a new process owns
    it, and the ending it had is cleared.  A snapshot from before that is about an attempt
    nobody is waiting on any more, so nothing it decided may be written to the one running now
    -- an old `handed_back` would silence the new ending for good, and an old `pending_inbox`
    clear would lose the new question.  Whose process it is and when it ended are what tell
    them apart; a record with neither, as an old receipt or a fixture has, is its own attempt.
    """
    return all(state.get(key) == record.get(key)
               for key in ("pid", "finished_at", "interrupted_at"))


def mark_delivery(run_dir, state, **marks):
    """Write what a run still owes somebody onto the record as it stands, and nothing else.

    Never the caller's whole snapshot: two processes can be holding one each, and a whole
    save would put the older one back over the newer's marks -- including the `handed_back`
    that is the only thing stopping a second line.  The read and the write are one stretch
    under `delivery_lock`, so nothing can land between them either, and the record has to
    still be the attempt the caller decided about -- see `same_attempt` -- or nothing is
    written at all.  A mark given as None is removed; `pending_inbox`, the merge question a
    run still owes the inbox, is written the same way and for the same reason.  The caller's
    own copy is updated too, so what it does next reads what the record says.  False when the
    record had moved on and the marks were dropped.
    """
    with delivery_lock(run_dir):
        current = run_record.read_state(run_dir)
        if current is None:
            current = dict(state)
        elif not same_attempt(state, current):
            return False
        for key, value in marks.items():
            if value is None:
                current.pop(key, None)
                state.pop(key, None)
            else:
                current[key] = state[key] = value
        # Past `save_state`'s guard on purpose: these are endings a stop always
        # refuses, so no stop can race them, and this lock plus that one in this
        # order would invert the order `reap` takes them in.  See `save_state`.
        run_record._write_state(run_dir, current, run_record.DELIVERY_TEMP)
        return True


def hand_back(state, run_dir, log, cfg=None):
    """Give the ending back to the live seat that launched it.  True when it was told.

    Typed into the seat's composer through the confirmed send, and only while its harness sits
    at its own prompt: a line typed into a turn in flight is swallowed.  Otherwise the record
    keeps `handback_pending` and the `ak watch` tick types it at the next quiet prompt, once.
    Call it inside `launcher_world`, so the seat is found and typed into where it was seen.

    Exactly once, whoever gets here first: the deciding, the typing and the mark are one
    stretch under `delivery_lock`, and whoever arrives second reads the record as it stands,
    sees the line was said and says nothing.  A delivered hand-back ends every other errand
    this run had -- `handed_back` says the ending is the orchestrator's for good, and an
    orphan notice left pending from a death the seat has since come back from is over,
    because the thing it was pending about has just been said.
    """
    session = launched_session(state)
    seat = orch.find(session) or {"name": session}
    with delivery_lock(run_dir):
        said = run_record.read_state(run_dir) or state
        if not same_attempt(state, said):
            # the run was resumed since this ending: nobody is waiting on it any more, and
            # the attempt running now will hand back an ending of its own
            log(f"run {run_dir.name} has moved on since this ending; nothing to hand back")
            return False
        if already_handed_back(said):
            state["handed_back"] = said["handed_back"]
            log(f"run {run_dir.name} was already handed back to the {session} seat")
            return True
        if (said.get("state") in run_record.ENDED and not said.get("handback_pending")
                and not said.get("notification_pending") and watch.is_preexisting(said)):
            mark_delivery(run_dir, state, handed_back=time.time(),
                          handback_note=watch.PREEXISTING_NOTE, handback_pending=None,
                          handback_wait_reason=None, notification_pending=None)
            log(f"run {run_dir.name} is a {watch.PREEXISTING_NOTE}")
            # The seat is not going to read the tree: the ending is history.
            worktrees._drop_told(run_record.read_state(run_dir) or state, log, run_dir)
            return True
        line = handback_line(state, run_dir, cfg)
        if watch.type_at_prompt(seat, line, log, cfg=cfg, typed=said.get("handback_typed"),
                                receipt=lambda mark: mark_delivery(run_dir, state,
                                                                   handback_typed=mark)):
            mark_delivery(run_dir, state, handed_back=time.time(), reported=True,
                          handback_pending=None, handback_typed=None, handback_note=None,
                          handback_wait_reason=None, notification_pending=None)
            log(f"handed run {run_dir.name} back to the {session} seat")
            # The seat was told. It reads result.md, not the checkout.
            worktrees._drop_told(run_record.read_state(run_dir) or state, log, run_dir)
            return True
        if not said.get("handback_pending") or state.get("handed_back"):
            # an ending is either said or waiting to be, never both: a mark the attempt
            # before this one left is neither, and goes with the same write
            mark_delivery(run_dir, state, handback_pending=True, handed_back=None,
                          handback_note=None)
    log(f"the {session} seat is not at its prompt; the tick hands run {run_dir.name} back")
    return False


def announce_safely(state, run_dir, log, cfg=None):
    """`announce`, for a caller whose own news outranks anything the hand-back can fail on."""
    try:
        announce(state, run_dir, log, cfg)
    except (config.Error, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
        log(f"WARN the ending was not handed back: {exc}")


def announce(state, run_dir, log, cfg=None):
    """The one message a run sends when it ends: to its orchestrator, or about a gone one.

    A run under an open seat is handed back to it -- one line into its composer saying how the
    run ended and that the next step is its own -- because the ending is the orchestrator's and
    never the owner's.  A run launched from no seat at all -- by hand, over ssh, from cron,
    from a test -- has nobody to hand back to and nobody to ping: its result is on the terminal
    it was started from and in `ak run status`.  The repair a red target started belongs to
    the seat whose run found it red, and tells it only what needs somebody: a merge or a
    `not needed` is routine, and the runs parked on it retry by themselves.  Only an orphan
    speaks to the owner, and first to its own seat: the seat is reopened on its saved
    conversation and told to continue, and the owner hears only when that fails -- or when
    there is no seat to reopen, one `ak orch stop` ended or one nothing is left of, which is
    asked of them as before.

    A run that reached a final state is an ending whatever else its record carries: a resume
    leaves `recovery_pending` behind it, and that is not unfinished work -- there is nothing
    left to resume -- so it hands back like any other ending rather than going round the
    recovery path again.

    A `stopped` run is the exception: the stop was deliberate, so it is handed back
    nowhere and no card goes out for it.  A run parked `waiting` is no ending either: it
    resumes itself after the next merge upstream, exactly as one sitting out a provider
    window, so it is handed back nowhere and nobody is told.  An error the tick will retry
    is the same: its retry is already scheduled, so there is no ending to tell.
    """
    if state.get("state") == "stopped":
        return
    if going(state) and state.get("state") == "error":
        return
    session = launched_session(state)
    if needs_recovery(state) and state.get("state") not in run_record.ENDED:
        # Inside a job the scheduler owns recovery: a run the job is adopting right now is
        # resumed by the job itself seconds later, and a recovery notice would be per-task
        # noise contradicting what happens next.
        if getattr(jobs._JOB_MUTE, "adopt", None):
            return
        reap(run_dir, state)
        return
    if state.get("state") not in run_record.ENDED:
        return
    if not session or state.get("repair") and (state.get("merged")
                                               or state.get("state") == "not_needed"):
        return
    with launcher_world(session) as live:
        if live:
            hand_back(state, run_dir, log, cfg)
            return
    if state.get("state") == "not_needed":
        mark_delivery(run_dir, state, reported=True, handback_pending=None,
                      handback_wait_reason=None, notification_pending=None)
        return
    if getattr(jobs._JOB_MUTE, "depth", 0) or jobs.job_started(state):
        # a job task's orphan is on the job's own card, never a per-task one -- and the
        # record has to say the ending went somewhere, or the tick, which runs in another
        # process with no thread-local mute of its own, would offer it again on every pass
        mark_delivery(run_dir, state, reported=True, handback_pending=None)
        return
    if state.get("review_pr"):
        # A review has no executor task for the owner to continue, so no orphan card asks them
        # to; GitHub and the inbox carry the verdict, and the watcher retries an unpublished one.
        return
    # History is never replayed, even when the run's own loop meets it directly -- but only
    # when first seen unmarked; a pending mark is the record of having been seen.
    with delivery_lock(run_dir):
        current = run_record.read_state(run_dir) or state
        if not same_attempt(state, current):
            log(f"run {run_dir.name} has moved on since this ending; nothing to hand back")
            return
        if (not current.get("handback_pending") and not current.get("notification_pending")
                and watch.is_preexisting(current)):
            mark_delivery(run_dir, state, handed_back=time.time(),
                          handback_note=watch.PREEXISTING_NOTE, handback_pending=None,
                          handback_wait_reason=None, notification_pending=None)
            log(f"run {run_dir.name} is a {watch.PREEXISTING_NOTE}")
            return
        state.update({k: current[k] for k in (
            "handed_back", "handback_pending", "handback_note", "handback_wait_reason",
            "notification_pending", "reported") if k in current})
    # A seat the owner closed stays closed: the hand-back waits for its reopening, recorded as
    # waiting with the reason, and never as a revival.  Already waiting is left alone: no
    # rewrite and no second line every tick.
    if watch.seat_closed_by_owner(session):
        with delivery_lock(run_dir):
            current = run_record.read_state(run_dir) or state
            if not same_attempt(state, current):
                log(f"run {run_dir.name} has moved on since this ending; nothing to hand back")
                return
            if (current.get("handed_back") is False and current.get("handback_pending")
                    and current.get("handback_wait_reason") == watch.OWNER_CLOSED_REASON):
                state.update(current)
                return
            mark_delivery(run_dir, state, handed_back=False, handback_pending=True,
                          handback_wait_reason=watch.OWNER_CLOSED_REASON, handback_note=None,
                          notification_pending=None)
        log(f"run {run_dir.name} waits for the {session} seat "
            f"({watch.OWNER_CLOSED_REASON})")
        return
    # the seat is gone, so a hand-back left pending for it is over: whatever happens below
    # is what this run says now, and the tick must not come back here every pass for it
    mark_delivery(run_dir, state, handback_pending=None, handback_wait_reason=None)
    task = state.get("title") or state.get("run_id") or run_dir.name
    verdict = ("DONE" if state.get("state") == "not_needed" else
               "PASS" if delivery(state, report_config(cfg)).startswith("PASS") else "FAIL")
    why = ""
    # A pre-existing ending with a stuck card keeps its retry below, but never wakes its seat.
    if (not watch.seat_closed(session) and watch.orphan_fresh(state, session)
            and not watch.is_preexisting(state)):
        log(f"the orchestrator session {session} this run was launched from is gone; "
            "reopening it")
        why = watch.revive(session, f"continue {task}: run {run_dir.name} finished {verdict}, "
                                    f"result at {run_dir / 'result.md'}", log,
                           prepare=lambda line: seat_notice(
                               line, state, run_dir, f"run {run_dir.name} finished {verdict}."))
        if why is None:
            log(f"reopened {session} and asked it to continue {run_dir.name}")
            mark_delivery(run_dir, state, reported=True, notification_pending=None)
            return
    log(f"the orchestrator session {session} this run was launched from is gone; "
        "asking the user to continue the task")
    line = (f"Its orchestrator session {session} is gone. Run finished: {verdict}. "
            f"Press n in the menu, then say: continue {task}."
            + (f" agentkit tried to reopen the seat and could not: {why}" if why else ""))
    mark_delivery(run_dir, state, notification_pending=True)
    event_id = f"orphan:{run_dir.name}:{state.get('started_at')}:{state.get('finished_at')}"
    with speaking_for(state):
        done = notify.shaped("needs", line, session=session, event_id=event_id) == 0
    if done:
        mark_delivery(run_dir, state, reported=True, notification_pending=None)
    else:
        log("WARN orphan notification was not accepted; retry required")


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


def run_depth():
    value = os.environ.get("AK_RUN_DEPTH", "0")
    if not value.isascii() or not value.isdigit():
        raise config.Error("AK_RUN_DEPTH must be a non-negative integer")
    return int(value)


def depth_refused():
    depth = run_depth()
    if depth < 2:
        return False
    print(f"a worker's worker may not start runs (depth {depth}); "
          "only the orchestrator, and a worker for its tests, may", file=sys.stderr)
    return True


def run_child_env():
    """The next depth and the run's marker, including to a job thread's done-when commands."""
    state = getattr(_RUN_CONTEXT, "state", {})
    env = {**config.seatless_env(),
           "AK_RUN_DEPTH": str(state.get("run_depth", run_depth()) + 1),
           "AK_PARENT_RUN": state.get("parent_run") or state.get("run_id") or
                            os.environ.get("AK_PARENT_RUN", "")}
    if state.get("run_id"):
        # The marker every process of this run carries, so the run's end -- and every
        # killed turn, every retry and every finished gate -- finds them however detached.
        env[worker.RUN_MARKER] = worker.run_marker(state["run_id"])
    return env


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


def needs_recovery(state):
    """Work a resume could still carry on.  `blocked` never is: the task itself is wrong.

    A resume leaves `recovery_pending` on the record it starts from, so an attempt that ends
    `blocked` would otherwise be offered for recovery it is refused -- see `cmd_resume`.
    A `stopped` run is a deliberate end, never an accident to offer back. Line
    members belong to the lander even if an earlier attempt left a recovery mark.
    """
    return (not landing_line(state) and
            state.get("state") not in (*run_record.ACTIVE, "pass", "blocked", "stopped", "not_needed") and
            (state.get("state") in ("interrupted", "exhausted", "stalled", "waiting_login") or
             bool(state.get("recovery_pending"))))


def recovery_reason(state):
    return ((state.get("error") if state.get("state") in ("error", "exhausted", "stalled",
                                                          "waiting_login") else None) or
            ("Resume attempt failed; `ak run status` shows the failed checks or review."
             if state.get("state") == "fail" and state.get("recovery_pending") else None) or
            state.get("interruption_reason") or
            state.get("error") or "The run stopped before recording completion.")


def interrupt(state, reason):
    state.update(state="interrupted", interrupted_at=time.time(),
                 interruption_reason=reason, recovery_pending=True)
    # finished_at and the review verdict describe completion, never detection of a dead loop.
    return state


def notify_recovery(run_dir, state):
    """Hand an unfinished run to its seat once, or use the existing needs-you fallback.

    Only for work that stopped without a verdict.  A run that reached a final state is an
    ending, `recovery_pending` or not, and `announce` owns it: saying it here too would hand
    the same line back twice, and escalate one already delivered to the owner once the seat
    closed.
    """
    if state.get("state") in run_record.ENDED or state.get("handed_back"):
        return  # an ending is announce's, and one already said is nobody's to say again
    if getattr(jobs._JOB_MUTE, "adopt", None):
        return  # the job resumes this run itself; a notice would contradict what happens next
    if state.get("state") == "stalled":
        return  # the tick told the seat (or sent the one card) when it parked the run
    if state.get("state") == "exhausted" and state.get("quota_dry"):
        return  # it waits for a provider window and resumes itself there; nobody is told
    if state.get("state") == "waiting_login":
        return  # ... and a run waiting on a login is the one card the babysitter already sent
    if (state.get("recovery_notified") or state.get("recovery_acknowledged_at") or
            os.environ.get("AK_RUN_ROLE") == "worker"):
        return
    owner = launched_session(state)
    if not owner:
        return                      # a by-hand run has no originating orchestrator
    log = logger(run_dir)
    # What the run says is worth reading when it is handed back, so it is written first: an
    # interruption has no result of its own, and a resumed one would otherwise point at the
    # attempt before it.
    record_result(run_dir, state, log)
    # A stop nothing will lift is an ending like any other, so the seat that launched it hears
    # the one line every ending uses, at its own prompt, and the owner is never asked instead:
    # a seat mid-turn leaves `handback_pending` for the tick, as a finished run does.
    with launcher_world(owner) as live:
        if live:
            # marked after the hand-back's own mark, or a concurrent reap would find none
            # and say it all over again; a line still pending is tried at the next quiet prompt
            if hand_back(state, run_dir, log):
                mark_delivery(run_dir, state, recovery_notified="orchestrator")
            return
    line = (f"Run {run_dir.name} ({notice_title(state)}) is unfinished: {recovery_reason(state)} "
            f"Run `ak run status {run_dir.name}` to look and `ak run resume {run_dir.name}` to resume. "
            "Do not automatically rerun it; check for effects from the interrupted attempt.")
    # A seat the owner closed stays closed: the interruption waits with the endings, for
    # the reopening that delivers them, and never reopens the seat itself.  Already waiting is
    # left alone: no rewrite and no second line every tick.
    if watch.seat_closed_by_owner(owner):
        with delivery_lock(run_dir):
            current = run_record.read_state(run_dir) or state
            if not same_attempt(state, current):
                log(f"run {run_dir.name} has moved on since this ending; nothing to hand back")
                return
            if (current.get("handback_pending")
                    and current.get("handback_wait_reason") == watch.OWNER_CLOSED_REASON):
                state.update(current)
                return
            mark_delivery(run_dir, state, handback_pending=True,
                          handback_wait_reason=watch.OWNER_CLOSED_REASON)
        log(f"run {run_dir.name} waits for the {owner} seat "
            f"({watch.OWNER_CLOSED_REASON})")
        return
    # The seat is gone, so it is brought back on its own conversation and told, exactly as an
    # ending's orphan path does; the owner hears only when there is no seat to bring back.  An
    # interruption old enough to be history keeps its card retry below, but never wakes its seat.
    why = ""
    if (not watch.seat_closed(owner) and watch.orphan_fresh(state, owner)
            and not watch.is_preexisting(state)):
        log(f"the orchestrator session {owner} this run was launched from is gone; reopening it")
        why = watch.revive(owner, line, log, prepare=lambda line: seat_notice(
            line, state, run_dir, f"run {run_dir.name} is unfinished."))
        if why is None:
            log(f"reopened {owner} and asked it to take up {run_dir.name}")
            mark_delivery(run_dir, state, recovery_notified="orchestrator",
                          handback_pending=None, handback_wait_reason=None)
            return
        line += f" agentkit tried to reopen the seat and could not: {why}"
    event_id = f"recovery:{run_dir.name}:{state.get('interrupted_at')}"
    with speaking_for(state):
        if notify.shaped("needs", line, session=owner, event_id=event_id) == 0:
            mark_delivery(run_dir, state, recovery_notified="needs", handback_pending=None,
                          handback_wait_reason=None)


# One run's memory, below the slice ceiling.  40% of that ceiling: a leak has to die
# inside its own scope, while the seat slice -- accounted apart, and with the higher
# weight -- is never the thing the kernel throttles.  Swap is capped at the same size
# so the excess cannot hide there.  4 GB is only the fallback where there is no
# ceiling to read.
RUN_MEMORY_DEFAULT_MB = 4096
RUN_MEMORY_SHARE = 40


def scope_is_real(scope):
    """Whether `scope` names a unit systemd actually holds, not a plain start."""
    return (isinstance(scope, str) and bool(scope) and scope != "none"
            and not scope.startswith("none"))


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


def memory_cap_line(mb):
    """The reason a run that hit `mb` mebibytes records: `killed: memory cap N GB`."""
    gb = mb / 1024
    if abs(gb - round(gb)) < 1e-9:
        shown = str(int(round(gb)))
    else:
        shown = f"{gb:.2f}".rstrip("0").rstrip(".")
    return f"killed: memory cap {shown} GB"


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


def _scope_units(scope):
    """The unit names a receipt's scope might be, scope first."""
    if not isinstance(scope, str) or not scope:
        return ()
    if scope.endswith(".scope") or scope.endswith(".service"):
        return (scope,)
    return (f"{scope}.scope", f"{scope}.service")


def _systemctl_fields(unit):
    """(Result, ControlGroup, OOMPolicy) for `unit`, or (None, "", "") when the manager
    cannot be asked.

    A unit it does not have is an empty Result, not a failure to ask: the caller
    tries the other suffix.  The labelled properties are parsed by name because
    `--value` does not promise the order they were requested in.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ControlGroup",
             "-p", "LoadState", "-p", "OOMPolicy"],
            capture_output=True, encoding="utf-8", errors="replace",
            env=orch.bus_env(), timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None, "", ""
    if proc.returncode != 0:
        return None, "", ""
    fields = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    if fields.get("LoadState") == "not-found":
        return "", "", ""
    return fields.get("Result", ""), fields.get("ControlGroup", ""), fields.get("OOMPolicy", "")


def _scope_oom_probe(state):
    """(systemd Result, oom_kill count) for the run's scope.  Either witness is enough.

    A scope that goes on past a kill (OOMPolicy=continue) counts none: the kill ended one
    process, and a loop dead in it later died of something else.
    """
    result, kills = "", 0
    for unit in _scope_units(state.get("scope")):
        shown, cgroup, policy = _systemctl_fields(unit)
        if shown is None:
            continue
        if policy != "continue":
            kills = max(kills, host._oom_kill_count(cgroup))
        if shown:
            result = shown
        if result == "oom-kill" or kills:
            return result, kills
    return result, kills


def memory_cap_reason(state, probe=None):
    """The memory-cap line when this scope was ended by its own cap, else None.

    A run that was not given a cap cannot have been killed by one, and a plain
    start has no scope to ask.  `probe` returns the unit Result and the oom_kill
    count so a test never asks the real manager.  Anything unreadable is not a
    memory kill: a dead loop with no witness stays the interruption it always was.
    """
    cap = state.get("memory_cap_mb")
    if type(cap) is not int or cap <= 0 or not scope_is_real(state.get("scope")):
        return None
    probe = _scope_oom_probe if probe is None else probe
    try:
        result, kills = probe(state)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return None
    if result == "oom-kill" or (type(kills) is int and kills > 0):
        return memory_cap_line(cap)
    return None


# "<cgroup> <oom_kill count>" this loop has logged.  In the environment, because a loop that
# picks up new code replaces its interpreter (`pickup_new_code`) in the same scope, and must
# not say those kills again; a resume in a new scope is a new process that starts without it.
OOM_LOGGED = "AK_MEMORY_CAP_LOGGED"
_OOM_LOCK = threading.Lock()   # a reviewer and a suite can end on two threads at once


def memory_cap_note(run_dir, log):
    """Log each process the kernel ended at this run's memory cap since the last look.

    Called as each worker turn and each done-when command ends.  That is all it does: the
    turn or command the kill ended goes on or ends the run as any failed command or killed
    worker does.  The count is the cgroup's this loop runs in, and only when that is the
    run's own scope: a run from a seat's shell sits in the seat's, whose kills are not its.
    """
    state = run_record.read_state(Path(run_dir)) or {}
    cap, scope = state.get("memory_cap_mb"), state.get("scope")
    if type(cap) is not int or cap <= 0 or not scope_is_real(scope):
        return
    cgroup = host.process_cgroup()
    if cgroup is None:
        return
    cgroup = cgroup.strip().rstrip("/")
    if cgroup.rsplit("/", 1)[-1] not in _scope_units(scope):
        return
    with _OOM_LOCK:
        where, _, said = os.environ.get(OOM_LOGGED, "").rpartition(" ")
        seen = int(said) if where == cgroup and said.isdigit() else 0
        kills = host._oom_kill_count(cgroup)
        if kills > seen:
            os.environ[OOM_LOGGED] = f"{cgroup} {kills}"
    for _ in range(kills - seen):
        log(f"{memory_cap_line(cap).removeprefix('killed: ')} hit: "
            "the process that grew was ended")


def conclude_memory_cap(run_dir, state, reason):
    """End the run `fail` on its memory cap, and stop the scope that hit it.

    The loop that was inside the scope is already dead, so the reason is written
    from outside: `log.txt`, `result.md`, and the state the hand-back reads.
    Stopping the scope is what returns the memory; the kernel has usually killed
    the processes already, and the stop collects whatever it missed.  It is not
    an interruption: resuming a leak repeats it.
    """
    state.update(state="fail", verdict="FAIL", finished_at=time.time(), error=reason)
    for key in ("recovery_pending", "interruption_reason", "interrupted_at",
                "waiting_for", "login_resume_at", "login_back_at"):
        state.pop(key, None)
    run_record.save_state(run_dir, state)
    try:
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(f"[{datetime.now():%H:%M:%S}] {reason}\n")
    except OSError:
        pass
    record_result(run_dir, state)
    # The reaper is outside the scope -- the loop is already dead -- so it can
    # wait for the stop.  That is what puts the memory back before the tick
    # moves on, instead of leaving systemctl running uncollected.
    stop_run_tree(state, wait=True)
    history_finish(state)
    try:
        redress_seat(launched_session(state))
    except config.Error:
        pass
    return state


def stop_run_tree(state, log=lambda _: None, wait=False):
    """End everything a run started: its marked processes, then its scope.

    The marker sweep is the backstop that runs everywhere: a plain host has no scope at
    all, and a scope the manager never made answers the stop with nothing stopped. The
    scope stop goes last and, by default, is fire-and-forget -- the loop calling it is
    usually inside that scope and on its way out, so nothing of ours still runs after
    it is asked.  A caller that is already outside the scope, the reaper after a
    memory-cap death, passes `wait` so the stop finishes and the memory is back.
    Never only a process group: a child that left its group is still the run's.
    One sweep ends the run's children too: the marker match covers `<marker>/...`.
    """
    scope = state.get("scope") if isinstance(state, dict) else None
    run_id = state.get("run_id") if isinstance(state, dict) else None
    if run_id:
        worker.kill_marked(worker.run_marker(run_id), log=log)
    orch.stop_scope(scope, log, wait=wait)


def tick_resumes(state):
    """A dead loop the tick continues itself, so its death is nobody's news.

    The dead-loop pass resumes a run whose loop process is gone in the tick that notices
    it, and puts the record straight back: an interruption a menu look reaped in between
    is one about to be undone, and spending the run's one recovery card on it would tell
    the seat about a death nobody had to answer.  A death the pass has given up on -- the
    third within an hour, which it parks itself -- and a launch that never got as far as a
    worktree are what is left for a person.
    """
    deaths = state.get("deaths") or []
    if deaths and isinstance(deaths[-1], dict) and deaths[-1].get("parked"):
        return False
    # Exactly what the pass itself will carry on, so the two never disagree over one
    # record: without a workspace to go back to there is nothing to continue, and a
    # recorded worktree that has gone is the one it hands back to a person.
    wt = state.get("worktree")
    return bool(wt) and Path(wt).is_dir()


def reap(run_dir, state, memory_probe=None):
    """Keep dead loops and abandoned launch receipts as unfinished, explicitly recoverable work.

    A scope the kernel ended for its memory cap is the exception: that is a `fail`,
    with the cap in the reason, not an interruption to resume.  `memory_probe`
    stands in for the manager so a test can say what the scope reported without
    asking a real one.
    """
    state = run_record.read_state(run_dir) or state
    if state.get("state") not in run_record.ACTIVE and not needs_recovery(state):
        if state.get("state") not in run_record.ENDED:
            return state
        # else: an ended run whose loop may have died before its final cleanup --
        # fall through and sweep what it left behind, once per loop
    with run_record.recovery_lock(run_dir):
        state = run_record.read_state(run_dir) or state  # a menu snapshot may predate a resume
        status = state.get("state")
        if status == "queued" and state.get("slot_waiting"):
            return state  # the tick adopts dead waiters without losing their place
        if status == "stalled":
            return state  # parked by the tick; only an explicit resume moves it
        resumed_at = state.get("stall_resume_at")
        if (status in run_record.ACTIVE and isinstance(resumed_at, (int, float))
                and not isinstance(resumed_at, bool)
                and 0 <= time.time() - resumed_at < STALL_RESUME_GRACE):
            return state  # the tick stopped this loop and ordered a resume; it adopts next
        holding = state.get("resume_after")
        if (status in run_record.ACTIVE and isinstance(holding, (int, float))
                and not isinstance(holding, bool) and time.time() < holding):
            return state  # the tick is waiting out this dead loop's backoff before its next try
        grace = (status == "queued" and
                 (state.get("launch_pending") or not state.get("process_identity")) and
                 time.time() - (state.get("queued_at") or state.get("started_at") or 0) < QUEUED_GRACE)
        if status in run_record.ACTIVE and not grace and not run_record.process_active(state):
            cap_reason = (memory_cap_reason(state, probe=memory_probe)
                          if status == "running" else None)
            if cap_reason:
                # Asked before the scope is stopped: the Result and the cgroup
                # events are what say it was the cap, and stopping drops them.
                conclude_memory_cap(run_dir, state, cap_reason)
            else:
                reason = ("Queued launcher exited before starting work." if status == "queued" else
                          "Run process exited or its identity changed.")
                if status == "running":
                    stop_run_tree(state)
                interrupt(state, reason)
                last = (state.get("deaths") or [None])[-1]
                if tick_resumes(state) and not (isinstance(last, dict) and not last.get("resumed_at")
                                                and last.get("pid") == state.get("pid")):
                    # Whoever notices the death records it, so the tick's dead-loop pass reads
                    # this record as a loop to carry on rather than as an interruption somebody
                    # was already told about -- and so it counts towards the third death. Once:
                    # one the tick recorded and held for its backoff is already there.
                    state["deaths"] = [*(state.get("deaths") or []),
                                       {"at": time.time(), "pid": state.get("pid"),
                                        "reason": reason}]
                run_record.save_state(run_dir, state)
        elif status == "interrupted" and not state.get("interrupted_at"):
            interrupt(state, state.get("error") or "Earlier interruption; detection time recorded now.")
            run_record.save_state(run_dir, state)
        if status in ("pass", *run_record.FAILED, "exhausted", "waiting_login",
                      "interrupted") and not run_record.process_active(state):
            swept = [state.get("pid"), state.get("process_identity")]
            if state.get("tree_stopped") != swept:
                # The loop recorded its ending and died before its final cleanup, so the
                # reaper ends what it left behind. Stamped with the loop it swept for:
                # every activation records a new pid, so a resumed run is swept again
                # without anyone clearing the stamp.
                stop_run_tree(state)
                state["tree_stopped"] = swept
                run_record.save_state(run_dir, state)
        # A death the tick resumes is nobody's news however many reaps see it before it does,
        # the tick's own included while it waits out a backoff.
        if needs_recovery(state) and not (state.get("state") == "interrupted" and state.get("deaths")
                                          and tick_resumes(state)):
            notify_recovery(run_dir, state)
    return state


def supersession_index(states):
    """Newest-first replacements per title and per branch: build once, then test runs
    without rescanning.

    `states` is an iterable of states, or `(run_dir, state)` pairs as `run_records`
    yields. Answers `{title: [(finished_when, run_id, display)]}` for merged runs
    with a title, and `{("from", repo, branch): [...]}` for every run relaunched
    `from:` a branch, each with a numeric finish (or start), newest first. Read-only.
    A merged relaunch is also answered under `{("merged-from", repo, branch): [...]}`,
    for the settled question, which only a merged replacement ends.
    """
    index = {}
    for item in states:
        other = item[1] if isinstance(item, (tuple, list)) and len(item) == 2 else item
        if not isinstance(other, dict):
            continue
        when = other.get("finished_at") or other.get("started_at") or 0
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        title = other.get("title")
        if other.get("merged") and title:
            index.setdefault(title, []).append(
                (when, other.get("run_id"), other.get("run_id") or title))
        if other.get("from"):
            entry = (when, other.get("run_id"), other.get("run_id") or other["from"])
            index.setdefault(("from", other.get("repo"), other["from"]), []).append(entry)
            if other.get("merged"):
                index.setdefault(("merged-from", other.get("repo"), other["from"]),
                                 []).append(entry)
    for entries in index.values():
        entries.sort(key=lambda entry: entry[0], reverse=True)
    return index


def superseded_by(state, records=None, index=None, merged_only=False):
    """The later run that replaced this one, or None. Read-only.

    A `↳` row appears only for a run nobody has replaced: a later merged run of the
    same title supersedes it, and so does a later run relaunched `from:` its branch in
    its repository, whatever that run's own ending -- the orchestrator took the work up
    again, and its title often says `(continued from its branch)`.  `r` names the
    replacement as `superseded by <run id>`.
    A merged run never supersedes itself. `records` is an iterable of states already
    read; when omitted the runs on disk are read once, never written. `index` is a
    `supersession_index` over the same states: pass it when testing many runs, so one
    draw scans the records once instead of once per run per seat. With `merged_only`
    only a replacement that merged counts: a relaunch still running settles nothing.
    """
    title, branch = state.get("title"), state.get("branch")
    if not (title or branch) or state.get("merged"):
        return None
    mine = state.get("finished_at") or state.get("started_at") or 0
    if not isinstance(mine, (int, float)) or isinstance(mine, bool):
        mine = 0
    if index is not None:
        relaunched = ("merged-from" if merged_only else "from",
                      state.get("repo"), branch)
        later = [(when, display) for when, run_id, display in (
                     *index.get(title, ()), *index.get(relaunched, ()))
                 if run_id != state.get("run_id") and when > mine]
        return max(later)[1] if later else None
    found = []
    if records is None:
        from . import menu  # here, not at the top: the menu draws without the loop
        for run_dir in run_record.run_dirs():
            other = run_record.read_state(run_dir)
            if other and not menu.smoke_run(other):
                found.append(other)
    else:
        for item in records:
            other = item[1] if isinstance(item, (tuple, list)) and len(item) == 2 else item
            if isinstance(other, dict):
                found.append(other)
    best, newest = None, mine
    for other in found:
        if merged_only and not other.get("merged"):
            continue
        if not ((title and other.get("merged") and other.get("title") == title) or
                (branch and other.get("from") == branch
                 and other.get("repo") == state.get("repo"))):
            continue
        if other.get("run_id") == state.get("run_id"):
            continue
        when = other.get("finished_at") or other.get("started_at") or 0
        if not isinstance(when, (int, float)) or isinstance(when, bool):
            continue
        if when > newest:
            best, newest = other, when
    return (best.get("run_id") or best.get("title")) if best else None


def is_superseded(state, records=None, index=None, merged_only=False):
    """Whether a later run replaced this one (see `superseded_by`). Read-only."""
    return superseded_by(state, records, index, merged_only) is not None


def settled(state, index=None):
    """Whether an ending is already its orchestrator's: handed back to the seat that launched
    it or waiting for that seat's next quiet prompt, acknowledged, or superseded by later work.

    These are the endings `menu.v5o_needs_look` counts as nobody's question, and as there
    an `exhausted` run the tick cannot resume is no ending: neither a hand-back nor its
    age settles it, only an acknowledgement -- or a later merged run taking the work up,
    which ends the question however the run parked.  `index` is a `supersession_index`;
    without one supersession is not read.
    """
    if state.get("state") == "exhausted":
        return bool(state.get("recovery_acknowledged_at")
                    or (index is not None
                        and is_superseded(state, None, index, merged_only=True)))
    return bool(state.get("handed_back") or state.get("handback_pending")
                or state.get("recovery_acknowledged_at")
                or (index is not None and is_superseded(state, None, index)))


def mark_looked_at(run_dir, state=None):
    """Opening a run by number, `ak run status <id>` or `2 acknowledge` marks it looked at.

    Sets `recovery_acknowledged_at` for `fail`, `error` and `pass` as well, so an
    ending under a live seat counts as `needs a look` until it is looked at, then as
    merged-or-gone, never `needs a look` again. A scheduled error is still working,
    like a merge wait: inspecting it does not cancel its retry; `ak run stop` does.
    A PASS still waiting on its merge leaves the menu the same way: looked at is
    looked at. Returns True when it marked.
    """
    with run_record.recovery_lock(run_dir):
        current = run_record.read_state(run_dir) if state is None else dict(state)
        if not current:
            return False
        if current.get("state") not in run_record.ENDED:
            return False
        if current.get("state") == "error" and going(current):
            return False
        if current.get("recovery_acknowledged_at"):
            return False
        current["recovery_acknowledged_at"] = time.time()
        current.pop("error_retry_at", None)
        current.pop("error_retries", None)
        run_record.save_state(run_dir, current)
        return True


def acknowledge(run_dir):
    with run_record.recovery_lock(run_dir):
        state = run_record.read_state(run_dir)
        if not state:
            raise config.Error("the run is no longer waiting for recovery")
        waiting = needs_recovery(state) or state.get("state") in run_record.FAILED
        if not waiting or state.get("recovery_acknowledged_at"):
            raise config.Error("the run is no longer waiting for recovery")
        state["recovery_acknowledged_at"] = time.time()
        state.pop("error_retry_at", None)
        state.pop("error_retries", None)
        run_record.save_state(run_dir, state)


def _cached_providers():
    """The usage cache's providers for display: {} when the cache cannot be read."""
    try:
        blob = json.loads((config.STATE / "usage.json").read_text())
        providers = blob.get("providers") if isinstance(blob, dict) else None
        return providers if isinstance(providers, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def executable_models(cfg, providers, workers, now, log=None, *, reviewers=None):
    """(model, provider) pairs that can execute now, in pick order.

    An eligible worker counts when the pick order keeps it, its budget is above zero
    with nothing unknown about it, and no refusal parked its provider until a future
    window.  The tick's availability and the waiting words share this one rule.  `log`
    is told each worker left out because its harness cannot run, as `ready_order` says it.
    """
    try:
        order = ready_order(cfg, providers, workers=workers, log=log, role="executor",
                            quiet=True, reviewers=reviewers)
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    available = []
    for name in order:
        try:
            provider = config.model(cfg, name)["provider"]
        except config.Error:
            continue
        prov = (providers or {}).get(provider)
        if not isinstance(prov, dict):
            continue
        until = prov.get("exhausted_until")
        if (isinstance(until, (int, float)) and not isinstance(until, bool) and until > now):
            continue  # a refusal parked this provider until its own window; honour the mark
        try:
            budget, reason = usage.model_budget(cfg, name, providers, now)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if reason is None and budget > 0:
            available.append((name, provider))
    return available


def reviewable_models(cfg, providers, workers, now, executor=None):
    """(model, provider) pairs that can review now, in pick order.

    The reviewer's half of `executable_models`, under the same rule: kept by the
    pick order, budget above zero with nothing unknown about it, provider not
    parked until a future window.  Legality against the saved executor is checked
    too -- a spare the policy forbids beside this executor is no reviewer to
    resume for, and the loop would only park the run again.  Without an executor
    the legality check has nothing to check against, so every available model
    counts.
    """
    try:
        order = ready_order(cfg, providers, workers=workers, role="reviewer",
                            quiet=True)
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    if executor:
        order = reviewer_order(cfg, executor, order)
    available = []
    for name in order:
        try:
            provider = config.model(cfg, name)["provider"]
        except config.Error:
            continue
        prov = (providers or {}).get(provider)
        if not isinstance(prov, dict):
            continue
        until = prov.get("exhausted_until")
        if (isinstance(until, (int, float)) and not isinstance(until, bool) and until > now):
            continue  # a refusal parked this provider until its own window; honour the mark
        try:
            budget, reason = usage.model_budget(cfg, name, providers, now)
        except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if reason is None and budget > 0:
            available.append((name, provider))
    return available


def exhausted_waits_for(state, providers, cfg=None, workers=None, now=None):
    """(provider, resets_at, dry) saying which window an `exhausted` run waits on.

    Only a quota run waits on a window at all: anything else, and anything with no
    spent eligible provider, comes back dry=False, and the row keeps the state word.
    Otherwise the answer is the spent eligible provider with the soonest future
    `resets_at` on any of its meters -- (None, None, True) when no spent provider
    carries a future reset, which reads as a window with no known hour.  A run a
    later merged run replaced waits on no window: the tick stood down, marked
    `replaced`, and naming an hour would promise a resume that never comes.
    """
    if state.get("replaced"):
        return None, None, False
    if state.get("state") != "exhausted" or not state.get("quota_dry"):
        return None, None, False
    now = time.time() if now is None else now
    if cfg is None:
        return None, None, True
    if workers is None:
        try:
            workers = run_workers(cfg, state) or config.workers(cfg)
        except (config.Error, KeyError, TypeError, AttributeError):
            return None, None, True
    try:
        names = {config.model(cfg, name)["provider"] for name in workers}
    except (config.Error, KeyError, TypeError, AttributeError):
        return None, None, True
    spent = [provider for provider in names
             if provider not in {prov for _, prov in executable_models(cfg, providers,
                                                                       workers, now)}]
    if not spent:
        return None, None, False
    best, at = None, None
    for provider in spent:
        prov = (providers or {}).get(provider)
        if not isinstance(prov, dict):
            continue
        for meter in prov.get("meters") or []:
            if not isinstance(meter, dict):
                continue
            resets_at = meter.get("resets_at")
            if (isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool)
                    and resets_at > now and (at is None or resets_at < at)):
                best, at = provider, resets_at
    return best, at, True


def waiting_word(state, providers=None, cfg=None, workers=None, now=None):
    """What a parked run's row says instead of the state word.

    `waiting for <harness> login` where a login expired under it, which the tick
    lifts by itself the moment that harness's `auth` verb passes again -- and
    `waiting to resume` once it has passed and only the launch is left.  Otherwise,
    for an `exhausted` run: `waiting for <provider> until HH:MM` for the soonest spent
    window it could use, `waiting for a provider window` when a window is spent but
    none names an hour, and `exhausted` when the run waits on no window at all.  Reads
    the usage cache and the config when they are not handed in; either unreadable
    means none is known.
    """
    if state.get("state") == "waiting_login":
        # the tick found the login back and has not got the resume away yet: what it waits
        # for now is the resume, and naming the login would send him to fix what is fixed
        return ("waiting to resume" if state.get("login_back_at") else
                f"waiting for {state.get('waiting_for') or 'a'} login")
    if providers is None:
        providers = _cached_providers()
    if cfg is None:
        try:
            cfg = config.load()
        except config.Error:
            cfg = None
    provider, at, dry = exhausted_waits_for(state, providers, cfg, workers, now)
    if not dry:
        return "exhausted"
    if provider is None or at is None:
        return "waiting for a provider window"
    try:
        return f"waiting for {provider} until {time.strftime('%H:%M', time.localtime(at))}"
    except (OverflowError, OSError, ValueError):
        return "waiting for a provider window"


def waiting(state, providers=None, cfg=None, workers=None, now=None):
    """The waiting sentence when a run sits out a provider window or an expired login, else "".

    Both resume themselves -- a window refills, a login comes back -- so the listings
    say what the run waits for, never that the owner should reach for its number.
    Anything else, and an exhausted run that waits on no window, reads "".
    """
    if state.get("state") == "queued":
        return gate.slot_note(state)
    if state.get("state") not in ("exhausted", "waiting_login"):
        return ""
    word = waiting_word(state, providers=providers, cfg=cfg, workers=workers, now=now)
    return word if word.startswith("waiting") else ""


ERROR_RETRY_CAP = 3600  # an errored run is retried at most hourly, however long the ladder


def error_retry_delay(retries):
    """How long the tick waits before retry number `retries` of an errored run.

    The loop's own transient ladder first -- the 1, 5, 15, 30 and 60 minutes a
    worker turn waits between attempts -- then hourly, indefinitely.  A provider
    that died under the run is worth another hour's patience every hour; giving
    up is the owner's decision, and he makes it with `ak run stop`.
    """
    if retries < len(TRANSIENT_BACKOFF):
        return TRANSIENT_BACKOFF[retries]
    return ERROR_RETRY_CAP


def schedule_error_retry(state, now=None):
    """Stamp the tick's next retry of this errored run onto its record.

    `error_retries` is the rung already tried, kept across attempts so the ladder
    never restarts: a run that errors again an hour later waits another hour, not
    another minute.  Only the stamp is written here; whether the run can be
    resumed at all is `error_resumable`'s answer, taken before this is called.
    """
    now = time.time() if now is None else now
    retries = state.get("error_retries") or 0
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        retries = 0
    state["error_retries"] = retries
    state["error_retry_at"] = now + error_retry_delay(retries)
    return state


def error_resumable(state, run_dir):
    """Whether an errored run is one a resume could carry on.

    The same checks `resume_run` refuses on, asked before anything is scheduled:
    a worktree that is still there, the keys a resume replays, and -- for a task
    run -- a task that still parses with a done-when.  A job's run is its job's to
    settle, never the tick's.  A run that fails any of the others is parked for a
    person, not for the tick: retrying a task nobody can run would only fail on
    the hour, every hour, saying nothing new.
    """
    if state.get("review_pr"):
        return False  # the watch relaunches the review itself; the run is never resumed
    if state.get("job_id"):
        return False  # its job settles it or reruns it elsewhere; a retry would race that
    wt = state.get("worktree")
    if not wt or not Path(wt).is_dir():
        return False
    keys = (("worktree", "rounds") if state.get("scratch") else
            ("repo", "worktree", "branch", "base", "base_sha", "rounds"))
    if any(not state.get(key) for key in keys):
        return False
    try:
        _, body, _ = taskfile.parse_task(Path(run_dir) / "task.md")
        taskfile.done_when(body, Path(run_dir) / "task.md")
    except (OSError, config.Error):
        return False
    return True


def park_error(run_dir, state, now=None):
    """Schedule the tick's retry for a run that just ended in error, or park it.

    An admitted, resumable error is born scheduled: the status line says when,
    and the seat stays working. Anything else -- a by-hand run, a settled ending,
    a worktree already gone, a task that never parsed -- keeps no stamp, so the
    run reads parked for a person from the start. Stale stamps from an earlier
    episode come off with it: the rung goes with the hour, and a run that is
    resumable again starts a new ladder.
    """
    if tick_admission(state, now=now) and error_resumable(state, run_dir):
        schedule_error_retry(state, now=now)
    else:
        state.pop("error_retry_at", None)
        state.pop("error_retries", None)
    return state


def exhausted_wait(state):
    """What the tick brings back to an `exhausted` run: `window`, `reviewer`, or nothing.

    A quota run waits on a provider window; a run off a dead reviewer -- which carries
    no quota mark, because no window was ever spent -- waits on a reviewer being
    eligible again.  `watch.resume_exhausted` resumes those two by itself and no other:
    rounds spent, a stopped tool or a reviewer stuck without a verdict wait on nobody
    until `ak run resume`, so `going` reads this too, and a run nothing will move keeps
    no seat working.  A run a later merged run replaced waits on neither: the tick
    stands down, marked `replaced`, and the wait is over however the run parked.
    """
    if state.get("state") != "exhausted":
        return ""
    if state.get("replaced"):
        return ""
    if state.get("quota_dry"):
        return "window"
    if reviewer_transport_dead(state.get("error")):
        return "reviewer"
    return ""


def going(state, now=None):
    """Whether the run keeps its seat working while it lasts.

    The `record.GOING` states -- queued, running, waiting, exhausted, stalled,
    waiting_login -- which resume themselves or are already running, plus an
    error the tick will retry. Errors and waits on a target ref need current admission:
    an old stamp cannot keep a seat working after its retry stopped being allowed,
    and an exhausted run keeps one working only while the tick can resume it
    (`exhausted_wait`): one that waits on nobody is his, not going. Line members
    stay going until the lander ends them.
    """
    if state.get("state") == "waiting" and (state.get("waiting_on") or {}).get("line"):
        return True  # the line is unfinished work, not an ending with timed recovery
    if state.get("state") in ("error", "waiting") and not tick_admission(state, now=now):
        return False
    if state.get("state") == "exhausted":
        return bool(exhausted_wait(state))
    if state.get("state") in run_record.GOING:
        return True
    if state.get("state") != "error":
        return False
    at = state.get("error_retry_at")
    return isinstance(at, (int, float)) and not isinstance(at, bool)


def conflict_upstream(state):
    """The `origin/<base>` a rebase conflict was against, from the loop's own words.

    The conflict notes name it -- `the rebase of origin/main conflicted` -- so
    the tick waits on exactly what the loop tripped over.  A note that names
    nothing waits on the run's base, which is what integration rebases onto.
    The capture stops at a `;`: the fixer note ends `... of origin/main; it was
    aborted`, and `origin/main;` is a ref that can never move.
    """
    match = re.search(r"(?:rebase|merge) of ([^\s;]+)", state.get("merge_note") or "")
    if match:
        return match.group(1)
    return f"origin/{state.get('base') or 'main'}"


CONFLICT_NOTE = re.compile(r"conflict|did not finish the (?:rebase|merge)", re.I)


def tick_admission(state, now=None):
    """Why the tick may take up this ending, or nothing if it belongs to a person.

    Line members belong to the lander until they end, however long they wait.
    A telling or acknowledgement settles an ending for good. Only an untold
    ending under a day old, from a session that still exists, is the tick's.
    Following the launch name also keeps a renamed seat's runs with that seat.
    """
    if landing_line(state):
        return "in line to land"
    if any(state.get(key) for key in (
            "handed_back", "recovery_notified", "recovery_acknowledged_at")):
        return ""
    now = time.time() if now is None else now
    ended = state.get("finished_at")
    if (not isinstance(ended, (int, float)) or isinstance(ended, bool)
            or not 0 <= now - ended < 86400):
        return ""
    try:
        seat = launched_session(state)
        if not seat or not config.session_path(seat).is_file():
            return ""
    except config.Error:
        return ""
    return (f"session {seat} exists; ending under 24h old; "
            "not handed back, carded or acknowledged")


def parkable_conflict(state, run_dir=None, now=None):
    """Whether this FAIL waits on main rather than on a person.

    A rebase or merge the loop could not land -- conflicted, or a fixer that did
    not finish it -- with rounds still to spend and the saved branch behind it.
    The work is reviewed; only main stands in its way, and main keeps moving.  A
    conflict FAIL at its budget is not one of these: more rounds are the owner's
    decision, never the tick's. Only an untold, unacknowledged ending under a
    day old from a session that still exists may be parked: anything the seat
    moved past is history, and a by-hand run waits for a person.  A job's run is
    never parked: its job has already settled that FAIL, and alone decides what next.
    """
    if state.get("job_id"):
        return False
    if not CONFLICT_NOTE.search(state.get("merge_note") or ""):
        return False  # cheap first: most FAILs never reach the log read below
    if len(state.get("round_summaries") or []) >= (state.get("rounds") or 0):
        return False
    if not tick_admission(state, now=now):
        return False
    return _integration_fail_guards(state, run_dir)


def upstream_sha(wt, ref):
    """What `ref` points at on origin now, or None when that cannot be read.

    A fetch first, so a merge to main since the last one moves the answer: the
    tick waits on the next merge, not the last fetch.  A fetch that fails, or a
    ref that will not parse, is not a move -- the waiter keeps waiting, silently,
    exactly as a window that has not refilled.  Only a full oid is an answer:
    `rev-parse` echoes an unresolved rev on stdout before it exits non-zero, and
    reading that echo as a sha would park the run on a move that can never come.
    Either object format counts: sha1 oids are 40 hex chars, sha256 ones 64.
    """
    try:
        if fetch(wt, "origin")[0] != 0:
            return None
        sha = git(wt, "rev-parse", f"{ref}^{{commit}}", check=False)
    except (config.Error, OSError):
        return None
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha or ""):
        return None
    return sha


def landing_line(state):
    """The repository lock named by a waiting line member."""
    return (state.get("waiting_on") or {}).get("line") if state.get("state") == "waiting" else None


def unfinished(state, records=None, index=None):
    """Runs that still own an active seat or await an explicit recovery decision.

    A run a later merged run replaced is neither: its work is done, elsewhere.
    `records` is an iterable of states already read, `index` a `supersession_index`
    over them; without either supersession is not read.
    """
    if state.get("state") in run_record.ACTIVE:
        return True
    if not (needs_recovery(state) and not state.get("recovery_acknowledged_at")):
        return False
    if records is None and index is None:
        return True
    return not is_superseded(state, records, index, merged_only=True)


def queued(run_dir):
    """The background launch receipt, possibly already holding its slot."""
    try:
        with run_record.recovery_lock(run_dir):
            state = run_record.read_state(run_dir)
            return (state.get("state") == "queued" or
                    (state.get("state") == "running" and state.get("pid") == os.getpid()
                     and state.get("slot_waiting") is False))
    except (OSError, ValueError, AttributeError):
        return False


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
        if previous.get("followup"):
            # These are siblings owned by the seat, not descendants for the ending's
            # process sweep to kill or tests sharing its admission slot.
            for key in (worker.RUN_MARKER, "AK_PARENT_RUN", "AK_RUN_LOG", "AK_RUN_SCOPE",
                        config.UNATTENDED_ENV, config.JOB_DIR_ENV, "AK_RUN_ROLE"):
                env.pop(key, None)
            env[config.SESSION_ENV] = launched_session(previous)
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


def log_is_stdout(run_dir):
    """Detached wakes already write the log; following it would feed it back into itself."""
    try:
        return os.path.samefile(run_dir / "log.txt", sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        return False


def foreground_cli(run_dir):
    return (not getattr(jobs._JOB_MUTE, "depth", 0)
            and threading.current_thread() is threading.main_thread()
            and Path(sys.argv[0]).resolve() == (config.REPO / "bin" / "ak").resolve()
            and not log_is_stdout(run_dir))


def logger(run_dir):
    def log(message):
        line = f"[{datetime.now():%H:%M:%S}] {message}"
        try:
            print(line, flush=True)
        except BrokenPipeError:
            # whoever read the launch stopped reading (`| head`): that ends the reading, never
            # the run, whose log keeps every line; later prints go nowhere
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        if not log_is_stdout(run_dir):
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(line + "\n")
    return log


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
    followup = receipt.get("followup")
    session_at_launch = receipt["launched_session"] if followup else config.current_session()
    workers = (receipt.get("workers") if followup else
               config.workers(cfg) if cfg is not None and session_at_launch else None)
    if followup:
        # A fix run keeps the lists start_followups bound when it wrote the receipt.
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
                         "run_depth": 0 if followup else run_depth(),
                         "parent_run": None if followup else os.environ.get("AK_PARENT_RUN"),
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
        if not followup:
            # A fix run waits for its slot from its first record on: whatever cuts its handoff
            # off before the launch, it is a slot wait, which the tick resumes.
            gate.reserve_slot(state, limit)
        run_record.save_state(run_dir, state)
    history_start(state)
    redress_seat(session_at_launch)   # the seat's bar says it from the start


def launch_line(run_id, title, executor, reviewer, *, self_review=None):
    """The one line a launch from a seat puts on the seat's terminal.

    A review-only run has no executor, so it names its reviewer instead of a pair;
    every other launch names both models.  One builder, every launch path.
    A round reviewed by the executor's own model says `self-reviewed`: the pair says
    it by name, except a review-only run of the seat's own PR, whose caller passes it.
    Callers that know the config pass identity, so an alias marks too.
    """
    if self_review is None:
        self_review = bool(executor and executor == reviewer)
    models = f"{executor}/{reviewer}" if executor else f"{reviewer} review"
    if self_review:
        models += ", self-reviewed"
    return (f"run {run_id} launched: {title} ({models}); "
            "it counts on this bar and in the menu; you will be told when it ends")


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
        every, once = taskfile.done_when_groups(body, run_dir / "task.md")
        repo = task_repo(meta, run_dir / "task.md", state.get("task_file"))
        if opts["--no-merge"] or repo is None:
            every = [taskfile.split_once(cmd)[0]
                     for cmd in taskfile.done_when(body, run_dir / "task.md")]
            once = []
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
        base = (meta.get("base") or default_base(repo, log)) if repo else "none"
        target, method = meta.get("target") or base, meta.get("merge") or "squash"
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
                state["merged"] = True
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
    if at_budget and state["rounds"] >= taskfile.TASK_MAX_ROUNDS:
        # the whole budget is spent: no --rounds carries it on, so the task is what changes
        raise config.Error(f"{argv[0]} FAILed at its round budget ({state['rounds']}); "
                           f"{taskfile.TASK_MAX_ROUNDS} rounds is the budget, so split or re-scope the task")
    if at_budget and (n_rounds is None or n_rounds <= state["rounds"]):
        raise config.Error(f"{argv[0]} FAILed at its round budget ({state['rounds']}); "
                           f"give --rounds N above it, at most {taskfile.TASK_MAX_ROUNDS}, to continue")
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


def record_result(run_dir, state, log=None, cfg=None):
    """result.md for a run that stopped rather than finished.

    The full report when there is a worktree to report on, else the reason and the relaunch:
    before a worktree exists there is no diff, no rounds and no delivery, so the file carries
    the title, no verdict, why the run stopped, and `ak run <task.md>` to try again.  Never
    itself a reason a stop goes unreported: whatever goes wrong writing the full report, the
    file still says what happened and what to do about it, and the caller still notifies.
    """
    try:
        if state.get("worktree") and "round_summaries" in state and not state.get("review_pr"):
            _, body, _ = taskfile.parse_task(run_dir / "task.md")
            write_result(run_dir, state, taskfile.done_when(body, run_dir / "task.md"), log, cfg)
            return
    except (config.Error, OSError) as exc:
        suffix = f"\n\n(the full result could not be written: {exc})"
    else:
        suffix = ""
    try:
        save_result(run_dir,
            f"# {delivery(state, report_config(cfg))} — {state.get('title') or run_dir.name}\n\n"
            f"VERDICT: {state.get('verdict') or 'none'}\n\n## Why this run stopped\n\n"
            f"{state.get('error') or 'no reason was recorded'}\n\n"
            f"relaunch: ak run {run_dir / 'task.md'}{suffix}\n\n{followup_report(state)}")
    except OSError:
        pass
    else:
        if log is not None and state.get("error"):
            log(f"ERROR {state['error']}")


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
    rc, out = gh(cwd, *args, timeout=timeout)
    if stopped(rc, out):
        raise Stopped(out)
    if rc != 0:
        return None, out[:400] or "gh timed out"
    try:
        return (config.json_pages(out) if "--paginate" in args else json.loads(out)), ""
    except ValueError as exc:
        return None, f"gh printed no JSON ({exc}): {out[-200:]}"


def pr_view(url):
    data, why = gh_json(config.RUNS, "pr", "view", url, "--json",
                        "number,title,body,author,baseRefName,headRefOid,url,state,isDraft")
    if not isinstance(data, dict):
        raise config.Error(f"gh pr view {url} failed: {why}")
    author = data.get("author") or {}
    data["author"] = author.get("login") or "?"
    return data


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
        trees = [git_bytes(repo, "ls-tree", "-r", "-z", ref) for ref in (base, head)]
        if any(meta.split(" ", 1)[0] not in ("100644", "100755")
               for tree in trees for meta, _, name in (entry.partition("\t")
                                                       for entry in tree.split("\0") if entry)
               if Path(name).name.upper() == "AGENTS.MD"):
            return False        # an AGENTS.md anywhere that is a link or a submodule
        entries = git_bytes(repo, "diff", "--raw", *raw, base, head, "--").split("\0")
        modes = [entry.split()[:2] for entry in entries[0::2] if entry.startswith(":")]
        entries = git_bytes(repo, "diff", "--numstat", *raw, base, head, "--").split("\0")
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
        return "\0" not in git_bytes(repo, "cat-file", "blob", f"{ref}:{path}")
    except (config.Error, Stopped):
        return False


def git_bytes(repo, *args):
    """git's output with every byte kept (surrogateescape), names included: a carriage return or
    a byte that is not UTF-8 stays itself, and handed back to git names the same file."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=TOOL_CAP, env=tool_env())
    except subprocess.TimeoutExpired:
        raise Stopped(f"git {' '.join(args[:2])} ran past {TOOL_CAP:g}s in {repo}")
    if proc.returncode:
        raise config.Error(f"git {' '.join(args[:2])} failed in {repo}: "
                           f"{proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode("utf-8", "surrogateescape")


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
    rc, out = gh(config.CODE, "repo", "clone", name_with_owner, str(target), "--", "-q")
    if rc != 0:
        if stopped(rc, out):
            raise Stopped(out)
        raise config.Error(f"gh repo clone {name_with_owner} failed: {out[-400:]}")
    return target


def declared(wt, key):
    """`key`'s value in the front matter of the checkout's AGENTS.md as written, or None."""
    try:
        text = (Path(wt) / "AGENTS.md").read_text(errors="replace")
    except OSError:
        return None
    return front_value(text, key)


def front_value(text, key):
    """`key`'s value in AGENTS.md front matter text as written, or None."""
    match = FRONT.match(text)
    if not match:
        return None
    for line in match.group(1).splitlines():
        name, sep, value = line.strip().partition(":")
        if sep and name.strip() == key and value.strip():
            return value.strip()
    return None


def declared_at(wt, ref, key):
    """`key`'s value in the front matter of AGENTS.md at `ref`, or None.

    A read that fails or runs slow is no declaration, never a failed run: the ref may
    not exist yet, the file may not be there, or git may be waiting on a prompt or a
    network nobody here can answer, and any of those leaves the run with what its own
    checkout says.
    """
    try:
        text = git(wt, "show", f"{ref}:AGENTS.md", check=False)
    except Exception:
        return None
    if not text:
        return None
    return front_value(text, key)


def users_declared(wt):
    """The checkout's `users:` answer, `real` or `none`, or None until the owner is asked.

    Read as the YAML scalar it is: `users: "real"  # launched in May` says `real`, and a
    comment or quotes left on the word would quietly drop the reviewer's rule for it.  Only
    this word is unwrapped; a `tests:` command is a shell line and keeps what it says.
    """
    value = re.sub(r"(^|\s)#.*", "", declared(wt, "users") or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    return value or None


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
    rc, out = gh(lp.run_dir, "api", f"repos/{owner}/{repo}/pulls/{number}/reviews",
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


def fail_pr_landing(lp, failure):
    """The PR's writer fixes a red landing tree, just as it fixes review findings."""
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
    if lp.state.get("own_pr") and lp.rnd < lp.rounds:
        lp.state.update(state="running", finished_at=None, own_pr_wait=lp.state["head_sha"])
    else:
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
        api, owner, repo, number = pr_parts(url)
        current, why = gh_json(lp.run_dir, *api, f"repos/{owner}/{repo}/pulls/{number}")
        if not isinstance(current, dict) or not (current.get("head") or {}).get("sha"):
            raise config.Error(f"cannot verify the PR before delivery: {why}")
        remote = current["head"]
        expected = own_pr_heads(lp.state)
        ours = (remote["sha"] in expected
                and (current.get("base") or {}).get("ref") == upstream.removeprefix("origin/"))
        if current.get("merged") and ours:
            lp.state["merged"] = True
            lp.write()
            return True
        if current.get("state") != "open" or not ours:
            path = lp.run_dir / "pr-changed.log"
            path.write_text("The PR head or target changed, or the PR closed, since review.\n")
            lp.state["review_stale"] = True
            return fail_pr_landing(lp, {"line": path.read_text().strip(), "log": str(path)})
        pinned = git(lp.wt, "rev-parse", "HEAD")
        # Keep the intended push before calling Git: a killed push may have gone through.
        lp.state["delivery_sha"] = pinned
        lp.write()
        if remote["sha"] != pinned:
            branch, source = remote.get("ref"), (remote.get("repo") or {}).get("clone_url")
            if not branch or not source:
                raise config.Error("cannot locate the PR branch to push its tested tree")
            rc, out = git_out(lp.wt, "push", f"--force-with-lease=refs/heads/{branch}:{remote['sha']}",
                              "--", source, f"HEAD:refs/heads/{branch}")
            if rc:
                raise config.Error(f"pushing the tested PR head failed: {out[-400:]}")
        lp.state["head_sha"] = pinned
        lp.write()
        return wait_checks(lp, url) and do_merge(lp, url, upstream)

    return join_line(lp, upstream, deliver)


def own_pr_wait_note(state):
    if (state.get("state") == "running" and state.get("own_pr")
            and state.get("own_pr_wait") == state.get("head_sha") and state.get("head_sha")):
        return f"waiting for the {launched_session(state)} seat to push fixes to its PR"
    return ""


def tell_own_pr_round(cfg, run_dir, state, log):
    """Hand back this FAIL without settling the run or collecting its checkout."""
    rnd = len(state["round_summaries"])
    session = launched_session(state)
    with delivery_lock(run_dir):
        said = run_record.read_state(run_dir) or state
        if not same_attempt(state, said) or said.get("own_pr_round_told") == rnd:
            return
        line = handback_line({**state, "state": "fail"}, run_dir, cfg, review_round=rnd)
        with launcher_world(session) as live:
            if live and watch.type_at_prompt(
                    orch.find(session) or {"name": session}, line, log, cfg=cfg,
                    typed=said.get("own_pr_round_typed"),
                    receipt=lambda mark: mark_delivery(run_dir, state, own_pr_round_typed=mark)):
                mark_delivery(run_dir, state, own_pr_round_told=rnd, own_pr_round_typed=None)


def wait_for_own_pr(cfg, run_dir, url, state, log):
    """The seat fixes the reviewed head; a push, close or stop ends this wait."""
    state.update(state="running", **run_record.process_owner(), finished_at=None,
                 step="waiting for the seat's push", step_at=time.time())
    run_record.save_state(run_dir, state)
    history.open_step(run_dir.name, state["step"], log=log)
    redress_seat(launched_session(state))
    log(own_pr_wait_note(state))
    while True:
        run_record.stop_check(run_dir)
        if state.get("verdict") == "FAIL":
            tell_own_pr_round(cfg, run_dir, state, log)
        try:
            info = pr_view(url)
        except Stopped:
            raise
        except config.Error as exc:
            log(f"WARN cannot check the PR head; retrying: {exc}")
            time.sleep(gate.SLOT_POLL)
            continue
        if info.get("state") != "OPEN":
            state.update(state="fail", error=f"{url} is {info.get('state', '?')}; review ended",
                         finished_at=time.time())
            state.pop("own_pr_wait", None)
            run_record.save_state(run_dir, state)
            _, body, _ = taskfile.parse_task(run_dir / "task.md")
            write_result(run_dir, state, taskfile.done_when(body, run_dir / "task.md"), log, cfg)
            return False
        if info["headRefOid"] != state["head_sha"]:
            return True
        time.sleep(gate.SLOT_POLL)


def pr_loop(cfg, run_dir, state, opts, log):
    """A PR review's record as a loop, for the steps between its rounds: a merge, a settled
    round, a move onto new code.  Like every loop it writes back only what it changed."""
    _, body, _ = taskfile.parse_task(run_dir / "task.md")
    cmds = taskfile.done_when(body, run_dir / "task.md")
    return Loop(cfg, run_dir, state, opts, log, Path(state["worktree"]), body, cmds, body, [])


def review_pr(cfg, run_dir, url, opts, log):
    """Own PRs wait for fixes between reviews; other authors get a single review."""
    while True:
        state = run_record.read_state(run_dir) or {}
        if state.get("own_pr_wait") and state.get("own_pr"):
            if not wait_for_own_pr(cfg, run_dir, url, state, log):
                return state
            # the push starts a round, and a round runs on the agentkit installed now: a wait
            # can outlast many merges
            pickup_new_code(pr_loop(cfg, run_dir, state, opts, log))
        summaries = state.get("round_summaries") or []
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
        elif (state.get("merged") or (state.get("own_pr") and state.get("own_pr_round_pending") and summaries
                and summaries[-1]["round"] == state["own_pr_round_pending"])):
            # A durable verdict still owes its post and delivery, even in round three.
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
    if info.get("state") != "OPEN":
        raise config.Error(f"{url} is {info.get('state', '?')}, not open")
    prior = run_record.read_state(run_dir) or {}
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
    n_rounds = taskfile.TASK_MAX_ROUNDS if is_own else 1
    if is_own and len(summaries) >= n_rounds:
        raise config.Error("three review rounds spent; split or re-scope the PR")
    advancing = bool(summaries and (summaries[-1]["verdict"] == "FAIL" or prior.get("review_stale")
                                   or prior.get("own_pr_wait"))
                     and prior.get("head_sha") != info["headRefOid"])
    if prior.get("worktree"):
        at = git(prior["worktree"], "rev-parse", "HEAD")
        recorded = (prior.get("review") or {}).get("head_sha") or prior.get("head_sha")
        # a reset to the head this round moves to may have finished just before a crash
        moved = advancing and at == info["headRefOid"]
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
    receipt.pop("own_pr_round_typed", None)
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
    tests = declared_suite(wt, base, ref=target_sha)
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
            + planned
            + "## Done when\n```bash\n" + (cmds[0] if cmds else "true   # AGENTS.md declares no tests:") + "\n```\n")
    (run_dir / "task.md").write_text(f"---\nrepo: {repo}\nrounds: {n_rounds}\n---\n{body}")
    state = stamp_origin({**(run_record.read_state(run_dir) or {}), "run_id": run_dir.name,
             "title": title, "task": str(run_dir / "task.md"),
             "launched_session": session_at_launch, "repo": str(repo), "scratch": False,
             "review_pr": url, "pr": url, "head_sha": head, "author": info["author"],
             "own_pr": is_own, "own_orchestrator": orchestrator if is_own else None,
             "base": f"origin/{base}", "target": base, "base_sha": base_sha,
             "target_sha": target_sha, "branch": branch,
             "worktree": str(wt), "executor": None, "reviewer": None, "rounds": n_rounds,
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
        state["own_pr_round_pending"] = len(summaries) + 1
    state.pop("own_pr_wait", None)       # this head is checked out and recorded
    state.pop("delivery_sha", None)      # a push an earlier round meant to make proves nothing here
    # nor does its review: this head's comes with this round, and judges what changed since
    # the commit the last one judged
    state["delta_from"] = (state.get("review") or {}).get("head_sha") if isinstance(
        state.get("review"), dict) else None
    state.pop("review", None)
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
    providers = collect_usage(cfg)
    exec_for_rule = orchestrator if is_own else None
    order = reviewer_order(cfg, exec_for_rule, ready_order(cfg, providers,
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
    context = f"Repo checkout: {wt}\nBranch: {branch} (PR #{number} head, based on origin/{base})\n\n{body}"
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, context, spares)
    lp.rnd += 1
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
    else:
        summary = (f"PR #{number} by {info['author']}: {info['title']}. agentkit executed nothing; "
                   "review the author's diff.")
    try:
        if summaries:
            verdict = review(lp, summary, ok, dw_log, preface="Re-review after a push.")
        else:
            verdict = review(lp, summary, ok, dw_log)
    except Blocked as exc:
        # No reviewer's harness can run: the review ends `blocked` on the harness's own line,
        # as a task run does, and not in an `error` the tick would retry into that harness.
        log(f"BLOCKED {exc}")
        state.update({"state": "blocked", "verdict": "BLOCKED", "error": str(exc),
                      "blocked": exc.section, "finished_at": time.time()})
        state.pop("own_pr_round_pending", None)
        run_record.save_state(run_dir, state)
        write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
        return state
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
    run_record.save_state(run_dir, state)
    write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
    return state


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


def reviewer_transport_dead(error):
    """Whether an `exhausted` run is off a reviewer's transport deaths, and only that.

    The transport half of `job_transport_exhausted`: the reviewer died on API or
    transport errors, with the meters still healthy.  A reviewer that twice answered
    without a verdict is not dead -- it is stuck, and another lap at the tick's pace
    will not unstick it -- so only this half resumes a run outside a job.
    """
    return "API/transport errors" in (error or "")


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
                      f"started {started}, \"{first['title']}\") shares {detail}; wait for "
                      "it, or add --anyway to start a second run", file=sys.stderr)
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
