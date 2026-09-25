"""The review loop: executor -> done-when -> another model's review, until PASS, then the merge.

No LLM decides anything here; the loop is a script and the verdict is a parsed line.

`ak run --review-pr <url>` is the same reviewer with no executor: somebody else's PR, checked
out at its head, judged against the repo and posted back as a GitHub review.
"""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import ExitStack, contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import command_help, config, history, notify, orch, retention, usage, watch, worker
from .harness import load as harness_plugin

DIFF_CAP = 300 * 1024
OUT_CAP = 20 * 1024
LESSONS_CAP = 4 * 1024
FOLLOWUPS_CAP = 24 * 1024   # the orchestrator reads the whole file before every task
# A worker that dies like this died on the provider, not on the task: it is retried, never scored.
# Only a fault, never the account: a usage or rate limit names the account and hands the
# round to another provider instead, through the manifests' own quota words.
TRANSIENT = re.compile(r"API Error|HTTP 5\d\d|Overloaded|Internal server error|"
                       r"Gateway Timeout|unexpected status|overloaded|529|at capacity|"
                       r"model stream idle timeout|Service unavailable|The service is busy|"
                       r"Can't reach the API server", re.I)
# What a harness says on stderr when it never ran the turn at all: it is not installed, it does
# not know a flag or the model it was given, or its login was refused.  No wait changes any of
# these, so an exit that left final.md empty and says one of them is no transient answer.
HARNESS_FAULT = re.compile(r"not installed|command not found|unknown (?:shorthand )?flag|"
                           r"unknown (?:option|argument|command|model)|unrecognized "
                           r"(?:option|argument)|unexpected argument|invalid (?:option|model)|"
                           r"model\b.{0,80}\b(?:not found|not exist|not supported)|"
                           r"model_?not_?found|not logged in|please (?:run )?/?log ?in|"
                           r"unauthori[sz]ed|authentication[ _](?:failed|required|error)|"
                           r"invalid[ _-](?:x-)?api[ _-]?key", re.I)
# ...unless the same stderr says the provider is down: a 5xx, an overload or a capacity refusal
# is waited out, whatever else the harness said on the way.
OUTAGE = re.compile(r"(?:API Error|HTTP|status)\W{0,3}5\d\d|overloaded|at capacity|"
                    r"Internal server error|Bad Gateway|Gateway Timeout|Service unavailable|"
                    r"The service is busy|idle timeout|Can't reach the API server", re.I)
# A transient answer is what a person answers by typing `continue`: the same worker session
# again, after 1, 5, 15, 30 and 60 minutes, then hourly, indefinitely.  The run stays
# `running` throughout, so its session reads `working`, and never ends in `error` for one.
TRANSIENT_BACKOFF = (60, 300, 900, 1800, 3600)
TRANSIENT_HOURLY = 3600
MAX_REFILLS = 3               # usage-limit resets one turn may spend before handing over
KILL_WINDOW = 60              # a second signal kill inside this many seconds parks the run
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
NOT_HARNESS = ("prompt.md", "session_id")
ANSWER = "final.md"             # and this one arrives as `text`, already read by worker.call
ECHO = 40                       # a prompt is recognised quoted back by this many of its own
                                # first characters -- the role preamble, which is one line and
                                # which no refusal begins with
REFUSAL_CAP = 1000              # a refusal replaces the answer instead of following it, so it is
                                # short; past this many characters what is there is an answer
# every role's preamble asks for one of these, so an answer carries one and a refusal does not
ANSWERED = re.compile(r"^\s{0,3}#{1,6}\s|^[\s>#*_`]*VERDICT:", re.M | re.I)
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
# tests/smoke.sh and the test_*.py files it runs create there (tests/acceptance.sh and
# tests/e2e-fresh.sh only ever write under $WORK).  The leftover sweep never commits these
# and the loop removes them before the next turn, whatever the repository's .gitignore says.
SANDBOX_PREFIXES = (
    ".acceptance-", ".auth-watch-", ".cards-", ".changed-checks-", ".codex-seat-",
    ".command-help-", ".config-home-", ".deferred-checks-", ".deferred-result-",
    ".gate-tolerance-", ".handback-", ".lessons-", ".login-", ".macbridge-",
    ".muse-probe-", ".no-sandbox-commit-", ".notify-", ".notify-smoke-",
    ".one-provider-", ".one-rulebook-", ".phone-", ".pins-", ".recover-runs-", ".refusal-",
    ".retention-", ".retry-notify-", ".review-contract-", ".review-gate-", ".rulebook-",
    ".run-quota-", ".run-scope-", ".run-v5r-", ".seat-hook.", ".seat-state-",
    ".session-state-", ".silence-", ".smoke-", ".stop-hook-", ".stop-nudge-",
    ".task-size-", ".tick-health-", ".usage-banner-", ".usage-fresh-", ".usage-test-",
    ".v4c-", ".v4l-", ".v4n-", ".v4z-no-history-", ".v5aa-", ".v5ab-", ".v5ac-",
    ".v5ad-", ".v5ae-", ".v5af-", ".v5ah-", ".v5aj-", ".v5al-", ".v5am-", ".v5d-",
    ".v5e-", ".v5e-list-", ".v5f-", ".v5l-", ".v5m-", ".v5p-", ".v5q-", ".v5w-",
    ".v5x-", ".verify-integration-", ".resume-midturn-", "codex-mflag-", "phone-tmux-",
    "v4l-tmux-",
)
MERGE_METHODS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}
CHECKS_CAP = 60 * 60            # a check suite still running after an hour is not going to finish
CHECKS_POLL = 10
TOOL_CAP = 120                  # a git or gh call still silent after two minutes is not working,
                                # it is waiting for an answer nobody here can give it
SILENCE_MINUTES = 20            # no command output or harness event for this long is a death
CEILING_HOURS = 6               # the whole done-when list, even if it keeps printing
PR_URL = re.compile(r"https://\S+?/pull/\d+")
# the race a merge can lose to a merge to the target between the push and this call; the
# answer is a retry, never an ending -- see `do_merge`
BASE_BRANCH_MODIFIED = re.compile(r"Base branch was modified", re.I)
MERGE_RETRIES = 3      # how often that race is re-fetched, re-checked and tried again
# what git and gh say when the prompt they wanted was refused; each is a stop, never a wait
PROMPTED = re.compile(r"terminal prompts disabled|could not read (?:Username|Password)|"
                      r"prompts (?:are )?disabled|askpass", re.I)
GC_INTERVAL = 86400             # background retention inspects old state at most once a day
GC_LOG_LIMIT = 1024 * 1024      # retain two bounded automatic-collection logs
GC_AGE = 7 * 86400              # failed/blocked/stopped checkouts, finished jobs, the status window
RUN_DIR_AGE = 30 * 86400        # a run directory whose session is gone is removed whole after this
DISK_LIMIT = 85                 # pressure shortens retention, never below one day
LIST_CAP = 500                  # files a scratch run's reviewer is shown before it is told the count
PUSH_RIGHTS = ("ADMIN", "MAINTAIN", "WRITE")
FORK_REMOTE = "fork"            # the remote a run adds for its fork; `origin` stays the upstream
PR_PARTS = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")
CLASSIC_CHECKS_QUERY = (
    "query($owner:String!,$name:String!,$branch:String!){repository(owner:$owner,name:$name){"
    "ref(qualifiedName:$branch){branchProtectionRule{requiresStatusChecks "
    "requiredStatusChecks{context app{databaseId}}}}}}")
TASK_MAX_POINTS = 3      # numbered points in ## Goal: more is more than one behaviour
TASK_MAX_WORDS = 500     # words outside the checks block: past this, split the task
TASK_MAX_CHECKS = 6      # done-when commands: past this, split the task
TASK_MAX_ROUNDS = 3      # the round budget, not a default: past it, split or re-scope
NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten")   # the hand-back spells the spent budget out
FRONT = re.compile(r"^---\n(.*?)\n---", re.S)
FINDINGS = re.compile(r"^(#+)[ \t]*Findings\b[^\n]*$", re.M | re.I)
FINDING_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\S", re.M)
FOLLOWUPS = re.compile(r"^(#+)[ \t]*Follow-ups\b[^\n]*$", re.M | re.I)
FOLLOWUP_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(\S.*)$", re.M)
FOLLOWUP_PLACE = re.compile(r"[`*]*([^\s`*]+:\d+)")   # the `path:line` an item leads with
# The two headings a worker's turn ends with: `## Summary` is the work, `## Blocked` is the
# task itself refusing to be done.  Only a heading on its own line counts, so a preamble
# quoting either word mid-sentence never ends a run.
BLOCKED_HEADING = re.compile(r"^##[ \t]*Blocked\b[^\n]*$", re.M | re.I)
SUMMARY_HEADING = re.compile(r"^##[ \t]*Summary\b[^\n]*$", re.M | re.I)
BLOCKED_SAME = ("the same checks fail the same way after a fix round: "
                "the task or its checks are wrong")
# What the loop itself adds to a done-when log, in its own words, after the commands have had
# their say: neither is a command's output, and reading one as such would make a failure that
# never moved look new every round.  See `run_done_when`, `verify_work` and `final_check`.
LOOP_NOTE = re.compile(r"^(?:Checkout changed during |done-when: stopped after )")
# Where a suite, unittest, pytest or TAP names what failed: at the start of the line it says so
# on, long before the tally it ends with.  See `first_failure`.
FAILURE_LINE = re.compile(r"^(?:FAIL(?:ED)?|ERROR|not ok)\b")
ENDED = ("pass", "fail", "error", "blocked", "stopped")    # a run that is over, however it got there
NOTICE = 100                    # a finished-run notice is one line, this wide: what a phone shows
                                # -- the menu's leading space included, so the line itself is 99
QUEUED_GRACE = 30               # old launchers did not record the background child's identity
try:
    SLOT_POLL = float(os.environ.get("AK_SLOT_POLL", "30"))
except ValueError:
    SLOT_POLL = 30
MIN_FREE_MB = history.MIN_FREE_MB
_RUN_CONTEXT = threading.local()  # job threads export their own depth and slot owner
_DELIVERY_HELD = threading.local()   # the delivery locks this thread is already inside
_RECOVERY_HELD = threading.local()   # the recovery locks this thread is already inside
STALL_RESUME_GRACE = 600        # the tick stopped this loop and its resume is on the way; reap
                                # leaves the record alone until then, and the resume adopts it
RESUME_VISIBLE = 3600           # ak run status names a mid-turn resume in the age column for this long
TURN_ROLES = ("executor", "fixer", "reviewer")   # the steps that are a model's turn to continue


class Stopped(config.Error):
    """A git or gh that ran out of time or was refused the prompt it wanted.

    Not the same as a tool that answered `no`: nothing was learned, so nothing can be decided
    on it, and the run is left where `ak run resume` can pick it up once the tool works again.
    """


class StopRequested(Exception):
    """A stop landed while this attempt still ran: the disk already says `stopped`.

    Raised by `save_state` when it would overwrite a deliberate end, so a job thread
    whose children were just killed aborts instead of saving `running` back over it.
    Never user-facing: `drive` catches it and keeps the record as the stop left it.
    """


def tool_env():
    """What git and gh are given: this run's environment, with every prompt turned off.

    A headless run has no terminal to answer on, so a credential prompt is not a question --
    it is a wait with nobody at the other end of it.
    """
    env = {**config.child_env(), "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    run_id = getattr(_RUN_CONTEXT, "state", {}).get("run_id")
    if run_id:
        # A git or gh the loop runs is the run's own: it carries the run's marker, so
        # detached or timeout-surviving descendants die with the run like any child.
        # An inherited marker already comes through child_env; this is the loop's own
        # context, which the loop never exports.
        env["AGENTKIT_RUN"] = run_id
    return env


def no_answer(cmd, what):
    """The one line a killed or unanswerable git/gh call leaves behind: what happened, what now."""
    return (f"`{' '.join(cmd[:3])}` {what}: nothing here can answer a credential prompt, so "
            "check `gh auth status` and the remote's credentials by hand, then resume the run")


def tool_run(cmd, cwd=None, timeout=None):
    """(exit code, stdout, stderr) for every git and gh call this module makes.

    The code is None when the call ran out of time, and stderr says so: a tool that has not
    answered inside `timeout` -- TOOL_CAP unless the caller has a shorter deadline of its own
    -- is waiting on a prompt or a network nobody is watching, and a run that waits on it
    stops without ever saying that it has.  A call that did come back because it was refused
    the prompt it wanted is the same problem seen from the other side, and gets the same
    remedy appended to its stderr.
    """
    timeout = TOOL_CAP if timeout is None else timeout
    try:
        proc = subprocess.run(cmd, cwd=None if cwd is None else str(cwd), capture_output=True,
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                              timeout=timeout, env=tool_env())
    except subprocess.TimeoutExpired:
        return None, "", no_answer(cmd, f"was killed after {timeout:g}s")
    err = proc.stderr
    if proc.returncode != 0 and PROMPTED.search(proc.stdout + err):
        err = err.rstrip() + "\n" + no_answer(cmd, "asked for a credential it may not ask for")
    return proc.returncode, proc.stdout, err


def stopped(code, text):
    """Did this call stop rather than answer -- out of time, or refused its prompt?"""
    return code is None or (code != 0 and bool(PROMPTED.search(text)))


def stall_minutes_for(run_dir, state):
    """The shared silence limit, preserving the one recorded when this run launched."""
    return state.get("silence_minutes", SILENCE_MINUTES)


def record_limits(state):
    """Migrate old receipts without reviving task-specific time budgets."""
    for key in ("done_when_minutes", "turn_hours", "stall_minutes"):
        state.pop(key, None)
    state.setdefault("silence_minutes", SILENCE_MINUTES)
    state.setdefault("ceiling_hours", CEILING_HOURS)


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


def worker_dry(cfg, name, text):
    """The harness's own quota word in a failed turn's text, or None.

    A refusal is what the harness itself said -- its manifest's quota words -- not what
    the work printed: an empty text says nothing at all, and a bare number glued into
    a bigger one (a line count, a byte count, a diff hunk) is not the harness refusing
    anything, so every word must stand on its own. The caller ensures only a non-zero
    turn can be one; a turn that exited 0 said what it meant to say.
    """
    if not text or not text.strip():
        return None
    try:
        words = watch.quotas(config.model(cfg, name)["harness"])
    except (config.Error, OSError, ValueError):
        return None
    return next((word for word in words
                 if re.search(r"\b" + re.escape(word) + r"\b", text, re.IGNORECASE)), None)


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
        # first; re-read its snapshot through the normal freshness/reset checks.
        # Retry once only: a persistent filesystem failure still propagates.
        read = usage.collect(cfg)
    return usage.readiness(cfg, read)


def handover_executor(state, cfg, reason, dry=(), log=None):
    """Hand a worker turn to the cheapest legal pair on a provider that refused nothing yet.

    Returns the new executor, or None where none is eligible.  Both roles are re-picked by
    budget under the one-provider rule, so the cheapest legal pair runs and the pair is
    always a legal one -- a reviewer kept from before can be the very model now executing.
    A refused provider never gets the work back (that is how a handover becomes a circle);
    its review is a different matter and takes the spares road if it refuses that too.
    Records the move in `executor_history` with the reason (`stalled`, `dry`). `dry` is
    every provider that already refused this piece of work.
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
        order = [n for n in ready_order(cfg, providers, workers, log)
                 if n != current and config.model(cfg, n)["provider"] not in refused]
        review_order = ready_order(cfg, providers, workers, role="reviewer")
        for name in order:
            candidates = reviewer_order(cfg, name, review_order)
            if candidates:
                new, reviewer = name, candidates[0]
                break
    except (config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    if new is None:
        state.setdefault("executor_history", []).append(
            {"at": time.time(), "from": current, "to": current,
             "reason": f"{reason} (no other provider)"})
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
    save_state(run_dir, state)
    try:
        _, body, _ = parse_task(run_dir / "task.md")
        cmds = done_when(body, run_dir / "task.md")
    except (OSError, config.Error):
        cmds = []
    try:
        write_result(run_dir, state, cmds)
    except (OSError, config.Error, ValueError, KeyError, TypeError):
        pass
    return state


def git(repo, *args, check=True):
    """The command's stdout, raising on failure unless `check` is off.

    `check=False` tolerates a git that said no, never one that never answered: a timeout, or a
    prompt it was refused, is not an empty result, and reading it as one is how a run loses the
    thing it was about to do.
    """
    code, out, err = tool_run(["git", "-C", str(repo), *args])
    halted = stopped(code, err)
    if (check or halted) and code != 0:
        raise (Stopped if halted else config.Error)(
            f"git {' '.join(args)} failed in {repo}: {err.strip()}")
    return out.strip()


def git_out(repo, *args):
    """(exit code, output) -- for the steps whose failure is a result to report, not an exception.

    A stop is never a result: a timeout, or a prompt it was refused, raises Stopped, so no
    caller can route it into conflict handling or read it as an ordinary non-zero exit.
    """
    code, out, err = tool_run(["git", "-C", str(repo), *args])
    if stopped(code, err):
        raise Stopped(f"git {' '.join(args)} stopped in {repo}: {(out + err).strip()}")
    return code, (out + err).strip()


def gh(cwd, *args, timeout=None):
    """(exit code, output); the code is None when the command ran out of time.

    The PR commands are handed the PR's own URL and run from the run directory rather than the
    worktree: outside a checkout `gh pr merge --delete-branch` has no local branch to switch
    away from, and deleting the branch out from under the run's own worktree is not what it means.
    """
    code, out, err = tool_run(["gh", *args], cwd=cwd, timeout=timeout)
    return code, (out + err).strip()


def parse_task(path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not match and text.startswith("---\n"):
        raise config.Error(f"{path}: front matter needs a closing --- line")
    meta, body = {}, match.group(2) if match else text
    for line in (match.group(1).splitlines() if match else []):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise config.Error(f"{path}: front matter line is not `key: value`: {line!r}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.split("#", 1)[0].strip()
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), path.stem)
    return meta, body, title


def project_lessons(repo, state, log):
    """Read the orchestrator's repository facts once for this loop's worker prompts."""
    if repo is None:
        return ""
    directory = config.HOME / "lessons"
    path = directory / f"{Path(repo).name}.md"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open("rb") as fh:
            data = fh.read(LESSONS_CAP + 1)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise config.Error(f"cannot read {path}: {exc}") from exc
    if len(data) > LESSONS_CAP and not state.get("lessons_truncated"):
        log("lessons file over 4 KB; truncated")
        state["lessons_truncated"] = True
    # Omit an incomplete UTF-8 character at the byte limit.
    text = data[:LESSONS_CAP].decode("utf-8", errors="ignore")
    return ("\n\n## Project lessons\n"
            "Facts earlier runs in this repository learned. Follow them; they are not part "
            f"of this task's scope.\n\n{text}")


def done_when(body, path):
    section = re.search(r"^##\s+Done when\s*$(.*?)(?=^##\s|\Z)", body, re.S | re.M | re.I)
    if not section:
        raise config.Error(f"{path}: no `## Done when` section")
    fence = re.search(r"```(?:bash|sh)?\n(.*?)```", section.group(1), re.S)
    if not fence:
        raise config.Error(f"{path}: `## Done when` has no ```bash fenced command block")
    cmds = [l.strip() for l in fence.group(1).splitlines() if l.strip() and not l.strip().startswith("#")]
    if not cmds:
        raise config.Error(f"{path}: `## Done when` block is empty; done means commands that exit 0")
    return cmds


ONCE_MARKER = re.compile(r"#\s*once\s*$")


def split_once(cmd):
    """(command, is_once): strip a trailing `# once` marker, when the line has one.

    The marker is the tail the spec names -- whitespace, `#`, `once` -- and only when
    its `#` is outside any quotes: `echo "# once"` names no marker, it runs one.  The
    stripped command is what the loop executes; bash would ignore the comment anyway,
    so an older loop that runs the line whole runs the same command.
    """
    single = double = False
    escaped = False
    for i, ch in enumerate(cmd):
        if escaped:
            escaped = False
        elif ch == "\\" and not single:
            escaped = True
        elif ch == "'" and not double:
            single = not single
        elif ch == '"' and not single:
            double = not double
        elif ch == "#" and not single and not double:
            if i > 0 and cmd[i - 1] in " \t" and ONCE_MARKER.match(cmd[i:]):
                return cmd[:i].rstrip(), True
    return cmd, False


def group_commands(cmds):
    """(every, once): a command list split on the `# once` marker, markers stripped."""
    every, once = [], []
    for cmd in cmds:
        bare, is_once = split_once(cmd)
        (once if is_once else every).append(bare)
    return every, once


def done_when_groups(body, path):
    """(every, once): the task's done-when commands, split on a trailing `# once` marker.

    `done_when` itself is unchanged -- the flat list, markers intact, for callers that
    want every command plus the once ones.  The every-commands run per round; the
    once-commands run a single time, on the commit about to ship.
    """
    return group_commands(done_when(body, path))


def with_suite(cmds, wt, target=None):
    """The done-when commands plus the declared `tests:` suite as a `# once` line.

    A repository names its full suite once, in AGENTS.md, rather than every task writing it
    into every round: it runs in the final check on the commit about to ship and nowhere
    else.  A task line that is the same command is that line, so it runs once, not twice.
    The checkout's own declaration wins; a checkout branched before the repository
    declared one reads the target branch as fetched instead (`origin/<target>`).
    """
    suite = declared(wt, "tests")
    if not suite and target:
        ref = target if target.startswith("origin/") else f"origin/{target}"
        suite = declared_at(wt, ref, "tests")
    if not suite:
        return cmds
    return [cmd for cmd in cmds if split_once(cmd)[0] != suite] + [f"{suite}  # once"]


def task_points(body):
    """Numbered points in the task's `## Goal` section: `1.` or `1)` with text after it."""
    section = re.search(r"^##\s+Goal\s*$(.*?)(?=^##\s|\Z)", body, re.S | re.M | re.I)
    if not section:
        return 0
    return len(re.findall(r"^[ \t]*\d+[.)][ \t]+\S", section.group(1), re.M))


def task_words(body):
    """Words outside the checks block: the fenced done-when commands are not prose."""
    section = re.search(r"^##\s+Done when\s*$(.*?)(?=^##\s|\Z)", body, re.S | re.M | re.I)
    if section:
        fence = re.search(r"```(?:bash|sh)?\n(.*?)```", section.group(1), re.S)
        if fence:
            body = body.replace(fence.group(0), "", 1)
    return len(body.split())


def task_size(body, cmds):
    """(words outside the checks block, numbered goal points, checks) for one task."""
    return task_words(body), task_points(body), len(cmds)


def task_size_refusal(body, cmds):
    """One sentence when the task is bigger than one behaviour, else None.

    Points first, then words, then checks: the first rule the task breaks is the one
    named, with its count, so the refusal is one sentence however far over it is.
    """
    points = task_points(body)
    if points > TASK_MAX_POINTS:
        return f"task has {points} numbered goal points (at most {TASK_MAX_POINTS})"
    words = task_words(body)
    if words > TASK_MAX_WORDS:
        return (f"task body has {words} words outside the checks block "
                f"(at most {TASK_MAX_WORDS})")
    if len(cmds) > TASK_MAX_CHECKS:
        return f"task has {len(cmds)} checks (at most {TASK_MAX_CHECKS})"
    return None


def rounds_refusal(value, what):
    """One sentence when a round budget asked for is over the rule, else None.

    Three rounds is the budget and never a default to raise: a run that has not passed by
    then goes back to its orchestrator with its findings, to split or re-scope, and no
    flag carries it further.  A value that is no number is left to the check that says so.
    """
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        return None
    if rounds <= TASK_MAX_ROUNDS:
        return None
    return (f"{what} {rounds} is over the budget: {TASK_MAX_ROUNDS} rounds, then a run goes "
            "back to its orchestrator to split or re-scope")


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    return slug or "task"


def task_repo(meta, task_path):
    """`repo:` if the task names one, else the git repository the `ak run` was invoked from.

    A task file that names no repo is the common case: the orchestrator writes it while sitting
    in the repo it is about.  None means there is no repository in this job at all -- `repo:
    none`, or nothing to inherit because the `ak run` was not launched from a checkout -- and
    the run works in a scratch workspace instead.
    """
    if meta.get("repo"):
        if meta["repo"].lower() == "none":
            return None
        repo = Path(meta["repo"]).expanduser().resolve()
        if not (repo / ".git").exists():
            raise config.Error(f"{task_path}: repo {repo} is not a git repository")
        return repo
    code, out, err = tool_run(["git", "rev-parse", "--show-toplevel"])
    if stopped(code, err):
        # "no repository here" is an answer; a git that never gave one must not be read as it,
        # or the work asked for in a checkout would quietly run in a scratch workspace instead
        raise Stopped(f"git rev-parse --show-toplevel failed: {err.strip()}")
    if code != 0:
        return None
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
        for name in workers if workers is not None else config.workers(cfg):
            if name in skip:
                log(f"skipped {name}: {skip[name]}")
    return usage.pick_order(cfg, providers, workers, skip=skip, **kwargs)


def refuse_unready(cfg, providers, name):
    """A model named outright whose harness cannot run here is refused, in one sentence."""
    why = usage.unready(cfg, name, providers)
    if why:
        raise config.Error(f"{name} cannot run here: {why}")


def pick_models(cfg, providers, want_exec, want_review, log, *, resuming=False, quiet=False,
                repo=None, workers=None):
    """The pair a run runs on.  `workers`, when given, is the run's bound list: every
    pick comes from it and an explicit model outside it is refused, exactly as a session
    refuses a name its owner left out.  A worker whose harness is not installed or not logged
    in is never picked, and says so in one line; a launch or resume naming one is refused.
    """
    order = ready_order(cfg, providers, workers, None if want_exec and want_review else log,
                        quiet=quiet, repo=repo)
    session = config.active_session(cfg)
    allowed = workers if workers is not None else (session["workers"] if session else None)
    if want_exec:
        config.model(cfg, want_exec)
        # Legacy callers without a bound run list retain an admitted orchestrator.
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
        if allowed is not None and want_review not in allowed:
            where = f"session {session['name']!r}" if session else "this run"
            raise config.Error(f"{want_review!r} is not a worker of {where}")
        refuse_unready(cfg, providers, want_review)
        reviewer = want_review
    else:
        review_order = ready_order(cfg, providers, workers, role="reviewer", quiet=quiet,
                                   repo=repo)
        for executor in [want_exec] if want_exec else order:
            candidates = reviewer_order(cfg, executor, review_order)
            if candidates:
                reviewer = candidates[0]
                break
        else:
            raise QuotaDry(f"no eligible reviewer: no legal second model for executor {executor}; "
                           "waiting for review")
    review_providers(cfg, executor, reviewer)
    return executor, reviewer


def pair_refusal(cfg, providers, workers, want_exec=None, want_review=None):
    """The one sentence a launch is refused with when no allowed pair can form, or None.

    Budgets are left out: a spent meter refills, and a run waiting on one is parked for a
    reason.  Nothing refills a harness that is not installed or not logged in, and waiting
    grows no second model, so a launch left without an allowed executor and reviewer is
    refused instead of parking on a review nobody can give.  `workers` None is a launch
    outside any session, which the config's default workers bind.
    """
    listed = workers if workers is not None else cfg["defaults"]["workers"]
    skipped = {name: usage.unready(cfg, name, providers) for name in listed}
    ready = [name for name in listed if not skipped[name]]
    reviewers = [want_review] if want_review else ready
    if any(reviewer_order(cfg, name, reviewers) for name in ([want_exec] if want_exec else ready)):
        return None
    why = "; ".join(f"{name}: {reason}" for name, reason in skipped.items() if reason)
    return (f"no two of the workers {', '.join(listed)} make an allowed executor and reviewer"
            + (f" ({why})" if why else "")
            + "; log in to another harness or add another model to the workers")


def review_providers(cfg, executor, reviewer):
    """Never the executor's model; its company is allowed unless the reviewer opts out."""
    executed = config.model(cfg, executor) if executor else None
    reviewed = config.model(cfg, reviewer)
    exec_provider = executed["provider"] if executed else None
    review_provider = reviewed["provider"]
    if executor == reviewer or (executed and exec_provider == review_provider
                                and executed["model"] == reviewed["model"]):
        raise config.Error(f"reviewer {reviewer} is the same model as executor {executor}")
    if exec_provider == review_provider:
        if not reviewed.get("reviews_own_provider", True):
            raise config.Error(f"reviewer {reviewer} shares provider {exec_provider} with executor "
                               f"{executor}; reviews_own_provider = false requires a different provider")
    return exec_provider, review_provider


def reviewer_order(cfg, executor, order):
    """Keep budget order within each company preference, dropping forbidden pairs."""
    cross, same = [], []
    for name in order:
        try:
            executed, reviewed = review_providers(cfg, executor, name)
        except config.Error:
            continue
        (same if executed == reviewed else cross).append(name)
    return cross + same


def review_pass(state, cfg):
    """A verdict alone (including a legacy PASS) is not evidence of a successful review."""
    evidence = state.get("review")
    if state.get("verdict") != "PASS" or not isinstance(evidence, dict):
        return False
    if state.get("repo") and not all(evidence.get(key) for key in ("head_sha", "tree_sha")):
        return False
    if (evidence.get("returncode") != 0 or evidence.get("verdict") != "PASS"
            or evidence.get("done_when") is not True
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
    """This worker's provider refused it, with no applicable reset left to spend.

    Not a death and not a FAIL -- nothing was executed and nothing was judged -- so the work
    goes to another provider rather than being retried where it cannot run.  The refusal and
    the dead session travel with it, so the post-mortem still has both.
    """

    def __init__(self, name, mark, code, text, session, until, message, quota):
        super().__init__(f"{name} refused: {message}")
        self.name, self.mark, self.code, self.text = name, mark, code, text
        self.session, self.until = session, until
        self.message, self.quota = message, quota
        self.why = "ran dry" if quota else "refused"
        self.detail = f"refused: {message}"

    def remember(self, state):
        """Remember a short refusal retry, or clear one when a quota window is parked."""
        if self.quota:
            state.pop("refusal_retry", None)
        else:
            state["refusal_retry"] = {"model": self.name, "at": self.until}


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
    here only once `cannot_run` has found no harness fault on stderr.
    """
    if code == 0 or killed_word(code):
        return None
    if not text.strip():
        return f"exited {code} with an empty final.md"
    hit = TRANSIENT.search(text)
    return f"exited {code} on {hit.group(0)!r}" if hit else None


def cannot_run(code, text, stderr):
    """The stderr line saying this harness never ran the turn at all, or None.

    Only for a non-zero exit, not a kill, that left final.md empty: whatever answered is an
    answer, and a kill takes its own road.  Never beside an OUTAGE line, which is waited out.
    `opencode.sh: opencode is not installed` is the case -- it was retried like a 500,
    hourly, for as long as nobody installed it.
    """
    if code == 0 or killed_word(code) or text.strip() or OUTAGE.search(stderr):
        return None
    return next((" ".join(line.split()) for line in stderr.splitlines()
                 if HARNESS_FAULT.search(line)), None)


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
            with recovery_lock(run_dir):
                state = read_state(run_dir)
                if state and state.get("state") == "running":
                    state["transient_wait"] = {"until": time.time() + delay, "pid": os.getpid()}
                    save_state(run_dir, state)
        except OSError:
            pass            # an unwritten mark costs a stall rung, never the wait itself
    step = history.close_step(run_dir.name)     # the wait is no step's work
    time.sleep(delay)
    history.open_step(run_dir.name, step)


def shell_foreground_note():
    """Keep long commands attached to the turn that must report their result."""
    return ("Run long commands, the test suite included, in the foreground and wait for them; "
            "a turn that ends with a command still running in the background is not finished.")


FINISH_IN_FOREGROUND = ("The command you left in the background was stopped when your turn ended. "
                        "Run it in the foreground now, wait for it, and report.")
NO_VERDICT_ASK = ("Your previous turn ended without a verdict. Review the diff now and end "
                  "your answer with VERDICT: PASS or VERDICT: FAIL. Do not start commands you "
                  "will not wait for in this turn.")


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
    harness managed to say, and it is short.  An answer carries the shape every role's preamble
    asks for -- a `## Summary` heading, a `VERDICT:` line -- and length of its own.
    """
    return len(text) > REFUSAL_CAP or bool(ANSWERED.search(text))


def without_output(node):
    """`node` with every command's and tool's output cut out of it, at any depth."""
    if isinstance(node, dict):
        return {k: without_output(v) for k, v in node.items() if k not in EVENT_OUTPUT}
    if isinstance(node, list):
        return [without_output(item) for item in node]
    return node


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


def refusal_event(node):
    """Whether an event explicitly says the turn failed, rather than a stream warning."""
    if isinstance(node, list):
        return any(refusal_event(item) for item in node)
    if not isinstance(node, dict):
        return False
    for key, value in node.items():
        if key in EVENT_KINDS and isinstance(value, str) \
                and value.lower() in ("turn.failed", "error"):
            return True
    return any(refusal_event(value) for value in node.values())


def failures(chunk, terminal, terminal_only=False):
    """The failure records of an event log, each minus the output of the work it quotes.

    The output goes first, so a command that failed while printing the words a refusal uses
    contributes its exit code and nothing else.  The run's terminal record is kept beside
    them, failure or not: with an empty final.md it is the only place a refusal can be, and
    the adapter may never have filled final.md at all.  A record that declares itself a
    failure is the harness speaking, whatever shape its text has; the answer-shape test
    decides only a terminal record that declares none, where an answer-shaped text is the
    worker's answer and never a refusal.  With ``terminal_only`` (the zero-exit path), only a
    terminal record's explicit refusal or unanswered text is kept, so an earlier stream warning
    cannot discard an answer.  A line that is not a JSON record is not one of the harness's events
    and says nothing here.
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
                       and (refusal_event(record) or not answered(record_text(record))))
        else:
            failure = (is_failure(record)
                       or (is_terminal(record, terminal)
                           and not answered(record_text(record))))
        if failure:
            records.append(json.dumps(record))
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
    if failures_only and answered(text):
        return ""
    terminal = watch.terminal(harness)
    parts = [] if failures_only else ([text] if not answered(text) else [])
    for path in sorted(out_dir.glob("*")):
        if path.name in NOT_HARNESS or path.name == ANSWER or not path.is_file():
            continue
        chunk = tail(path)
        if path.suffix == ".jsonl":
            parts += failures(chunk, terminal, terminal_only=failures_only)
        elif not failures_only:
            parts.append(chunk[-REFUSAL_CAP:])
    return "\n".join(line for part in parts for line in part.splitlines()
                      if line.strip() and not (echo and echo in line))


def ran_dry(code, said, harness, refusal=False):
    """The harness's own word for a spent provider window in this exit, or None.

    Its words and not ours: they come from `[stall] quotas` in adapters/<harness>.toml, the
    same list the babysitter reads off a seat's screen.  A non-zero exit is as required here as
    it is for `transient`, because a worker that exited 0 said what it meant to say.  The scoped
    terminal refusal path may pass ``refusal`` for an exit-zero turn that never answered.
    """
    if code == 0 and not refusal:
        return None
    low = said.lower()
    return next((mark for mark in watch.quotas(harness) if mark.lower() in low), None)


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


def call_retrying(cfg, name, body, workspace, out_dir, role, session, log, limit=None,
                  fresh_body=None, resume_note=None):
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

    A turn that ends with a command still running in the background is unfinished rather than
    answered: the same session is called once more, with no backoff, to run it in the
    foreground and report -- the same round, and not one of the transient waits.  That
    turn gets artifacts of its own (`<role>-retry-foreground`, beside the transient retries'
    `-retryN`, so `written_answer` still finds whose answer the round recorded): the first
    turn's diagnostics survive it, and only what the second turn itself wrote determines
    completion and retry behavior.  A second turn that ends the same way is carried on from
    with a WARN, as if it had been finished.

    Only an answer that names the account hands the round over.  A spent window goes to the
    reset policy first, at the moment of need: a credit spent buys a fresh week, so the same
    worker goes again at once, on its own session and with no backoff.  Nothing to spend
    leaves `RanDry` for the caller, whose job is another provider, not another try here.
    An empty exit whose stderr says the harness never ran the turn leaves `CannotRun` the
    same way, at once: another provider, or a run blocked on that line.

    A worker exit by signal is neither: it reads as the signal, resumes once at once, and on
    a second kill inside a minute raises `Killed` for the run to park on.
    """
    limit = 60 * SILENCE_MINUTES if limit is None else limit
    out_dir = Path(out_dir)
    note = shell_foreground_note()
    if note not in body:
        # the executor and fixer bodies already carry it in the context header; the reviewer
        # body is built from the task text, so it gets it here, said once either way
        body = f"{note}\n\n{body}"
    entry = config.model(cfg, name)
    # Mark only the worker child; the loop's orphaned-orchestrator fallback may still speak.
    # Every role (and retry) lives under <run>/round-N/<role> and inherits this audit log.
    env = {**run_child_env(), "AK_RUN_ROLE": "worker",
           "AK_RUN_LOG": str(out_dir.parent.parent / "log.txt")}
    attempt, calls, refills, last_kill = 1, 0, 0, None

    def turn(text, target, session):
        """One call, with a login failure taken aside before it costs a wait.

        No call starts on a stopped run: the stop lands first and the sweep after
        it, so a retry that outlived the sweep would otherwise run a whole turn no
        record wants anymore.
        """
        stop_check(out_dir.parent.parent)
        try:
            return worker.call(cfg, name, text, workspace, target, role, session, env=env,
                               limit=limit)
        except worker.LoginExpired as expired:
            log(f"{role} {name} cannot authenticate: {expired.why}; the run waits for that "
                "login rather than retrying into it")
            expired.session = expired.session or session
            raise

    while True:
        target = out_dir if not calls else out_dir.with_name(f"{out_dir.name}-retry{calls}")
        # Only the conversation the caller handed in is a resume. An id this ladder's own
        # first attempt left behind is a fresh turn's, and an empty exit on it is the
        # transport failure the three attempts are for, not a session that cannot be opened.
        asked = session if not calls else None
        code, text, sid, killed = turn(body, target, session)
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
            code, text, sid, killed = turn(body, target, None)
            session = sid or None
            calls += 1
        else:
            session, calls = sid or session, calls + 1
        if not killed and turn_unfinished(target):
            log(f"{role} {name} ended its turn with a command still in the background; asking "
                "it to finish in the foreground")
            finish = target.with_name(f"{target.name}-retry-foreground")
            # One extra call per turn covers both reasons it can be needed: a reviewer
            # that left work in the background is asked for its verdict in the same
            # call, so review() never spends a second extra call on the same turn.
            finish_body = (f"{FINISH_IN_FOREGROUND} {NO_VERDICT_ASK}"
                           if role.startswith("reviewer") else FINISH_IN_FOREGROUND)
            code, text, sid, killed = turn(finish_body, finish, session)
            session = sid or session
            if not killed and turn_unfinished(finish):
                log(f"WARN {role} {name} ended its turn with a command still in the background "
                    "again; carrying on with what it reported")
            target = finish
        # A harness that never ran the turn says so on stderr, and that outranks the refusal
        # words below: a 404 for a model it does not have reads `API Error` like a 500, and
        # Codex's missing model suggests `try a different model` like its capacity refusal.
        # Not a wait: the caller hands the work over, or the run is blocked on this line.
        fault = None if killed else cannot_run(code, text, tail(target / "stderr.log"))
        if fault:
            worker.kill_marked(env.get("AGENTKIT_RUN"), log=log)
            log(f"WARN {role} {name} cannot run: {fault}")
            raise CannotRun(name, fault)
        # Some adapters exit zero after streaming turn.failed; that event still refused
        # the turn. On a successful exit only failure events speak, never answer text.
        said = harness_said(target, text, entry["harness"], failures_only=code == 0)
        mark = next((word for word in watch.refusals(entry["harness"])
                     if word.lower() in said.lower()), None)
        if mark:
            # The attempt is refused and its children are not the next one's: whatever
            # the dead turn left behind dies before the refill retry, the handover,
            # or the transient wait.
            worker.kill_marked(env.get("AGENTKIT_RUN"), log=log)
            quota = ran_dry(code, said, entry["harness"],
                            refusal=code == 0 and bool(said))
            lines = [line for line in said.splitlines() if mark.lower() in line.lower()]
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
                delay = transient_delay(attempt)
                log(f"WARN {role} {name} transient {mark!r}: {message} "
                    f"(attempt {attempt}); retrying in {delay}s"
                    + (f", resuming session {session}" if session else ""))
                attempt += 1
                transient_wait(out_dir, delay)
                continue
            spent, left = (usage.replenish(cfg, entry["provider"])
                           if refills < MAX_REFILLS else (False, 0.0))
            if spent:
                refills += 1
                log(f"{role} {name} ran dry; reset spent ({left:g} left), retrying"
                    + (f", resuming session {session}" if session else ""))
                continue
            requested = try_again_at(said)
            until = usage.mark_exhausted(cfg, entry["provider"], requested) or requested
            parked = (f"; nothing is picked on {entry['provider']} until "
                      + time.strftime("%Y-%m-%d %H:%M", time.localtime(until)))
            log(f"WARN {role} {name} refused: {message}{parked}")
            raise RanDry(name, quota, code, text, session, until, message, True)
        sig = killed_word(code) if not killed else None
        if sig:
            # The worker died by signal, not on the provider and not on the task: it
            # resumes once, at once, on the session it left behind.  A second kill
            # inside the minute is somebody -- or something -- killing it on purpose,
            # and the run parks for a person instead of retrying into it.
            worker.kill_marked(env.get("AGENTKIT_RUN"), log=log)
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
            return code, text, session, False
        # The attempt failed and its children are not the next one's: whatever the dead
        # turn left behind dies before the retry, so a retry never inherits them.
        worker.kill_marked(env.get("AGENTKIT_RUN"), log=log)
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


GATE_POLL = 15      # seconds between a waiting gate's tries for a turn; each rewrites its log line


def gate_lock(repo, slot):
    """The lock file of one of a repository's gate turns: its main checkout, whichever worktree."""
    digest = hashlib.sha256(str(repo).encode()).hexdigest()
    return config.RUNS / f".gate-{digest}-{slot}.lock"


def take_slot(slots):
    """The first of the open slot files this call locks, or None while a gate holds each."""
    for slot in slots:
        try:
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            continue
        return slot
    return None


def mark_gate_wait(run_dir, of):
    """Put `waiting for a gate turn of <repo>` on the record, or take it off (`of` None).

    With this process's pid, as the merge turn's mark is: one a kill left behind says nothing.
    """
    try:
        with recovery_lock(run_dir):
            state = read_state(run_dir)
            if state and state.get("state") == "running":
                if of:
                    state["gate_turn"] = {"pid": os.getpid(), "of": of}
                else:
                    state.pop("gate_turn", None)
                save_state(run_dir, state)
    except OSError:
        pass            # an unmarked record costs a status line, never the turn


def gate_turn_note(state):
    """`waiting for a gate turn of <repo>` while a run waits in `gate_turn`, else ""."""
    turn = state.get("gate_turn")
    if (state.get("state") != "running" or not isinstance(turn, dict)
            or turn.get("pid") != state.get("pid")):
        return ""
    return f"waiting for a gate turn of {turn.get('of')}"


def _first_gate_waiters(of, exclude):
    """Whether a `--first` run besides `exclude` waits for a gate turn of `of`."""
    for directory in run_dirs():
        if directory.name == exclude:
            continue
        other = read_state(directory) or {}
        if (other.get("first") and
                gate_turn_note(other) == f"waiting for a gate turn of {of}"):
            return True
    return False


@contextmanager
def gate_turn(run_dir, log_path, log):
    """One of the repository's `max_gates` done-when turns, held for as long as the list runs.

    The host is disk-bound and a gate writes tens of gigabytes: three gates of one repository
    each take as long as one alone, five take four times as long, and nothing capped them.  So
    the gates of one main checkout -- whichever worktree, seat or process -- take turns,
    `max_gates` at once.  A turn is a flock on one of the repository's slot files, which the
    kernel lets go of when its holder dies, so a killed gate never blocks the next.  A waiting
    gate rewrites its own log every poll, so the stall ladder reads the wait as life, and says
    so on its record for `ak run status`; the ceiling starts once the turn is its own, and a
    stop lands while it waits as it does mid-list.  A run without a repository, a direct caller
    with no record, the test suites' `AK_MAX_RUNS=0` and `max_gates = 0` all take no turn.
    A `--first` run takes the next free turn ahead of gates already waiting: a gate
    without it lets a free slot go while one waits.
    """
    record = read_state(run_dir) or {} if run_dir else {}
    repo = record.get("repo")
    is_first = bool(record.get("first"))
    self_id = run_dir.name if run_dir else None
    limit = config.max_gates() if repo and os.environ.get("AK_MAX_RUNS") != "0" else 0
    if not limit:
        yield
        return
    config.RUNS.mkdir(parents=True, exist_ok=True)
    name = Path(repo).name
    with ExitStack() as files:
        slots = [files.enter_context(gate_lock(repo, i).open("a")) for i in range(limit)]
        slot = take_slot(slots)
        if slot is None or (not is_first and slot is not None
                            and _first_gate_waiters(name, self_id)):
            if slot is not None:
                fcntl.flock(slot, fcntl.LOCK_UN)
            began = time.monotonic()
            said = f"waiting for a gate turn · {limit} of {name} running"
            if log is not None:
                log(f"done-when: {said}")
            mark_gate_wait(run_dir, name)
            step = history.close_step(run_dir.name)     # the wait is no step's work
            try:
                while True:
                    log_path.write_text(said + "\n")
                    stop_check(run_dir)
                    time.sleep(GATE_POLL)
                    slot = take_slot(slots)
                    if slot is None:
                        continue
                    if not is_first and _first_gate_waiters(name, self_id):
                        fcntl.flock(slot, fcntl.LOCK_UN)
                        continue
                    break
            finally:
                mark_gate_wait(run_dir, None)
            history.open_step(run_dir.name, step)
            if log is not None:
                log(f"done-when: took a gate turn of {name} after "
                    f"{orch.span(time.monotonic() - began)}")
        yield


def run_done_when(cmds, cwd, log_path, artifacts, limit=None, log=None, silence=None,
                  run_dir=None):
    """Run commands while they produce output, with a ceiling on the whole list.

    Each command gets its own silence window. The list's ceiling never resets,
    so a command that prints forever still fails the round. Output goes straight
    to the gate log so the external stall ladder sees the same activity.

    A stopped gate is a failed gate, never a stopped run: the fixer round runs as it does
    for any other failure.  Whatever the commands newly dirty -- __pycache__, build output
    -- goes into `artifacts`: that is the loop's own droppings, not the executor's work,
    and commit_leftovers must never hand it to the reviewer.

    The commands run seatless, as the workers do: an `ak run` or a smoke suite a done-when
    starts is launched from no seat, so it is nobody's to report and in no seat's tally.

    No command starts on a stopped run: each one asks first, so a stop that lands
    mid-list aborts the gate instead of running commands no record wants anymore.

    A command that exits non-zero runs once more at once, within the same ceiling, and the
    re-run decides it: under load a timing test fails by chance far more often than a change
    breaks it.  A pass that took the re-run is said, not hidden -- a `flaky:` record after
    the command's keeps the first failure's last lines, and the repository's follow-ups file
    gets a dated line (`note_flake`).  A killed command is not re-run: it spent the silence
    window or the ceiling, which a second go would only spend again.

    The list runs on one of the repository's gate turns (`gate_turn`), taken before its first
    command and let go however the list ends; the ceiling counts from the turn, not the wait.
    """
    limit = 3600 * CEILING_HOURS if limit is None else limit
    silence = 60 * SILENCE_MINUTES if silence is None else silence
    before = set(dirty_paths(cwd))
    chunks, ok = [], True
    spent, killed, kept = None, False, ""   # the command the limit ran out on, whether it had
                                            # begun, and the output it had produced by then
    reason = []
    with gate_turn(run_dir, log_path, log):
        deadline = time.monotonic() + limit
        log_path.write_text("")
        for cmd in cmds:
            first = None        # the output of a first run that failed, while its re-run decides
            while True:
                stop_check(run_dir)
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                with log_path.open("ab") as progress:
                    progress.write(f"$ {cmd}\n".encode())
                    progress.flush()
                    offset = progress.tell()
                    code, _, killed = worker.limited(
                        ["bash", "-c", cmd], left, silence=silence, activity=log_path,
                        on_timeout=reason.append, cwd=str(cwd), output=progress,
                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=run_child_env())
                with log_path.open("rb") as progress:
                    progress.seek(max(offset, log_path.stat().st_size - OUT_CAP))
                    out = progress.read().decode("utf-8", errors="replace")
                if code == 0 or killed or first is not None:
                    break
                first = out
            if left <= 0 and first is None:
                # the list is out of time: starting this command would give it a limit of its own
                spent, killed, kept = cmd, False, ""
                chunks.append(f"$ {cmd}\n[not run: the done-when limit was already spent]")
                break
            ok &= code == 0
            chunks.append(f"$ {cmd}\n[{'killed at the limit' if killed else f'exit {code}'}]\n"
                          f"{out[-OUT_CAP:]}".rstrip())
            if first is not None and code == 0:
                # blank lines dropped: a record is what lies between two, and these are one
                tail = [line for line in first.splitlines() if line.strip()][-20:]
                chunks.append("\n".join([f"flaky: {cmd} failed, then passed on its re-run",
                                         *tail]))
                if log is not None:
                    log(f"done-when: flaky: {cmd} failed, then passed on its re-run")
                note_flake(run_dir, cmd, tail[-1] if tail else "(no output)")
            if killed:
                spent, kept = cmd, out
                break
    if spent is not None:
        ok = False
        if killed:
            tail = kept.strip().splitlines()
            last = tail[-1] if tail else "(no output)"
            if len(last) > 160:
                last = last[:159] + "…"
            cause = (f"{silence / 60:g} min of silence" if reason == ["silence"] else
                     f"{limit / 3600:g}h ceiling")
            stopped_line = f"done-when: stopped after {cause}: {spent} (last output: {last})"
        else:
            stopped_line = (f"done-when: stopped after {limit / 3600:g}h ceiling: {spent} "
                            f"(the limit was spent before it could start)")
        chunks.append(stopped_line + ", and the commands after it, if any, were not run.")
        if log is not None:
            log(stopped_line)
    text = "\n\n".join(chunks)
    log_path.write_text(text)
    # The gate is over and its children are not the round's: a command that exited 0 may
    # still have left processes behind, and they die with the gate, however detached.
    worker.kill_marked(run_child_env().get("AGENTKIT_RUN"), log=log)
    artifacts.update(set(dirty_paths(cwd)) - before)
    return ok, text


def note_flake(run_dir, cmd, last):
    """One dated line in the repository's follow-ups file: a done-when line passed on its re-run.

    The gate let the flake through, so the orchestrator is the one told it happened: the run
    id, the command and the last line its first failure printed.  Written under the lock
    `append_followups` rewrites the file under, so neither loses the other's line.  A direct
    caller with no record, or a run with no repository, has no file to write to.
    """
    repo = (read_state(run_dir) or {}).get("repo") if run_dir else None
    if not repo:
        return
    if len(last) > 160:
        last = last[:159] + "\u2026"
    day = time.strftime("%Y-%m-%d", time.localtime())
    directory = config.HOME / "followups"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with (directory / f"{Path(repo).name}.md").open("a", errors="replace") as out:
                out.write(f"- {day} run {Path(run_dir).name}: flaky: {cmd} failed, then passed "
                          f"on its re-run; its first failure ended: {last}\n")
    except OSError:
        pass              # the gate output already says it; the file is the copy


def commit_leftovers(wt, log, artifacts):
    """Commit whatever the executor left uncommitted, so the reviewer sees a real diff.

    The reviewer only ever reads `base...HEAD`.  An executor that wrote the whole change and
    forgot to commit would otherwise be reviewed on an empty diff -- and a review of nothing
    is worse than no review, because it produces a verdict.

    Everything the done-when commands generated is left alone.  Committing that instead earns
    a FAIL on junk the next round's commands recreate, so the fixer can never get out of it.

    A test sandbox is left alone too: a path under a suite sandbox prefix, or one `git
    check-ignore` would ignore, is never committed, whatever the repository's .gitignore
    says -- a test killed mid-way must not ship its stub git and fake adapters.  Sandboxes
    git already ignores are listed back for the count below, since `dirty_paths` never
    sees them.
    """
    paths = [p for p in dirty_paths(wt) if p not in artifacts]
    real, sandbox = [], []
    for path in paths:
        if path.split("/", 1)[0].startswith(SANDBOX_PREFIXES):
            sandbox.append(path)
        elif git_out(wt, "check-ignore", "-q", "--", path)[0] == 0:
            sandbox.append(path)
        else:
            real.append(path)
    sandbox = sorted(set(sandbox) | set(ignored_sandbox_paths(wt, artifacts)))
    if sandbox:
        log(f"left {len(sandbox)} untracked sandbox files uncommitted: "
            f"{', '.join(sandbox[:3])}")
    if not real:
        return
    try:
        git(wt, "add", "--", *real)
        git(wt, "commit", "-m", "wip: uncommitted executor changes", "--", *real)
    except Stopped:
        # a git that stopped verifies nothing: the round ends on the stop, never on a review
        # of a diff the loop did not pin
        raise
    except config.Error as exc:
        log(f"WARN could not commit the executor's uncommitted changes: {exc}")
        return
    log("WARN committed uncommitted executor changes: " + ", ".join(real))


def ignored_sandbox_paths(wt, artifacts):
    """Ignored sandbox files: invisible to `dirty_paths`, still uncommitted.

    Once the repository's .gitignore names the suite's sandbox prefixes, a killed test's
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
        if not entry.rstrip("/").split("/", 1)[0].startswith(SANDBOX_PREFIXES):
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
    names under a suite sandbox prefix are touched; anything else is the work's own.
    """
    try:
        names = sorted(path.name for path in Path(wt).iterdir()
                       if path.name.startswith(SANDBOX_PREFIXES))
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
    git(repo, "worktree", "add", str(wt), "-b", branch, base)
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
        # the per-round commands and the ones that run a single time, on the commit
        # about to ship; without a `# once` line the two are the list and the empty one
        self.every, self.once = group_commands(cmds)
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
        self.done_when_limit = 3600 * state.get("ceiling_hours", CEILING_HOURS)
        self.turn_limit = 60 * state.get("silence_minutes", SILENCE_MINUTES)

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
        self.state.update(executor=self.executor, reviewer=self.reviewer,
                          exec_session=self.exec_sid, review_session=self.review_sid)
        save_state(self.run_dir, self.state)
        history.update_run(self.state.get("run_id"), repo=self.state.get("repo"),
                           executor=self.executor, reviewer=self.reviewer,
                           rounds_used=len(self.state.get("round_summaries") or []),
                           session=launched_session(self.state), log=self.log)

    def step(self, name):
        """Record which step this run is in, and since when, for `ak run status` to read."""
        now = time.time()
        history.open_step(self.state.get("run_id"), name, now, log=self.log)
        self.state.update(step=name, step_at=now)
        self.save()


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


def next_executor(cfg, providers, dry, reviewer, log, repo=None, workers=None):
    """(executor, reviewer) for work whose provider has run dry, or Exhausted when none is left.

    Both roles are re-picked by budget under the one-provider rule, so the cheapest legal
    pair runs: the first executor in the pick order that leaves a legal reviewer, with that
    reviewer beside it.  Keeping the current reviewer instead would force a dearer executor
    on the run -- on 2026-09-22 a Grok refusal kept reviewer Muse and pushed execution onto
    Claude, though executor Muse with reviewer Claude was legal and cheaper.

    `dry` is every provider that has already refused this piece of work, not just the last one:
    a refusal the meters cannot see is still a refusal, and handing the work back to a provider
    that has just turned it down is how a handover becomes a circle.  `workers`, when given,
    is the run's bound list: nothing outside it is ever picked.
    """
    order = [n for n in ready_order(cfg, providers, workers, log, repo=repo)
             if config.model(cfg, n)["provider"] not in dry]
    review_order = [n for n in ready_order(cfg, providers, workers, role="reviewer",
                                           repo=repo)
                    if config.model(cfg, n)["provider"] not in dry]
    for executor in order:
        candidates = reviewer_order(cfg, executor, review_order)
        if candidates:
            return executor, candidates[0]
    raise QuotaDry(f"nothing is left to execute with a legal reviewer: "
                   f"{', '.join(sorted(dry))} ran dry; resume when a meter refills")


def hand_executor(lp, why, detail, dry):
    """Give this round's work to a model on a provider that refused nothing yet.

    The work keeps its identity: the same worktree, the same branch, the same round number and
    the same round budget.  Only the model changes, and it changes in run.json too, so what
    `ak run status` shows and what the result reads is who really did which round.

    Returns the new executor, or None where none is eligible: the refused providers and the
    handover attempt are recorded either way, because the post-mortem needs the attempt as
    well as the move.  `dry` is every provider that already refused this piece of work, not
    just the last one -- handing the work back to one of those is how a handover becomes a
    circle -- so the caller's set grows here and stays grown for the rest of the round.
    """
    before = lp.executor
    workers = run_workers(lp.cfg, lp.state)
    try:
        dry.add(config.model(lp.cfg, before)["provider"])
    except config.Error:
        pass
    try:
        providers = collect_usage(lp.cfg)
        new, reviewer = next_executor(lp.cfg, providers, dry, lp.reviewer, lp.log,
                                      lp.state.get("repo"), workers)
    except (Exhausted, config.Error, OSError, ValueError, KeyError, TypeError, AttributeError):
        new = None
    rnd = started_round(lp.run_dir, lp.state)
    if new is None:
        note_handover(lp.state, before, why, rnd, to=before, reason="dry (no other provider)")
        lp.save()
        return None
    note_handover(lp.state, before, why, rnd, to=new, reason="dry")
    lp.executor, lp.exec_sid = new, None
    previous = lp.reviewer
    if reviewer != previous:
        lp.reviewer, lp.review_sid = reviewer, None
    lp.spares = [n for n in ready_order(lp.cfg, providers, workers, role="reviewer",
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


def open_turn(round_dir, name):
    """`(resume|fresh, session)` when this role's latest attempt never finished.

    `final.md` is written when the harness exits, so its absence is a turn the host
    cut off. A session id recorded there — or recoverable from the event stream — is
    resumed; a directory with neither is a fresh turn, because there is nothing to
    continue. A finished attempt is `(None, None)`.
    """
    dirs = attempt_dirs(round_dir, name)
    if not dirs:
        return None, None
    latest = dirs[-1]
    if (latest / "final.md").exists():
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


def open_worker(lp):
    """`(name, kind, session)` of the open executor/fixer attempt, or three Nones."""
    rd = lp.round_dir
    if not rd.is_dir():
        return None, None, None
    best = None
    for path in rd.iterdir():
        if not path.is_dir() or "-retry" in path.name:
            continue
        base = role_base(path.name)
        if base.startswith("reviewer"):
            continue
        kind, sid = open_turn(rd, base)
        if not kind:
            continue
        latest = attempt_dirs(rd, base)[-1]
        try:
            mtime = latest.stat().st_mtime
        except OSError:
            mtime = 0
        if best is None or mtime >= best[0]:
            best = (mtime, base, kind, sid)
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def open_review(round_dir):
    """`(name, kind, session)` of the open reviewer attempt, or three Nones.

    A review that fell back to another model writes under `reviewer-<model>`, so the
    attempt to continue is the newest reviewer directory of any name, not `reviewer`
    alone: a fallback cut off mid-turn would otherwise start its review over. What a
    turn's own diagnostics left beside it is not an attempt to continue: a retry and a
    foreground finish are named as such, and `review` finds them by those names too.
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
        latest = attempt_dirs(rd, base)[-1]
        try:
            mtime = latest.stat().st_mtime
        except OSError:
            mtime = 0
        if best is None or mtime >= best[0]:
            best = (mtime, base, kind, sid)
    return (None, None, None) if best is None else (best[1], best[2], best[3])


def saved_worker_text(round_dir):
    """The executor or fixer answer already written for this round."""
    for name in ("fixer", "executor"):
        text = finished_answer(round_dir, name)
        if text is not None:
            return text
    if not Path(round_dir).is_dir():
        return ""
    for path in sorted(Path(round_dir).iterdir(), key=lambda item: item.name):
        if not path.is_dir() or "-retry" in path.name:
            continue
        base = role_base(path.name)
        if base.startswith("reviewer"):
            continue
        text = finished_answer(round_dir, base)
        if text:
            return text
    return ""


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
    return (passed == len(lp.every)) if lp.every else passed == total, text


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
    if (lp.state.get("step") == "done-when" or finished_answer(rd, "executor") is not None
            or finished_answer(rd, "fixer") is not None):
        return "done-when"
    return None


def blocked_section(text):
    """The `## Blocked` section a worker ended its turn with instead of `## Summary`, or None.

    The one thing a worker may say that ends the run before anything is judged: the task
    cannot be done as written -- a check that tests the wrong thing, access it does not have,
    two constraints that contradict each other.  It is a `## Blocked` heading on its own line
    with no `## Summary` heading anywhere in the turn, because a turn that summarised its work
    did the work; a preamble or a finding that names either word mid-sentence is neither.  The
    answer is the heading and everything under it up to the next `##` heading, which is what
    result.md carries.
    """
    heading = BLOCKED_HEADING.search(text or "")
    if not heading or SUMMARY_HEADING.search(text):
        return None
    rest = text[heading.end():]
    # the next heading of the same level or higher ends it, never a deeper one: a worker
    # explaining itself under `### Missing access` is still explaining the block
    end = re.search(r"^#{1,2}(?!#)[ \t]*\S", rest, re.M)
    return (heading.group(0) + (rest[:end.start()] if end else rest)).strip()


def blocked_reason(section):
    """The one line a `## Blocked` section comes down to, for the notice and the row.

    The first prose line under the heading: a worker asked to say exactly why puts the why
    first, and everything after it is detail result.md already keeps whole.
    """
    body = [" ".join(line.split()) for line in (section or "").splitlines()[1:]]
    first = next((line for line in body if line and not line.startswith("#")), "")
    first = first.lstrip("-*+ \t") or "the task cannot be completed as written"
    return first if len(first) <= 200 else first[:199] + "\u2026"


def execute(lp, role, text, name):
    """One executor/fixer turn of the current round.  Returns its summary.

    A provider that runs dry mid-round does not end the round: the turn goes to a model
    on a provider that refused nothing yet, in a fresh out dir on a fresh session. Only
    when no provider is left does the round stop -- `exhausted` and resumable, never an
    error for a window that refills.  A turn that died on a transient fault instead of the
    quota never leaves this call: the same session is resumed, indefinitely, inside it.

    A harness that cannot authenticate is neither: no other provider is asked, because the
    work is fine and only the login is not, and the run parks `waiting_login` on the session
    this turn left behind.  A turn killed by signal twice within a minute is neither either:
    the run parks as an interruption, reading `needs you` with the signal for a reason.

    A turn that ends with a `## Blocked` section instead of `## Summary` says the task cannot
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
    out, body, dry = free_dir(lp, name), text, set()
    # Only a turn whose body was replaced by the handover has a conversation that can be
    # refused, and only that turn hands the original prompt and the notice down.
    resume = {}
    note = None
    if kind == "resume":
        body = host_ended_prompt(lp.state)
        lp.exec_sid = sid
        note = {"at": time.time(), "role": role, "restarted": False}
        lp.state["resume_notice"] = note
        resume = {"fresh_body": text, "resume_note": note}
    elif kind == "fresh":
        # The host cut the turn off before a session id was recorded. A fresh
        # conversation gets the original prompt; an older id must not be resumed.
        lp.exec_sid = None
        note = {"at": time.time(), "role": role, "restarted": True}
        lp.state["resume_notice"] = note
    while True:
        # read once the attempt ends, however it ends -- a refused, parked or killed turn spent
        # tokens too -- off its own model and directory, which a handover below moves on from
        model, attempt = lp.executor, out
        try:
            code, summary, lp.exec_sid, dead = call_retrying(lp.cfg, lp.executor, body, lp.wt,
                                                             out, lp.role(role), lp.exec_sid,
                                                             lp.log, lp.turn_limit, **resume)
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
            out = free_dir(lp, f"{name}-{lp.executor}")
            continue
        except RanDry as refused:
            lp.exec_sid = refused.session
            refused.remember(lp.state)
            lp.save()           # the refused session is named in run.json before it is dropped
            before = lp.executor
            new = hand_executor(lp, refused.why, refused.detail, dry)
            if new is None:
                lp.save()  # keep the refused providers and the handover attempt on the record
                raise QuotaDry(f"{role} {before} ran dry on {refused.mark!r}: {refused.detail}; "
                               f"no other provider can execute; "
                               + ("retrying in ten minutes. " if lp.state.get("refusal_retry")
                                  else "resume when a meter refills. ") +
                               f"See {out}*/stderr.log")
            body = f"{HANDOVER.format(before=before)}\n\n{text}"
            out = free_dir(lp, f"{name}-{lp.executor}")
            continue
        finally:
            history_role_tokens(lp.state.get("run_id"), "executor", attempt, lp.log,
                                lp.cfg, model)
        if code != 0:
            lp.log(f"WARN {role} {killed_word(code) or f'exited {code}'}; "
                   f"see {out / 'stderr.log'}")
        lp.save()
        mark = worker_dry(lp.cfg, lp.executor, summary) if code != 0 else None
        if mark is None:
            section = blocked_section(summary)
            if section:
                raise Blocked(blocked_reason(section), section)
            return summary
        # quota the event layer missed still hands over, straight to the other provider:
        # the reset policy already had its moment in call_retrying and found nothing.
        before = lp.executor
        new = hand_executor(lp, "ran dry", f"ran dry on {mark!r}", dry)
        if new is None:
            lp.save()  # keep the refused providers and the handover attempt on the record
            raise QuotaDry(f"{role} {before} ran dry on {mark!r} and no other provider "
                           f"can execute; resume when a meter refills. See {out}*/stderr.log")
        body = f"{HANDOVER.format(before=before)}\n\n{text}"
        out = free_dir(lp, f"{name}-{lp.executor}")


def commit_identity(wt):
    return {"head_sha": git(wt, "rev-parse", "HEAD"),
            "tree_sha": git(wt, "rev-parse", "HEAD^{tree}")}


def current_review(lp):
    """A successful review belongs to exactly the commit that was tested and reviewed."""
    if not review_pass(lp.state, lp.cfg):
        return False
    return lp.scratch or all(lp.state["review"].get(k) == v
                             for k, v in commit_identity(lp.wt).items())


def verify_work(lp, cmds=None):
    """Pin done-when to a commit before running commands, including leftover executor edits.

    Runs `cmds`, or the run's per-round commands when none are given: a `# once` line
    never runs here, only in the final check on the commit about to ship.
    """
    if cmds is None:
        cmds = lp.every
    lp.step("done-when")
    if not lp.scratch and not lp.state.get("review_pr"):
        commit_leftovers(lp.wt, lp.log, lp.artifacts)
    lp.validation = {} if lp.scratch else commit_identity(lp.wt)
    clean = lp.scratch or lp.state.get("review_pr") or git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
    ok, text = run_done_when(cmds, lp.wt, lp.round_dir / "donewhen.log", lp.artifacts,
                             lp.done_when_limit, lp.log, silence=lp.turn_limit,
                             run_dir=lp.run_dir)
    if not lp.scratch and not lp.state.get("review_pr") and (
            not clean or commit_identity(lp.wt) != lp.validation or
            git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0):
        ok = False
        text += "\n\nCheckout changed during done-when; these commands do not verify the pinned commit."
    if lp.validation:
        text = (f"Commit: {lp.validation['head_sha']}\nTree: {lp.validation['tree_sha']}\n\n"
                + text)
        (lp.round_dir / "donewhen.log").write_text(text)
    return ok, text


def pending_review(lp, reason):
    """Invalidate before integration can be delivered, without granting extra task rounds."""
    entries = lp.state["round_summaries"]
    lp.state.update(verdict=None, review=None,
                    review_pending={"round": lp.rnd + 1,
                                    "summary": entries[-1]["summary"] if entries else "",
                                    "reason": reason})
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
                  if pending["round"] <= TASK_MAX_ROUNDS else "split or re-scope the task")
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


def review_verdicts(text):
    """Return verdict words in line order, allowing markdown around a verdict line."""
    return re.findall(r"^[\s>#*_`]*VERDICT:\s*(PASS|FAIL)(?=[\W_]|$)", text, re.M | re.I)


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
            found.append((directory.joinpath("final.md").stat().st_mtime, directory / "final.md"))
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
    for directory in sorted(out.parent.glob(f"{out.name}-retry*"), reverse=True) + [out]:
        if read_answer(directory / "final.md") == text:
            return directory / "final.md"
    return out / "final.md"


def record_findings(lp, out, text):
    """What the reviewer said, and where the whole of it is.

    Written together everywhere, because a `findings_file` left pointing at another answer
    would hand the next fixer the wrong review -- worse than the tail it replaces.
    """
    lp.findings = text
    lp.state["findings"] = text.strip()[-8000:]
    lp.state["findings_file"] = str(written_answer(out, text))


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


def finding_count(text):
    """How much the reviewer found: the list items under its `## Findings` heading.

    The section ends at the next heading of the same level or higher, never at a deeper one:
    a reviewer asked to group its findings by pattern writes `### <pattern>` subheadings
    inside the list, and those sites are findings like any other.  Counted the same way for
    every round, because what it is for is comparing one round's count with the round before.
    No heading, or no list under it, is none.
    """
    return len(FINDING_ITEM.findall(findings_section(text)))


def findings_section(text):
    """What the reviewer wrote under its `## Findings` heading, or "" without one.

    Bounded the way `finding_count` counts it, so the follow-ups listed after it are never
    read as blocking.
    """
    text = text or ""
    heading = FINDINGS.search(text)
    if not heading:
        return ""
    section = text[heading.end():]
    end = re.search(rf"^#{{1,{len(heading.group(1))}}}[ \t]", section, re.M)
    return section[:end.start()] if end else section


def followups_in(text):
    """The reviewer's `## Follow-ups` items, in order, markers stripped.

    Read like `finding_count` reads `## Findings`: the section ends at the next heading of
    the same level or higher, never at a deeper one, and every list item in it is one.
    """
    heading = FOLLOWUPS.search(text or "")
    if not heading:
        return []
    section = text[heading.end():]
    end = re.search(rf"^#{{1,{len(heading.group(1))}}}[ \t]", section, re.M)
    return [item.strip() for item in
            FOLLOWUP_ITEM.findall(section[:end.start()] if end else section)]


def followup_key(item):
    """What deduplicates a follow-up: `path:line - what`, without the why it matters."""
    parts = [part.strip() for part in item.split(" - ")]
    return " - ".join(parts[:2]) if len(parts) > 1 else parts[0]


def followup_keys(item):
    """What makes a follow-up repeat an open one: its `path:line - what`, or its `path:line`."""
    place = FOLLOWUP_PLACE.match(item)
    return {followup_key(item), *([place.group(1)] if place else [])}


def record_followups(lp, text):
    """Fold this review's `## Follow-ups` into the run's own, deduplicated by `path:line - what`.

    A later round re-listing what an earlier one already said adds nothing: the PR description
    and the repo's follow-ups file each carry every item once.
    """
    seen = {followup_key(item) for item in lp.state.get("followups") or []}
    for item in followups_in(text):
        if followup_key(item) not in seen:
            seen.add(followup_key(item))
            lp.state.setdefault("followups", []).append(item)


def append_followups(state, pr_url):
    """Append this run's follow-ups to the repo's file, one bullet each, never a repeat.

    The file is `~/.agentkit/followups/<repo basename>.md`, and every bullet carries the
    date, the run id and the PR number, so the orchestrator reading it before planning the
    next task knows where each item came from.  An item that repeats an open one -- the same
    `path:line`, or the same `path:line - what` -- from an earlier round or an earlier run is
    not written again.  A repository has one file whatever the case of its name: another
    one (`acme.md` beside `ACME.md`) is merged in by date and removed.  The orchestrator
    reads the whole file before every task, so past FOLLOWUPS_CAP the oldest bullets move to
    `<repo basename>.archive.md`, which keeps every one of them and which nobody is told to
    read.  An entry is a bullet and the lines under it, and it is merged, kept or moved
    whole.  A run with no repository has no file to write to.

    The read and the rewrite hold one exclusive lock together, on the directory rather than
    the file, since `repo` and `REPO` rewrite each other's: two runs appending at once
    would otherwise both see the same item as new and write it twice, or each remove the
    file the other merged into.
    """
    items = state.get("followups") or []
    repo = state.get("repo")
    if not items or not repo:
        return
    directory = config.HOME / "followups"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{Path(repo).name}.md"
    number = pr_url.rstrip("/").rsplit("/", 1)[-1]
    day = time.strftime("%Y-%m-%d", time.localtime())
    try:
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            others = [other for other in directory.iterdir() if other.name != path.name
                      and other.name.casefold() == path.name.casefold()]
            entries = []
            for source in (path, *others):
                block = []      # a line that is no bullet belongs to the entry above it
                for line in (source.read_text(errors="replace")
                             if source.exists() else "").splitlines():
                    if line.startswith("- ") or not block:
                        block.append(line)
                    else:
                        block[-1] += f"\n{line}"
                entries += block
            if others:
                # stable: a file's own order stands, and an undated entry counts as oldest
                entries.sort(key=lambda entry: entry[2:12]
                             if re.match(r"- \d{4}-\d\d-\d\d", entry) else "")
            # an entry's item is its first line past the bullet and any `<date> ...: ` stamp,
            # which a hand-written bullet may not have
            known = set().union(*(
                followup_keys(re.sub(r"^- (?:\d{4}-\d\d-\d\d[^:\n]*: )?", "",
                                     entry.split("\n", 1)[0]))
                for entry in entries if entry.startswith("- ")))
            added = []
            for item in items:
                if not followup_keys(item) & known:
                    known |= followup_keys(item)
                    added.append(f"- {day} run {state['run_id']} PR #{number}: {item}")
            entries += added
            size, cut = sum(len(entry.encode()) + 1 for entry in entries), 0
            while size > FOLLOWUPS_CAP:
                size -= len(entries[cut].encode()) + 1
                cut += 1
            if not (added or others or cut):
                return
            # the archive first, then the whole new file in one rename, then the merged-in
            # ones: whatever fails, every entry is still in one file or another
            if cut:
                with (directory / f"{Path(repo).name}.archive.md").open(
                        "a", errors="replace") as archive:
                    archive.write("".join(f"{entry}\n" for entry in entries[:cut]))
            tmp = path.with_suffix(".tmp")
            tmp.write_text("".join(f"{entry}\n" for entry in entries[cut:]), errors="replace")
            tmp.replace(path)
            for other in others:
                other.unlink()
    except OSError:
        pass              # the PR description already carries them; the file is the copy


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

    `gate` keeps each set of commands to its own history: the per-round commands and the
    `# once` ones run at different moments on different trees, so an ordinary round passing
    must not wipe what the final check keeps saying, and the two can never be compared with
    each other anyway.  `compare=False` records without judging, for a round resumed from
    another process, where nothing here knows whether a fixer preceded it.

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
    the commands again.

    `record` is off for a merge pipeline's conflict rounds only: they are not task rounds
    and must not spend one, so no summary of them enters the rounds' own history -- see
    `resolve_conflicts`.  The verdict is recorded either way, because delivery is decided
    on it.
    """
    lp.state.update(verdict=None, review=None,
                    review_pending={"round": lp.rnd, "summary": summary})
    if not record:
        lp.state["review_pending"]["record"] = False
    if hasattr(lp, "step"):
        lp.step("reviewer")
    else:
        lp.state.update(step="reviewer", step_at=time.time())
        lp.save()
    checks = ""
    if lp.scratch:
        work = f"## Workspace ({lp.wt})\n```\n{listing(lp.wt)}\n```"
    else:
        head = "HEAD"
        if lp.state.get("review_pr"):
            head = lp.state["head_sha"]
            restore_review_checkout(lp, "tests")
        else:
            commit_leftovers(lp.wt, lp.log, lp.artifacts)
        diff = git(lp.wt, "diff", f"{lp.base_sha}...{head}", check=False)
        if len(diff) > DIFF_CAP:
            diff = diff[:DIFF_CAP] + f"\n\n[diff truncated at {DIFF_CAP} bytes; use git in {lp.wt} for the rest]"
        work = f"## Diff ({lp.base}...HEAD in {lp.wt})\n```diff\n{diff}\n```"
        # Include removed paths too: renaming a test out of discovery must remain visible.
        changed = git(lp.wt, "diff", "--name-only", "-z", "--no-renames",
                      f"{lp.base_sha}...{head}").split("\0")
        paths = [p for p in changed if p and (
            any(part in ("tests", "test") for part in Path(p).parts[:-1])
            or Path(p).name.startswith("test_") or Path(p).match("*_test.*")
            or any(p in cmd for cmd in getattr(lp, "cmds", [])))]
        if paths:
            # Leave room for full names, including git's quoted non-ASCII paths.
            width = max(len(p.encode()) * 4 + 2 for p in paths)
            stat = git(lp.wt, "diff", f"--stat={width + 80},{width}", "--no-renames",
                       f"{lp.base_sha}...{head}", "--", *(f":(literal){p}" for p in paths))
            checks = ("## Checks the executor changed\n```\n"
                      + "\n".join(stat.splitlines()[:-1]) + "\n```\n\n")
    identity = {} if lp.scratch else commit_identity(lp.wt)
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
        deferred = ("\n".join(f"deferred to the final check on the shipping commit: {cmd}"
                               for cmd in lp.once)
                    + "\nThese run after this review passes; their absence here is by design "
                      "and is never a finding.")
    flaky = ""
    if re.search(r"^flaky: ", dw_log or "", re.M):
        flaky = ("A `flaky:` record is ak's own rule, not a weakened check: a done-when command "
                 "that fails runs once more at once, and it passes if that re-run does.")
    lp.log(f"--- round {lp.rnd}: reviewer {lp.reviewer}")
    rbody = (f"{lp.body}\n\n{work}\n\n"
             f"## Executor summary\n{summary}\n\n{heading}\n"
             + (f"{deferred}\n" if deferred else "")
             + (f"{flaky}\n" if flaky else "")
             + f"```\n{dw_log}\n```")
    if preface:
        rbody = f"{preface}\n\n{rbody}"
    rbody = checks + rbody
    # A review cut off mid-turn is continued where it was, fallback model and all: the
    # attempt after a fallback wrote under `reviewer-<model>`, and asking `reviewer` for
    # it would start the review over in a directory beside the one holding its session.
    # The round is read off `dir`, which is what free_dir writes through.
    rd = lp.dir("reviewer").parent
    name = open_review(rd)[0] or "reviewer"
    def fall_back(reason, out):
        """The path a dry or twice-silent reviewer takes: next spare, else Exhausted."""
        # Recheck at the point of fallback, including spares from saved/legacy callers, and
        # against the meters as they read now: a spare whose own provider has run dry is none.
        try:
            providers = collect_usage(lp.cfg)
        except config.Error as exc:
            providers = {}      # meters nobody could read withhold no spare from a dead review
            lp.log(f"WARN could not read the meters before falling back: {exc}")
        order = ready_order(lp.cfg, providers, run_workers(lp.cfg, lp.state), lp.log,
                            role="reviewer", repo=lp.state.get("repo"))
        lp.spares = reviewer_order(lp.cfg, lp.executor,
                                  [n for n in order if n in lp.spares and n != lp.reviewer])
        if not lp.spares:
            raise Exhausted(f"reviewer {lp.reviewer} {reason} and no eligible reviewer is left "
                            f"to review; waiting for review. See {out}*/stderr.log")
        lp.reviewer, lp.review_sid = lp.spares.pop(0), None
        lp.save()
        # said only where it is true: a spare may share the executor's company
        theirs, spare = review_providers(lp.cfg, lp.executor, lp.reviewer)
        lp.log(f"WARN reviewer fell back to {lp.reviewer}"
               f"{' on another provider' if theirs not in (None, spare) else ''}")
        return f"reviewer-{lp.reviewer}"
    while True:
        if not lp.executor and not lp.state.get("review_pr"):
            raise config.Error("task review requires a recorded executor")
        exec_provider, review_provider = review_providers(lp.cfg, lp.executor, lp.reviewer)
        # The open attempt is read before free_dir creates the next directory.
        turn_kind, turn_sid = open_turn(rd, name)
        out = free_dir(lp, name)
        asked_body, note, resume = rbody, None, {}
        if turn_kind == "resume":
            asked_body = host_ended_prompt(lp.state)
            lp.review_sid = turn_sid
            note = {"at": time.time(), "role": "reviewer", "restarted": False}
            lp.state["resume_notice"] = note
            resume = {"fresh_body": rbody, "resume_note": note}
        elif turn_kind == "fresh":
            lp.review_sid = None
            note = {"at": time.time(), "role": "reviewer", "restarted": True}
            lp.state["resume_notice"] = note
        why = "died on API/transport errors"
        model = lp.reviewer     # a fallback below moves on from it before its tokens are read
        try:
            code, text, lp.review_sid, dead = call_retrying(lp.cfg, lp.reviewer, asked_body,
                                                            lp.wt, out, lp.role("reviewer"),
                                                            lp.review_sid, lp.log,
                                                            lp.turn_limit, **resume)
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
        except RanDry as dry:
            # A spent window is the other way a reviewer stops without judging the diff, so it
            # takes the same road out: the spares, checked against the executor and config.
            dry.remember(lp.state)
            code, text, lp.review_sid, dead, why = dry.code, dry.text, dry.session, True, dry.detail
        finally:
            history_role_tokens(lp.state.get("run_id"), "reviewer", out, lp.log, lp.cfg, model)
        if code != 0:
            lp.log(f"WARN reviewer {killed_word(code) or f'exited {code}'}; "
                   f"see {out / 'stderr.log'}")
        if dead:
            record_findings(lp, out, text)
            lp.save()
            name = fall_back(why, out)
            continue
        if review_verdicts(text):
            break
        # A missing verdict is a reviewer that has not answered, never an answer: ask the
        # same session once more, same round, no backoff, not a transport attempt.  When
        # the turn already spent its one extra call finishing background work in the
        # foreground, that call already carried the verdict ask, so a second silence
        # means the reviewer is gone: no round is recorded, same as a dead reviewer.
        if list(lp.round_dir.glob(f"{out.name}*foreground*")):
            record_findings(lp, out, text)
            lp.save()
            # The fallback must not inherit the twice-silent turn's children: whatever
            # the attempts without a verdict left behind dies before the spare starts.
            worker.kill_marked(run_child_env().get("AGENTKIT_RUN"), log=lp.log)
            name = fall_back("gave no verdict twice", out)
            continue
        lp.log(f"reviewer {lp.reviewer} gave no verdict; asking once more")
        out2 = lp.dir(name)
        attempt2 = 1
        while out2.exists():
            attempt2 += 1
            out2 = lp.dir(f"{name}-attempt{attempt2}")
        env2 = {**run_child_env(), "AK_RUN_ROLE": "worker",
                "AK_RUN_LOG": str(out2.parent.parent / "log.txt")}
        stop_check(lp.run_dir)
        try:
            code2, text2, sid2, killed2 = worker.call(lp.cfg, lp.reviewer, NO_VERDICT_ASK, lp.wt,
                                                      out2, lp.role("reviewer"), lp.review_sid,
                                                      env=env2, limit=lp.turn_limit)
        except worker.LoginExpired as expired:
            lp.review_sid = expired.session or lp.review_sid
            lp.save()           # the parked conversation is in run.json before the run parks
            raise
        finally:
            history_role_tokens(lp.state.get("run_id"), "reviewer", out2, lp.log,
                                lp.cfg, lp.reviewer)
        lp.review_sid = sid2 or lp.review_sid
        if code2 != 0:
            lp.log(f"WARN reviewer {killed_word(code2) or f'exited {code2}'}; "
                   f"see {out2 / 'stderr.log'}")
        if not killed2 and turn_unfinished(out2) and review_verdicts(text2):
            lp.log(f"WARN reviewer {lp.reviewer} ended its turn with a command still in the "
                   "background again; carrying on with what it reported")
        if review_verdicts(text2):
            code, text, out = code2, text2, out2
            break
        record_findings(lp, out2, text2)
        lp.save()
        # The fallback must not inherit the silent turn's children: whatever the extra
        # ask left behind dies before the spare reviewer starts.
        worker.kill_marked(run_child_env().get("AGENTKIT_RUN"), log=lp.log)
        name = fall_back("gave no verdict twice", out2)

    verdicts = review_verdicts(text)
    verdict = verdicts[-1].upper()
    overridden = None       # why the loop failed what the reviewer passed, for the hand-back
    if code != 0 and verdict == "PASS":
        verdict = "FAIL"
        overridden = f"the reviewer said PASS but {killed_word(code) or f'exited {code}'}"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    if not ok and verdict == "PASS":
        verdict = "FAIL"
        overridden = "the reviewer said PASS while done-when is failing"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    if not lp.scratch and (identity != validation or commit_identity(lp.wt) != identity
                           or (not lp.state.get("review_pr") and
                               git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0)):
        verdict = "FAIL"
        overridden = "the checkout changed after verification"
        lp.log(f"WARN {overridden}; overriding to FAIL")
    record_findings(lp, out, text)
    record_followups(lp, text)
    if record:
        lp.state["round_summaries"].append(
            {"round": lp.rnd, "verdict": verdict, "done_when": ok,
             "finding_count": finding_count(text),
             "summary": summary.strip()[-4000:], **validation})
    lp.log(f"round {lp.rnd} verdict: {verdict}")
    lp.state["verdict"] = verdict
    lp.state["review"] = {"executor": lp.executor, "executor_provider": exec_provider,
                          "reviewer": lp.reviewer, "reviewer_provider": review_provider,
                          "returncode": code, "verdict": verdict, "done_when": ok, **validation,
                          **({"overridden": overridden} if overridden else {})}
    lp.state.pop("review_pending", None)
    lp.save()
    return verdict


def round_findings(lp, entry):
    """How much a round found: the number it recorded, or the answer it left on disk.

    A run saved before the count was recorded still has its reviewer's text in the round
    directory, and a budget decision must not read a missing number as "found nothing".
    None when neither is there -- that is not a count, and nothing can be compared to it.
    """
    if isinstance(entry.get("finding_count"), int):
        return entry["finding_count"]
    files = review_files(lp.run_dir, entry.get("round"))
    whole = read_answer(files[-1]) if files else None
    return finding_count(whole) if whole is not None else None


def rounds(lp):
    """Executor -> done-when -> reviewer, until PASS or the round budget is spent.

    Only a recorded successful review by an eligible model can skip straight to delivery.
    An unfinished review resumes on the saved work without spending another executor turn.
    """
    invalidate_saved_pass(lp.state, lp.cfg, lp.log)
    lp.rounds = lp.state["rounds"]
    lp.save()
    if review_pass(lp.state, lp.cfg) and not current_review(lp):
        pending_review(lp, "The saved reviewed commit changed; verify the current checkout.")
    if current_review(lp):
        lp.log(f"already passed at round {lp.rnd}/{lp.rounds}; going straight to the merge")
        return
    pending = lp.state.get("review_pending")
    if pending:
        # a review finished on a resume is the round's verdict
        if resume_review(lp) == "PASS":
            return
    while lp.rnd < lp.rounds:
        lp.rnd += 1
        cut = continuation(lp)
        if cut in ("reviewer", "done-when"):
            # The worker already answered. A done-when that was cut off runs again;
            # a review that was the open step is continued, not preceded by another
            # executor turn.
            summary = saved_worker_text(lp.round_dir)
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
                    summary = execute(lp, "fixer",
                                      f"{lp.context}\n\n## Reviewer findings to fix\n{lp.findings}",
                                      "executor")
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
    save_state(lp.run_dir, lp.state)
    return False


def park_waiting(lp, reason, ref, sha=None):
    """Park the run `waiting` on the next merge to `ref`, with the reason.

    Not an ending and never a FAIL: the work passed review and only the world stands in
    its way, and the world keeps moving.  The record carries the whole of the wait -- the
    reason on `merge_note` and on `error`, the ref to watch and the sha a fetch reads now
    -- so the tick picks the run up after the next merge to `ref` and retries it there
    rather than anybody losing the passed work behind a note.
    """
    note(lp, reason, failed=False)
    waiting_on = {"ref": ref}
    if sha:
        waiting_on["sha"] = sha
    lp.state.update(state="waiting", error=reason, waiting_on=waiting_on)
    lp.state.pop("recovery_pending", None)  # the wait is the tick's now
    save_state(lp.run_dir, lp.state)
    lp.log(f"--- merge: parked waiting; retried after the next merge to {ref}")
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
    """The branch now carries the pinned tip, so that is what its diff is against from here on."""
    lp.state["base_sha"] = git(lp.wt, "rev-parse", f"{tip}^{{commit}}")
    save_state(lp.run_dir, lp.state)


def on_pass(lp):
    """The dependency whose passed branch this branch still stands on, or None.

    From the cut until the first integration puts the branch on a target commit instead: the
    dependency's commits are under it, and reach the target only with its own merge.
    """
    after = lp.state.get("from_pass")
    return after["task"] if after and lp.base_sha == after.get("tip") else None


def dep_wait_note(state):
    """`waiting for <dep> to merge` while a run waits in `wait_for_dependency`, else "".

    The mark names the process that waits, so one a kill left on the record, or a resume
    carried forward to a new process, says nothing.
    """
    wait = state.get("dep_wait")
    if (state.get("state") != "running" or not isinstance(wait, dict)
            or wait.get("pid") != state.get("pid")):
        return ""
    return f"waiting for {wait.get('of')} to merge"


def wait_for_dependency(lp):
    """Hold a branch cut from a dependency's passed branch until the dependency has merged.

    Landing first would deliver the dependency's work under this task's name, so the run
    waits for its job to settle that task, then `integrate` replays only its own commits.
    A dependency settled without merging leaves nothing to stand on: the run stops before
    landing, its branch kept, and the job skips the task as `after:` always did.
    """
    dep = on_pass(lp)
    if not dep:
        return True
    waited, step = False, None
    while True:
        stop_check(lp.run_dir)
        job = read_job(config.JOBS / str(lp.state.get("job_id")))
        word = (job_task_by_name(job, dep) or {}).get("state") if job else None
        if word in ("merged", "passed"):
            break
        if word is None or word in (*JOB_UNDELIVERED, "skipped"):
            lp.state["skipped_dep"] = dep
            lp.state.pop("dep_wait", None)
            return note(lp, f"{dep} did not merge; this branch stands on its work and is kept")
        if not waited:
            lp.state["dep_wait"] = {"pid": os.getpid(), "of": dep}
            save_state(lp.run_dir, lp.state)
            lp.log(f"--- merge: waiting for {dep} to merge before landing on it")
            step = history.close_step(lp.state.get("run_id"), log=lp.log)   # a wait, not work
            waited = True
        time.sleep(JOB_TICK)
    if waited:
        lp.state.pop("dep_wait", None)
        save_state(lp.run_dir, lp.state)
        history.open_step(lp.state.get("run_id"), step, log=lp.log)
        lp.log(f"--- merge: {dep} merged; landing")
    return True


def abort_integration(lp, how):
    """Put the branch back, and drop the re-review the abandoned integration asked for.

    `integrate` records that pending review before git rewrites HEAD, so an interruption
    mid-rebase cannot leave a saved PASS.  Once the rebase or merge is aborted the branch is
    exactly what it was and the record describes work that never happened: left behind, it
    would spend a resumed run's next round re-reviewing instead of fixing, and record that
    round twice.  The invalidated verdict stays invalidated -- only the pending work goes.
    """
    git_out(lp.wt, how, "--abort")
    lp.state.pop("review_pending", None)
    save_state(lp.run_dir, lp.state)


CONFLICT_ROUNDS = 3      # the merge pipeline's own fixer rounds per conflicted rebase or merge,
                         # and per final check that keeps failing


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
    what = f"the {how} of {upstream}"
    while lp.rnd < lp.rounds:
        fix = f"{lp.context}\n\n## Reviewer findings to fix\n{lp.findings}"
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
    again.
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
            summary = execute(lp, "fixer", text, f"{how}-fixer")
        except (Dead, Blocked, Exhausted, Killed, worker.LoginExpired):
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
    # Verification or review can park on a provider too. Its resume must keep the
    # conflict round out of the task budget just as the uninterrupted path does.
    lp.state["review_pending"] = {"round": lp.rnd, "summary": summary,
                                  "reason": f"Re-review after {what}.", "record": False}
    lp.save()
    ok, dw_log = verify_work(lp)
    lp.log(f"done-when after the {how}: {'all passed' if ok else 'FAILED'}")
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


def integrate(lp, upstream):
    """Fetch origin and bring the branch up to date with it, resolving conflicts if there are any.

    A rebase, unless `how_to_integrate` says this branch's history has to survive the trip.
    The tip is resolved once per lap and every check after it uses that pinned commit, never
    the moving branch name again.  When origin moved while the lap landed, the lap goes round
    again, at most three laps; a move still unlanded after the third parks the run `waiting`,
    as a conflict does, and never ends it FAIL.  A branch left with no diff is False too, a
    PASS noted as already on the target, so no caller pushes it.

    A fetch, merge or rebase that stops -- out of time, or refused its prompt -- is not a
    conflict and never reaches `resolve_conflicts`: `git_out` raises Stopped, the worktree
    goes back on the branch head, and the stop propagates, so the run ends retryable with
    its remedy instead of spending a round on it.
    """
    for lap in (1, 2, 3):
        # --prune: a merged PR's branch, deleted on origin, otherwise leaves its tracking ref
        # behind, and push's lease holds a later run that reuses the name to that dead head
        rc, out = git_out(lp.wt, "fetch", "origin", "--prune")
        if rc != 0:
            return note(lp, f"git fetch origin failed: {out[-400:]}", failed=True)
        if not git(lp.wt, "rev-parse", "--verify", "--quiet", f"{upstream}^{{commit}}",
                   check=False):
            return note(lp, f"{upstream} does not exist on origin; nothing to merge into",
                        failed=True)
        tip = git(lp.wt, "rev-parse", f"{upstream}^{{commit}}")
        # a branch cut from a dependency's passed branch replays only its own commits: the
        # dependency most often lands squashed, its commits on the target under other names
        onto = ("--onto", tip, lp.base_sha) if on_pass(lp) else (tip,)
        how = "rebase" if on_pass(lp) else how_to_integrate(lp)
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
        # Persist invalidation before git rewrites HEAD: interruption must not leave a saved PASS.
        if not integrated(lp.wt, tip):
            pending_review(lp, f"Re-review after the {how} of {upstream}.")
        try:
            if how == "merge":
                lp.log(f"--- merge: merging {upstream} ({tip[:12]}) into {lp.state['branch']}")
                # check 19 in tests/smoke.sh pins the bare line below; the SHA line above
                # records the pinned tip this lap integrated.
                lp.log(f"--- merge: merging {upstream} into {lp.state['branch']}")
                rc, out = git_out(lp.wt, "merge", "--no-edit", tip)
            else:
                lp.log(f"--- merge: rebasing {lp.state['branch']} onto {upstream} ({tip[:12]})")
                rc, out = git_out(lp.wt, "rebase", *onto)
        except Stopped:
            abort_stopped_integration(lp, how)
            raise
        if rc != 0:
            if not resolve_conflicts(lp, upstream, out, how, tip):
                return False
        else:
            set_base(lp, tip)
            if current_review(lp):
                lp.log("--- merge: unchanged commit; reusing done-when and review evidence")
            else:
                # a passed review survives a clean integration whatever it leaves, an empty
                # diff included: the done-when runs again on the new commit, and only its
                # failure or a commit it changed sends the work back to the reviewer
                if (was_pass and saved is not None and pre_identity is not None
                        and saved.get("head_sha") == pre_identity.get("head_sha")
                        and saved.get("tree_sha") == pre_identity.get("tree_sha")):
                    try:
                        post_identity = commit_identity(lp.wt)
                    except Stopped:
                        raise
                    except config.Error:
                        post_identity = None
                    if post_identity is None:
                        if not lp.state.get("review_pending"):
                            pending_review(lp, f"Re-review after the {how} of {upstream}.")
                        if (resume_review(lp) != "PASS"
                                and not fix_after_failed_review(lp, upstream, how)):
                            return note(lp, f"done-when or review after the {how} of {upstream} "
                                            "did not pass")
                    else:
                        pending = lp.state.get("review_pending")
                        pending_round = pending["round"] if pending else lp.rnd + 1
                        old_rnd = lp.rnd
                        lp.rnd = pending_round
                        lp.round_dir.mkdir(parents=True, exist_ok=True)
                        ok, dw_log = verify_work(lp)
                        lp.log(f"done-when after the {how}: {'all passed' if ok else 'FAILED'}")
                        if ok:
                            new_identity = commit_identity(lp.wt)
                            if new_identity != post_identity:
                                if not lp.state.get("review_pending"):
                                    pending_review(lp, f"Re-review after the {how} of {upstream}.")
                                if (resume_review(lp, verified=(ok, dw_log)) != "PASS"
                                        and not fix_after_failed_review(lp, upstream, how)):
                                    return note(lp, f"done-when or review after the {how} of {upstream} "
                                                    "did not pass")
                            else:
                                lp.log(f"--- merge: clean {how} of {upstream}; "
                                       "done-when passed again, review kept")
                                lp.state["review"] = {**saved, "head_sha": new_identity["head_sha"],
                                                      "tree_sha": new_identity["tree_sha"],
                                                      "rebased_from": old_head,
                                                      "patch_id": patch_id(lp.wt, tip)}
                                lp.state["verdict"] = saved_verdict
                                lp.state.pop("review_pending", None)
                                lp.save()
                                lp.rnd = old_rnd
                        else:
                            if not lp.state.get("review_pending"):
                                pending_review(lp, f"Re-review after the {how} of {upstream}.")
                            if (resume_review(lp, verified=(ok, dw_log)) != "PASS"
                                    and not fix_after_failed_review(lp, upstream, how)):
                                return note(lp, f"done-when or review after the {how} of {upstream} "
                                                "did not pass")
                else:
                    if not lp.state.get("review_pending"):
                        pending_review(lp, f"Re-review after the {how} of {upstream}.")
                    if (resume_review(lp) != "PASS"
                            and not fix_after_failed_review(lp, upstream, how)):
                        return note(lp, f"done-when or review after the {how} of {upstream} "
                                        "did not pass")
        rc, out = git_out(lp.wt, "fetch", "origin", "--prune")
        if rc != 0:
            return note(lp, f"git fetch origin failed: {out[-400:]}", failed=True)
        new_tip = git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False)
        if not new_tip:
            return note(lp, f"{upstream} does not exist on origin; nothing to merge into",
                        failed=True)
        if integrated(lp.wt, new_tip):
            if git_out(lp.wt, "diff", "--quiet", new_tip, "HEAD")[0] == 0:
                # the target already carries every line of the branch, however it got there:
                # nothing is left to push, and the job counts the run as passed
                lp.state["on_target"] = True
                return note(lp, f"its work is already on {upstream.removeprefix('origin/')}")
            return True
        if lap == 3:
            # the world moving, like a conflict: parked on the tip this lap landed, which
            # origin is already past, so the tick's next pass retries it
            return park_waiting(lp, f"{upstream} moved three times during integration",
                                upstream, tip)
        lp.log(f"--- merge: {upstream} moved to {new_tip[:12]} while the fix ran; rebasing again")
    return False


def push(lp):
    require_review_pass(lp)
    branch = lp.state["branch"]
    head = git(lp.wt, "rev-parse", "HEAD", check=False)
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
    save_state(lp.run_dir, lp.state)
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
    save_state(lp.run_dir, lp.state)
    return True


def pr_body(state):
    last = state["round_summaries"][-1]["summary"].strip() if state["round_summaries"] else ""
    lines = [last, "", "---", "",
             f"- verdict: {state['verdict']}",
             f"- rounds: {len(state['round_summaries'])} of {state['rounds']}",
             f"- executor: {state['executor']}, reviewer: {state['reviewer']}",
             f"- run: {state['run_id']}"]
    if state.get("followups"):
        lines += ["", "## Follow-ups", "",
                  *(f"- {item}" for item in state["followups"])]
    return "\n".join(lines + [""])


def open_pr(lp, target_branch):
    """The PR's URL, opening it first unless this branch already has one."""
    if lp.state.get("pr"):
        # a re-review after the PR already existed may have collected more follow-ups
        (lp.run_dir / "pr-body.md").write_text(pr_body(lp.state))
        append_followups(lp.state, lp.state["pr"])
        return lp.state["pr"]
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
    save_state(lp.run_dir, lp.state)
    append_followups(lp.state, lp.state["pr"])
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


def checks(lp, url):
    """Wait for the target's required names, including checks that have not registered yet."""
    pr = urlsplit(url)
    match = re.fullmatch(r"/([^/\s]+)/([^/\s]+)/pull/(\d+)/?", pr.path)
    if not match or pr.scheme != "https" or not pr.hostname or pr.username or pr.query or pr.fragment:
        return False, f"cannot read required checks for {url}"
    owner, repo, _ = match.groups()
    api = ("api",) if pr.netloc == "github.com" else ("api", "--hostname", pr.netloc)
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
                                else "fail" for check in matches]
                if not (apps - {None}).issubset({check["app"]["id"] for check in matches}):
                    missing_apps.add(name)
                    states[name] = []  # a same-named check from another app cannot satisfy it
        except (KeyError, TypeError, ValueError) as exc:
            return False, f"cannot read required check runs: {exc}"
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
                        if any(bucket in ("fail", "cancel") for bucket in buckets))
        if failed:
            return False, f"required checks failed: {', '.join(failed)}"
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
        append_followups(lp.state, lp.state["pr"])
        lp.log(f"--- merge: PR {lp.state['pr']}" + (" (already open)" if rc != 0 else ""))
    else:
        # a re-review after the PR already existed may have collected more follow-ups
        (lp.run_dir / "pr-body.md").write_text(pr_body(lp.state))
        append_followups(lp.state, lp.state["pr"])
    lp.state["foreign"] = True
    return note(lp, "waiting for the maintainer")


def do_merge(lp, url, upstream):
    """Merge the PR, integrating once more if origin moved under it while the checks ran.

    `gh pr merge` answering `Base branch was modified` is a race with a merge to the
    target between the push and this call, not an ending: the answer is re-fetched, the
    PR is re-checked to still be mergeable, and the merge is tried again -- three times,
    with a growing wait -- and only then does the run park `waiting` with the reason,
    retried after the next merge to the target.  Work that passed review is never thrown
    away over one lost race.
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
                rc, out = gh(lp.run_dir, "pr", "merge", url, MERGE_METHODS[method], "--delete-branch",
                             "--match-head-commit", lp.state["delivery_sha"])
            if rc == 0 or stopped(rc, out) or not BASE_BRANCH_MODIFIED.search(out or ""):
                break
            if raced >= MERGE_RETRIES:
                lost = True
                break
            raced += 1
            delay = transient_delay(raced)
            lp.log(f"WARN the base branch was modified under the merge; re-fetching, "
                   f"re-checking and retrying in {delay}s ({raced}/{MERGE_RETRIES})")
            step = history.close_step(lp.state.get("run_id"), log=lp.log)   # a wait, not work
            time.sleep(delay)
            history.open_step(lp.state.get("run_id"), step, log=lp.log)
            frc, fetched = git_out(lp.wt, "fetch", "origin")
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
            if (info.get("headRefOid") != lp.state["delivery_sha"]
                    or info.get("baseRefName") != upstream.removeprefix("origin/")):
                return note(lp, "PR head or target changed since PASS; a new run is required",
                            failed=True)
            seen, mergeable = info.get("state"), info.get("mergeable")
            if seen == "MERGED":
                lp.state["merged"] = True
                save_state(lp.run_dir, lp.state)
                lp.log(f"--- merge: merged {url} with --{method}, remote branch deleted")
                return True
            if seen != "OPEN":
                return note(lp, "PR is closed without a merge", failed=True)
            # A moving target can change both the patch and its checks. Reuse the same
            # integration path as a BEHIND retry before authorizing the new head.
            head = lp.state["delivery_sha"]
            if not integrate(lp, upstream):
                return False
            if git(lp.wt, "rev-parse", "HEAD") != head:
                if not final_check(lp, upstream) or not push(lp) or not wait_checks(lp, url):
                    return False
                (lp.run_dir / "pr-body.md").write_text(pr_body(lp.state))
                append_followups(lp.state, url)
                ready = True
            else:
                # GitHub may still be computing mergeability. An unconfirmed answer
                # uses the remaining retries to re-check before authorizing a merge.
                ready = mergeable == "MERGEABLE"
        if rc == 0:
            lp.state["merged"] = True
            save_state(lp.run_dir, lp.state)
            lp.log(f"--- merge: merged {url} with --{method}, remote branch deleted")
            return True
        if lost:
            return park_waiting(
                lp, f"gh pr merge --{method} failed after {MERGE_RETRIES} retries of a "
                    f"modified base; the PR is open at {url}", upstream,
                git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False) or None)
        vrc, why = gh(lp.run_dir, "pr", "view", url, "--json", "mergeStateStatus",
                      "-q", ".mergeStateStatus")
        if stopped(rc, out) or stopped(vrc, why):
            # A merge that stopped may still have gone through server-side.  Only `state`
            # says MERGED -- mergeStateStatus carries mergeability (BEHIND/BLOCKED/CLEAN and
            # the rest), never the outcome -- so that is what confirms it.
            src, current = gh(lp.run_dir, "pr", "view", url, "--json", "state",
                              "-q", ".state")
            if src == 0 and current.strip() == "MERGED":
                lp.state["merged"] = True
                save_state(lp.run_dir, lp.state)
                lp.log(f"--- merge: merged {url} with --{method}, remote branch deleted")
                return True
            raise Stopped(out if stopped(rc, out) else why)
        if attempt == 2 or why not in ("BEHIND", "DIRTY"):
            break
        lp.log(f"WARN the PR is {why}; taking {upstream} in once more and retrying the merge")
        # the retry pushes a new head, so its checks are a new run: wait them out again rather
        # than merging on the strength of the ones that passed for the commit just replaced --
        # and its `# once` commands too, which have only ever run on that commit
        if (not integrate(lp, upstream) or not final_check(lp, upstream) or not push(lp)
                or not wait_checks(lp, url)):
            return False
        # the retry's re-review may have collected more follow-ups after the PR already existed
        (lp.run_dir / "pr-body.md").write_text(pr_body(lp.state))
        append_followups(lp.state, url)
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


def final_check(lp, upstream):
    """Run every-commands plus once-commands on the commit about to be pushed.

    True when the commit may be pushed.  A `# once` line runs nowhere else in the
    run, so this is its single execution; without one there is nothing to do and
    today's evidence reuse stands.  The run is pinned the way `verify_work` pins
    one: the commit and tree are recorded, and a checkout that changes during the
    check fails it.  The output goes to `<run dir>/final-check.log`.

    A failed check is handled like a rebase conflict.  The work already passed review,
    and what fails this late is as often the world -- a login, a scope, a service -- as
    the work, so a final-check fixer round spends no task round and the check never ends
    the run FAIL.  Up to `CONFLICT_ROUNDS` of them work from the failing output; each is
    verified and re-reviewed, then integration and this check run again.  A re-review
    that does not pass is a failed review like any other -- a fixer round on its
    findings, within the round budget it may spend, and once that is spent a review FAIL
    handed back with them.  Still failing after the last one, the run parks `waiting`
    with the check's first failing line, retried after the next merge to `upstream`.
    """
    if not lp.once:
        return True
    fixed = 0       # the fixer rounds this run has spent on these commands here
    while True:
        sha = git(lp.wt, "rev-parse", "HEAD")
        cmds = [*lp.every, *lp.once]
        lp.log(f"--- merge: final check: {len(cmds)} commands "
               f"({len(lp.once)} once) on {sha[:12]}")
        identity = commit_identity(lp.wt)
        clean = git_out(lp.wt, "diff", "--quiet", "HEAD")[0] == 0
        ok, text = run_done_when(cmds, lp.wt, lp.run_dir / "final-check.log", lp.artifacts,
                                 lp.done_when_limit, lp.log, silence=lp.turn_limit,
                                 run_dir=lp.run_dir)
        if (not clean or commit_identity(lp.wt) != identity
                or git_out(lp.wt, "diff", "--quiet", "HEAD")[0] != 0):
            ok = False
            text += ("\n\nCheckout changed during the final check; "
                     "these commands do not verify the pinned commit.")
        text = (f"Commit: {identity['head_sha']}\nTree: {identity['tree_sha']}\n\n" + text)
        (lp.run_dir / "final-check.log").write_text(text)
        # the once-commands keep a history of their own: an ordinary round passing says
        # nothing about them, and a fixer round that leaves them failing exactly as they
        # were is the same task defect any other gate's would be.  Judged only once a fixer
        # has actually had a turn at them here: a resume walks back in on the signature its
        # last attempt left, and nothing has been asked to fix anything since.
        try:
            same_failure(lp, ok, text, gate="once", compare=fixed > 0)
        except Blocked as exc:
            # the hand-back names what kept failing, not only that something did
            raise Blocked(f"{exc}; the final check still fails on {first_failure(text)}",
                          exc.section) from None
        if ok:
            lp.log("final check: all passed")
            lp.state["final_check"] = {"outcome": "passed", "sha": sha}
            save_state(lp.run_dir, lp.state)
            return True
        failing = first_failure(text)
        lp.log("final check: FAILED")
        lp.state["final_check"] = {"outcome": "failed", "sha": sha, "line": failing}
        save_state(lp.run_dir, lp.state)
        if fixed >= CONFLICT_ROUNDS:
            return park_waiting(
                lp, f"the final check still fails after {CONFLICT_ROUNDS} fixer rounds: "
                    f"{failing}", upstream,
                git(lp.wt, "rev-parse", f"{upstream}^{{commit}}", check=False) or None)
        fixed += 1
        lp.log(f"--- merge: final check round {fixed}/{CONFLICT_ROUNDS}: "
               f"fixer {lp.executor} (final check)")
        fix = (f"{lp.context}\n\n## The final check failed. Fix the root cause.\n```\n"
               f"{text[-OUT_CAP:]}\n```")
        # as after a conflict, and before the turn: whatever cuts this round off -- the
        # fixer's turn, the check or the review after it -- resumes as this round's review,
        # never as a task round, and never as a run with its budget spent and nothing pending
        lp.state["review_pending"] = {"round": lp.rnd, "summary": "",
                                      "reason": "Re-review after the final check.",
                                      "record": False}
        lp.save()
        summary = execute(lp, "fixer", fix, "final-fixer")
        lp.state["review_pending"]["summary"] = summary
        lp.save()
        ok, dw_log = verify_work(lp)
        lp.log(f"done-when after the final check: {'all passed' if ok else 'FAILED'}")
        # This gate is not the one a fixer was asked to fix, and it has nothing to compare
        # against: the last per-round gate passed, which is how the run reached the merge at
        # all.  Recording it would only overwrite the rounds' own history with a merge
        # pipeline's answer.  What this fixer was asked about is judged where it belongs, by
        # the once-gate at the top of the next pass -- and the reviewer reads the rest.
        if (review(lp, summary, ok, dw_log, "Re-review after the final check.",
                   record=False) != "PASS"
                and not fix_after_failed_review(lp, upstream, "final check")):
            # the budget is spent on reviews that failed the work: a review FAIL like the
            # rounds' own, with its findings -- a wait would only end in the same one
            return note(lp, "done-when or review after the final check did not pass")
        if not integrate(lp, upstream):
            return False


def land(lp, upstream, verify, deliver):
    """Verify without the merge turn, then hold it only for the minutes landing takes.

    `verify` brings the branch onto a target commit and checks it there: the rebase, the
    done-when and final check re-runs, and every conflict fixer, final-check fixer and
    re-review they need.  On a loaded host that is an hour, and with fixer rounds a night,
    and a turn held through it lands nothing for the runs queued behind.  So the turn covers
    a fetch and `deliver` -- the push, the PR, its required checks and the merge.  A target
    still on the commit the branch was verified on lands.  One moved only by commits that
    touch none of this branch's files is rebased onto under the turn and lands on the
    verified checks.  Any other move gives the turn to the next run while this one verifies
    again, and a third such lap parks the run `waiting`, as a target moving under three
    integrations does.  A branch cut from a dependency's passed branch first waits for that
    dependency to merge (`wait_for_dependency`).
    """
    if not wait_for_dependency(lp):
        return False
    for lap in (1, 2, 3):
        if not verify():
            return False
        verified = lp.base_sha
        with merge_turn(lp, upstream):
            rc, out = git_out(lp.wt, "fetch", "origin", "--prune")
            if rc != 0:
                return note(lp, f"git fetch origin failed: {out[-400:]}", failed=True)
            tip = git(lp.wt, "rev-parse", "--verify", "--quiet", f"{upstream}^{{commit}}",
                      check=False)
            if not tip:
                return note(lp, f"{upstream} does not exist on origin; nothing to merge into",
                            failed=True)
            if tip == verified or disjoint_move(lp, upstream, verified, tip):
                return deliver()
        if lap < 3:
            lp.log(f"--- merge: {upstream} moved to {tip[:12]}, touching this branch's files; "
                   "verifying again outside the merge turn")
    # parked on the tip the last lap verified, which origin is already past, so the tick's
    # next pass retries it
    return park_waiting(lp, f"{upstream} moved three times while this run verified",
                        upstream, verified)


def disjoint_move(lp, upstream, verified, tip):
    """Bring the branch from `verified` onto `tip` under the turn, when no check can tell.

    True when `tip` only adds commits to `verified` and they touch none of the files this
    branch changes: the branch is rebased onto it (merged, where `how_to_integrate` says so)
    and the review of the verified commit is carried onto the new one, as a clean
    integration keeps its review.  False, the branch back where it was, for anything else.
    """
    if git_out(lp.wt, "merge-base", "--is-ancestor", verified, tip)[0] != 0:
        return False
    ours = git(lp.wt, "diff", "--no-renames", "--name-only", verified, "HEAD").splitlines()
    theirs = git(lp.wt, "diff", "--no-renames", "--name-only", verified, tip).splitlines()
    if set(ours) & set(theirs):
        return False
    how = how_to_integrate(lp)
    old_head = git(lp.wt, "rev-parse", "HEAD")
    kept = {"review": lp.state["review"], "verdict": lp.state["verdict"]}
    # as in `integrate`: the PASS is withdrawn before git rewrites HEAD, so an interruption
    # cannot leave one saved on a commit nothing checked
    pending_review(lp, f"Re-review after the {how} of {upstream}.")
    try:
        rc, _ = git_out(lp.wt, *(("merge", "--no-edit", tip) if how == "merge"
                                 else ("rebase", tip)))
    except Stopped:
        abort_stopped_integration(lp, how)
        raise
    if rc == 0:
        set_base(lp, tip)
        kept["review"] = {**kept["review"], **commit_identity(lp.wt),
                          "rebased_from": old_head, "patch_id": patch_id(lp.wt, tip)}
        moved = git(lp.wt, "rev-list", "--count", f"{verified}..{tip}")
        lp.log(f"--- merge: {upstream} moved {moved} commits, none touching this branch's "
               "files; landing on the verified checks")
    else:
        git_out(lp.wt, how, "--abort")
    lp.state.update(kept)
    lp.state.pop("review_pending", None)
    lp.save()
    return rc == 0


@contextmanager
def merge_turn(lp, upstream):
    """This host's one run at a time landing on `upstream`, from its last fetch to the merge.

    Passed runs of one repository that land together undo each other: each pushes a branch
    verified on a target the other's merge has just moved.  So the runs of one origin and
    target branch take turns, and `land` keeps everything long outside them.  The turn is a
    flock, which the kernel lets go of when its holder dies, so a run killed mid-merge never
    blocks the next.  A run waiting for it says so on its record, and host admission does
    not count it as a running worker meanwhile.
    """
    url = git(lp.wt, "remote", "get-url", "origin", check=False) or str(lp.state.get("repo"))
    config.RUNS.mkdir(parents=True, exist_ok=True)
    with merge_turn_lock(url, upstream).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            what = f"{Path(lp.state.get('repo') or lp.wt).name} {upstream.removeprefix('origin/')}"
            lp.state["merge_turn"] = {"pid": os.getpid(), "of": what}
            save_state(lp.run_dir, lp.state)
            lp.log(f"--- merge: waiting for the merge turn of {what}; another run is landing on it")
            step = history.close_step(lp.state.get("run_id"), log=lp.log)   # a wait, not work
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
            finally:
                lp.state.pop("merge_turn", None)
                save_state(lp.run_dir, lp.state)
            history.open_step(lp.state.get("run_id"), step, log=lp.log)
            lp.log(f"--- merge: took the merge turn of {what}")
        yield


def merge_turn_lock(url, upstream):
    """The lock file of one repository's merge turn at `upstream`, however a clone spells it.

    `git@github.com:acme/widget.git`, `ssh://git@github.com:22/acme/widget` and
    `https://github.com/Acme/widget` are one repository and so one turn: the host and the
    path are what is kept, without a user, a port, a trailing `.git`, or the case GitHub
    ignores.  A local path is itself.  The name is a digest of all of it and the branch, so
    no two repositories share a turn by spelling alike.
    """
    scp = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(?!//)(.+)", url)
    parts = urlsplit(url)
    host, path = (scp[1], scp[2]) if scp else (parts.hostname, parts.path)
    if host:
        url = f"{host}/{path.strip('/').removesuffix('.git')}".lower()
    digest = hashlib.sha256(f"{url}\n{upstream}".encode()).hexdigest()
    return config.RUNS / f".merge-{digest}.lock"


def merge_turn_note(state):
    """`waiting for the merge turn of <repo> <branch>` while a run waits in `merge_turn`, else "".

    The mark names the process that waits, so one a kill left on the record, or a resume
    carried forward to a new process, says nothing.
    """
    turn = state.get("merge_turn")
    if (state.get("state") != "running" or not isinstance(turn, dict)
            or turn.get("pid") != state.get("pid")):
        return ""
    return f"waiting for the merge turn of {turn.get('of')}"


def merge(lp):
    """A passed run finishes the job: integrate, final check, push, PR, checks, merge.

    Never a model's call.

    Everything here is about `target` -- the branch the PR merges into -- and not about `base`,
    which is only where the run's branch was cut from.  They are the same branch unless the
    task said otherwise.
    """
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

    def deliver():
        require_review_pass(lp)
        lp.step("merge")        # integration may have spent rounds of its own on the way here
        upstream_repo, permission = rights(lp)
        if upstream_repo and permission not in PUSH_RIGHTS:
            return fork_and_pr(lp, target_branch, upstream_repo, permission)
        if not push(lp):
            return False
        url = open_pr(lp, target_branch)
        if not url or not wait_checks(lp, url):
            return False
        return do_merge(lp, url, upstream)
    return land(lp, upstream, lambda: integrate(lp, upstream) and final_check(lp, upstream),
                deliver)


def loop(cfg, run_dir, task_path, opts, log, prior=None):
    receipt = read_state(run_dir) or {}
    # a --bg parent's pick, consumed here: one launch, one pick, whichever process prints it
    preset_exec = receipt.pop("launch_executor", None)
    preset_rev = receipt.pop("launch_reviewer", None)
    session_at_launch = launch_session(run_dir)
    meta, body, title = parse_task(task_path)
    ignore_time_keys(run_dir, meta, log)
    cmds = done_when(body, task_path)
    sized_words, sized_points, sized_checks = task_size(body, cmds)
    if disk_pressure():
        gc(log)     # before this run adds a worktree of its own
    if prior:
        state = stamp_origin(prior)
        state.update(state="running", **process_owner(), finished_at=None, error=None,
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
        save_state(run_dir, stamp_origin({**receipt, "run_id": run_dir.name, "title": title, "task": str(task_path),
                             "launched_session": session_at_launch, "state": "running",
                             "verdict": None, **process_owner(), "started_at": time.time(),
                             "reported": False, "task_words": sized_words,
                             "task_points": sized_points, "task_checks": sized_checks}))
        history_start(read_state(run_dir) or receipt, log)
        repo = task_repo(meta, task_path)
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
            base = meta.get("base") or default_base(repo, log)
            # where the PR goes: a run cut from `dev` can still be meant for `main`
            target = meta.get("target") or base
            # a branch name moves with the executor's commits, so pin the diff to the commit it names
            base_sha = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
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
                # checkout starts where that branch left off, the PR still targets
                # `target`, and the reviewer still reads the full diff against `base`.
                if not git(repo, "rev-parse", "--verify", "--quiet",
                           f"refs/heads/{from_branch}", check=False):
                    raise config.Error(f"{task_path}: from: {from_branch!r} "
                                       "is not a local branch")
                wt, branch = make_worktree(repo, run_dir.name, slugify(title), from_branch)
            else:
                if receipt.get("from_pass"):
                    # a dependency's passed branch that has not merged yet: the run stands on
                    # its reviewed tip, so its own diff, and later its rebase, start there
                    base_sha = receipt["from_pass"]["tip"]
                wt, branch = make_worktree(repo, run_dir.name, slugify(title), base_sha)
        # run.json names the worktree before anything else can fail: a step that ends the run here
        # -- exclude_junk does -- would otherwise leave a worktree `ak run clean` cannot find
        state = stamp_origin({**receipt, "run_id": run_dir.name, "title": title, "task": str(task_path),
                 "launched_session": session_at_launch,
                 "repo": str(repo) if repo else None, "scratch": scratch,
                 "base": base, "target": target, "base_sha": base_sha, "branch": branch,
                 "worktree": str(wt), "stalls": [],
                 "executor": None, "reviewer": None, "rounds": n_rounds, "state": "running",
                 "verdict": None, **process_owner(), "started_at": time.time(),
                 "finished_at": None, "round_summaries": [], "findings": "",
                 "merge_method": method, "no_merge": bool(opts["--no-merge"]) or scratch,
                 "pr": None, "merged": False, "merge_note": None, "reported": False,
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
            elif state.get("from_pass"):
                log(f"worktree {wt} on {branch} from {state['from_pass']['task']}'s passed "
                    f"branch ({base_sha[:12]}), landing on {target} after it merges")
            else:
                log(f"worktree {wt} on {branch} from {base} ({base_sha[:12]})"
                    + (f", merging into {target}" if target != base else ""))
        history_start(state, log)
    invalidate_saved_pass(state, cfg, log)
    try:
        save_state(run_dir, state)
    except StopRequested:
        # A stop landed after a fresh checkout was cut but before its paths reached
        # the record: the stop removed nothing for lack of paths, so the checkout
        # goes here instead of orphaning a worktree and branch nobody names.  A
        # resumed run's paths were recorded long ago -- the stop removes those itself.
        if prior is None and not state.get("scratch") and not opts["--no-worktree"]:
            drop_unrecorded_checkout(repo, wt, branch, log)
        raise
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
    if opts["--exec"] and opts["--review"]:
        review_providers(cfg, opts["--exec"], opts["--review"])
    providers = collect_usage(cfg)
    workers = run_workers(cfg, state)
    order = ready_order(cfg, providers, workers, role="reviewer", repo=repo)
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
                        else set(), reviewer, log, workers=workers)
                except (Exhausted, config.Error):
                    # nowhere to hand the saved turn to: keep the saved pair and let the
                    # round itself surface the quota, exactly as a fresh launch would.
                    picked = None
                if picked is None:
                    handed = None
                    executor, reviewer = pick_models(cfg, providers, executor, reviewer,
                                                     log, resuming=True, repo=repo,
                                                     workers=workers)
                else:
                    handed = executor
                    executor, reviewer = picked
                    note_handover(state, handed, "ran dry" if spent else gone,
                                  started_round(run_dir, state), to=executor, reason="dry")
                    log(f"handing executor to {executor}: {handed} "
                        + ("ran dry, no reset left" if spent else gone))
            else:
                executor, reviewer = pick_models(cfg, providers, executor, reviewer, log,
                                                 resuming=True, repo=repo, workers=workers)
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
                                         resuming=True, repo=repo, workers=workers)
    else:
        try:
            executor, reviewer = pick_models(cfg, providers, opts["--exec"], opts["--review"],
                                             log, repo=repo, workers=workers)
        except QuotaDry:
            refusal = pair_refusal(cfg, providers, workers, opts["--exec"], opts["--review"])
            if refusal:
                raise config.Error(refusal) from None
            raise
    # who takes over when the reviewer dies on its provider rather than on the diff
    spares = [n for n in order if n != reviewer]
    log(f"executor={executor} reviewer={reviewer} rounds={state['rounds']}")
    state["executor"], state["reviewer"] = executor, reviewer
    save_state(run_dir, state)
    if prior is None and session_at_launch and not preset_exec:
        # A launch from a seat says where to look: this run counts on the seat's own
        # bar and in the menu from here, and the seat is told when it ends.  A plain
        # print, not the timestamped log: this one line is the launch announcement.
        # A --bg child stays silent -- its stdout is the log, and the parent, which
        # picked first, already printed it on the terminal.
        print(launch_line(run_dir.name, title, executor, reviewer))

    if state.get("scratch"):
        where = (f"Workspace: {wt}\nThere is no git repository here: nothing to commit, no branch "
                 "and no PR. What you leave in the workspace is the deliverable.")
    else:
        target = state.get("target") or state["base"]
        where = (f"Repo checkout: {wt}\nBranch: {state['branch']} (based on {state['base']}"
                 + (f", to be merged into {target}" if target != state["base"] else "") + ")")
    if not state.get("scratch"):
        cmds = with_suite(cmds, wt, target)
    every, once = group_commands(cmds)
    body += project_lessons(repo, state, log)
    save_state(run_dir, state)
    context = (f"{where}\n\n{body}\n\n"
               f"{shell_foreground_note()}\n\n"
               f"Done-when commands, all must exit 0 (run them in {wt}):\n"
               + "\n".join(f"  $ {c}" for c in every))
    if once:
        context += ("\nOnce, on your final commit before you hand over "
                    "(the loop runs these once more before the merge):\n"
                    + "\n".join(f"  $ {c}" for c in once))
    if handed:
        # a handover on resume is the same handover as one mid-round, and the model taking over
        # is owed the same note: the round it is joining was already started by another
        context = f"{HANDOVER.format(before=handed)}\n\n{context}"
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, context, spares)
    try:
        rounds(lp)
        if review_pass(state, cfg) and not state.get("no_merge"):
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
    except Dead as exc:
        log(f"ERROR {exc}")
        state.update({"state": "error", "verdict": "ERROR", "error": str(exc),
                      "finished_at": time.time()})
        park_error(run_dir, state)
        save_state(run_dir, state)
        write_result(run_dir, state, cmds, log, cfg)
        settle_run(state, run_dir, log)
        return state
    except Blocked as exc:
        # The task cannot be done as written: a final state of its own, because there is no
        # verdict on work here and nothing a resume could spend.  The orchestrator that wrote
        # the task hears why and writes a new one.
        log(f"BLOCKED {exc}")
        state.update({"state": "blocked", "verdict": "BLOCKED", "error": str(exc),
                      "blocked": exc.section, "finished_at": time.time()})
        state.pop("quota_dry", None)
        save_state(run_dir, state)
        write_result(run_dir, state, cmds, log, cfg)
        settle_run(state, run_dir, log)
        return state

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
    state["finished_at"] = time.time()
    save_state(run_dir, state)
    write_result(run_dir, state, cmds, log, cfg)
    settle_run(state, run_dir, log)
    return state


def _write_state(run_dir, state):
    """The bare record write every save ends in; the guard and the lock live in `save_state`."""
    record_limits(state)
    path = run_dir / "run.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def save_state(run_dir, state):
    """Write the record, unless a stop landed first -- the check and the write are atomic.

    The guard reads under `recovery_lock`, the same lock a stop marks under, so a
    writer that read `running` can never replace the `stopped` receipt afterward: it
    either lands first and the stop re-reads it, or it raises `StopRequested` and the
    deliberate end stands.  `mark_delivery` alone writes past this, through
    `_write_state`: it holds `delivery_lock`, marks endings a stop always refuses, and
    taking this lock there would invert `reap`'s lock order into a deadlock.

    A first write skips the lock: a stop refuses a run with no receipt, so none can
    be racing it -- and no lock file is left behind for a record written once.
    """
    if not (run_dir / "run.json").exists():
        return _write_state(run_dir, state)
    with recovery_lock(run_dir):
        if state.get("state") != "stopped":
            try:
                existing = json.loads((run_dir / "run.json").read_text())
            except (OSError, ValueError):
                existing = None
            if isinstance(existing, dict) and existing.get("state") == "stopped":
                raise StopRequested(f"{run_dir.name} was stopped")
        _write_state(run_dir, state)


def stop_check(run_dir):
    """Raise `StopRequested` if the run was stopped: every spawn boundary asks first.

    Read under `recovery_lock`, the lock a stop marks under, so the read itself
    cannot straddle the commit: a checker queued behind the stop sees the stopped
    record and never starts work the sweep already passed.  A missing run, or a
    receipt that cannot be read, is not a stop -- direct unit-test callers and a
    record removed underfoot carry on as before.
    """
    if run_dir is None:
        return
    try:
        with recovery_lock(run_dir):
            try:
                stopped = (json.loads((Path(run_dir) / "run.json").read_text())
                           .get("state") == "stopped")
            except (OSError, ValueError):
                return
    except OSError:
        return
    if stopped:
        raise StopRequested(f"{Path(run_dir).name} was stopped")


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


def history_finish(state, log=None):
    """Publish a terminal receipt and close the step this process was running, if any."""
    now = state.get("finished_at") or time.time()
    history.close_step(state.get("run_id"), now, log=log)
    files = changed_files(state)
    history.finish_run(state.get("run_id"), repo=state.get("repo"),
                       executor=state.get("executor"), reviewer=state.get("reviewer"),
                       rounds_used=len(state.get("round_summaries") or []),
                       final_state=state.get("state"), verdict=state.get("verdict"),
                       started_at=state.get("started_at"), finished_at=now,
                       session=launched_session(state), peak_rss_mb=state.get("peak_rss_mb"),
                       task_files=json.dumps(files) if files is not None else None,
                       log=log)


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


def mark_state(run_dir, name, error=None, log=None):
    """Record how a run died, so `ak run status` never shows a dead run as running.

    A concurrent stop wins over the mark: the record already says `stopped`, the
    history and the tally already heard it from the stop, and there is nothing left
    to record, so the disk as it stands is returned instead of raising.
    """
    try:
        state = json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        state = {"run_id": run_dir.name, "verdict": None}
    if not state.get("title"):
        # nothing had written the title yet, and the message the user gets has to carry it
        try:
            state["title"] = parse_task(run_dir / "task.md")[2]
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
    if error:
        state["error"] = error
    try:
        save_state(run_dir, state)
    except StopRequested:
        return read_state(run_dir) or state
    history_finish(state, log)
    try:
        refresh_seat_tally(launched_session(state))   # every state change lands on the bar
    except config.Error:
        pass
    return state


def failed_at_budget(state):
    """A FAIL that ran out of rounds rather than out of work, so more rounds carry it on.

    Deliberately not part of `needs_recovery`: nothing was interrupted here, so this is no
    recovery decision for the menu to raise, for the seat to be told about or for `announce`
    to swallow the finished-run notice over.  An explicit `--rounds` above the saved budget,
    and no higher than `TASK_MAX_ROUNDS`, continues it and nothing else does -- see
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
    if failed_at_budget(state) and state["rounds"] < TASK_MAX_ROUNDS:
        # up to the budget and no further: past it the task is split or re-scoped instead
        return f"continue: ak run resume {state['run_id']} --rounds {TASK_MAX_ROUNDS}"
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
    """The run's `final check:` result.md line: what the once-commands came to, if any."""
    record = state.get("final_check") or {}
    if record.get("outcome") in ("passed", "failed") and record.get("sha"):
        return f"final check: {record['outcome']} on {record['sha']}"
    if not group_commands(cmds)[1]:
        return "final check: none (no once-commands)"
    return "final check: not run"


def result_done_when(cmds):
    """Commands as result.md shows them, including when a command runs only at final check."""
    marked = []
    for cmd in cmds:
        bare, once = split_once(cmd)
        if once:
            cmd = bare if bare.endswith("(once, final check)") else f"{bare} (once, final check)"
        marked.append(cmd)
    return marked


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
    parts += ["", "## Done-when", "```", "\n".join(result_done_when(cmds)), "```", ""]
    parts += [final_check_line(state, cmds), ""]
    for entry in state["round_summaries"]:
        parts += [f"## Round {entry['round']} ({entry['verdict']}, done-when "
                  f"{'passed' if entry['done_when'] else 'failed'})", "", entry["summary"], ""]
    if state.get("error"):
        parts += ["## Why this run stopped", "", state["error"], ""]
    if state["verdict"] != "PASS" and state["findings"]:
        parts += ["## Reviewer findings", "", state["findings"], ""]
    onward = continue_line(state, run_dir)
    if onward:
        parts += [onward, ""]
    (run_dir / "result.md").write_text("\n".join(parts))


def run_for_pr(url):
    """(run_dir, state) of the run that opened that PR, or (None, None)."""
    for run_dir in run_dirs():
        state = read_state(run_dir)
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
    save_state(run_dir, state)
    result = run_dir / "result.md"
    try:
        if state.get("worktree") and Path(state["worktree"]).is_dir():
            _, body, _ = parse_task(run_dir / "task.md")
            write_result(run_dir, state, done_when(body, run_dir / "task.md"))
        elif note not in result.read_text():
            # The worktree is gone, so the diff stat cannot be produced again: keep the result
            # as it was written and add what has happened to it since.
            with result.open("a") as fh:
                fh.write(f"\n## The maintainer decided\n\n{note}\n")
    except (config.Error, OSError, KeyError):
        pass          # the note is on the run; a result we cannot rewrite from here is not news
    return state


# --- telling the user, when nobody else will --------------------------------


def run_workers(cfg, state):
    """The workers list this run is bound to: its session's selection at launch.

    Every role of the run -- executor, reviewer, every handover and every fixer -- is picked
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
        meta = parse_task(config.RUNS / state["run_id"] / "task.md")[0]
    except (KeyError, TypeError, OSError, ValueError, config.Error):
        return task_project(state.get("repo"), state.get("task_file"))
    named = meta.get("repo") or ""
    named = Path(named).expanduser() if named.lower() not in ("", "none") else None
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

    Nobody chooses a session's project: the runs it launched vote, each for its
    `run_project` from the moment it is queued, and a run that belongs to no checkout has no
    vote (`session_vote`).  Returns the project the session has after the count.

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
        if runs is None or not repo:
            repo = session_vote(session, (read_state(directory) or {} for directory in run_dirs())
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


def refresh_seat_tally(session):
    """Put that seat's run tally on its own status bar, in the menu's words.

    The bar counts what the seat's menu row counts -- runs still queued or running,
    then endings nobody has acknowledged, both through `menu.bar_tally` over the
    same records, so the two never disagree.  Merges and empty seats the row shows
    another way, so the bar shows them no way at all.  Only the seat that launched
    the run is ever written.  Best-effort: the run's state on disk is what matters,
    never the bar.
    """
    if not session:
        return
    try:
        from . import menu  # here, not at the top: the menu draws without the loop
        records = list(menu.run_records())
        tallies = seat_tallies(state for _, state in records)
        queued = [state for _, state in records
                  if state.get("state") == "queued" and launched_session(state) == session]
        orch.set_runs(session, menu.bar_tally(
            tallies.get(session), queued, menu.seat_estimate(session)))
    except (config.Error, OSError, ValueError):
        pass


def seat_tallies(records, now=None):
    """What the runs each seat launched add up to: {seat: (running, needing him, merged)}.

    `running` is the runs still going of their own accord -- `going`, the same test the
    seat row's own reason counts, so `1 running` on the row and `1 running` in this tally can
    never disagree about a run parked on a window; the second figure is the endings still his
    -- menu.v5o_needs_look, again the test the row's reason reads; `merged` the merges of the
    last GC_AGE.  From records already
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
            if isinstance(finished, (int, float)) and now - GC_AGE <= finished <= now:
                counts[2] += 1
    return {seat: tuple(counts) for seat, counts in found.items()}


def verdict_word(state, cfg=None):
    """PASS, FAIL or ERROR: the three words a notice is allowed to carry.

    A run that stopped on an error says so; everything else is the delivery outcome, so an
    exhausted or interrupted run reads FAIL, exactly as `delivery` already calls it.
    """
    if state.get("state") == "error":
        return "ERROR"
    return "PASS" if delivery(state, report_config(cfg)).startswith("PASS") else "FAIL"


def whereabouts(state, short=False):
    """Where the work ended up: delivered, merged, the PR it is still waiting in, or neither.

    `short` names an open PR by its number instead of its URL.  A URL is never cut -- half a
    link is not a link, and the number is the one thing that still finds the PR by hand -- so
    this is what goes on the line when the whole URL will not fit on it.  A run with no
    repository is `delivered`: there was never a branch for `not merged` to be about.
    """
    if state.get("scratch"):
        return "delivered"
    if state.get("merged"):
        return "merged"
    pr = state.get("pr")
    if not pr:
        return "not merged"
    return f"PR #{pr.rstrip('/').rsplit('/', 1)[-1]}" if short else f"PR {pr}"


def notice_title(state):
    """The run's title for the notice, with every path token dropped.

    A word carrying `/` or `~` is a path, and a path on this line is the worst of both: long
    enough to push the rest off it, and useless on the phone that reads it.  result.md has the
    paths, and `ak run status` names result.md.
    """
    words = (state.get("title") or state.get("run_id") or "agentkit run").split()
    return " ".join(word for word in words if "/" not in word and "~" not in word)


def fit(title, tail, room):
    """`<title> — <tail>` inside `room` characters, or None when the tail alone will not fit.

    Only the title gives way: first shortened, then dropped altogether.
    """
    if len(tail) > room:
        return None
    left = room - len(tail) - 3            # the ` — ` that joins the title to the rest
    if len(title) > left:
        title = title[:left - 3] + "..." if left >= 4 else ""
    return f"{title} — {tail}" if title else tail


def summary_line(state, cfg=None):
    """What happened, in one line of at most NOTICE characters, for a human.

    Written for a phone, not for a log reader: what it was, whether it passed, where it went,
    and nothing else. The seat that opens after an unattended run prints this line with one
    space in front of it, and that space is part of the NOTICE budget. It carries no merge
    error and no path -- both are long, and both are in result.md, which `ak run status` names.

    The title is what gives way when the line will not fit, never the PR link: it is shortened,
    then dropped, and only once a bare `PASS — PR <url>` is still too long does the URL give
    up its place to the PR's number.
    """
    if needs_recovery(state):
        return f"{notice_title(state)} — unfinished; r in the menu offers recovery"[:NOTICE - 1]
    room = NOTICE - 1                      # the menu prints this line with one space in front
    title, verdict = notice_title(state), verdict_word(state, cfg)
    for short in (False, True):
        line = fit(title, f"{verdict} — {whereabouts(state, short)}", room)
        if line is not None:
            return line
    return f"{verdict} — {whereabouts(state, True)}"[:room]


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
    """The five words a hand-back line may carry about how a run ended.

    `PASS merged`, `PASS not merged`, `FAIL`, `BLOCKED`, `ERROR` -- the delivery outcome, not
    the review verdict, because what the orchestrator decides next turns on where the work
    went and not on what the reviewer thought of it.
    """
    if state.get("state") == "blocked":
        return "BLOCKED"
    if state.get("state") == "error":
        return "ERROR"
    if not delivery(state, report_config(cfg)).startswith("PASS"):
        return "FAIL"
    return "PASS merged" if state.get("merged") else "PASS not merged"


def handback_reason(state, cfg=None):
    """The one line after the verdict: why it ended that way, in the run's own words."""
    if state.get("state") in ("blocked", "error", "waiting"):
        return " ".join((state.get("error") or "no reason was recorded").split())[:300]
    # A memory-cap death is the whole news: rounds and findings say nothing about a
    # run the kernel stopped before it could finish a turn.
    cap_line = " ".join((state.get("error") or "").split())
    if cap_line.startswith("killed: memory cap"):
        return cap_line[:300]
    if state.get("state") not in ENDED and needs_recovery(state):
        # an interruption, or a stop no window will lift: what stopped it is the whole news,
        # and rounds and findings say nothing about a run that never reached its verdict.  A
        # resumed attempt that did reach one is an ending, `recovery_pending` or not, and says
        # what every other ending says.  Its own full stop goes: the line puts one after it.
        return " ".join(recovery_reason(state).split()).rstrip(".")[:300]
    word = delivery(state, report_config(cfg))
    if word.startswith("PASS, not merged: "):
        return word[len("PASS, not merged: "):]
    if word.startswith("PASS"):
        return state.get("pr") or word[len("PASS, "):]
    # a FAIL hands back what the next step turns on: the rounds it spent and why they did
    # not pass -- the findings themselves, never their count, or the check still failing
    spent = len(state.get("round_summaries") or [])
    if review_failed(state):
        # the whole review, not run.json's tail of it: the first findings are its top
        text = saved_findings(None, state)
        blocking = (findings_section(text).strip()
                    or re.sub(r"^[^\n]*VERDICT:[^\n]*$", "", text, flags=re.M | re.I).strip())
        return (f"after {spent} rounds, open findings: "
                + (" ".join(blocking.split())[:600] or "none listed")).rstrip(".")
    # else a PASS the loop overrode says why it did, and a check still failing names its line
    review = state.get("review") if isinstance(state.get("review"), dict) else {}
    why = "; ".join(filter(None, (review.get("overridden"), failed_check(state))))
    if why:
        return f"after {spent} rounds, {why}".rstrip(".")
    return " ".join((state.get("merge_note") or state.get("error")
                     or "no reason was recorded").split())[:300].rstrip(".")


def review_failed(state):
    """Whether the last review on the record failed the work: its own `VERDICT: FAIL`.

    What tells a FAIL its reviewers gave from one a check left behind.  A final check that
    failed on a missing login, after reviews that all passed, says nothing about the work:
    neither its findings nor splitting the task would help.  Read off the whole review: a
    long one's verdict can be further from its end than run.json keeps.
    """
    verdicts = review_verdicts(saved_findings(None, state))
    return bool(verdicts) and verdicts[-1].upper() == "FAIL"


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
        return ("the final check failed: "
                + (record.get("line") or first("once") or "see final-check.log"))
    if first("every"):
        return f"the done-when failed: {first('every')}"
    return None


def handback_line(state, run_dir, cfg=None):
    """The one line a finished run types into the seat that launched it.

    `run <id> finished <verdict>: <why>. Result: <path>. Decide the next step.` -- an ending
    is the orchestrator's to act on, so it gets the three things a decision needs and nothing
    else: what happened, where the whole of it is written down, and that the next move is its
    own.  The owner is never the fallback for a run that did not work out.  A FAIL whose
    reviews spent the whole round budget says so and says to split: the task was too big, not
    the worker.  A FAIL a check left behind says no such thing: more rounds of the same task
    would not have passed it either.  A scratch run names its workspace too: the files
    there are what it delivered.  A run whose lessons file was past its cap says so: the
    orchestrator keeps that file, and only it can tighten it.
    """
    workspace = (f" Workspace: {state['worktree']}."
                 if state.get("scratch") and state.get("worktree") else "")
    repo = state.get("repo")
    lessons = (f" {config.HOME / 'lessons' / Path(repo).name}.md is past its 4 KB cap and "
               "reached the workers cut short: tighten it."
               if state.get("lessons_truncated") and repo else "")
    line = (f"run {run_dir.name} finished {handback_verdict(state, cfg)}: "
            f"{handback_reason(state, cfg)}. Result: {run_dir / 'result.md'}.{workspace}{lessons} "
            "Decide the next step.")
    spent = len(state.get("round_summaries") or [])
    if (state.get("state") == "fail" and (state.get("rounds") or 0) > 0
            and spent >= (state.get("rounds") or 0) and review_failed(state)):
        word = NUMBER_WORDS[spent] if 0 <= spent < len(NUMBER_WORDS) else str(spent)
        line += f" {word} rounds spent: split or re-scope"
    return line


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
    return (state.get("state") in ENDED and not already_handed_back(state)
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
    ending twice.  Its own file, never `recovery.lock`: `reap` already holds that one while it
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
        current = read_state(run_dir)
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
        _write_state(run_dir, current)
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
    line = handback_line(state, run_dir, cfg)
    with delivery_lock(run_dir):
        said = read_state(run_dir) or state
        if not same_attempt(state, said):
            # the run was resumed since this ending: nobody is waiting on it any more, and
            # the attempt running now will hand back an ending of its own
            log(f"run {run_dir.name} has moved on since this ending; nothing to hand back")
            return False
        if already_handed_back(said):
            state["handed_back"] = said["handed_back"]
            log(f"run {run_dir.name} was already handed back to the {session} seat")
            return True
        if (said.get("state") in ENDED and not said.get("handback_pending")
                and not said.get("notification_pending") and watch.is_preexisting(said)):
            mark_delivery(run_dir, state, handed_back=time.time(),
                          handback_note=watch.PREEXISTING_NOTE, handback_pending=None,
                          handback_wait_reason=None, notification_pending=None)
            log(f"run {run_dir.name} is a {watch.PREEXISTING_NOTE}")
            # The seat is not going to read the tree: the ending is history.
            _drop_told(read_state(run_dir) or state, log, run_dir)
            return True
        if watch.type_at_prompt(seat, line, log, cfg=cfg, typed=said.get("handback_typed"),
                                receipt=lambda mark: mark_delivery(run_dir, state,
                                                                   handback_typed=mark)):
            mark_delivery(run_dir, state, handed_back=time.time(), reported=True,
                          handback_pending=None, handback_typed=None, handback_note=None,
                          handback_wait_reason=None, notification_pending=None)
            log(f"handed run {run_dir.name} back to the {session} seat")
            # The seat was told. It reads result.md, not the checkout.
            _drop_told(read_state(run_dir) or state, log, run_dir)
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
    it was started from and in `ak run status`.  Only an orphan speaks to the owner, and first
    to its own seat: the seat is reopened on its saved conversation and told to continue, and
    the owner hears only when that fails -- or when there is no seat to reopen, one `ak orch
    stop` ended or one nothing is left of, which is asked of them as before.

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
    if needs_recovery(state) and state.get("state") not in ENDED:
        # Inside a job the scheduler owns recovery: a run the job is adopting right now is
        # resumed by the job itself seconds later, and a recovery notice would be per-task
        # noise contradicting what happens next.
        if getattr(_JOB_MUTE, "adopt", None):
            return
        reap(run_dir, state)
        return
    if state.get("state") not in ENDED:
        return
    if not session:
        return
    with launcher_world(session) as live:
        if live:
            hand_back(state, run_dir, log, cfg)
            return
    if getattr(_JOB_MUTE, "depth", 0) or job_started(state):
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
        current = read_state(run_dir) or state
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
            current = read_state(run_dir) or state
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
    verdict = "PASS" if delivery(state, report_config(cfg)).startswith("PASS") else "FAIL"
    why = ""
    # A pre-existing ending with a stuck card keeps its retry below, but never wakes its seat.
    if (not watch.seat_closed(session) and watch.orphan_fresh(state, session)
            and not watch.is_preexisting(state)):
        log(f"the orchestrator session {session} this run was launched from is gone; "
            "reopening it")
        why = watch.revive(session, f"continue {task}: run {run_dir.name} finished {verdict}, "
                                    f"result at {run_dir / 'result.md'}", log)
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


# --- status, gc, clean, resume ----------------------------------------------


def run_dirs():
    return sorted(d for d in config.RUNS.iterdir() if d.is_dir()) if config.RUNS.exists() else []


def alive(pid):
    """Process existence only; run ownership also requires process_active's identity check."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_identity(pid):
    """Linux process birth, including the boot so a reboot cannot recycle an identity."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        ticks = int(fields[19])
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        btime = next(line.split()[1] for line in Path("/proc/stat").read_text().splitlines()
                     if line.startswith("btime "))
        return {"boot": boot, "ticks": ticks,
                "started_at": int(btime) + ticks / os.sysconf("SC_CLK_TCK")}
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def process_owner(pid=None):
    pid = os.getpid() if pid is None else pid
    return {"pid": pid, "process_identity": process_identity(pid)}


def process_active(state):
    pid = state.get("pid")
    if not alive(pid):
        return False
    current = process_identity(pid)
    if current is None:
        # A zombie still answers kill(0). An unreadable /proc, however, is not proof of death.
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
        except (OSError, IndexError):
            return True
    saved = state.get("process_identity")
    if saved:
        return all(saved.get(key) == current[key] for key in ("boot", "ticks"))
    # Old records lack the fingerprint: check birth time and the actual run command. A
    # recycled PID starts after the old receipt, or belongs to a different kind of process.
    if state.get("started_at") and current["started_at"] > state["started_at"] + 1:
        return False
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
    except OSError:
        return True
    return any(Path(arg).name == "ak" and args[i + 1:i + 2] == ["run"]
               for i, arg in enumerate(args))


@contextmanager
def recovery_lock(run_dir):
    """Serialize reaping, acknowledgment and launch handoff; never hold across model work.

    Reentrant within a thread, and counted here because flock is not: `save_state`
    takes it for every write it makes, and `reap`, `cmd_stop` and the launch handoff
    hold it across the read-decide-write the save is the end of.
    """
    held = getattr(_RECOVERY_HELD, "paths", None)
    if held is None:
        held = _RECOVERY_HELD.paths = set()
    mine = str(run_dir)
    if mine in held:
        yield
        return
    held.add(mine)
    try:
        with (Path(run_dir) / "recovery.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    finally:
        held.discard(mine)


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
        env["AGENTKIT_RUN"] = state["run_id"]
    return env


@contextmanager
def slot_lock():
    """One atomic count-and-claim across seats, processes and job threads."""
    config.RUNS.mkdir(parents=True, exist_ok=True)
    with (config.RUNS / ".slots.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def slot_order(state):
    return (not state.get("first"),
            state.get("queued_at") or state.get("started_at") or 0,
            state.get("run_id") or "")


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read_number(path, *, bytes_to_mb=False):
    try:
        value = path.read_text().strip()
    except OSError:
        return None
    if value == "max":
        return None
    try:
        value = float(value)
    except ValueError:
        return None
    return value / (1024 * 1024) if bytes_to_mb else value


def _reclaimable_mb(path):
    """Reclaimable file cache in MB from a cgroup's memory.stat, or None.

    The kernel takes file cache back freely under pressure, so it is not use;
    only what remains can stop a run. Older kernels name the counter
    inactive_file where newer ones say file.
    """
    try:
        text = path.read_text()
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(" ")
        if key in ("file", "inactive_file"):
            try:
                values[key] = float(rest.split()[0])
            except (ValueError, IndexError):
                continue
    if "file" in values:
        return values["file"] / (1024 * 1024)
    if "inactive_file" in values:
        return values["inactive_file"] / (1024 * 1024)
    return None


def _unit_memory_limits(cgroup_file=None, cgroup_root=None):
    """The nearest ancestor with a finite memory.high, as one (used, high, raw, name).

    Walking up from this run's own scope stops at the first limit -- the slice
    holding the run, not the user unit above it -- and the used figure excludes
    reclaimable file cache. An empty list means no limit or no answer, and the
    gate fails open.
    """
    if cgroup_file is None:
        cgroup_file = os.environ.get("AK_CGROUP_FILE", "/proc/self/cgroup")
    if cgroup_root is None:
        cgroup_root = os.environ.get("AK_CGROUP_ROOT", "/sys/fs/cgroup")
    try:
        relative = next(line.split("::", 1)[1] for line in
                        Path(cgroup_file).read_text().splitlines()
                        if "::" in line)
    except (OSError, StopIteration, IndexError):
        return []
    root, current = Path(cgroup_root), Path(cgroup_root) / relative.lstrip("/")
    while current == root or root in current.parents:
        high = _read_number(current / "memory.high", bytes_to_mb=True)
        if high is not None:
            raw = _read_number(current / "memory.current", bytes_to_mb=True)
            if raw is None:
                return []
            cache = _reclaimable_mb(current / "memory.stat")
            if cache is None:
                return []
            return [(max(0.0, raw - cache), high, raw,
                     current.name if current != root else "/")]
        if current == root:
            break
        current = current.parent
    return []


def host_readings(source=None, cgroup_file=None, cgroup_root=None):
    """Read the host gates once; ``source`` is an offline-test injectable mapping/callable."""
    if source is not None:
        readings = source() if callable(source) else source
        return dict(readings or {})
    injected = os.environ.get("AK_HOST_READINGS")
    if injected:
        try:
            readings = json.loads(injected)
            if isinstance(readings, dict):
                return readings
        except (json.JSONDecodeError, TypeError):
            pass
    meminfo = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, value = line.partition(":")
            fields = value.split()
            if fields:
                meminfo[key] = float(fields[0]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        load = float(Path("/proc/loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        load = None
    limits = _unit_memory_limits(cgroup_file, cgroup_root)
    readings = {"free_mb": meminfo.get("MemAvailable"), "mem_total_mb": meminfo.get("MemTotal"),
                "load": load, "cpus": os.cpu_count() or 1, "unit_limits": limits}
    if limits and isinstance(limits[0], (tuple, list)) and len(limits[0]) >= 4:
        used, high, raw, name = limits[0][:4]
        readings["unit_memory_current_mb"] = used
        readings["unit_memory_high_mb"] = high
        readings["unit_memory_raw_mb"] = raw
        readings["unit_memory_name"] = name
    return readings


def _reading(readings, *names):
    for name in names:
        value = _number(readings.get(name))
        if value is not None:
            return value
    return None


def resource_limits(readings):
    """Resolve configured gates against one host-reading snapshot."""
    total = _reading(readings, "mem_total_mb", "total_mb", "mem_total")
    cpus = _reading(readings, "cpus", "nproc") or 1
    return config.min_free_mb(total if total is not None else 0), config.max_load(cpus)


def _g(value):
    if value is None:
        return "?"
    value = value / 1024
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _load(value):
    return "?" if value is None else f"{value:g}"


def host_status_line():
    """The one host-admission line at the top of human ``ak run status`` output.

    A positive `max_runs` is a gate like the other two, so the line names it: `at most 4
    runs at once`.
    """
    readings = host_readings()
    minimum, maximum = resource_limits(readings)
    cpus = _reading(readings, "cpus", "nproc") or 1
    gates = []
    if minimum:
        gates.append(f"≥ {_g(minimum)} G free")
    if maximum:
        gates.append(f"load ≤ {_load(maximum)}")
    admitted = ("a run is admitted while " + " and ".join(gates) if gates else
                "a run is admitted (host memory and load gates off)")
    try:
        limit = config.max_runs()
    except config.Error:
        limit = 0
    if limit:
        admitted += f" · at most {limit} run{'s' if limit != 1 else ''} at once"
    segment = ""
    unit = _unit_memory(readings)
    if unit and len(unit) > 3 and unit[3]:
        segment = f" · {unit[3]} {_g(unit[0])} of {_g(unit[1])} G in use"
    return (f"host: {int(cpus)} cpus · load {_load(_reading(readings, 'load', 'load1'))} · "
            f"{_g(_reading(readings, 'free_mb', 'mem_available_mb'))} G free{segment} · "
            f"{admitted}")


def free_memory_mb():
    """Compatibility reading retained for callers outside the slot gate."""
    return history.available_memory_mb()


def memory_requirement(repo):
    """Compatibility estimate retained; host readings now decide admission."""
    return history.memory_requirement(repo, MIN_FREE_MB)


def slot_counts(state):
    """Live slot owners, and top-level receipts ahead of this one (including dead waiters).

    A run waiting for its merge turn owns no slot while it waits: it only sits there.
    """
    running, ahead = 0, 0
    for directory in run_dirs():
        other = read_state(directory) or {}
        if other.get("run_id") == state.get("run_id") or other.get("run_depth", 0):
            continue
        if (other.get("state") == "running" and process_active(other)
                and not merge_turn_note(other)):
            running += 1
        elif (other.get("state") == "queued" and other.get("slot_waiting") and
              slot_order(other) < slot_order(state)):
            ahead += 1
    return running, ahead


def slot_note(state):
    running, ahead = slot_counts(state)
    shown = ahead if state.get("first") else running + ahead
    return state.get("slot_wait_reason") or f"waiting for a slot · {shown} ahead"


def _unit_memory(readings):
    """(used, high, raw, name) for the cgroup the gate reads, or None.

    ``used`` excludes reclaimable file cache; ``raw`` is memory.current with
    it, and None where the readings predate it. A list carries the nearest
    limit first, so the first valid entry wins.
    """
    limits = readings.get("unit_limits")
    if isinstance(limits, (tuple, list)):
        for entry in limits:
            if not isinstance(entry, (tuple, list)):
                continue
            if len(entry) == 2:
                used, high = entry
                if (_number(used) is not None and _number(high) is not None
                        and high >= 0):
                    return (used, high, None, None)
            elif len(entry) >= 3:
                used, high, raw = entry[0], entry[1], entry[2]
                name = entry[3] if len(entry) > 3 else None
                if (_number(used) is None or _number(high) is None
                        or high < 0):
                    continue
                raw = _number(raw)
                name = name if isinstance(name, str) and name else None
                return (used, high, raw, name)
    current = _reading(readings, "unit_memory_current_mb", "memory_current_mb")
    high = _reading(readings, "unit_memory_high_mb", "memory_high_mb")
    if current is not None and high is not None and high >= 0:
        raw = _reading(readings, "unit_memory_raw_mb", "unit_memory_with_cache_mb",
                       "memory_raw_mb")
        name = readings.get("unit_memory_name", readings.get("unit_name"))
        name = name if isinstance(name, str) and name else None
        return (current, high, raw, name)
    return None


def _wait_reason(readings, minimum, maximum):
    # An unreadable gate fails open, as the memory check before it did: a host
    # that cannot answer (no /proc on macOS, no cgroup file in a container)
    # must not queue every run forever.
    free = _reading(readings, "free_mb", "mem_available_mb", "mem_available")
    if minimum and free is not None and free < minimum:
        return f"waiting for memory · {_g(free)} G free, needs {_g(minimum)} G", "memory"
    load = _reading(readings, "load", "load1", "load_1m")
    if maximum and load is not None and load > maximum:
        return f"waiting for the host to calm · load {_load(load)}, limit {_load(maximum)}", "load"
    unit = _unit_memory(readings)
    if unit and unit[0] > unit[1] * .75:
        raw = unit[2] if len(unit) > 2 else None
        if raw is not None:
            return (f"waiting for the unit's memory · {_g(unit[0])} of {_g(unit[1])} G "
                    f"in use ({_g(raw)} with cache)", "unit memory")
        return (f"waiting for the unit's memory · {_g(unit[0])} of {_g(unit[1])} G",
                "unit memory")
    return None, None


def claim_slot(state, limit, readings=None):
    """Called under slot_lock: count, FIFO and two steady host polls decide admission."""
    running, ahead = slot_counts(state)
    # AK_MAX_RUNS=0 is the test-suite escape hatch: it disables count and host gates together.
    ungated = os.environ.get("AK_MAX_RUNS") == "0"
    if state.get("run_depth", 0) or ungated:
        state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                     **process_owner())
        state.pop("resume_from", None)
        return True
    is_first = bool(state.get("first"))
    if ahead or (limit and running >= limit and not is_first):
        state["slot_waited"] = True
        shown = ahead if is_first else running + ahead
        state["slot_wait_reason"] = f"waiting for a slot · {shown} ahead"
        state["slot_wait_kind"] = "count"
        state["slot_healthy_polls"] = 0
        return False
    readings = host_readings() if readings is None else readings
    minimum, maximum = resource_limits(readings)
    if is_first:
        maximum = 0
    reason, kind = _wait_reason(readings, minimum, maximum)
    if reason:
        state["slot_waited"] = True
        state["slot_wait_reason"], state["slot_wait_kind"] = reason, kind
        state["slot_healthy_polls"] = 0
        return False
    polls = state.get("slot_healthy_polls", 0) + 1
    if polls < 2:
        state["slot_healthy_polls"] = polls
        # The gates pass but steadiness is still owed: say that, with the
        # readings behind it, rather than the count sentence nothing waits on.
        # The kind stays whatever gate (if any) actually delayed this wait.
        free = _reading(readings, "free_mb", "mem_available_mb", "mem_available")
        load = _reading(readings, "load", "load1", "load_1m")
        state["slot_wait_reason"] = (
            f"waiting for steady readings · {_g(free)} G free, load {_load(load)}")
        return False
    state.update(state="running", slot_waiting=False, slot_started_at=time.time(),
                 **process_owner())
    for key in ("resume_from", "slot_healthy_polls", "reservation_pending",
                "slot_wait_reason", "slot_wait_kind"):
        state.pop(key, None)
    return True


def wait_for_slot(run_dir):
    """Reserve a slot in run.json before work starts; no process-local semaphore can do this."""
    announced = False
    first_poll = True
    wait_kind = None
    while True:
        limit = config.max_runs()
        with slot_lock(), recovery_lock(run_dir):
            state = read_state(run_dir) or {}
            if state.get("state") == "running" and state.get("pid") == os.getpid():
                return state
            if first_poll and state.get("state") != "queued" and not process_active(state):
                # drive also accepts a saved receipt directly (the job/recovery API).
                state.update(run_id=run_dir.name, state="queued", slot_waiting=True,
                             queued_at=time.time(), **process_owner())
                state.setdefault("run_depth", run_depth())
                # A new queue episode starts with no memory of the last one's wait.
                for key in ("slot_waited", "slot_wait_reason", "slot_wait_kind"):
                    state.pop(key, None)
                save_state(run_dir, state)
            if state.get("state") != "queued" or state.get("pid") != os.getpid():
                raise config.Error(f"{run_dir.name}: another process owns this launch")
            first_poll = False
            if claim_slot(state, limit):
                save_state(run_dir, state)
                break
            # Admission clears the kind, so the receipt below reads this copy.
            wait_kind = state.get("slot_wait_kind") or wait_kind
            save_state(run_dir, state)
        if not announced:
            print(slot_note(state), flush=True)
            refresh_seat_tally(state.get("launched_session"))
            announced = True
        time.sleep(SLOT_POLL)
    if state.get("slot_waited"):
        minutes = max(0, int((time.time() - state["queued_at"]) / 60))
        kind = wait_kind or "count"
        line = f"waited {minutes} min for a slot ({kind})\n"
        # Preflight and a detached waiter's stdout already live here. Keep the waiting
        # receipt first, without replacing the inode the background child's stdout owns.
        path = run_dir / "log.txt"
        with path.open("r+", encoding="utf-8") as fh:
            content = fh.read()
            fh.seek(0)
            fh.write(line + content)
        print(line.rstrip(), flush=True)
    refresh_seat_tally(state.get("launched_session"))
    return state


@contextmanager
def run_slot(run_dir, prior=None):
    state = wait_for_slot(run_dir)
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
    A `stopped` run is a deliberate end, never an accident to offer back.
    """
    return (state.get("state") not in ("queued", "running", "pass", "blocked", "stopped") and
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
    if state.get("state") in ENDED or state.get("handed_back"):
        return  # an ending is announce's, and one already said is nobody's to say again
    if getattr(_JOB_MUTE, "adopt", None):
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
    log = logger(run_dir, True)
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
            current = read_state(run_dir) or state
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
        why = watch.revive(owner, line, log)
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


def read_state(run_dir):
    try:
        state = json.loads((run_dir / "run.json").read_text())
        return state if isinstance(state, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


# One run's memory, below the slice ceiling.  4 GB, or 40% of that ceiling when the
# ceiling is the smaller of the two: a leak has to die inside its own scope, while
# the seat slice -- accounted apart, and with the higher weight -- is never the thing
# the kernel throttles.  Swap is capped at the same size so the excess cannot hide there.
RUN_MEMORY_DEFAULT_MB = 4096
RUN_MEMORY_SHARE = 40


def scope_is_real(scope):
    """Whether `scope` names a unit systemd actually holds, not a plain start."""
    return (isinstance(scope, str) and bool(scope) and scope != "none"
            and not scope.startswith("none"))


def memory_cap_mb(ceiling_mb=None):
    """The cap for one run, in mebibytes.

    `run_memory_max_mb` in the config, when it is set.  Otherwise the smaller of
    4 GB and 40% of the slice's MemoryMax.  No ceiling at all -- a host with no
    drop-in, a Mac -- keeps the 4 GB bound, which is still below an uncapped user
    unit.  The share is integer arithmetic so 40% of an odd ceiling does not
    drift.
    """
    configured = config.run_memory_max_mb()
    if configured is not None:
        return configured
    if ceiling_mb is None:
        ceiling_mb = orch.slice_memory_max_mb()
    cap = RUN_MEMORY_DEFAULT_MB
    if (isinstance(ceiling_mb, (int, float)) and not isinstance(ceiling_mb, bool)
            and ceiling_mb > 0):
        share = max(1, (int(ceiling_mb) * RUN_MEMORY_SHARE) // 100)
        cap = min(cap, share)
    return cap


def memory_cap_line(mb):
    """The reason a run that hit `mb` mebibytes records: `killed: memory cap N GB`."""
    gb = mb / 1024
    if abs(gb - round(gb)) < 1e-9:
        shown = str(int(round(gb)))
    else:
        shown = f"{gb:.2f}".rstrip("0").rstrip(".")
    return f"killed: memory cap {shown} GB"


def run_scope_limits(ceiling_mb=None):
    """(cap in MiB, systemd properties) for one run scope.

    CPU and I/O weight stay below the seats' 100, and the memory cap is applied
    as both MemoryMax and MemorySwapMax: the same number, so a leak cannot trade
    one for the other and keep going.  The properties are what `systemd-run -p`
    takes; the cap is what the receipt records, so the reason can still name the
    number after the process that knew it is gone.
    """
    cap = memory_cap_mb(ceiling_mb)
    return cap, ("-p", "CPUWeight=40", "-p", "IOWeight=40",
                 "-p", f"MemoryMax={cap}M", "-p", f"MemorySwapMax={cap}M")


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
    """(Result, ControlGroup) for `unit`, or (None, "") when the manager cannot be asked.

    A unit it does not have is an empty Result, not a failure to ask: the caller
    tries the other suffix.  The labelled properties are parsed by name because
    `--value` does not promise the order they were requested in.
    """
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "Result", "-p", "ControlGroup",
             "-p", "LoadState"],
            capture_output=True, encoding="utf-8", errors="replace",
            env=orch.bus_env(), timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    if proc.returncode != 0:
        return None, ""
    fields = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    if fields.get("LoadState") == "not-found":
        return "", ""
    return fields.get("Result", ""), fields.get("ControlGroup", "")


def _oom_kill_count(cgroup):
    """How many processes the kernel OOM-killed in that cgroup, or 0 if it cannot be read.

    Read before the scope is stopped: stopping it is what gives the memory back,
    and it may remove the cgroup the count lives in.
    """
    if not cgroup:
        return 0
    path = orch.CGROUP_ROOT / cgroup.lstrip("/") / "memory.events"
    try:
        text = path.read_text()
    except OSError:
        return 0
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if key == "oom_kill" and value.strip().isdigit():
            return int(value.strip())
    return 0


def _scope_oom_probe(state):
    """(systemd Result, oom_kill count) for the run's scope.  Either witness is enough."""
    result, kills = "", 0
    for unit in _scope_units(state.get("scope")):
        shown, cgroup = _systemctl_fields(unit)
        if shown is None:
            continue
        kills = max(kills, _oom_kill_count(cgroup))
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
    save_state(run_dir, state)
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
        refresh_seat_tally(launched_session(state))
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
    """
    scope = state.get("scope") if isinstance(state, dict) else None
    run_id = state.get("run_id") if isinstance(state, dict) else None
    if run_id:
        worker.kill_marked(run_id, log=log)
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
    state = read_state(run_dir) or state
    if state.get("state") not in ("running", "queued") and not needs_recovery(state):
        if state.get("state") not in ENDED:
            return state
        # else: an ended run whose loop may have died before its final cleanup --
        # fall through and sweep what it left behind, once per loop
    with recovery_lock(run_dir):
        state = read_state(run_dir) or state  # a menu snapshot may predate a resume
        status = state.get("state")
        if status == "queued" and state.get("slot_waiting"):
            return state  # the tick adopts dead waiters without losing their place
        if status == "stalled":
            return state  # parked by the tick; only an explicit resume moves it
        resumed_at = state.get("stall_resume_at")
        if (status in ("running", "queued") and isinstance(resumed_at, (int, float))
                and not isinstance(resumed_at, bool)
                and 0 <= time.time() - resumed_at < STALL_RESUME_GRACE):
            return state  # the tick stopped this loop and ordered a resume; it adopts next
        holding = state.get("resume_after")
        if (status in ("running", "queued") and isinstance(holding, (int, float))
                and not isinstance(holding, bool) and time.time() < holding):
            return state  # the tick is waiting out this dead loop's backoff before its next try
        grace = (status == "queued" and
                 (state.get("launch_pending") or not state.get("process_identity")) and
                 time.time() - (state.get("queued_at") or state.get("started_at") or 0) < QUEUED_GRACE)
        resuming = False
        if status in ("running", "queued") and not grace and not process_active(state):
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
                resuming = tick_resumes(state)
                if resuming:
                    # Whoever notices the death records it, so the tick's dead-loop pass reads
                    # this record as a loop to carry on rather than as an interruption somebody
                    # was already told about -- and so it counts towards the third death.
                    state["deaths"] = [*(state.get("deaths") or []),
                                       {"at": time.time(), "pid": state.get("pid"),
                                        "reason": reason}]
                save_state(run_dir, state)
        elif status == "interrupted" and not state.get("interrupted_at"):
            interrupt(state, state.get("error") or "Earlier interruption; detection time recorded now.")
            save_state(run_dir, state)
        if status in ("pass", "fail", "error", "blocked", "exhausted", "waiting_login",
                      "interrupted") and not process_active(state):
            swept = [state.get("pid"), state.get("process_identity")]
            if state.get("tree_stopped") != swept:
                # The loop recorded its ending and died before its final cleanup, so the
                # reaper ends what it left behind. Stamped with the loop it swept for:
                # every activation records a new pid, so a resumed run is swept again
                # without anyone clearing the stamp.
                stop_run_tree(state)
                state["tree_stopped"] = swept
                save_state(run_dir, state)
        if needs_recovery(state) and not resuming:
            notify_recovery(run_dir, state)
    return state


def supersession_index(states):
    """Newest-first replacements per title and per branch: build once, then test runs
    without rescanning.

    `states` is an iterable of states, or `(run_dir, state)` pairs as `run_records`
    yields. Answers `{title: [(finished_when, run_id, display)]}` for merged runs
    with a title, and `{("from", repo, branch): [...]}` for every run relaunched
    `from:` a branch, each with a numeric finish (or start), newest first. Read-only.
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
            index.setdefault(("from", other.get("repo"), other["from"]), []).append(
                (when, other.get("run_id"), other.get("run_id") or other["from"]))
    for entries in index.values():
        entries.sort(key=lambda entry: entry[0], reverse=True)
    return index


def superseded_by(state, records=None, index=None):
    """The later run that replaced this one, or None. Read-only.

    A `↳` row appears only for a run nobody has replaced: a later merged run of the
    same title supersedes it, and so does a later run relaunched `from:` its branch in
    its repository, whatever that run's own ending -- the orchestrator took the work up
    again, and its title often says `(continued from its branch)`.  `r` names the
    replacement as `superseded by <run id>`.
    A merged run never supersedes itself. `records` is an iterable of states already
    read; when omitted the runs on disk are read once, never written. `index` is a
    `supersession_index` over the same states: pass it when testing many runs, so one
    draw scans the records once instead of once per run per seat.
    """
    title, branch = state.get("title"), state.get("branch")
    if not (title or branch) or state.get("merged"):
        return None
    mine = state.get("finished_at") or state.get("started_at") or 0
    if not isinstance(mine, (int, float)) or isinstance(mine, bool):
        mine = 0
    if index is not None:
        later = [(when, display) for when, run_id, display in (
                     *index.get(title, ()), *index.get(("from", state.get("repo"), branch), ()))
                 if run_id != state.get("run_id") and when > mine]
        return max(later)[1] if later else None
    found = []
    if records is None:
        for run_dir in run_dirs():
            if "smoke-" in run_dir.name:
                continue
            other = read_state(run_dir)
            if other:
                found.append(other)
    else:
        for item in records:
            other = item[1] if isinstance(item, (tuple, list)) and len(item) == 2 else item
            if isinstance(other, dict):
                found.append(other)
    best, newest = None, mine
    for other in found:
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


def is_superseded(state, records=None, index=None):
    """Whether a later run replaced this one (see `superseded_by`). Read-only."""
    return superseded_by(state, records, index) is not None


def settled(state, index=None):
    """Whether an ending is already its orchestrator's: handed back to the seat that launched
    it or waiting for that seat's next quiet prompt, acknowledged, or superseded by later work.

    These are the endings `menu.v5o_needs_look` counts as nobody's question, and as there
    an `exhausted` run the tick cannot resume is no ending: only an acknowledgement settles
    it.  `index` is a `supersession_index`; without one supersession is not read.
    """
    if state.get("state") == "exhausted":
        return bool(state.get("recovery_acknowledged_at"))
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
    with recovery_lock(run_dir):
        current = read_state(run_dir) if state is None else dict(state)
        if not current:
            return False
        if current.get("state") not in ENDED:
            return False
        if current.get("state") == "error" and going(current):
            return False
        if current.get("recovery_acknowledged_at"):
            return False
        current["recovery_acknowledged_at"] = time.time()
        current.pop("error_retry_at", None)
        current.pop("error_retries", None)
        save_state(run_dir, current)
        return True


def acknowledge(run_dir):
    with recovery_lock(run_dir):
        state = read_state(run_dir)
        if not state:
            raise config.Error("the run is no longer waiting for recovery")
        waiting = needs_recovery(state) or state.get("state") in ("fail", "error", "blocked")
        if not waiting or state.get("recovery_acknowledged_at"):
            raise config.Error("the run is no longer waiting for recovery")
        state["recovery_acknowledged_at"] = time.time()
        state.pop("error_retry_at", None)
        state.pop("error_retries", None)
        save_state(run_dir, state)


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
    return retention.clean_worktree(Path(repo), wt, state, JUNK)


def seat_file_stale(path, now):
    """The seat a `<kind>-<name>.*` state file is named for, when that seat has no record and
    the file has not been written for a day; None for anything else."""
    stem, dot, ext = path.name.rpartition(".")
    kind, sep, name = stem.partition("-")
    if (kind not in orch.SEAT_FILE_KINDS or not dot or not ext or not sep or not name
            or not retention.safe(path) or not path.is_file()):
        return None
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
        if state and (unfinished(state) or state.get("handback_pending")):
            try:
                held.add(launched_session(state))
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
    return (ext == "json" and pid.isdigit() and not alive(int(pid)) and retention.safe(path)
            and path.is_file()
            and retention.expired(path.lstat().st_mtime, now, retention.EPHEMERAL_AGE))


def stale_compact_stamps(now):
    return [{"action": "remove", "kind": "compact-stamp", "path": str(path),
             "why": f"its wrapper, pid {compact_pid(path)}, is gone"}
            for path in retention.children(config.STATE / "idle-compact")
            if compact_stamp_stale(path, now)]


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
        if (not retention.present(directory / "run.tmp") and not retention.busy(directory, paths)
                and retention.expired(wt.lstat().st_mtime, now, retention.EPHEMERAL_AGE)):
            return {"action": "remove", "kind": "orphan-worktree", "path": str(wt),
                    "why": "no run record"}
        return None
    state = retention.read_json(directory / "run.json")
    finished = (state or {}).get("finished_at")
    if (state and state.get("run_id") == wt.name and state.get("worktree") == str(wt)
            and state.get("state") == "pass" and not state.get("merged")
            and (state.get("merge_note") or state.get("no_merge"))
            and not state.get("scratch") and provably_final(state)
            and retention.expired(finished, now, GC_AGE)
            and not retention.present(directory / "run.tmp")):
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
    shutil.rmtree(tree, ignore_errors=True)
    if repo is not None and repo != tree and repo.is_dir():
        try:
            git(repo, "worktree", "prune", check=False)
        except Stopped as exc:
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
            and tree.is_dir() and not under_code(tree))


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
    allowed = (tree is not None and own_tree(state) == tree and provably_final(state)
               and clearable(tree)
               and (tree.parent == config.WORK and with_run if state.get("scratch")
                    else checkout_removable(state)))
    try:
        drop_checkout(state, report, keep_branch=keep_branch, with_run=with_run)
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
                and not retention.present(directory / "run.tmp")
                and retention.safe(directory)):
            yield {"action": "remove", "kind": "throwaway-run", "path": str(directory),
                   "run": str(directory), "throwaway": True,
                   "state_identity": retention.fingerprint(directory / "run.json")}
            continue
        # One age for the directory itself. A seat that still exists keeps its
        # runs however old they are; the seat is what they belong to. Pending
        # hand-backs and cards are not consulted: with the session gone there is
        # no seat left to tell, and the directory goes with them untold.
        if (state and state.get("run_id") == directory.name and provably_final(state)
                and run_aged_out(directory, state, now)
                and not retention.writer_active(state) and not retention.busy(directory, paths)
                and not retention.present(directory / "run.tmp") and retention.safe(directory)):
            try:
                owner = launched_session(state)
            except config.Error:
                owner = ""
                keep_for_seat = True
            else:
                keep_for_seat = session_lives(owner)
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
                and provably_final(state)
                and not retention.writer_active(state) and not retention.busy(directory, paths)
                and not retention.present(directory / "run.tmp")
                and (retention.expired(finished, now, GC_AGE)
                     or (already_handed_back(state)
                         and not resume_holds_tree(state, directory)))
                and disposable_workspace(directory, state) and state["worktree"] not in left
                and not retention.busy(Path(state["worktree"]), paths)):
            yield {"action": "remove", "kind": "ended-worktree", "path": str(state["worktree"]),
                   "run": str(directory), "loose": True, "final": True,
                   "state_identity": retention.fingerprint(directory / "run.json")}
        if (not state or state.get("run_id") != directory.name or state.get("scratch")
                or state.get("state") != "pass" or not state.get("merged")
                or not provably_final(state)
                or state.get("notification_pending") or state.get("pending_inbox")
                or state.get("handback_pending")
                or retention.writer_active(state) or retention.busy(directory, paths)
                or retention.present(directory / "run.tmp") or not collectible_worktree(directory, state)):
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
            job = retention.read_json(directory / "job.json")
            finished = (job or {}).get("finished_at")
            if (not job or not isinstance(job.get("tasks"), list) or not job["tasks"]
                    or not all(task.get("state") in JOB_TERMINAL for task in job["tasks"])
                    or not retention.expired(finished, now, age)
                    or job.get("handback_pending")
                    or retention.writer_active(job) or retention.busy(directory, paths)
                    or retention.present(directory / "job.tmp")):
                continue
            yield {"action": "remove", "kind": "finished-job", "path": str(directory),
                   "job": str(directory),
                   "state_identity": retention.fingerprint(directory / "job.json")}
    yield from retention.ephemeral_plan(now, pressure, paths)
    yield from stale_worktrees(now, paths)
    yield from stale_seat_files(now)
    yield from stale_compact_stamps(now)
    yield from retention.harness_plan()


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
            for item in gc_candidates():
                path = Path(item["path"])
                try:
                    # the planner's own proof once more, now: a seat launched under the name,
                    # a wrapper or a run back in the checkout since, and it all stays
                    if item["kind"] in ("seat-file", "compact-stamp"):
                        if not (seat_file_stale if item["kind"] == "seat-file"
                                else compact_stamp_stale)(path, time.time()):
                            continue
                        path.unlink()
                        done = True
                    elif item["kind"] in ("orphan-worktree", "unmerged-worktree"):
                        # A resume commits under the run's recovery lock: it lands before
                        # the second look, and the tree stays, or finds the tree gone.
                        directory = config.RUNS / path.name
                        recovery = directory / "recovery.lock"
                        if retention.present(directory) and (
                                not retention.safe(directory) or recovery.is_symlink()
                                or (recovery.exists() and not retention.safe(recovery))):
                            continue
                        paths = retention.process_paths()   # before our own lock is open
                        with (recovery_lock(directory) if retention.present(directory)
                              else nullcontext()):
                            if not stale_worktree(path, time.time(), paths, leftovers()):
                                continue
                            clear_tree(path, report)
                            done = not left_behind(path, report)
                    elif item["kind"] == "harness-entries":
                        done = retention.prune_harness(path)
                    elif item.get("throwaway") or item.get("whole"):
                        directory = Path(item["run"])
                        recovery = directory / "recovery.lock"
                        if (not retention.safe(directory) or recovery.is_symlink()
                                or (recovery.exists() and not retention.safe(recovery))):
                            continue
                        paths = retention.process_paths()
                        with recovery_lock(directory):
                            state = retention.read_json(directory / "run.json")
                            # A provably final run does not wait for a second look at
                            # its fingerprint. A run that has since resumed still does.
                            same = (item.get("final") and provably_final(state or {})) or (
                                retention.fingerprint(directory / "run.json") == item["state_identity"])
                            if (not same or retention.writer_active(state or {})
                                    or retention.busy(directory, paths)):
                                continue
                            if item.get("whole"):
                                try:
                                    owner = launched_session(state or {})
                                except config.Error:
                                    continue
                                if session_lives(owner) or not provably_final(state or {}):
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
                                    drop_local_branch(state.get("repo"), state.get("branch"),
                                                      report)
                                else:
                                    drop_tree(state, tree, report, keep_branch=False,
                                              with_run=True)
                            shutil.rmtree(directory, ignore_errors=False)
                            done = not directory.exists()
                    elif "run" not in item and "job" not in item:
                        done = retention.remove_ephemeral(item)
                    elif "job" in item:
                        directory = Path(item["job"])
                        if not retention.safe(directory):
                            continue
                        paths = retention.process_paths()
                        with recovery_lock(directory):
                            job = retention.read_json(directory / "job.json")
                            tasks = (job or {}).get("tasks")
                            if (retention.fingerprint(directory / "job.json") != item["state_identity"]
                                    or retention.writer_active(job or {})
                                    or retention.busy(directory, paths)
                                    or not isinstance(tasks, list) or not tasks
                                    or not all(task.get("state") in JOB_TERMINAL for task in tasks)):
                                continue
                            shutil.rmtree(directory, ignore_errors=False)
                            done = not directory.exists()
                    else:
                        directory = Path(item["run"])
                        paths = retention.process_paths()
                        recovery = directory / "recovery.lock"
                        if recovery.is_symlink() or (recovery.exists() and not retention.safe(recovery)):
                            continue
                        with recovery_lock(directory):
                            state = retention.read_json(directory / "run.json")
                            # Final and the loop gone: do not wait for the fingerprint
                            # taken while planning. Anything that has started again stays.
                            same = (item.get("final") and provably_final(state or {})) or (
                                retention.fingerprint(directory / "run.json") == item["state_identity"])
                            worktree = (state or {}).get("worktree")
                            if (not same or retention.writer_active(state or {})
                                    or retention.busy(directory, paths)
                                    or (isinstance(worktree, str) and retention.busy(Path(worktree), paths))
                                    or (not item.get("loose")
                                        and not collectible_worktree(directory, state))):
                                continue
                            if not provably_final(state or {}):
                                continue
                            if item["action"] == "compress":
                                done = retention.compress(path, item["identity"])
                            elif item.get("loose"):
                                if not (
                                        retention.expired(
                                            state.get("finished_at"), time.time(), GC_AGE)
                                        or (already_handed_back(state)
                                            and not resume_holds_tree(state, directory))):
                                    continue
                                done = drop_tree(state, path, report)
                            else:
                                try:
                                    code, _ = git_out(state["repo"], "worktree", "remove",
                                                      str(path))
                                except Stopped as exc:
                                    # a stop is not a verdict on the candidate: it stays put,
                                    # and the remedy is reported rather than raised past the pass
                                    report(f"gc: {item['kind']} {path} left in place: {exc}")
                                    continue
                                gone = not left_behind(path, report)
                                done = code == 0 and gone
                                if done:
                                    drop_local_branch(state.get("repo"), state.get("branch"), report)
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
                or not provably_final(state) or retention.present(directory / "run.tmp")):
            continue
        repo, worktree = state.get("repo"), state.get("worktree")
        if (not isinstance(repo, str) or not repo or not isinstance(worktree, str)
                or Path(worktree) != config.WT / directory.name or Path(repo) == Path(worktree)):
            continue
        wt = Path(worktree)
        if (under_code(wt) or not retention.present(wt) or not retention.safe(wt)
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
    git_out(repo, "worktree", "remove", "--force", str(wt))
    if retention.present(wt):
        shutil.rmtree(wt)
    if Path(repo).is_dir():
        git(repo, "worktree", "prune", check=False)
    drop_local_branch(repo, state.get("branch"), report)


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
                        shutil.rmtree(path)
                except Stopped as exc:
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


def _cached_providers():
    """The usage cache's providers for display: {} when the cache cannot be read."""
    try:
        blob = json.loads((config.STATE / "usage.json").read_text())
        providers = blob.get("providers") if isinstance(blob, dict) else None
        return providers if isinstance(providers, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def executable_models(cfg, providers, workers, now, log=None):
    """(model, provider) pairs that can execute now, in pick order.

    An eligible worker counts when the pick order keeps it, its budget is above zero
    with nothing unknown about it, and no refusal parked its provider until a future
    window.  The tick's availability and the waiting words share this one rule.  `log`
    is told each worker left out because its harness cannot run, as `ready_order` says it.
    """
    try:
        order = ready_order(cfg, providers, workers=list(workers), log=log, role="executor",
                            quiet=True)
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
        order = ready_order(cfg, providers, workers=list(workers), role="reviewer",
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
    carries a future reset, which reads as a window with no known hour.
    """
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
        return slot_note(state)
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
    run -- a task that still parses with a done-when.  A run that fails any of
    them is parked for a person, not for the tick: retrying a task nobody can run
    would only fail on the hour, every hour, saying nothing new.
    """
    if state.get("review_pr"):
        return False  # the watch relaunches the review itself; the run is never resumed
    wt = state.get("worktree")
    if not wt or not Path(wt).is_dir():
        return False
    keys = (("worktree", "rounds") if state.get("scratch") else
            ("repo", "worktree", "branch", "base", "base_sha", "rounds"))
    if any(not state.get(key) for key in keys):
        return False
    try:
        _, body, _ = parse_task(Path(run_dir) / "task.md")
        done_when(body, Path(run_dir) / "task.md")
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
    no seat working.
    """
    if state.get("state") != "exhausted":
        return ""
    if state.get("quota_dry"):
        return "window"
    if reviewer_transport_dead(state.get("error")):
        return "reviewer"
    return ""


def going(state, now=None):
    """Whether the run keeps its seat working while it lasts.

    The GOING states -- queued, running, waiting, exhausted, stalled,
    waiting_login -- which resume themselves or are already running, plus an
    error the tick will retry. Errors and merge waits also need current admission:
    an old stamp cannot keep a seat working after its retry stopped being allowed,
    and an exhausted run keeps one working only while the tick can resume it
    (`exhausted_wait`): one that waits on nobody is his, not going.
    """
    if state.get("state") in ("error", "waiting") and not tick_admission(state, now=now):
        return False
    if state.get("state") == "exhausted":
        return bool(exhausted_wait(state))
    if state.get("state") in watch.GOING:
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

    A telling or acknowledgement settles the ending for good. Only an untold
    ending under a day old, from a session that still exists, is the tick's.
    Following the launch name also keeps a renamed seat's runs with that seat.
    """
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
    moved past is history, and a by-hand run waits for a person.
    """
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
        if git_out(wt, "fetch", "origin")[0] != 0:
            return None
        sha = git(wt, "rev-parse", f"{ref}^{{commit}}", check=False)
    except (config.Error, OSError):
        return None
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha or ""):
        return None
    return sha


def parked_line(state, run_id=None, now=None):
    """The dim line under a parked run's status row: its state as such, and when.

    An error with a scheduled retry names its hour (`error · retry 14:32`, or
    `retry due` once the hour has passed and the tick just has not fired yet); a
    `waiting` run names the merge it waits for; an `exhausted` run off a dead
    reviewer names the reviewer it waits for.  A quota run already says its
    window on the waiting line, and a stalled one its stall lines, so neither
    says anything here. An admitted ending also names the conditions that let
    the tick take it up. Anything parked with no scheduled resume says who it
    waits for instead: `run <id> parked: <reason>`.
    """
    now = time.time() if now is None else now
    name = run_id or state.get("run_id") or "?"
    word = state.get("state")
    admission = tick_admission(state, now=now) if word in ("error", "waiting") else ""
    admitted = f" · {admission}" if admission else ""
    if word in ("error", "waiting") and not admission:
        return f"run {name} parked: {handback_reason(state)}"
    if word == "error":
        at = state.get("error_retry_at")
        if isinstance(at, (int, float)) and not isinstance(at, bool):
            if at <= now:
                return "error · retry due" + admitted
            try:
                return f"error · retry {time.strftime('%H:%M', time.localtime(at))}" + admitted
            except (OverflowError, OSError, ValueError):
                return "error · retry due" + admitted
        return f"run {name} parked: {handback_reason(state)}"
    if word == "waiting":
        ref = (state.get("waiting_on") or {}).get("ref") or conflict_upstream(state)
        return f"waiting · retry after the next merge to {ref}" + admitted
    if word == "exhausted" and exhausted_wait(state) == "reviewer":
        return "exhausted · resumes when a reviewer is eligible"
    return ""


def executor_line(state):
    """Who executed: `astra \u2192 opus (ran dry)` where the work changed hands mid-run.

    The arrow reads in the order the models held the work, and the reason in brackets is why
    the last one before the current model stopped -- never a guess, always what run.json says.
    The tick's entries name the move without the model half, so a link reads `from` where
    `model` is missing and the brackets read `reason` where `why` is.
    """
    name = str(state.get("executor", "?"))
    history = [entry for entry in state.get("executor_history") or [] if isinstance(entry, dict)]
    if not history:
        return name
    # a handover attempt that went nowhere held no new round, so it is not a link
    held = [e for e in history
            if e.get("from") is None or e.get("to") is None or e["from"] != e["to"]]
    chain = " \u2192 ".join([*(str(e.get("model") or e.get("from") or "?") for e in held), name])
    return f"{chain} ({history[-1].get('why') or history[-1].get('reason') or 'changed'})"


def blocked_note(state, word=None):
    """`! blocked \u00b7 <why>` for a run the orchestrator has to write a new task for, else "".

    The one dim line `ak run status` keeps under a blocked row: the glyph
    and the word for what it is, then why.  A blocked run is final -- `ak run resume` refuses
    it -- so the line says what happened and never offers a number to resume from.  `word`
    is the row's own, where the row's word is the listing's (`status_state_word`).
    """
    if state.get("state") != "blocked":
        return ""
    from . import menu, terminal
    why = " ".join((state.get("error") or "the task cannot be completed as written").split())
    return f"{terminal.state_glyph(word or menu.run_state_word(state))} blocked \u00b7 {why}"


def handback_waiting(state):
    """`hand-back waiting: <why>` for an ending held for a closed seat, else "".

    The one line `ak run status` keeps under a row whose seat the owner closed: the ending was
    never typed and the seat never reopened, so the wait has to be visible somewhere.  A seat
    mid-turn leaves the same flag without a reason, and shows no line: the tick types it at the
    next quiet prompt.
    """
    if not state.get("handback_pending"):
        return ""
    why = state.get("handback_wait_reason")
    if not why:
        return ""
    return f"hand-back waiting: {why}"


def run_scope_dir(scope):
    """This run's scope directory under the runs slice, or None where there is none.

    A scope the manager never made -- a plain start, or one already collected --
    has no directory, and says nothing: the marker scan below is the fallback.
    """
    if not isinstance(scope, str) or not scope or scope == "none" or scope.startswith("none ("):
        return None
    try:
        runs_dir = orch.slice_cgroup() / orch.run_slice_name()
    except (OSError, ValueError):
        return None
    for suffix in (".scope", ".service"):
        name = scope if scope.endswith(suffix) else f"{scope}{suffix}"
        candidate = runs_dir / name
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def _scope_readings(scope_dir):
    """(live processes, resident bytes) from a scope's cgroup files, or None.

    `cgroup.procs` names every live process the kernel still holds there, one
    pid a line; `memory.current` is their resident bytes.  Either file missing
    or unreadable is no reading, never a zero.
    """
    try:
        procs = (Path(scope_dir) / "cgroup.procs").read_text().split()
        mem = (Path(scope_dir) / "memory.current").read_text().strip()
    except OSError:
        return None
    try:
        return len([line for line in procs if line.strip().isdigit()]), int(mem)
    except (ValueError, TypeError):
        return None


def _marked_rss(pid, proc_root="/proc"):
    """Resident bytes for one pid from its statm, or None where unread."""
    try:
        resident = int((Path(proc_root) / str(pid) / "statm").read_text().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    try:
        return resident * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return None


def scope_alive(state, scope_dir=None, _marker=None, _rss=None, _active=None):
    """(live processes, resident bytes) for an unfinished run, or None.

    The scope's cgroup answers first, where the run has one; without systemd
    the marker scan counts what still carries the run's name, plus the loop
    itself while it is still the run's own.  A finished run owns nothing and
    says nothing.  Anything unreadable fails open to no reading, the way every
    gate here does: no cgroup, no answer, no line.
    """
    if (state or {}).get("state") in ENDED:
        return None
    if scope_dir is None and (state or {}).get("scope"):
        scope_dir = run_scope_dir(state.get("scope"))
    if scope_dir is not None:
        readings = _scope_readings(scope_dir)
        if readings is not None:
            return readings
    run_id = (state or {}).get("run_id")
    marker = _marker or marker_pids
    try:
        pids = list(marker(run_id)) if run_id else []
    except (OSError, ValueError, TypeError):
        return None
    active = _active or process_active
    try:
        loop_alive = bool(active(state))
    except (OSError, ValueError, TypeError, AttributeError):
        loop_alive = False
    pid = (state or {}).get("pid")
    if loop_alive and isinstance(pid, int) and pid > 0 and pid not in pids:
        pids.append(pid)
    rss = _rss or _marked_rss
    total = 0
    for member in pids:
        try:
            reading = rss(member)
        except (OSError, ValueError, TypeError):
            reading = None
        if reading is not None:
            total += reading
    if not pids:
        # Without /proc there is no scan to believe: a host that cannot answer
        # shows no line rather than a zero.
        try:
            if not Path("/proc").is_dir():
                return None
        except OSError:
            return None
    return len(pids), total


def format_alive_memory(mem_bytes):
    """Resident bytes the way the host line says gigabytes: `1.2 GB`, `50 MB`."""
    try:
        mb = float(mem_bytes) / (1024 * 1024)
    except (TypeError, ValueError):
        return "? MB"
    if mb >= 1024:
        return f"{_g(mb)} GB"
    if mb >= 1:
        return f"{mb:.0f} MB"
    kb = mb * 1024
    return f"{kb:.0f} KB" if kb >= 1 else "0 KB"


def format_alive(count, mem_bytes):
    """`3 processes · 1.2 GB`: live processes and their resident memory, one line."""
    word = "processes" if count != 1 else "process"
    return f"{count} {word} · {format_alive_memory(mem_bytes)}"


def alive_line(state, scope_dir=None, _marker=None, _rss=None, _active=None):
    """`3 processes · 1.2 GB` under an unfinished run's row, else "".

    The one dim line that says what is still alive under the run: the scope's
    cgroup count and resident memory, or the marker scan's where there is no
    scope.  A finished run shows neither count nor memory.
    """
    readings = scope_alive(state, scope_dir, _marker, _rss, _active)
    if readings is None:
        return ""
    count, mem_bytes = readings
    return format_alive(count, mem_bytes)


def stop_note(state):
    """`stopped · <why>` for a run a cap or a kill ended, else "".

    The one dim line a stopped run keeps under its row: what ended it, in the
    run's own words.  A run the memory cap killed says its ceiling here too,
    so a `fail` on `killed: memory cap 4 GB` never reads as work that was judged.
    """
    if (state or {}).get("state") == "stopped":
        why = " ".join((state.get("error") or "stopped by the user").split())
        return f"stopped · {why}"
    err = " ".join(((state or {}).get("error") or "").split())
    lowered = err.lower()
    if "killed" in lowered or "memory cap" in lowered:
        return err
    return ""


def status_word(state, cfg=None):
    """What `ak run status` says became of a finished run's work.

    `delivery` already knows: this is that answer with the verdict taken off, because the
    status line carries the verdict in a column of its own.  So a run with no repository reads
    `delivered`, and `merged` and `not merged: <reason>` stay what they always were -- a
    repository run's answer, about a branch a run without one never had.  A merged run is
    `merged` whatever today's config makes of its review's providers: the merge happened.
    """
    if not state.get("finished_at"):
        return ""
    if state.get("merged"):
        return "merged"
    if state.get("pr"):
        return "PR open"
    word = delivery(state, report_config(cfg))
    return word[len("PASS, "):] if word.startswith("PASS, ") else ""


def step_word(state):
    """The step a live run is in and how long it has been there: `executor 41m`, `merge 1m`.

    Only a running run has one.  A finished run's step is over, and what became of its work is
    the column that says something.
    """
    if state.get("state") != "running" or not state.get("step"):
        return ""
    at = state.get("step_at")
    if type(at) not in (int, float):
        return str(state["step"])
    return f"{state['step']} {orch.span(time.time() - at)}"


def unfinished(state):
    """Runs that still own an active seat or await an explicit recovery decision."""
    return (state.get("state") in ("running", "queued") or
            (needs_recovery(state) and not state.get("recovery_acknowledged_at")))


def actionable(state):
    if state.get("recovery_acknowledged_at"):
        return False
    finished = state.get("finished_at") or state.get("started_at")
    recent_failure = (state.get("state") in ("fail", "error", "blocked") and
                      type(finished) in (int, float) and time.time() - GC_AGE < finished <= time.time())
    pending_delivery = (state.get("state") == "pass" and state.get("repo")
                        and not state.get("merged") and not state.get("no_merge")
                        and not state.get("on_target")
                        and not state.get("review_pr") and not state.get("review_posted"))
    return bool(unfinished(state) or recent_failure or pending_delivery)


def status_key(pair):
    state = pair[1]
    return (state.get("state") in ("running", "queued"), bool(actionable(state)),
            state.get("interrupted_at") or state.get("finished_at") or state.get("started_at") or 0)


def result_paths(directory, state):
    return {"result": str(directory / "result.md"), "record": str(directory / "run.json"),
            "logs": str(directory), "workspace": state.get("worktree"),
            "workspace_present": bool(state.get("worktree") and Path(state["worktree"]).exists())}


def workspace_location(state, present):
    """`present`, or what a missing checkout still leaves behind.

    Every other cleanup keeps the local branch, so `removed; branch/PR retained`
    is the whole story -- except a stop without `--keep`, a merged run, and a
    branch a session stop took, which say `removed; branch removed` instead.
    """
    if present:
        return "present"
    if state.get("state") == "stopped" and not state.get("stop_kept"):
        return "removed; branch removed"
    if state.get("merged") or state.get("branch_removed"):
        return "removed; branch removed"
    return "removed; branch/PR retained"


def resume_age(state, now=None):
    """`resumed 13:05 · continued the executor's turn` for an hour after a resume, else "".

    The age column carries it, in the same cell the row's age usually occupies, and only
    while the resume is still the news. `turn restarted` is a session the harness could
    not continue, so the role went on in a fresh conversation.

    Only a model turn is a turn: a slot wait, the done-when gate and the merge are steps
    the loop continues itself, and the line names them as what they are.
    """
    note = state.get("resume_notice")
    if not isinstance(note, dict):
        return ""
    at = note.get("at")
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return ""
    now = time.time() if now is None else now
    if not 0 <= now - at <= RESUME_VISIBLE:
        return ""
    clock = time.strftime("%H:%M", time.localtime(at))
    if note.get("restarted"):
        return f"resumed {clock} · turn restarted"
    role = note.get("role") or "executor"
    what = f"the {role}'s turn" if role in TURN_ROLES else f"the {role}"
    return f"resumed {clock} · continued {what}"


def death_lines(state):
    """One line per recorded death, for `ak run status <id>`."""
    lines = []
    for death in state.get("deaths") or []:
        if not isinstance(death, dict):
            continue
        when = death.get("at")
        if isinstance(when, (int, float)) and not isinstance(when, bool):
            clock = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
        else:
            clock = "?"
        reason = death.get("reason") or ""
        parked = " parked" if death.get("parked") else ""
        lines.append(f"  death {clock} pid {death.get('pid')}{parked}: {reason}")
    return lines


STATUS_HEADERS = ["id", "title", "state", "worker", "round", "age"]


def status_state_word(state, index=None):
    """`ak run status`'s word for a run: `menu.run_state_word`'s, except that a `needs you`
    ending already `settled` reads `done`.

    The record's own word stays the menu's.  This is the listing's, which knows what came
    after the run, so it tells the truth the seat's row tells: an ending handed back,
    acknowledged or superseded is nobody's question any more.
    """
    from . import menu
    word = menu.run_state_word(state)
    return "done" if word == "needs you" and settled(state, index) else word


def status_id_cell(name, room):
    """The id as its date and time, then the slug cut at a word.

    A run id is `YYYYMMDD-HHMM-slug`; the cell keeps the whole id where it
    fits and falls back to `YYYYMMDD HHMM <slug cut at a word>` where the
    screen cannot hold it.
    """
    from . import terminal
    if terminal.cells(name) <= room:
        return name
    match = re.match(r"^(\d{8})-(\d{4})-(.*)$", name, re.DOTALL)
    if not match:
        return terminal.cut(name, room)
    date, clock, slug = match.groups()
    head = f"{date} {clock} "
    if terminal.cells(head) >= room:
        return terminal.cut(name, room)
    room -= terminal.cells(head)
    if terminal.cells(slug) <= room:
        return head + slug
    # the slug's words are dash-separated: keep whole words, never mid-word;
    # the ellipsis takes the last cell, so the words keep all but one
    current = ""
    for word in slug.split("-"):
        added = word if not current else current + "-" + word
        if terminal.cells(added) > room - 1:
            break
        current = added
    if not current:
        return head + terminal.cut(slug, room)
    return head + current + "…"


def status_rows(found, width, index=None):
    """The status table's header and one line group per row.

    Fixed columns with two-space gutters, sized once from the rows on screen:
    id (its date and time, then the slug cut at a word), title (all the
    remaining width, wrapped once at a word onto an indented continuation, cut
    with ` \u2026` only past that), state, worker, round, age. The state reads the
    table's words from terminal.STATES: unfinished, working, done or failed.
    Returns (header, groups): the header drawn once, each group's lines for
    one row, so the caller can print a run's detail lines indented under it.
    `index` is the listing's `supersession_index`, for `status_state_word`.
    """
    from . import menu, terminal
    if not found:
        widths = [terminal.cells(head) for head in STATUS_HEADERS]
        return terminal.table_row(STATUS_HEADERS, widths, "", ["dim"] * 6), []
    rows = []
    for directory, state in found:
        done = len(state.get("round_summaries") or [])
        total = state.get("rounds")
        going = state.get("state") in ("queued", "running")
        rnd = min(done + 1, total) if going and total else done
        rounds = f"round {rnd}/{total or '?'}"
        if state.get("extended"):
            rounds += f" (+{state['extended']})"
        rows.append([directory.name, state.get("title") or directory.name,
                     status_state_word(state, index),
                     f"{state.get('executor', '?')}/{state.get('reviewer', '?')}",
                     rounds,
                     resume_age(state) or terminal.format_age(menu.run_age_secs(state))])
    fixed = [2, 3, 4, 5]
    natural = [max([terminal.cells(row[i]) for row in rows] + [terminal.cells(STATUS_HEADERS[i])])
               for i in fixed]
    # natural is [state, worker, round, age]; the title takes what is left after
    # the id, which keeps whole ids where they fit and cuts the slug at a word
    # past that. The id is a machine token that --plain, --json and the detail
    # lines already carry whole, so the title keeps its floor first and the id
    # takes the rest: one long id never starves every title in the table.
    state_texts = [terminal.state_text(row[2]) for row in rows]
    natural[0] = max([terminal.cells(line) for line in state_texts] +
                     [terminal.cells(STATUS_HEADERS[2])])
    gutter = 2
    title_min = 20
    id_budget = max(15, width - sum(natural) - gutter * 5 - title_min)
    id_room = min(max([terminal.cells(row[0]) for row in rows]), id_budget)
    title_room = width - id_room - sum(natural) - gutter * 5
    narrow = title_room < 12
    first_room = max(1, width - id_room - gutter)
    widths = [id_room, max(1, title_room), natural[0], natural[1], natural[2], natural[3]]
    if narrow:
        header = terminal.table_row(STATUS_HEADERS[:2], [id_room, first_room], "",
                                    ["dim"] * 2)
    else:
        header = terminal.table_row(STATUS_HEADERS, widths, "", ["dim"] * 6)
    groups = []
    for row, line in zip(rows, state_texts):
        word = row[2]
        kind = terminal.state_colour(word)
        cell = status_id_cell(row[0], id_room)
        if not narrow:
            titled = terminal.title_lines(row[1], title_room)
            group = [terminal.table_row([cell, titled[0], line, row[3], row[4], row[5]],
                                        widths, "", [None, None, kind, None, None, None])]
            if len(titled) > 1:
                group.append(" " * (id_room + gutter) + titled[1])
        else:
            titled = terminal.title_lines(row[1], first_room)
            group = [terminal.table_row([cell, titled[0]], [id_room, first_room])]
            if len(titled) > 1:
                group.append(" " * (id_room + gutter) + titled[1])
            # the tail is measured plain and printed coloured: a cut never
            # touches a styled cell, and the state itself is never cut
            plain = [line, row[3], row[4], row[5]]
            if terminal.cells("  " + "  ".join(plain)) <= width:
                plain[0] = terminal.state_cell(word)
                group.append(("  " + "  ".join(plain)).rstrip())
            else:
                head, rest = plain[:2], plain[2:]
                head_line = "  " + "  ".join(head)
                if terminal.cells(head_line) > width:
                    over = terminal.cells(head_line) - width
                    head[1] = terminal.cut(head[1], max(1, terminal.cells(head[1]) - over))
                head[0] = terminal.state_cell(word)
                group.append(("  " + "  ".join(head)).rstrip())
                group.append(("  " + "  ".join(rest)).rstrip())
        groups.append(group)
    return header, groups


def status_details(directory, state, providers=None, cfg=None, index=None):
    """The lines indented under one status row: result, record, workspace,
    and -- where the run waits -- why it stopped and what reopens it.

    `providers` and `cfg` are one listing's usage cache and config, handed
    down so a waiting run's line does not re-read them per row; `index` is its
    `supersession_index`, so a blocked note wears the row's glyph.
    """
    paths = result_paths(directory, state)
    lines = [f"  result: {paths['result']}", f"  record: {paths['record']}",
             f"  limits: silence_minutes={state.get('silence_minutes', SILENCE_MINUTES):g}, "
             f"ceiling_hours={state.get('ceiling_hours', CEILING_HOURS):g}"]
    if state.get("workers") is not None:
        lines.append(f"  workers: {', '.join(state['workers'])}")
    if paths["workspace"]:
        location = workspace_location(state, paths["workspace_present"])
        lines.append(f"  workspace: {paths['workspace']} ({location})")
    if state.get("first"):
        lines.append("  first")
    stalled = stall_summary(state)
    if stalled:
        lines.append(f"  {stalled}")
    lines.extend(death_lines(state))
    if state.get("state") == "queued":
        lines.append(f"  {slot_note(state)}")
    elif merge_turn_note(state):
        lines.append(f"  {merge_turn_note(state)}")
    elif dep_wait_note(state):
        lines.append(f"  {dep_wait_note(state)}")
    elif gate_turn_note(state):
        lines.append(f"  {gate_turn_note(state)}")
    if needs_recovery(state):
        reason = recovery_reason(state)
        wait = waiting(state, providers=providers, cfg=cfg)
        # a run sitting out a provider window resumes itself: the lines say
        # what it waits for, never that the owner should reach for its number
        lines.append(f"  {reason}; {wait}" if wait else
                     f"  {reason}; ak run resume {directory.name} offers recovery")
    note = blocked_note(state, status_state_word(state, index))
    if note:
        from . import terminal
        lines.append("  " + terminal.styled(note, "dim"))
    parked = parked_line(state, directory.name)
    if parked:
        from . import terminal
        lines.append("  " + terminal.styled(parked, "dim"))
    if handback_waiting(state):
        from . import terminal
        lines.append("  " + terminal.styled(handback_waiting(state), "dim"))
    living, ended = alive_line(state), stop_note(state)
    if living or ended:
        from . import terminal
        if living:
            lines.append("  " + terminal.styled(living, "dim"))
        if ended:
            lines.append("  " + terminal.styled(ended, "dim"))
    onward = continue_line(state, directory)
    if onward:
        lines.append(f"  {onward}")
    return lines


def size_summary_line(repo):
    """One line per repository for `ak run status --history`: median rounds overall,
    over long tasks and over many-pointed ones, so the orchestrator sizes the next task
    from what this repository's last twenty actually took."""
    summary = history.size_summary(repo)
    if summary is None:
        return None

    def med(value):
        return f"median {value:g} rounds" if value is not None else "–"

    overall, words, points = summary
    return (f"{repo}: last 20 tasks: {med(overall)} · over 400 words: {med(words)} · "
            f"over 3 points: {med(points)}")


def cmd_status(argv):
    show_history, machine = "--history" in argv, "--json" in argv
    plain, why = "--plain" in argv, "--why" in argv
    pending = "--pending" in argv
    args = [arg for arg in argv
            if arg not in ("--history", "--json", "--plain", "--why", "--pending")]
    if len(args) > 1 or any(arg.startswith("-") for arg in args):
        raise config.Error(
            "usage: ak run status [ID] [--history] [--why] [--plain] [--json] [--pending]")
    wanted = args[0] if args else None
    jobs = [(d, read_job(d)) for d in job_dirs()]
    jobs = [(d, job) for d, job in jobs if job and isinstance(job.get("tasks"), list)]
    from . import menu
    # Whether a run was superseded asks every record, whichever run or job is shown, but
    # never the smoke suite's own, as on the menu.
    index = None if machine else supersession_index(
        state for state in map(read_state, run_dirs()) if state and not menu.smoke_run(state))
    if wanted:
        for directory, job in jobs:
            if directory.name == wanted:
                if machine:
                    print(json.dumps({**job, "paths": {
                        "record": str(directory / "job.json"),
                        "logs": str(directory / "log.txt")}}, indent=2))
                    return 0
                print(host_status_line())
                alive = reap_job(directory, job)
                shown = job_now(job, alive, report_config(), index)
                print(job_block_line(shown))
                if not alive:
                    print(job_gone_line(directory, job))
                for task in shown["tasks"]:
                    line = f"  {task['name']} {task['state']} {task.get('run_id') or '-'}"
                    if task.get("verdict_line"):
                        line += f"  {task['verdict_line']}"
                    print(line)
                print(f"  record/log: {directory}/job.json {directory}/log.txt")
                return 0
    dirs = run_dirs()
    if wanted:
        dirs = [d for d in dirs if d.name == wanted]
        if not dirs:
            raise config.Error(f"no such run: {wanted} (looked in {config.RUNS})")
        # Showing an ending by id marks it looked at. A scheduled error is still
        # working: inspecting its retry does not acknowledge the ending.
        looked = set()
        for single in dirs:
            try:
                if mark_looked_at(single):
                    looked.add(single)
            except (OSError, ValueError):
                pass
    if not machine:
        # The header reads the live host, so it prints only once the target
        # resolved: an unknown id errors without any host inspection.
        print(host_status_line())
    found, hidden = [], 0
    for directory in dirs:
        state = read_state(directory)
        # the smoke suite's own runs are the toolkit testing itself, as on the menu;
        # naming one by id still shows it
        if state and not wanted and menu.smoke_run(state):
            continue
        state = reap(directory, state) if state else {"run_id": directory.name,
                                                     "state": "unreadable"}
        if wanted and not machine and directory in looked:
            # the look that just acknowledged an ending still shows it as it found it
            state = {**state, "recovery_acknowledged_at": None}
        # An admitted error or merge wait still belongs to the tick. Once admission
        # ends it ages out of the listing like any other ending, stale stamp or not.
        live = going(state) and state.get("state") in ("waiting", "error")
        if (not wanted and not show_history and state.get("state") not in ("running", "queued", "stalled",
                                                                  "unreadable")
                and not actionable(state) and not live and
                time.time() - (state.get("finished_at") or state.get("started_at") or 0) > GC_AGE):
            hidden += 1
            continue
        found.append((directory, state))
    if pending:
        found = [(d, s) for d, s in found if handback_waiting(s)]
    found.sort(key=status_key, reverse=True)
    if machine:
        rows = []
        for directory, state in found:
            row = history.get(state.get("run_id") or directory.name) or {}
            rows.append({**row, **state, "paths": result_paths(directory, state)})
        print(json.dumps(rows, indent=2))
        return 0
    shown_jobs = 0
    if not wanted:
        now = time.time()
        job_cfg = report_config() if jobs else None
        for directory, job in sorted(jobs, key=lambda pair: pair[1].get("started_at") or 0,
                                     reverse=True):
            finished = job.get("finished_at")
            # finished jobs older than the run history window are history, like old runs
            if not show_history and isinstance(finished, (int, float)) and now - finished > GC_AGE:
                continue
            alive = reap_job(directory, job)
            shown = job_now(job, alive, job_cfg, index)
            print(job_block_line(shown))
            if not alive:
                print(job_gone_line(directory, job))
            for task in shown["tasks"]:
                if task.get("verdict_line"):
                    print(f"  {task['verdict_line']}")
            shown_jobs += 1
    if not found and not shown_jobs:
        print(f"no current runs in {config.RUNS}")
    if plain:
        # Read one config for the delivery and waiting words; only waiting needs usage.
        plain_cfg = report_config()
        plain_providers = (_cached_providers() if any(
            state.get("state") == "exhausted" for _, state in found) else {})
        # a `waiting_login` row names its harness out of run.json and reads no meters
        for d, state in found:
            word = state.get("state", "?")
            if word == "queued":
                word = "waiting"
            if word in ("exhausted", "waiting_login"):
                # the run waits for a provider window or a login; both lift by themselves,
                # and the drill-down keeps the state word
                word = waiting_word(state, providers=plain_providers, cfg=plain_cfg)
            line = (f"{d.name:<40} {word:<11} {str(state.get('verdict')):<5} "
                    f"{executor_line(state)}/{state.get('reviewer', '?')}  "
                    f"{state.get('branch') or 'scratch'}")
            outcome, step = status_word(state, plain_cfg), step_word(state)
            if state.get("extended"):
                line += (f"  round {len(state.get('round_summaries') or [])}/{state['rounds']} "
                         f"(+{state['extended']})")
            stalled = stall_summary(state)
            if stalled:
                line += f"  {stalled}"
            if needs_recovery(state):
                line += f"  {recovery_reason(state)}; ak run resume {d.name} offers recovery"
            if state.get("state") == "blocked":
                line += f"  blocked: {' '.join((state.get('error') or '').split())}"
            if state.get("pr"):
                line += f"  {outcome} {state['pr']}"
            elif outcome:
                line += f"  {outcome}"
            if step:
                line += f"  {step}"
            resumed = resume_age(state)
            if resumed:
                line += f"  {resumed}"
            waiting = handback_waiting(state)
            if waiting:
                from . import terminal as _terminal
                line += f"  {_terminal.styled(waiting, 'dim')}"
            print(line)
            if state.get("state") == "queued":
                print(f"  {slot_note(state)}")
            elif merge_turn_note(state):
                print(f"  {merge_turn_note(state)}")
            elif dep_wait_note(state):
                print(f"  {dep_wait_note(state)}")
            elif gate_turn_note(state):
                print(f"  {gate_turn_note(state)}")
            if state.get("first"):
                print("  first")
            living, ended = alive_line(state), stop_note(state)
            if living or ended:
                from . import terminal as _terminal
                if living:
                    print("  " + _terminal.styled(living, "dim"))
                if ended:
                    print("  " + _terminal.styled(ended, "dim"))
            if why:
                print(f"  limits: silence_minutes={state.get('silence_minutes', SILENCE_MINUTES):g}, "
                      f"ceiling_hours={state.get('ceiling_hours', CEILING_HOURS):g}")
            paths = result_paths(d, state)
            print(f"  result: {paths['result']}  record/logs: {d}")
            if paths["workspace"]:
                location = workspace_location(state, paths["workspace_present"])
                print(f"  workspace: {paths['workspace']} ({location})")
            for death in death_lines(state):
                print(death)
            onward = continue_line(state, d)
            if onward:
                print(f"  {onward}")
    else:
        from . import terminal
        header, groups = status_rows(found, terminal.content_width(), index)
        if wanted or why:
            # one id, or every run with --why: each run's lines indented under
            # its own row, never in one block after the table. The usage cache
            # and the config are read once for the waiting lines, never per
            # row -- and nothing is read when no run waits. With no rows there
            # is no header either: `no current runs` above is the whole answer.
            if any(needs_recovery(state) for _, state in found):
                try:
                    scope_cfg = config.load()
                except config.Error:
                    scope_cfg = None
                scope_providers = _cached_providers()
            else:
                scope_cfg, scope_providers = None, {}
            if groups:
                print(header)
            for (directory, state), group in zip(found, groups):
                print("\n".join(group))
                for line in status_details(directory, state, scope_providers, scope_cfg,
                                           index):
                    print(line)
        elif found:
            print(header)
            for (directory, state), group in zip(found, groups):
                print("\n".join(group))
                parked = parked_line(state, directory.name)
                if state.get("state") == "queued":
                    print(f"  {slot_note(state)}")
                elif merge_turn_note(state):
                    print(f"  {merge_turn_note(state)}")
                elif dep_wait_note(state):
                    print(f"  {dep_wait_note(state)}")
                elif gate_turn_note(state):
                    print(f"  {gate_turn_note(state)}")
                elif blocked_note(state):
                    word = status_state_word(state, index)
                    print("  " + terminal.styled(blocked_note(state, word), "dim"))
                elif handback_waiting(state):
                    print("  " + terminal.styled(handback_waiting(state), "dim"))
                elif parked:
                    print("  " + terminal.styled(parked, "dim"))
                if state.get("first"):
                    print("  first")
                living, ended = alive_line(state), stop_note(state)
                if living:
                    print("  " + terminal.styled(living, "dim"))
                if ended:
                    print("  " + terminal.styled(ended, "dim"))

    if not wanted:
        print(f"{hidden} older run(s) hidden; ak run status --history [--json] shows full history")
    if show_history and not wanted and not machine:
        for repo in history.finished_repos():
            line = size_summary_line(repo)
            if line:
                print(line)
        for line in history.role_lines():
            print(line)
    return 0


def cmd_clean(argv):
    if len(argv) != 1:
        raise config.Error("usage: ak run clean <runid>")
    run_dir = config.RUNS / argv[0]
    if not (run_dir / "run.json").exists():
        raise config.Error(f"no such run: {argv[0]} (looked in {config.RUNS})")
    state = read_state(run_dir)
    if state is None:
        raise config.Error(f"{argv[0]}: cannot read {run_dir / 'run.json'}")
    if state.get("scratch"):
        workspace = state.get("worktree")
        if not isinstance(workspace, str) or not Path(workspace).is_dir():
            print(f"{argv[0]}: its workspace is gone; result.md lists what was there")
            return 0
        print(f"{argv[0]}: ran in the scratch workspace {workspace}; its files are "
              "the deliverable, so nothing is removed")
        return 0
    repo, worktree = state.get("repo"), state.get("worktree")
    if not repo or not worktree:
        raise config.Error(f"{argv[0]}: run.json records no worktree; nothing to remove")
    wt = Path(worktree)
    if wt == Path(repo):
        print(f"{argv[0]}: ran with --no-worktree; nothing to remove")
        return 0
    code, out = git_out(repo, "worktree", "remove", "--force", str(wt))
    if code != 0 and wt.exists():
        raise config.Error(f"could not remove worktree {wt}: {out}")
    git(repo, "worktree", "prune", check=False)
    print(f"{argv[0]}: removed worktree {wt}; branch {state.get('branch', '?')} kept")
    return 0


def marker_pids(run_id):
    """Pids still carrying this run's marker in their environment, except this process.

    Every worker turn and done-when command runs with `AK_PARENT_RUN` set to the run
    that started it -- see `run_child_env` -- so a child that outlived its parent, or
    was reparented away from the loop's own tree, still names the run it belongs to.
    """
    found = []
    me = os.getpid()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me or pid <= 0:
            continue
        try:
            env = (entry / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        needle = f"AK_PARENT_RUN={run_id}".encode()
        if needle in env:
            found.append(pid)
    return found


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
    return isinstance(state, dict) and state.get("state") in ENDED and pid_gone(state)


def session_lives(name):
    """Whether that seat still exists: its record, or a tmux session under the name.

    A missing or unreadable name is not proof the seat is gone. `None` — a run
    nobody's seat launched — is not a living session.
    """
    if not isinstance(name, str) or not name:
        return False
    try:
        if config.session_path(name).exists():
            return True
    except config.Error:
        return True
    try:
        return orch.find(name) is not None
    except (config.Error, OSError, TypeError, ValueError):
        return True


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
    if not git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        return
    try:
        code, out = git_out(repo, "branch", "-D", branch)
    except Stopped as exc:
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
        return bool(needs_recovery(state) or failed_at_budget(state)
                    or failed_in_integration(state, run_dir)
                    or judged_in_integration(state, run_dir))
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
    if state.get("merged"):
        drop_checkout(state, log)
        return
    if state.get("state") in ("fail", "error", "blocked", "stopped"):
        if resume_holds_tree(state, run_dir):
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
    unless a resume can still take it, which holds the checkout for the
    seven-day clock -- and keeps its branch, the only copy a run that never
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
    if state.get("merged"):
        drop_checkout(state, log)
        return
    if (state.get("state") in ("fail", "error", "blocked", "stopped")
            and already_handed_back(state) and not resume_holds_tree(state, run_dir)):
        drop_checkout(state, log)


def stop_owned_runs(name):
    """Stop every unfinished run this seat launched, the way `ak run stop` stops one.

    The first half of a seat stop, run before the seat's lock: each run costs up
    to STALL_KILL_WAIT inside kill_tree, and nothing it touches is the seat's
    state. A run that refuses is named and left; the seat still ends.
    """
    try:
        dirs = run_dirs()
    except OSError:
        return
    for run_dir in dirs:
        try:
            state = read_state(run_dir)
        except (OSError, ValueError):
            continue
        if not state:
            continue
        try:
            if launched_session(state) != name:
                continue
        except config.Error:
            continue
        if state.get("state") not in ENDED:
            try:
                cmd_stop([run_dir.name])
            except config.Error as exc:
                print(f"could not stop {run_dir.name}: {exc}")
            except (OSError, ValueError, KeyError, TypeError):
                print(f"could not stop {run_dir.name}")


def release_session(name):
    """Stop every unfinished run this seat launched, and drop every checkout it still owns.

    Run directories stay for their results. Browser tabs the seat or those runs
    opened close here; a tab with no recorded opener is not theirs to close.
    The branches go with the checkouts: ending the seat is the deliberate stop
    that takes everything connected to it.
    """
    from . import browser
    stop_owned_runs(name)
    ids = []
    try:
        dirs = run_dirs()
    except OSError:
        dirs = []
    for run_dir in dirs:
        try:
            state = read_state(run_dir)
        except (OSError, ValueError):
            continue
        if not state:
            continue
        try:
            if launched_session(state) != name:
                continue
        except config.Error:
            continue
        ids.append(run_dir.name)
        if state.get("state") in ENDED:
            if not drop_checkout(state, lambda _message: None, keep_branch=False):
                continue
            # the branch went with the checkout: the status row reads this mark,
            # since only a stop without `--keep` says so on its own
            try:
                with recovery_lock(run_dir):
                    current = read_state(run_dir) or state
                    current["branch_removed"] = True
                    save_state(run_dir, current)
            except (OSError, ValueError, TypeError):
                pass
    try:
        browser.close_owned(session=name, runs=ids)
    except (OSError, ValueError, TypeError):
        pass


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
    try:
        code, out = git_out(repo, "worktree", "remove", "--force", str(wt))
    except Stopped as exc:
        log(f"WARN could not remove worktree {wt}: {exc}")
        return False
    if code != 0 and wt.exists():
        log(f"WARN could not remove worktree {wt}: {out}")
        return False
    git(repo, "worktree", "prune", check=False)
    if not keep_branch:
        drop_local_branch(repo, branch, log)
    return True


def stop_line(run_id, branch, kept):
    """The one line a stop prints: what ended, and -- when kept -- the `from:` line.

    The `from:` line is only advertised while its branch exists to relaunch from;
    a removed branch leaves the run's name on the line and nothing unusable after it.
    """
    if not branch:
        return f"stopped {run_id}"
    if not kept:
        return f"stopped {run_id}: branch {branch} removed"
    return f"stopped {run_id}: branch {branch} kept; relaunch with from: {branch}"


def cmd_stop(argv):
    """End a run deliberately: its record first, then its loop and its checkout.

    The record goes first -- `stopped`, committed under the lock -- so a scheduler
    that notices its dead child finds the stop already there and aborts instead of
    replacing it.  Then the loop and everything it started: its systemd scope where
    one exists, else its process tree by the run's pid and its `AK_PARENT_RUN`
    marker.  The run reads `stopped`, a final state that is never resumed, never
    handed back and never cards anyone.  The worktree and the local branch go with
    it unless `--keep` keeps them for a relaunch from the printed `from:` line.
    """
    keep = "--keep" in argv
    args = [arg for arg in argv if arg != "--keep"]
    if len(args) != 1 or Path(args[0]).name != args[0] or args[0] in (".", ".."):
        raise config.Error("usage: ak run stop ID [--keep]")
    run_id = args[0]
    run_dir = config.RUNS / run_id
    if not (run_dir / "run.json").exists():
        raise config.Error(f"no such run: {run_id} (looked in {config.RUNS})")
    state = read_state(run_dir)
    if state is None:
        raise config.Error(f"{run_id}: cannot read {run_dir / 'run.json'}")
    if state.get("state") == "stopped":
        print(stop_line(run_id, state.get("branch"), state.get("stop_kept", False)))
        return 0
    # `error` reads ended but the tick retries it hourly: stopping one is its
    # owner's off-switch for the ladder, the way stopping a waiting run ends
    # its wait.  Every other ending sits inert, so there is nothing to stop.
    if state.get("state") in ENDED and state.get("state") != "error":
        raise config.Error(f"{run_id} is already {state.get('state')}; "
                           "only unfinished work can be stopped")
    log = note_in(run_dir / "log.txt")
    with recovery_lock(run_dir):
        current = read_state(run_dir) or state
        if current.get("state") == "stopped":
            print(stop_line(run_id, current.get("branch"),
                            current.get("stop_kept", False)))
            return 0
        if current.get("state") in ENDED and current.get("state") != "error":
            raise config.Error(f"{run_id} is already {current.get('state')}; "
                               "only unfinished work can be stopped")
        kept = bool(keep or not checkout_removable(current))
        current.update(state="stopped", verdict="STOPPED", finished_at=time.time(),
                       error="stopped by the user", reported=True, stop_kept=kept)
        for key in ("recovery_pending", "recovery_notified", "recovery_acknowledged_at",
                    "handback_pending", "handback_wait_reason", "handback_note",
                    "notification_pending", "pending_inbox", "quota_dry", "refusal_retry",
                    "waiting_for", "login_resume_at", "login_back_at", "stall_resume_at",
                    "resume_after", "error_retry_at", "error_retries", "waiting_on",
                    "waiting_resume_at", "slot_waiting", "launch_pending", "resume_from"):
            current.pop(key, None)
        save_state(run_dir, current)
        history_finish(current, log)
        try:
            refresh_seat_tally(launched_session(current))
        except config.Error:
            pass
        try:
            record_result(run_dir, current, log)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        state = current
    # The scope where one exists, else the tree by the run's marker -- in practice both,
    # so a scope that refused to stop still loses its processes, and a plain start loses
    # nothing by the scope attempt missing.  The record already says stopped, so whatever
    # notices the dead children aborts instead of replacing them.
    if orch.user_manager():
        unit = f"agentkit-run-{run_id}"
        for suffix in (".scope", ".service"):
            try:
                subprocess.run(["systemctl", "--user", "stop", f"{unit}{suffix}"],
                               capture_output=True, encoding="utf-8", errors="replace",
                               env=orch.bus_env(), timeout=orch.SLICE_WAIT)
            except (OSError, subprocess.SubprocessError):
                pass
    pid = state.get("pid")
    # Only a run of its own is ended by its tree: a task whose pid is still its live
    # scheduler's is ended by its marker below, and a task resumed by hand -- a new
    # pid under an old stamp -- is ended by its tree like any run of its own.
    if not job_scheduler_owns(run_id, state) and isinstance(pid, int) and pid > 0 \
            and pid != os.getpid() and process_active(state):
        try:
            watch.kill_tree(pid, log)
        except (OSError, ValueError):
            pass
    for member in marker_pids(run_id):
        try:
            watch.kill_tree(member, log)
        except (OSError, ValueError):
            pass
    if not keep and not stop_checkout(state, log):
        # The checkout is still there -- a live loop, or a git that said no --
        # so the branch stays with it, and the record says kept: `from:` carries
        # that committed work into a relaunch the same way `--keep` does. Read
        # back under the lock: the dict above predates the kill by whole seconds.
        state["stop_kept"] = True
        try:
            with recovery_lock(run_dir):
                current = read_state(run_dir) or state
                current["stop_kept"] = True
                save_state(run_dir, current)
        except (OSError, ValueError, TypeError):
            pass
    try:
        from . import browser
        browser.close_owned(run=run_id)
    except (OSError, ValueError, TypeError):
        pass
    log(f"stopped {run_id}")
    print(stop_line(run_id, state.get("branch"), state.get("stop_kept", False)))
    return 0


def queued(run_dir):
    """The background launch receipt, possibly already holding its slot."""
    try:
        with recovery_lock(run_dir):
            state = json.loads((run_dir / "run.json").read_text())
            return (state.get("state") == "queued" or
                    (state.get("state") == "running" and state.get("pid") == os.getpid()
                     and state.get("slot_waiting") is False))
    except (OSError, ValueError, AttributeError):
        return False


def spawn_bg(run_dir, argv, expected=None):
    log_path = run_dir / "log.txt"
    env = dict(os.environ, **{config.RUN_DIR_ENV: str(run_dir)})
    child = [sys.executable, str(config.REPO / "bin" / "ak"), "run"] + [a for a in argv if a != "--bg"]
    with slot_lock(), recovery_lock(run_dir):
        previous = read_state(run_dir) or {}
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
                 "slot_waiting": not claimed, "launch_pending": True, **process_owner()}
        state.setdefault("scope", None)
        state.setdefault("run_depth", run_depth())
        if previous.get("state") != "queued":
            state.pop("slot_waited", None)
        env["AK_RUN_DEPTH"] = str(state["run_depth"])
        if argv[:1] == ["resume"]:
            state["resume_from"] = previous.get("resume_from") or (
                "interrupted" if previous.get("state") == "queued" else previous["state"])
        save_state(run_dir, state)
        try:
            unit = f"agentkit-run-{run_dir.name}"
            if (previous.get("scope") and
                    str(previous.get("scope")) not in ("none",) and
                    not str(previous.get("scope")).startswith("none (") and
                    not (config.TMP / f"{unit}.placed").exists()):
                unit = orch.next_scope_unit(unit)
            # Into agentkit's slice, like every other agent process: a run started from a seat
            # is already inside it, and one started from the owner's own shell -- or by a tick
            # from cron -- would otherwise be the one heavy thing on the machine with no
            # ceiling over it.  The pid that comes back is the one really doing the work.
            placement = {}
            cap, properties = run_scope_limits()
            pid = orch.start_in_slice(
                child, unit, env, log_path,
                log=note_in(log_path), target_slice=orch.run_slice_name(),
                properties=properties,
                nice=True, placement=placement)
            # The child waits on this lock before adopting the receipt. The parent can never
            # overwrite a running child's state, and reaping sees the child, not its launcher.
            state.update(process_owner(pid), scope=placement.get("scope"),
                         scope_reason=placement.get("scope_reason"))
            remember_memory_cap(state, placement, cap)
            state["launch_pending"] = False
            state.pop("reservation_pending", None)
            save_state(run_dir, state)
            update_scope_line(run_dir, state)
        except (OSError, config.Error) as exc:
            reason = f"Could not launch the run: {exc}"
            if (previous.get("reservation_pending") and
                    previous.get("pid") == os.getpid()):
                state = interrupt(previous, reason)
            elif previous.get("slot_waiting"):
                state = {**previous, "pid": None, "process_identity": None,
                         "launch_pending": False, "launch_error": reason}
            else:
                state = interrupt(previous, reason)
            save_state(run_dir, state)
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


def logger(run_dir, to_file):
    def log(message):
        line = f"[{datetime.now():%H:%M:%S}] {message}"
        print(line, flush=True)
        if to_file:   # the --bg child's stdout already is log.txt; writing again would double it
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(line + "\n")
    return log


def launch_session(run_dir):
    """The owner captured by the parent before preflight, including an explicit no-seat."""
    state = read_state(run_dir) or {}
    return (state["launched_session"] if "launched_session" in state else
            config.current_session())


def capture_launch(run_dir, opts=None, job_id=None, cfg=None, task_file=None):
    """The owner, and whether anybody owns this launch at all.

    `unattended` is the run nobody started: no seat, and no terminal either, because a worker
    or a done-when command below another run started it.  Nothing is told about it and the
    menu does not offer it -- `ak run status` has it, though never the smoke suite's own runs.

    The session's worker list goes on the receipt here too, when there is a session: what
    it holds at this launch is the list every later pick for this run may use
    (`run_workers`), however the record moves afterwards and whichever seat the process
    doing a later pick speaks for.  A run from no seat has no list to bind to.

    A job names itself here, in the same write as the scheduler pid the receipt
    records: the scheduler only writes `task["run_id"]` after preflight, and a stop
    in between must still recognise one of its tasks and spare the scheduler.

    The task file it was launched from goes on too, because the run keeps only a copy:
    where the file lives is what files a scratch run's seat under a project (`run_project`).
    """
    session_at_launch = config.current_session()
    workers = config.workers(cfg) if cfg is not None and session_at_launch else None
    limit = config.max_runs()
    with slot_lock():
        state = stamp_origin({"run_id": run_dir.name, "state": "queued", "verdict": None,
                         "launched_session": session_at_launch, "started_at": time.time(),
                         "queued_at": time.time(), "slot_waiting": True,
                         "run_depth": run_depth(), "parent_run": os.environ.get("AK_PARENT_RUN"),
                         "reservation_pending": True,
                         "unattended": not session_at_launch and config.unattended(),
                         **process_owner(), "launch_opts": opts or {},
                         **({"workers": workers} if workers else {}),
                         "review_pr": (opts or {}).get("--review-pr"), "reported": False})
        if job_id is not None:
            state["job_id"] = job_id
        if task_file is not None:
            state["task_file"] = str(task_file)
        if (opts or {}).get("--first"):
            state["first"] = True
        claim_slot(state, limit)
        # Steadiness is counted by the waiter's own polls, not banked here: the
        # launch check only records an early reason, and admission still needs
        # two consecutive healthy polls from the waiter itself.
        state.pop("slot_healthy_polls", None)
        save_state(run_dir, state)
    history_start(state)
    refresh_seat_tally(session_at_launch)   # the seat's bar counts it from the start


def launch_line(run_id, title, executor, reviewer):
    """The one line a launch from a seat puts on the seat's terminal.

    A review-only run has no executor, so it names its reviewer instead of a pair;
    every other launch names both models.  One builder, every launch path.
    """
    models = f"{executor}/{reviewer}" if executor else f"{reviewer} review"
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
        workers = run_workers(cfg, read_state(run_dir) or {})
        try:
            executor, reviewer = pick_models(cfg, providers, opts["--exec"], opts["--review"],
                                             log, quiet=True, workers=workers)
        except QuotaDry:
            refusal = pair_refusal(cfg, providers, workers, opts["--exec"], opts["--review"])
            if not refusal:
                raise
            raise config.Error(refusal) from None
    except config.Error as exc:
        refused(run_dir, exc, log, cfg)
        raise
    except Exception:  # noqa: BLE001 - the child reproduces any real failure itself
        return None, None
    save_state(run_dir, {**(read_state(run_dir) or {}),
                         "launch_executor": executor, "launch_reviewer": reviewer})
    return executor, reviewer


def preset_review_model(cfg, opts, workers=None):
    """The reviewer for a --review-pr launch, picked in the parent, or None.

    Same shape as the pick inside review_pr, minus the checkout the parent has not
    done: an explicit --review, else the first reviewer in the order.  A bare None
    means the child picks exactly as it always did; an explicit one that cannot run is
    refused here.
    """
    try:
        providers = collect_usage(cfg)
        order = reviewer_order(cfg, None, ready_order(
            cfg, providers, workers, role="reviewer", quiet=True))
        if not opts["--review"]:
            return order[0] if order else None
        config.model(cfg, opts["--review"])
    except Exception:  # noqa: BLE001 - the child reproduces any real failure itself
        return None
    refuse_unready(cfg, providers, opts["--review"])
    return opts["--review"]


def refused(run_dir, exc, log, cfg):
    """A launch its parent refuses ends as a refused preflight does: recorded and told."""
    state = mark_state(run_dir, "error", str(exc), log)
    record_result(run_dir, state, log, cfg)
    announce_safely(state, run_dir, log, cfg)


def prepare(run_dir, opts, log, cfg=None, job_id=None, task_file=None):
    capture_launch(run_dir, opts, job_id, cfg, task_file)
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
        state = read_state(run_dir) or {}
        state["title"] = f"Review PR #{number}: {info['title']}"
        save_state(run_dir, state)
        repo, base, target = f"{owner}/{name}", info["baseRefName"], info["baseRefName"]
        method, action = "none (review only)", f"review {url} at {info['headRefOid']}; publish findings"
        commands = "AGENTS.md tests: command from the PR checkout, if declared"
    else:
        meta, body, title = parse_task(run_dir / "task.md")
        state = read_state(run_dir) or {}
        state["title"] = title
        save_state(run_dir, state)
        every, once = done_when_groups(body, run_dir / "task.md")
        commands = " ; ".join(every)
        if once:
            commands += f"{' ; ' if commands else ''}once: {' ; '.join(once)}"
        repo = task_repo(meta, run_dir / "task.md")
        # What this run will deliver, settled before it ever waits for a slot: a scratch task
        # and `--no-merge` both push nothing, and the receipt is read long before the loop
        # writes the same answer into the full state -- `ak watch` reads it to know which
        # seats a logged-out gh is holding up.  So is the project its seat is filed under, the
        # same queued and once it works (`run_project`), and the seat is filed now.  Resolved
        # here because only the process that launched the run stands in the checkout the task
        # inherits when it names none, or the one a relative `repo:` means.
        checkout = task_project(repo if meta.get("repo") else None, state.get("task_file"))
        save_state(run_dir, {**(read_state(run_dir) or {}),
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
                                       done_when(body, run_dir / "task.md"),
                                       exclude=run_dir)
            alongside = rivals[0]["id"] if rivals else None
    log("--- preflight")
    if alongside:
        log(f"--- preflight: started alongside {alongside} (--anyway)")
    log(f"repo: {repo or 'none (scratch)'} | base: {base} | target: {target} | merge: {method}")
    log(f"delivery: {action}")
    log(f"done-when: {commands}")
    if state.get("workers") is not None:
        log(f"workers: {', '.join(state['workers'])}")
    log(f"limits: silence {state['silence_minutes']:g}m | "
        f"done-when ceiling {state['ceiling_hours']:g}h | git/gh {TOOL_CAP}s")
    scope = state.get("scope")
    if scope == "none":
        scope = f"none ({state.get('scope_reason') or 'plain process session'})"
    log(f"scope: {'pending' if opts.get('--bg') and not scope else scope or 'none (foreground launch)'}")
    log(f"result: {run_dir / 'result.md'} | log: {run_dir / 'log.txt'}")
    session = launch_session(run_dir)
    if url:
        log(f"notification: verdict on GitHub; PASS with green checks offered to {watch.inbox()} "
            "and needs to Discord (stderr if unconfigured)")
    else:
        log(f"notification: {session}; dead-seat fallback: needs to Discord if that seat is gone "
            "at the end (stderr if unconfigured)" if session else
            "notification: none: no orchestrator session launched this run, so nothing is sent; "
            "the result is here and in `ak run status`")


def update_scope_line(run_dir, state):
    """Append the detached placement after it starts, without racing its live log writer."""
    scope = state.get("scope")
    if scope == "none":
        scope = f"none ({state.get('scope_reason') or 'plain process session'})"
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
        refresh_seat_tally(launched_session(state))   # the ending lands on the bar too
    except config.Error:
        pass
    announce(state, run_dir, log, cfg)
    history_finish(state, log)
    settle_run(read_state(run_dir) or state, run_dir, log)
    if state["state"] == "error":
        log(f"FAIL -> {run_dir / 'result.md'} (error)")
        return 2
    cfg = report_config(cfg)
    log(f"{delivery(state, cfg)} -> {run_dir / 'result.md'}")
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
    with recovery_lock(run_dir) if run_dir.is_dir() else nullcontext():
        state = read_state(run_dir)
    if state is not None:
        # a finished PASS waits on no window: a quota mark left over from an earlier
        # stop is stale by definition, so a delivery retry that exhausts cannot
        # inherit it.
        state.pop("quota_dry", None)
    if not state or state.get("verdict") != "PASS" or state.get("state") != "pass":
        raise config.Error(f"{argv[0]}: merge requires a finished PASS")
    if (state.get("review_pr") or state.get("scratch")
            or not (state.get("pr") or state.get("merge_failed"))):
        raise config.Error(f"{argv[0]}: no delivery PR to merge")
    cfg = config.load()
    if not review_pass(state, cfg):
        raise config.Error(f"{argv[0]}: merge requires a successful reviewer allowed by the model policy; "
                           f"run ak run resume {argv[0]} to obtain review")
    log = logger(run_dir, True)
    if state.get("merged"):
        log(delivery(state, cfg))
        return 0
    head = state.get("delivery_sha")
    if state.get("pr") and not head:
        raise config.Error(f"{argv[0]}: no recorded delivery SHA; cannot safely retry the merge")
    _, body, _ = parse_task(run_dir / "task.md")
    cmds = with_suite(done_when(body, run_dir / "task.md"), state["worktree"],
                      state.get("target") or state.get("base"))
    body += project_lessons(state.get("repo") or None, state, log)
    lp = Loop(cfg, run_dir, state, {}, log, Path(state["worktree"]),
              body, cmds, f"Repo checkout: {state['worktree']}\n\n{body}", [])
    stopped_on = state.get("merge_note") or "delivery did not finish"
    # This process owns the run while it delivers: a retry that is killed here must leave a
    # `running` receipt with this pid on it, so the reaper -- the menu, `ak run status` or the
    # watch tick -- marks it interrupted, rather than a finished PASS with its failure cleared
    # off and nobody to pick it up.  The step is what `ak run status` shows while it works.
    state.update(state="running", merge_failed=False, merge_note=None, on_target=False,
                 reported=False, finished_at=None, **process_owner())
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
            upstream = lp.target if lp.target.startswith("origin/") else f"origin/{lp.target}"
            if info is None:
                log(f"no delivery PR: {stopped_on}; delivering again from integration")
                merge(lp)
            else:
                # the delivered head was final-checked and pushed already; only a new one owes it
                land(lp, upstream,
                     lambda: (integrate(lp, upstream)
                              and (git(lp.wt, "rev-parse", "HEAD") == head
                                   or final_check(lp, upstream))),
                     lambda: ((git(lp.wt, "rev-parse", "HEAD") == head or push(lp))
                              and wait_checks(lp, state["pr"])
                              and do_merge(lp, state["pr"], upstream)))
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
        state.update(state="exhausted", error=str(exc))
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
            state.update(state="exhausted", error=str(exc))
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
    state["finished_at"] = time.time()
    save_state(run_dir, state)
    write_result(run_dir, state, cmds, log, cfg)
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
            with recovery_lock(directory):
                state = read_state(directory) or {}
                if (state.get("state") == "queued" and state.get("slot_waiting") and
                        state.get("pid") == os.getpid()):
                    # the ending is announced from here on, and a hand-back naming a
                    # result.md nothing wrote -- or the attempt before this one's -- is no
                    # hand-back: the reason goes in the file before anything reads it
                    state = mark_state(directory, "error", str(exc))
                    record_result(directory, state, logger(directory, True))
                stop_run_tree(state)
        raise


def resume_run(argv):
    ids = [arg for arg in argv if not arg.startswith("-") and arg != "--bg"]
    if ids and (config.JOBS / ids[0] / "job.json").exists():
        result = cmd_job_resume(argv)
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
    refusal = rounds_refusal(n_rounds, "--rounds")
    if refusal:
        raise config.Error(refusal)
    config.ensure_dirs()
    run_dir = config.RUNS / argv[0]
    state = read_state(run_dir) if (run_dir / "run.json").exists() else None
    if state is None:
        raise config.Error(f"no resumable run: {argv[0]} (looked in {config.RUNS})")
    # spawn_bg has already handed this queued receipt to this particular child. Ordinary
    # invocations must never adopt another process's launch, even with an inherited variable.
    with recovery_lock(run_dir):
        state = read_state(run_dir)
    child = (os.environ.get(config.RUN_DIR_ENV) == str(run_dir) and
             state.get("state") == "queued" and state.get("resume_from") and
             state.get("pid") == os.getpid() and process_active(state))
    if not child and state.get("state") in ("running", "queued"):
        if process_active(state):
            raise config.Error(f"{argv[0]} is still running as pid {state['pid']}")
        state = reap(run_dir, state)
    if state.get("state") == "blocked":
        # The task itself is what failed, so there is nothing here to carry on: another
        # round would spend a model turn to be told the same thing again.
        raise config.Error("blocked runs are not resumed; the orchestrator writes a new task")
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
    if at_budget and state["rounds"] >= TASK_MAX_ROUNDS:
        # the whole budget is spent: no --rounds carries it on, so the task is what changes
        raise config.Error(f"{argv[0]} FAILed at its round budget ({state['rounds']}); "
                           f"{TASK_MAX_ROUNDS} rounds is the budget, so split or re-scope the task")
    if at_budget and (n_rounds is None or n_rounds <= state["rounds"]):
        raise config.Error(f"{argv[0]} FAILed at its round budget ({state['rounds']}); "
                           f"give --rounds N above it, at most {TASK_MAX_ROUNDS}, to continue")
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
        _, body, _ = parse_task(run_dir / "task.md")
        done_when(body, run_dir / "task.md")
    if n_rounds is not None:
        if n_rounds < (state.get("rounds") or 0):
            raise config.Error("--rounds cannot reduce the saved round budget")
        state["rounds"] = n_rounds
    # A FAIL that carries a pending review carries a stale one, and so does a `waiting`
    # run the tick parked off one: every path that ends a run `fail` either recorded its
    # review or had its integration aborted under it, and an abort puts the branch back
    # exactly as it was. Runs saved before `abort_integration` dropped that record still
    # hold one, and resuming on it would spend the next round re-reviewing a round already
    # recorded instead of fixing what the reviewer found.
    # Its delivery note is stale in the same way -- what it says did not deliver is exactly
    # what this resume is about to do again -- so it goes too, the way `ak run merge` drops it
    # before its own retry; `note` writes a fresh one the moment anything fails again.
    if state.get("state") in ("fail", "waiting"):
        state.pop("review_pending", None)
        state.update(merge_failed=False, merge_note=None)
    if integration_record:
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
    with slot_lock(), recovery_lock(run_dir):
        if read_state(run_dir) != expected:
            raise config.Error("the run changed while choosing recovery; select it again")
        state.update(resume_from=state["state"], state="queued", slot_waiting=True,
                     queued_at=(expected.get("queued_at") if expected.get("state") == "queued"
                                else None) or time.time(),
                     **process_owner(), recovery_pending=not legacy_pass,
                     recovery_acknowledged_at=None, error=None, finished_at=None)
        clear_delivery(state)
        # the harness a login parked it on, and the stamps that paced and released the
        # retry: this resume is the answer to all of them, and a later stop for another
        # reason must not inherit any
        for key in ("waiting_for", "login_resume_at", "login_back_at"):
            state.pop(key, None)
        # the wait this resume answers is over too: main moved, or a hand hurried it
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
        save_state(run_dir, state)
    log = logger(run_dir, not child)
    log(f"resume {run_dir.name}: {run_dir / 'task.md'}")
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
            _, body, _ = parse_task(run_dir / "task.md")
            write_result(run_dir, state, done_when(body, run_dir / "task.md"), log, cfg)
            return
    except (config.Error, OSError) as exc:
        suffix = f"\n\n(the full result could not be written: {exc})"
    else:
        suffix = ""
    try:
        (run_dir / "result.md").write_text(
            f"# {delivery(state, report_config(cfg))} — {state.get('title') or run_dir.name}\n\n"
            f"VERDICT: {state.get('verdict') or 'none'}\n\n## Why this run stopped\n\n"
            f"{state.get('error') or 'no reason was recorded'}\n\n"
            f"relaunch: ak run {run_dir / 'task.md'}{suffix}\n")
    except OSError:
        pass
    else:
        if log is not None and state.get("error"):
            log(f"ERROR {state['error']}")


def drive(cfg, run_dir, opts, log, prior=None, job=None):
    """The loop plus every way it can end: one place decides the exit code and who is told."""
    existing = read_state(run_dir)
    if existing is not None and existing.get("state") == "stopped":
        return 1  # a stop landed before this attempt started; the record stands as left
    sampler = history.Sampler(run_dir.name, log=log)
    stop_after_finally = False
    sampler.start()
    try:
        with run_slot(run_dir, prior):
            state = job() if job else loop(cfg, run_dir, run_dir / "task.md", opts, log, prior)
    except StopRequested:
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
        parked = read_state(run_dir) or {}
        parked["waiting_for"] = expired.harness
        save_state(run_dir, parked)
        state = mark_state(run_dir, "waiting_login", str(expired))
        record_result(run_dir, state, log, cfg)
        announce(state, run_dir, log, cfg)
        stop_run_tree(read_state(run_dir) or state, log)
        return 1
    except Killed as exc:
        # A worker turn killed by signal twice within a minute: nothing was executed and
        # nothing was judged, and retrying into it is how a run burns a night being
        # killed.  The run parks as an interruption -- resumable, reading `needs you`
        # with the signal for a reason -- on the worktree, the round and the session.
        log(f"killed: {exc}")
        parked = read_state(run_dir) or {}
        interrupt(parked, str(exc))
        save_state(run_dir, parked)
        state = parked
        record_result(run_dir, state, log, cfg)
        announce(state, run_dir, log, cfg)
        stop_run_tree(read_state(run_dir) or state, log)
        return 1
    except (Exhausted, Stopped) as exc:
        # Both leave work a later run can pick up -- a provider that is spent, or a git or gh
        # that stopped -- and `exhausted` is the state the menu and `ak run resume` offer
        # recovery for.  An `error` here would be a remedy nothing can act on.  Only the
        # quota kind waits on a window: the tick resumes nothing else by itself.
        log(f"exhausted: {exc}")
        state = mark_state(run_dir, "exhausted", str(exc), log)
        if isinstance(exc, QuotaDry):
            state["quota_dry"] = True
            save_state(run_dir, state)
        elif "quota_dry" in state:
            # a stale mark from an earlier quota stop must not survive a stop for any
            # other reason: the tick resumes quota runs only, and this one is not one.
            del state["quota_dry"]
            state.pop("refusal_retry", None)
            save_state(run_dir, state)
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
            state = read_state(run_dir) or state
            state["peak_rss_mb"] = max(float(state.get("peak_rss_mb") or 0), latest)
            save_state(run_dir, state)
        if stop_after_finally:
            stop_run_tree(read_state(run_dir) or state, log)
        # Endings that raise never reach finish(); the checkout and the tabs still go.
        try:
            settled = read_state(run_dir) or state
        except NameError:
            settled = None  # the stop landed before the loop saved anything
        if isinstance(settled, dict):
            settle_run(settled, run_dir, log)
    result = finish(state, run_dir, log, cfg)
    stop_run_tree(read_state(run_dir) or state, log)
    return result


# --- somebody else's PR: the reviewer alone ---------------------------------


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


def checkout_for(name_with_owner, log):
    """The clone of that GitHub repo under ~/code, made with gh if there is none yet."""
    want = name_with_owner.lower()
    if config.CODE.is_dir():
        for path in sorted(config.CODE.iterdir()):
            if not (path / ".git").exists():
                continue
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
    """The findings, as a GitHub review: a comment on PASS, changes requested on FAIL."""
    head = lp.state["head_sha"]
    current, why = gh_json(lp.run_dir, "pr", "view", url, "--json", "headRefOid,state")
    lp.state["review_posted"] = False
    lp.state.pop("review_stale", None)
    lp.state.pop("review_error", None)
    if not isinstance(current, dict) or not current.get("headRefOid"):
        lp.state["review_error"] = f"cannot verify the PR head: {why}"
        save_state(lp.run_dir, lp.state)
        return False
    if current["headRefOid"] != head or current.get("state") != "OPEN":
        lp.state["review_stale"] = True
        lp.state["review_error"] = "PR head changed or closed; discarded review; watcher will re-queue"
        lp.log(f"WARN {lp.state['review_error']}")
        save_state(lp.run_dir, lp.state)
        return False
    path = lp.run_dir / "review.md"
    path.write_text(f"agentkit review of {head[:12]} by {lp.reviewer} (run {lp.run_dir.name})\n\n"
                    + lp.findings.strip() + "\n")
    how = "COMMENT" if verdict == "PASS" else "REQUEST_CHANGES"
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
    save_state(lp.run_dir, lp.state)
    return rc == 0


def review_pr(cfg, run_dir, url, opts, log):
    """Check out the PR head, have the reviewer judge it, post the verdict, offer the merge."""
    session_at_launch = launch_session(run_dir)
    info = pr_view(url)
    if info.get("state") != "OPEN":
        raise config.Error(f"{url} is {info.get('state', '?')}, not open")
    prior = read_state(run_dir) or {}
    if prior.get("worktree") and (prior.get("head_sha") != info["headRefOid"] or
                                 git(prior["worktree"], "rev-parse", "HEAD") != info["headRefOid"]):
        raise config.Error("the PR head or review checkout changed; existing work is kept for inspection")
    # Persist before fetch/checkout/provider work: the PR can move at any of those steps.
    save_state(run_dir, stamp_origin({**(read_state(run_dir) or {}), "run_id": run_dir.name,
                         "state": "running", **process_owner(),
                         "launched_session": session_at_launch,
                         "review_pr": url, "head_sha": info["headRefOid"],
                         "started_at": time.time(), "review_posted": False}))
    owner, name, number = PR_PARTS.match(url).groups()
    repo = checkout_for(f"{owner}/{name}", log)
    if disk_pressure():
        gc(log)
    base, head = info["baseRefName"], info["headRefOid"]
    git(repo, "fetch", "-q", "origin", f"pull/{number}/head", base)
    git(repo, "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}")
    base_sha = git(repo, "merge-base", f"origin/{base}", head)
    if prior.get("worktree"):
        wt, branch = Path(prior["worktree"]), prior["branch"]
    else:
        wt, branch = make_worktree(repo, run_dir.name, f"pr-{number}", head)
    tests = declared(wt, "tests")
    cmds = [tests] if tests else []
    title = f"Review PR #{number}: {info['title']}"
    body = (f"# {title}\n\n## Goal\nJudge {url} by {info['author']} against this repository: "
            "its AGENTS.md, README, tests and conventions, and the intent the PR states. Nobody "
            "from agentkit executed anything here; the diff is the author's.\n\n"
            f"## The PR says\n{(info.get('body') or '(no description)').strip()}\n\n"
            "## Done when\n```bash\n" + (tests or "true   # AGENTS.md declares no tests:") + "\n```\n")
    (run_dir / "task.md").write_text(f"---\nrepo: {repo}\nrounds: 1\n---\n{body}")
    state = stamp_origin({**(read_state(run_dir) or {}), "run_id": run_dir.name,
             "title": title, "task": str(run_dir / "task.md"),
             "launched_session": session_at_launch, "repo": str(repo), "scratch": False,
             "review_pr": url, "pr": url, "head_sha": head, "author": info["author"],
             "base": f"origin/{base}", "target": base, "base_sha": base_sha, "branch": branch,
             "worktree": str(wt), "executor": None, "reviewer": None, "rounds": 1,
             "state": "running", "verdict": None, **process_owner(), "started_at": time.time(),
             "finished_at": None, "round_summaries": [], "findings": "", "merge_method": "squash",
             "no_merge": True, "merged": False, "merge_note": None, "reported": False})
    # a review is a run like any other: its history row carries its task's size, measured
    # off the same body the task file on disk holds
    sized_words, sized_points, sized_checks = task_size(
        body, done_when(body, run_dir / "task.md"))
    state.update(task_words=sized_words, task_points=sized_points,
                 task_checks=sized_checks)
    save_state(run_dir, state)
    join_session_project(session_at_launch)     # a review is a launch too, and votes
    history_start(state, log)
    log(f"worktree {wt} on {branch}: PR #{number} by {info['author']} at {head[:12]}, "
        f"base origin/{base} ({base_sha[:12]})")
    exclude_junk(wt, log)
    env = config.repo_env(repo)
    if env:
        os.environ.update(env)
        log(f"env: {config.ENV / f'{repo.name}.env'} -> {', '.join(sorted(env))}")

    providers = collect_usage(cfg)
    order = reviewer_order(cfg, None, ready_order(cfg, providers,
                                                  run_workers(cfg, state), log,
                                                  role="reviewer"))
    # a --bg parent's reviewer, adopted when it is still in the live order
    preset_rev = (read_state(run_dir) or {}).get("launch_reviewer")
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
        reviewer = opts["--review"]
    elif preset_rev or order:
        reviewer = preset_rev or order[0]
    else:
        raise QuotaDry("every worker has a gate meter at 100% used")
    spares = [n for n in order if n != reviewer]
    state["reviewer"] = reviewer
    state.pop("launch_reviewer", None)   # consumed: a resume re-picks, as before
    save_state(run_dir, state)
    log(f"reviewer={reviewer} (no executor: this is a review of somebody else's PR)")
    if session_at_launch and not prior.get("reviewer"):
        # the first reviewer pick starts the review: the launch line (on the terminal
        # for a foreground launch, in the log for a --bg child whose parent printed it)
        print(launch_line(run_dir.name, title, None, reviewer))
    body += project_lessons(repo, state, log)
    save_state(run_dir, state)
    context = f"Repo checkout: {wt}\nBranch: {branch} (PR #{number} head, based on origin/{base})\n\n{body}"
    lp = Loop(cfg, run_dir, state, opts, log, wt, body, cmds, context, spares)
    lp.rnd = 1
    lp.round_dir.mkdir(parents=True, exist_ok=True)
    if cmds:
        lp.step("done-when")
        ok, dw_log = run_done_when(cmds, wt, lp.round_dir / "donewhen.log", lp.artifacts,
                                   lp.done_when_limit, log, silence=lp.turn_limit,
                                   run_dir=lp.run_dir)
        log(f"tests ({tests}): {'passed' if ok else 'FAILED'}")
    else:
        ok, dw_log = True, "(AGENTS.md declares no `tests:` command; nothing was run)"
        log("tests: AGENTS.md declares none")
    summary = (f"PR #{number} by {info['author']}: {info['title']}. agentkit executed nothing; "
               "review the author's diff.")
    try:
        verdict = review(lp, summary, ok, dw_log)
    except Blocked as exc:
        # No reviewer's harness can run: the review ends `blocked` on the harness's own line,
        # as a task run does, and not in an `error` the tick would retry into that harness.
        log(f"BLOCKED {exc}")
        state.update({"state": "blocked", "verdict": "BLOCKED", "error": str(exc),
                      "blocked": exc.section, "finished_at": time.time()})
        save_state(run_dir, state)
        write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
        return state
    restore_review_checkout(lp, "reviewer")
    if not post_review(lp, url, verdict):
        # the job was a review on GitHub; a verdict nobody can read there is not one, so the
        # run is an error -- no merge offer -- and `ak watch` launches it again next tick
        state["error"] = f"the review was not posted to {url}: {state.get('review_error')}"
        state["state"], state["finished_at"] = "error", time.time()
        save_state(run_dir, state)
        write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
        log(f"ERROR {state['error']}")
        return state
    if verdict == "PASS":
        green, why = checks(lp, url)
        current, _ = gh_json(run_dir, "pr", "view", url, "--json", "headRefOid,state")
        if (green and isinstance(current, dict) and current.get("headRefOid") == head
                and current.get("state") == "OPEN"):
            question = f"PR #{number} by {info['author']}: {info['title']}. Merge? yes/no"
            if watch.ask_inbox(cfg, question, url, head, log) == 0:
                state["merge_note"] = f"offered to the {watch.inbox()} session at {head[:12]}"
            else:
                state["merge_note"] = "merge question notification requires retry"
                state["pending_inbox"] = {"question": question, "url": url, "sha": head}
        else:
            if green:
                why = "the PR head changed, closed, or could not be verified after the checks"
            state["merge_note"] = f"not offered for merge: {why}"
            log(f"WARN {state['merge_note']}")
    state["state"] = "pass" if verdict == "PASS" else "fail"
    state["finished_at"] = time.time()
    save_state(run_dir, state)
    write_result(run_dir, state, cmds or ["(none declared)"], log, cfg)
    return state


def already_under_way(task_path, meta, title, cmds, exclude=None):
    """Runs still going in the same repository that look like the same job, newest first.

    A match is a run whose state is `running` or `queued` with a live process
    (`process_active`), in the task's repository, launched by anybody, where either a
    done-when of the new task and of the running run name the same test file, or their
    titles share at least four significant words.  Each match is a dict with the run's
    id, seat (None for nobody's), started_at, title, shared test files and shared
    title-word count.  Read-only: run state comes only from run_dirs(), read_state()
    and process_active(), and a running run's done-when from its own task.md.  A
    scratch task, or one whose repository cannot be resolved, is never checked.
    """
    stop = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
            "is", "are", "that", "this", "from", "into"}

    def test_files(commands):
        """Done-when tokens naming a test file, quotes stripped for the comparison.

        The basename itself has to look like a test: a shared runner such as
        `bash tests/smoke.sh` names no test file, however many jobs run it.
        """
        found = set()
        for command in commands:
            for token in command.split():
                name = token.strip("\"'")
                if not name:
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
    mine_files = test_files(cmds)
    mine_words = significant_words(title, repo.name)
    matches = []
    for directory in run_dirs():
        if exclude is not None and Path(directory) == Path(exclude):
            continue
        state = read_state(directory)
        if not state or state.get("state") not in ("running", "queued"):
            continue
        if not process_active(state):
            continue
        try:
            rival_meta, body, parsed_title = parse_task(directory / "task.md")
            other_cmds = done_when(body, directory / "task.md")
        except (OSError, config.Error):
            rival_meta, other_cmds, parsed_title = {}, [], None
        # `repo` only reaches run.json once the run builds its worktree, so a queued
        # receipt -- and a running run still that early -- is matched through the repo
        # its own task names; without one there is nothing to compare, so it is skipped
        if state.get("repo"):
            try:
                same = Path(state["repo"]).expanduser().resolve() == repo
            except OSError:
                continue
        elif rival_meta.get("repo"):
            try:
                same = task_repo(rival_meta, directory / "task.md") == repo
            except (config.Error, OSError):
                continue
        else:
            continue
        if not same:
            continue
        shared = sorted(mine_files & test_files(other_cmds))
        other_title = state.get("title") or parsed_title or directory.name
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
    owner, name, number = PR_PARTS.match(url).groups()
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
            prepare(run_dir, opts, logger(run_dir, True), cfg)
        except StopRequested:
            # A stop landed during preflight: the receipt already says so, and the
            # stopper printed the line -- this end names it and stands down alike.
            print(stop_line(run_dir.name, None, False))
            return 1
        if flags["--bg"]:
            try:
                reviewer = preset_review_model(cfg, opts,
                                               run_workers(cfg, read_state(run_dir) or {}))
            except config.Error as exc:
                refused(run_dir, exc, logger(run_dir, True), cfg)
                raise
            title = (read_state(run_dir) or {}).get("title")
            if reviewer:
                try:
                    save_state(run_dir, {**(read_state(run_dir) or {}),
                                         "launch_reviewer": reviewer})
                except StopRequested:
                    print(stop_line(run_dir.name, None, False))
                    return 1
            rc = spawn_bg(run_dir, argv)
            if reviewer and title and launch_session(run_dir):
                # the seat's terminal sees the launch line; the child's stdout is the log
                print(launch_line(run_dir.name, title, None, reviewer))
            return rc
    opts = dict(opts, **flags)
    log = logger(run_dir, not resumed)
    log(f"run {run_dir.name}: review of {url}")
    return drive(cfg, run_dir, opts, log, job=lambda: review_pr(cfg, run_dir, url, opts, log))


# --- several task files are one job (v5q) -----------------------------------

JOB_PICKER_INTERVAL = 60  # the executor picker is re-run on every job tick, at most this often
JOB_TICK = 2              # seconds between scheduler passes over the job receipt
JOB_TERMINAL = ("merged", "passed", "failed", "blocked", "skipped", "stopped")
# What a dependant cannot build on: `after:` skips behind either, because a task whose own
# work never landed leaves the next one nothing to stand on -- a blocked one counts as failed
# there exactly as the spec asks, while keeping its own word on the log and the status block.
# A stopped one is the same: deliberately ended, so nothing to stand on.
JOB_UNDELIVERED = ("failed", "blocked", "stopped")
_JOB_MUTE = threading.local()  # per-thread job quiet: announce/notify_recovery read it, never swap it


def job_dirs():
    return sorted(d for d in config.JOBS.iterdir() if d.is_dir()) if config.JOBS.exists() else []


def read_job(job_dir):
    try:
        state = json.loads((Path(job_dir) / "job.json").read_text())
        return state if isinstance(state, dict) else None
    except (OSError, ValueError):
        return None


def save_job(job_dir, job):
    path = Path(job_dir) / "job.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2))
    tmp.replace(path)


def job_logger(job_dir, to_file):
    def log(message):
        line = f"{datetime.now():%H:%M:%S} {message}"
        print(line, flush=True)
        if to_file:  # the --bg child's stdout already is log.txt; writing again would double it
            with (Path(job_dir) / "log.txt").open("a") as fh:
                fh.write(line + "\n")
    return log


def job_task_by_name(job, name):
    for task in job["tasks"]:
        if task["name"] == name:
            return task
    return None


def job_for_run(run_id):
    """(job_dir, job, task) holding that run, or None: a run belongs to at most one job.

    Read-only.  A stop asks the receipt's own `job_id` first -- it names the job
    from the first write, before the scheduler files the run id -- and this is the
    fallback for receipts a previous version wrote.
    """
    for job_dir in job_dirs():
        job = read_job(job_dir)
        if not job or not isinstance(job.get("tasks"), list):
            continue
        for task in job["tasks"]:
            if isinstance(task, dict) and task.get("run_id") == run_id:
                return job_dir, job, task
    return None


def job_scheduler_owns(run_id, state):
    """Whether the run's pid is still a live job scheduler's, not one loop's.

    The stamp alone cannot say: a task resumed by hand keeps its `job_id` but runs
    under its own pid, and stopping it must end that loop like any run of its own.
    Only a job that is still alive and still owns this exact pid spares the tree.
    """
    job = None
    if state.get("job_id"):
        job_dir = config.JOBS / state["job_id"]
        if (job_dir / "job.json").exists():
            job = read_job(job_dir)
    if job is None:
        found = job_for_run(run_id)
        job = found[1] if found else None
    if not job or job.get("pid") != state.get("pid"):
        return False
    try:
        return bool(process_active(job))
    except (TypeError, ValueError, AttributeError, OSError):
        return False  # an old receipt with no pid to check owns nothing live


def job_resolve_after(raw, tasks, task_path):
    """Match one `after:` value to another task file in the job, by basename or title."""
    for cand in tasks:
        if raw in (cand["name"], cand.get("stem"), cand.get("title")):
            return cand["name"]
    raise config.Error(f"{task_path}: after {raw!r} matches no other task file in the job")


def job_make_id(first_title):
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    base = f"{stamp}-{slugify(first_title)}"
    job_dir = config.JOBS / base
    n = 1
    while job_dir.exists():
        n += 1
        job_dir = config.JOBS / f"{base}-{n}"
    return job_dir


def job_create(cfg, task_paths, opts, parallel):
    """Build the job receipt before the first run starts; every change after saves it again."""
    if opts.get("--no-worktree"):
        raise config.Error("--no-worktree runs in the repo's current branch: one checkout cannot "
                           "hold a job of concurrent tasks; drop the flag so each task gets its "
                           "own worktree")
    infos = []
    for raw in task_paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise config.Error(f"no such task file: {path}")
        meta, body, title = parse_task(path)
        # reject malformed commands before allocating anything, as well as a task bigger
        # than one behaviour or over the round budget, which nothing waives, and one that
        # looks already under way in the same repository -- unless --anyway says to start
        # beside it regardless, the way a single run does
        cmds = done_when(body, path)
        infos.append({"path": path, "meta": meta, "title": title, "stem": path.stem,
                      "name": path.name, "cmds": cmds, "after_raw": config.task_afters(path),
                      "size_note": task_size_refusal(body, cmds)})
    seen = {}
    for info in infos:
        if info["name"] in seen:
            raise config.Error(f"{info['path']}: another task file in the job is already called "
                               f"{info['name']!r} ({seen[info['name']]}); the job keys tasks, "
                               "threads and `after:` on that basename, so rename one")
        seen[info["name"]] = info["path"]
    for info in infos:
        if info["size_note"]:
            raise config.Error(f"{info['path']}: {info['size_note']}; split it into one "
                               "behaviour per task")
        refusal = rounds_refusal(info["meta"].get("rounds"), "task rounds")
        if refusal:
            raise config.Error(f"{info['path']}: {refusal}")
    if not opts.get("--anyway"):
        for info in infos:
            rivals = already_under_way(info["path"], info["meta"], info["title"], info["cmds"])
            if rivals:
                first = rivals[0]
                detail = ", ".join(first["files"]) if first["files"] \
                    else f"{first['words']} title words"
                if len(rivals) > 1:
                    detail += f" and {len(rivals) - 1} more"
                try:
                    started = datetime.fromtimestamp(first["started"]).strftime("%H:%M")
                except (OSError, OverflowError, ValueError, TypeError):
                    started = "??:??"
                seat = first["seat"] or "nobody's"
                raise config.Error(
                    f"{info['path']}: this looks already under way: {first['id']} ({seat}, "
                    f"started {started}, \"{first['title']}\") shares {detail}; wait for "
                    "it, or add --anyway to start a second run")
    for info in infos:
        info["after"] = [job_resolve_after(dep, infos, info["path"]) for dep in info["after_raw"]]
        if info["name"] in info["after"]:
            raise config.Error(f"{info['path']}: a task cannot be after itself")
    # a dependency cycle never starts: it would wait forever
    visiting, done = set(), set()

    def visit(name, chain):
        if name in done:
            return
        if name in visiting:
            raise config.Error(f"tasks are after one another in a circle: {' -> '.join([*chain, name])}")
        visiting.add(name)
        task = next(t for t in infos if t["name"] == name)
        for dep in task["after"]:
            visit(dep, [*chain, name])
        visiting.discard(name)
        done.add(name)

    for info in infos:
        visit(info["name"], [])
    seat = config.current_session()
    job_dir = job_make_id(infos[0]["title"])
    job_dir.mkdir(parents=True)
    (job_dir / "log.txt").touch()
    job = {"job_id": job_dir.name, "seat": seat, "started_at": time.time(), "finished_at": None,
           "parallel": parallel, "executor_history": [], **process_owner(), "cwd": os.getcwd(),
           "opts": {key: opts.get(key) for key in ("--rounds", "--exec", "--review",
                                                   "--no-merge", "--no-worktree", "--anyway",
                                                   "--first")},
           "tasks": [{"name": info["name"], "title": info["title"], "after": info["after"],
                      "state": "queued" if not info["after"] else "waiting",
                      "run_id": None, "executor": None, "reviewer": None,
                      "started_at": None, "finished_at": None, "task_file": str(info["path"])}
                     for info in infos]}
    save_job(job_dir, job)
    return job_dir, job


def job_next_executor(cfg, current, workers=None):
    """The next model after `current` in the run's worker list (`config.workers` without), or None.

    A rerun is still that run's executor pick: the rotation goes around the list its
    session bound it to, never wider.
    """
    order = list(workers) if workers else config.workers(cfg)
    if current in order:
        rest = order[order.index(current) + 1:] + order[:order.index(current)]
    else:
        rest = order
    for name in rest:
        if name != current:
            return name
    return None


def job_classify(run_state, cfg):
    """A finished run's job state: merged, passed (no merge was asked, or the target already
    had the work), skipped (the dependency it was cut from never merged), blocked or failed.

    `blocked` is a failure a dependant treats like any other -- see `JOB_UNDELIVERED` -- and
    it keeps its own word because no resume, rerun or larger budget can move it: the task
    itself is what was wrong, and only a new task written for it can go anywhere.
    A `stopped` run keeps its own word the same way: deliberately ended, nothing to retry.
    """
    if run_state.get("state") == "stopped":
        return "stopped"
    if run_state.get("state") == "blocked":
        return "blocked"
    if review_pass(run_state, cfg):
        if run_state.get("merged"):
            return "merged"
        if run_state.get("skipped_dep"):
            return "skipped"    # cut from a dependency's passed branch that never merged
        if run_state.get("no_merge") or run_state.get("scratch") or run_state.get("on_target"):
            return "passed"
        if str(run_state.get("target") or "").lower() == "none":
            return "passed"
        return "failed"
    return "failed"


def job_verdict_line(task, run_state=None):
    """The one per-task line for the job log and `ak run status`."""
    name = task["name"]
    if task["state"] == "skipped":
        dep = (task.get("skipped_dep") or (run_state or {}).get("skipped_dep")
               or (task.get("after") or ["?"])[0])
        return f"{name}: skipped: {dep} did not merge"
    if task["state"] == "stopped":
        return f"{name}: stopped"
    if task["state"] == "blocked":
        why = " ".join(((run_state or {}).get("error") or "").split())
        return f"{name}: BLOCKED: {why or 'the task cannot be completed as written'}"
    if task["state"] in ("merged", "passed"):
        rounds = len((run_state or {}).get("round_summaries") or [])
        word = "merged" if task["state"] == "merged" else "passed"
        pr = (run_state or {}).get("pr")
        tail = f" {pr}" if word == "merged" and pr and str(pr).startswith("http") else ""
        return f"{name}: PASS, {word} after {rounds} rounds{tail}".replace(" after 0 rounds", "")
    rounds = len((run_state or {}).get("round_summaries") or [1])
    rerun = task.get("rerun_executor")
    if task.get("resume_attempted") and rerun:
        return (f"{name}: FAIL after {rounds} rounds, resumed once, rerun on {rerun}, "
                "still failing: needs you")
    if task.get("resume_attempted"):
        return f"{name}: FAIL after {rounds} rounds, resumed once, still failing: needs you"
    if rerun:
        return f"{name}: FAIL after {rounds} rounds, rerun on {rerun}, still failing: needs you"
    return f"{name}: FAIL after {rounds} rounds: needs you"


def job_hand_back(seat, line, log, typed=None, receipt=lambda mark: None):
    """Type a finished job's line into its seat: `sent`, `busy` or `gone`.

    The seat has to be found and typed into in the same world -- see `launcher_world` -- and
    only at its own prompt, exactly as a single run's ending is handed back.  `busy` is a seat
    that is there with a turn in flight: the line waits on the job's record and the tick types
    it at the next quiet prompt, because a seat still in its chair is never a reason to ask the
    owner instead.  Only `gone` is.  `typed` and `receipt` are the job record's side of
    `watch.type_at_prompt`'s: a line in the composer is never typed a second time.
    """
    with launcher_world(seat) as live:
        if not live:
            return "gone"
        if watch.type_at_prompt(orch.find(seat) or {"name": seat}, line, log,
                                typed=typed, receipt=receipt):
            return "sent"
    return "busy"


def mark_job_delivery(job_dir, job, **marks):
    """`mark_delivery` for a job: write what its delivery decided and nothing else.

    The job's own loop owns the rest of `job.json` -- every task's state and verdict -- and
    keeps writing it while the tick is here.  A whole save from this side would put a copy of
    the tasks from before back over them, and a job resumed since this copy was taken is no
    more this delivery's to mark than a resumed run is.  A mark given as None is removed.
    """
    with delivery_lock(job_dir):
        current = read_job(job_dir)
        if current is None:
            current = dict(job)
        elif not same_attempt(job, current):
            return False
        for key, value in marks.items():
            if value is None:
                current.pop(key, None)
                job.pop(key, None)
            else:
                current[key] = job[key] = value
        save_job(job_dir, current)
        return True


def deliver_job_handbacks(log):
    """Hand a finished job's line to a seat that was mid-turn when it ended, at the next prompt.

    The tick's pass for jobs, and the same promise a run's `handback_pending` carries: once,
    at the next quiet prompt, and the owner is asked only once the seat is gone.  Two ticks
    can overlap, so the line is read, typed and struck off inside the job's own
    `delivery_lock`, exactly as a run's ending is: whoever takes it second finds nothing left
    to say.
    """
    for job_dir in job_dirs():
        with delivery_lock(job_dir):
            job = read_job(job_dir)
            line = (job or {}).get("handback_pending")
            seat = (job or {}).get("seat")
            if not line or not seat:
                continue
            answer = job_hand_back(seat, line, log, job.get("handback_typed"),
                                   lambda mark: mark_job_delivery(job_dir, job, handback_typed=mark))
            if answer == "busy":
                continue
            # the card says what the job's own card says, never the typed line: that one
            # names a path, and a path is the last thing a seat's row or a phone has room for
            card = job.get("handback_card") or line
            done = {"handback_pending": None, "handback_card": None, "handback_typed": None}
            if answer == "sent":
                log(f"handed job {job_dir.name} back to the {seat} seat")
                mark_job_delivery(job_dir, job, card_sent={"kind": "handback",
                                                           "at": job.get("finished_at")}, **done)
            elif notify.shaped("needs", card, session=seat,
                               event_id=f"job:{job.get('job_id')}:{job.get('finished_at')}") == 0:
                mark_job_delivery(job_dir, job, card_sent={"kind": "needs",
                                                           "at": job.get("finished_at")}, **done)
            else:
                log(f"WARN job {job_dir.name}: its card was not accepted; retry required")
                mark_job_delivery(job_dir, job, card_pending=True, **done)


def job_block_line(job):
    """`job <id>: 2 running, 1 waiting on v5j, 3 merged` for `ak run status`."""
    counts = {}
    for task in job["tasks"]:
        counts[task["state"]] = counts.get(task["state"], 0) + 1
    parts = []
    if counts.get("running"):
        parts.append(f"{counts['running']} running")
    if counts.get("queued"):
        parts.append(f"{counts['queued']} queued")
    for task in job["tasks"]:
        if task["state"] == "waiting":
            dep = (task.get("after") or ["?"])[0]
            parts.append(f"1 waiting on {dep}")
    known = ("merged", "passed", "skipped", "failed", "blocked", "stopped")
    for state in known:
        if counts.get(state):
            parts.append(f"{counts[state]} {state}")
    # a task whose launcher is gone reads its run's own word (`job_now`): `2 interrupted`
    parts += [f"{count} {state}" for state, count in counts.items()
              if state not in ("running", "queued", "waiting", *known)]
    return f"job {job['job_id']}: {', '.join(parts) if parts else 'no tasks'}"


def job_now(job, alive, cfg=None, index=None):
    """The job as its runs stand now, for `ak run status`.

    A job writes a task's word and line when the task settles and never again, so a run
    resumed and merged since would still read FAIL, and a task whose launcher died would
    still read `running` over a run that was interrupted.  A settled task, and every task of
    a job whose launcher is gone (`alive` false), reads its run's current state instead; a
    task the live launcher still drives keeps its word, since its ladder may yet resume or
    rerun the run.  A line stops saying `needs you` once the job's own line was handed back
    to its seat, or once the task's run is `settled`.  The job's record is never written; its
    runs are reaped as the listing reaps every run, so a dead loop reads as one.
    """
    handed = ((job.get("card_sent") or {}).get("kind") == "handback"
              or bool(job.get("handback_pending")))
    tasks = []
    for task in job["tasks"]:
        run_state = reap(config.RUNS / task["run_id"], {}) if task.get("run_id") else {}
        if run_state.get("state") and (not alive or task.get("state") in JOB_TERMINAL):
            ended = run_state["state"] in ENDED
            # a merge is merged whatever today's config makes of its review's providers
            word = ("merged" if run_state.get("merged") else
                    job_classify(run_state, report_config(cfg)) if ended else
                    {"waiting": "waiting to merge"}.get(run_state["state"], run_state["state"]))
            # a run that finished after the job wrote its line has new rounds to tell
            if word != task.get("state") or (
                    (run_state.get("finished_at") or 0) > (task.get("finished_at") or 0)):
                task = {**task, "state": word, "verdict_line": (
                    job_verdict_line({**task, "state": word}, run_state) if ended
                    else f"{task['name']}: {word}")}
        if task.get("verdict_line") and (handed or settled(run_state, index)):
            task = {**task, "verdict_line": task["verdict_line"].replace(": needs you", "")}
        tasks.append(task)
    return {**job, "tasks": tasks}


def job_allocate_run_dir(title):
    """An ordinary run directory with a name no concurrent task takes: mkdir wins the race."""
    run_id = f"{datetime.now():%Y%m%d-%H%M}-{slugify(title)}"
    n = 1
    while True:
        run_dir = config.RUNS / (run_id if n == 1 else f"{run_id}-{n}")
        try:
            run_dir.mkdir(parents=True)
        except FileExistsError:
            n += 1
            continue
        (run_dir / "log.txt").touch()
        return run_dir


@contextmanager
def job_muted():
    """A job sends nothing per finished task: blocked runs still speak.

    A counter on thread-local state, so threads entering and leaving interleave safely --
    no globals are swapped and nothing is left behind. `announce` and `notify_recovery`
    read it and stay quiet only for finished attempts (pass/fail/error, which carry
    `recovery_pending` after a resume); genuinely blocked runs notify as today.
    """
    _JOB_MUTE.depth = getattr(_JOB_MUTE, "depth", 0) + 1
    try:
        yield
    finally:
        _JOB_MUTE.depth -= 1


def job_started(state):
    """Whether this process is a task its job started in a scope of its own (`job_scoped`).

    The job's quiet is thread-local in its own process.  A task it placed apart inherits the
    job's directory in its environment instead, and names that job on its receipt.
    """
    return bool(state.get("job_id")) and \
        Path(os.environ.get(config.JOB_DIR_ENV) or "").name == state["job_id"]


@contextmanager
def job_adopting(run_name):
    """While the job adopts one run, that run's recovery notice stays unsent.

    The scheduler reaps the run to learn its state, then resumes it itself seconds
    later: a "do not automatically rerun it" message now would be per-task noise the
    job immediately contradicts. Thread-local like `job_muted`, and it names the run
    so a glance at the flag says whose notice is held.
    """
    previous, _JOB_MUTE.adopt = getattr(_JOB_MUTE, "adopt", None), run_name
    try:
        yield
    finally:
        _JOB_MUTE.adopt = previous


def job_budget_exhausted(error):
    """Whether an `exhausted` error is spent provider budget (wait) rather than a stop.

    Only these messages mean more budget later: gate meters at 100% and no eligible
    reviewer. A twice-silent reviewer names the same spare
    shortage but spends reviewer turns on every resume, so it waits capped below
    instead. A stopped tool, a refused prompt, or a structural delivery complaint
    needs the owner instead.
    """
    text = error or ""
    return "100% used" in text or ("no eligible reviewer" in text
                                   and "gave no verdict twice" not in text)


def job_transport_exhausted(error):
    """Whether an `exhausted` error spends reviewer turns on every resume: a reviewer
    dying on API/transport errors, or one that twice answered without a verdict.

    The meters read healthy either way, so the picker keeps passing and every resume
    re-spends reviewer turns before failing again: the wait is capped, never forever.
    """
    text = error or ""
    return "API/transport errors" in text or "gave no verdict twice" in text


def reviewer_transport_dead(error):
    """Whether an `exhausted` run is off a reviewer's transport deaths, and only that.

    The transport half of `job_transport_exhausted`: the reviewer died on API or
    transport errors, with the meters still healthy.  A reviewer that twice answered
    without a verdict is not dead -- it is stuck, and another lap at the tick's pace
    will not unstick it -- so only this half resumes a run outside a job.
    """
    return "API/transport errors" in (error or "")


def job_round_shortfall(run_state):
    """Whether an `exhausted` run is really a spent round budget, which only more rounds fix.

    Integration invalidating the review at the last round (and a merge error with a
    pending review) raises `Exhausted` with outstanding `review_pending` work that only
    a resume finishes -- the run itself prints the way on. The ladder treats this like a
    FAIL at its budget that no review failed: no more rounds, since three is the budget,
    but the one rerun on the next executor model, rather than the budget wait (which would
    never help) or a failure on the spot.
    """
    if run_state.get("state") != "exhausted":
        return False
    if run_state.get("review_pending"):
        return True
    return "round budget" in (run_state.get("error") or "")


def job_wait_budget(job_dir, job, task, log, lock, error, where, rounds=None):
    """Requeue a budget-exhausted task with pacing; transport outages get a cap.

    Gate-meter exhaustion waits indefinitely -- the spec never fails a task for lack of
    budget, and the resume spends no model turn while the picker still says exhausted.
    A transport outage does spend (reviewer turns with backoff on every resume), so
    after `JOB_TRANSPORT_WAITS` paced waits the task needs its owner instead of
    burning turns silently forever. The cap counts one outage, not history: when the
    attempt completed more rounds than the last wait saw, a new episode starts at one.
    Returns True when the task now waits in `queued`.
    """
    if job_transport_exhausted(error):
        last = task.get("transport_rounds")
        if rounds is not None and last is not None and rounds > last:
            waits = 1
        else:
            waits = task.get("transport_waits", 0) + 1
        task["transport_waits"] = waits
        task["transport_rounds"] = rounds
        if waits > JOB_TRANSPORT_WAITS:
            task.update(state="failed", finished_at=time.time(),
                        verdict_line=f"{task['name']}: FAIL: needs you ({error[:300]})",
                        findings=error)
            with lock:
                save_job(job_dir, job)
            log(task["verdict_line"])
            return False
    else:
        task["exhausted_waits"] = task.get("exhausted_waits", 0) + 1
    task["budget_wait"] = True
    task["retry_after"] = time.time() + JOB_PICKER_INTERVAL
    task["state"] = "queued"
    with lock:
        save_job(job_dir, job)
    count = task.get("transport_waits") or task.get("exhausted_waits")
    log(f"{task['name']}: exhausted {where} ({error}); "
        f"waiting for budget (wait {count})")
    return True


JOB_TRANSPORT_WAITS = 5  # paced outage waits before a transport-exhausted task needs its owner


def job_wait_login(job_dir, job, task, log, lock, run_state, where):
    """Whether this attempt parked on an expired login, and if so, wait beside it.

    Nothing in a job can log anybody in, and the tick resumes the run itself the moment that
    harness's `auth` verb passes: the task waits at the picker's own rate, the way it waits
    for spent budget, rather than spending its one resume and its one rerun on a wall and
    then calling work nobody faulted a failure.  Every attempt a task makes asks this.
    """
    if run_state.get("state") != "waiting_login":
        return False
    job_wait_budget(job_dir, job, task, log, lock,
                    run_state.get("error") or "a harness login expired", where,
                    rounds=len(run_state.get("round_summaries") or []))
    return True


def job_passed_branch(cfg, job, task, dep):
    """Where `task` starts before its one unmerged dependency `dep` lands, or None: it waits.

    A dependency whose review passed has only its landing left, which on a busy repository
    takes hours.  Its reviewed tip is what the dependant is cut from when both work in one
    repository; `wait_for_dependency` holds the dependant's own landing until `dep` merged.
    """
    dep_task = job_task_by_name(job, dep) or {}
    state = read_state(config.RUNS / dep_task["run_id"]) if dep_task.get("run_id") else None
    if (not state or state.get("state") not in ("running", "waiting", "pass")
            or state.get("no_merge") or not state.get("branch") or not review_pass(state, cfg)):
        return None
    try:
        path = Path(task["task_file"])
        meta = parse_task(path)[0]
        repo = None if meta.get("from") else task_repo(meta, path)
    except (config.Error, OSError):
        return None
    if repo is None or str(repo) != state.get("repo"):
        return None
    return {"task": dep, "branch": state["branch"], "tip": state["review"]["head_sha"]}


def job_start_task(cfg, job_dir, task, opts, log):
    """Allocate an ordinary run directory and launch it; the caller marks running first."""
    task_path = Path(task["task_file"])
    _, _, title = parse_task(task_path)
    run_dir = job_allocate_run_dir(title)
    extra = task.get("starting_branch")
    text = task_path.read_text()
    if extra:
        text = text.rstrip() + (f"\n\n## Starting point\nPrevious attempt branch: {extra}\n")
    (run_dir / "task.md").write_text(text)
    run_opts = {"--rounds": opts.get("--rounds"), "--exec": task.get("exec_override") or opts.get("--exec"),
                "--review": task.get("review_override") or opts.get("--review"),
                "--review-pr": None,
                "--no-merge": bool(opts.get("--no-merge")), "--no-worktree": bool(opts.get("--no-worktree")),
                "--anyway": bool(opts.get("--anyway")), "--first": bool(opts.get("--first")),
                "--bg": False}
    if task.get("rerun_attempted") and run_opts["--review"]:
        try:
            review_providers(cfg, run_opts["--exec"], run_opts["--review"])
        except config.Error as exc:
            log(f"{task['name']}: {exc}; the rerun will pick another reviewer")
            run_opts["--review"] = None
    prepare(run_dir, run_opts, logger(run_dir, True), cfg, job_id=job_dir.name, task_file=task_path)
    if task.get("from_pass"):
        save_state(run_dir, {**(read_state(run_dir) or {}), "from_pass": task["from_pass"]})
    log(f"{task['name']} start: {run_dir.name}")
    return run_dir, run_opts


def job_scoped(job):
    """Whether this process sits in the job's own scope, whose one memory cap is not a task's.

    `spawn_job_bg` places a job in `agentkit-job-<id>`, and a task run in that process would
    share the job's cap with every other task.  So a job in a scope of its own starts each
    task in one of its own instead, the way `--bg` starts a lone run.  A job run from a
    terminal -- or resumed there after its scoped launcher died -- runs its tasks in its own
    process, as a lone run from a terminal does.
    """
    scope = job.get("scope")
    if not scope_is_real(scope):
        return False
    try:
        line = next(row for row in orch.OWN_CGROUP.read_text().splitlines()
                    if row.startswith("0::"))
    except (OSError, StopIteration):
        return False
    return line.rstrip("/").rsplit("/", 1)[-1] in (f"{scope}.scope", f"{scope}.service")


def job_await(run_dir):
    """Follow a task's run in its own scope until the job's ladder can take it up.

    It is a lone run in everything but its voice, so it goes on as one does: while its
    process lives, and while the tick carries a death of it on -- a resume ordered or backing
    off, or a death recorded for the dead-loop pass -- it is still going.  What comes back is
    its ending, a wait for budget or a login, or what the tick left for a person.
    """
    while True:
        state = read_state(run_dir) or {}
        if not process_active(state):
            with job_adopting(run_dir.name):
                state = reap(run_dir, state)
            if not (state.get("state") in ("queued", "running")
                    or (state.get("state") == "interrupted" and state.get("deaths")
                        and tick_resumes(state))):
                return state
        time.sleep(JOB_TICK)


def job_drive(cfg, run_dir, run_opts, box, scoped=False):
    """One `drive` to completion, muted so the job stays the only voice; never raises.

    `scoped` starts it the way `--bg` starts a lone run, in a run scope with a memory cap of
    its own, and follows it there (see `job_scoped`).
    """
    try:
        if scoped:
            argv = [str(run_dir / "task.md")]
            for key in ("--rounds", "--exec", "--review"):
                if run_opts.get(key):
                    argv += [key, str(run_opts[key])]
            argv += [key for key in ("--no-merge", "--anyway", "--first") if run_opts.get(key)]
            spawn_bg(run_dir, argv)
            box["state"] = job_await(run_dir)
            box["rc"] = 0 if job_classify(box["state"], cfg) in ("merged", "passed") else 1
            return
        log = logger(run_dir, True)
        with job_muted():
            box["rc"] = drive(cfg, run_dir, run_opts, log)
        box["state"] = read_state(run_dir) or {}
    except config.Error as exc:
        box["rc"] = 2
        box["state"] = read_state(run_dir) or {"state": "error", "verdict": "ERROR",
                                               "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - a crashed task run must still end its thread
        box["rc"] = 2
        box["state"] = read_state(run_dir) or {"state": "error", "verdict": "ERROR",
                                               "error": repr(exc)}


def job_exit_line(task, run_dir, run_state, rc):
    merged = bool(run_state.get("merged"))
    return (f"{task['name']} exit {rc}: {run_dir.name} {run_state.get('state')} "
            f"{run_state.get('verdict')} {'merged' if merged else 'not merged'}")


def job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock):
    """A terminal attempt becomes the task's result; the receipt is current before returning."""
    outcome = job_classify(run_state, cfg)
    task.update(state=outcome, finished_at=time.time(), verdict_line=job_verdict_line(
        {**task, "state": outcome}, run_state))
    if outcome == "failed":
        task["findings"] = run_state.get("findings") or run_state.get("error") or ""
    with lock:
        save_job(job_dir, job)
    log(task["verdict_line"])


def job_ladder(cfg, job_dir, job, task, run_dir, run_state, rc, log, lock):
    """The retries, in the worker thread, so the scheduler keeps scheduling while they run.

    An `exhausted` run waits for budget rather than failing; a PASS whose delivery failed is
    finished with `ak run merge`, not re-executed; only then comes the one rerun on the next
    executor model, for a FAIL at its budget its reviews did not fail.  No task is given
    more rounds, and one its reviews failed is not rerun either: it goes back to the seat
    with its findings, as a single run does, to be split or re-scoped.
    """
    task["executor"] = run_state.get("executor") or task.get("executor")
    task["reviewer"] = run_state.get("reviewer") or task.get("reviewer")
    log(job_exit_line(task, run_dir, run_state, rc))
    if run_state.get("state") == "waiting":
        # a PASS parked on the next merge to its target is no ending: the tick resumes it
        # then, and the task follows it there, so its dependants wait instead of skipping
        log(f"{task['name']}: parked waiting ({run_state.get('error')}); following it")
    while run_state.get("state") == "waiting" and tick_admission(run_state):
        time.sleep(JOB_TICK)
        run_state = read_state(run_dir) or run_state
        if run_state.get("state") != "waiting":
            run_state = job_await(run_dir)
    if job_wait_login(job_dir, job, task, log, lock, run_state, "mid-run"):
        return
    if run_state.get("state") == "stopped":
        # Deliberately ended: no resume, no rerun, no budget wait. The task keeps
        # the run's word, and `after:` tasks skip behind it like any undelivered one.
        job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
        return
    if run_state.get("state") == "exhausted":
        error = run_state.get("error") or "no reason was recorded"
        if job_budget_exhausted(error) or job_transport_exhausted(error):
            # the message decides first: a pending review parked on spent meters waits
            # for budget even with `review_pending` still set -- the resume the shortfall
            # rule would spend has nothing to bill to
            job_wait_budget(job_dir, job, task, log, lock, error, "mid-run",
                            rounds=len(run_state.get("round_summaries") or []))
            return
        if not job_round_shortfall(run_state):
            # a stopped tool or a structural complaint: no resume can fix it, the owner
            # is needed
            task.update(state="failed", finished_at=time.time(),
                        verdict_line=f"{task['name']}: FAIL: needs you ({error[:300]})",
                        findings=error)
            with lock:
                save_job(job_dir, job)
            log(task["verdict_line"])
            return
    outcome = job_classify(run_state, cfg)
    if outcome in ("merged", "passed", "skipped"):
        job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
        return
    if run_state.get("state") == "pass" and run_state.get("merge_failed"):
        # reviewed work with only its delivery left: finish it with the one command for that
        log(f"{task['name']}: PASS needs delivery; merging with ak run merge {run_dir.name}")
        try:
            if job_scoped(job):
                # in a run scope of its own, like every other attempt the task makes
                pid = watch.launch_resume(run_dir.name, log, verb="merge")
                launched = process_owner(pid) if pid else {}
                while process_active(launched):
                    time.sleep(JOB_TICK)
                settled = job_await(run_dir) if pid else {}
                mrc = 0 if job_classify(settled, cfg) in ("merged", "passed") else 1
            else:
                with job_muted():
                    mrc = cmd_merge([run_dir.name])
        except config.Error as exc:
            mrc = 2
            log(f"{task['name']}: merge refused: {exc}")
        run_state = read_state(run_dir) or run_state
        task["executor"] = run_state.get("executor") or task.get("executor")
        task["reviewer"] = run_state.get("reviewer") or task.get("reviewer")
        log(job_exit_line(task, run_dir, run_state, mrc))
        if job_wait_login(job_dir, job, task, log, lock, run_state, "on delivery"):
            return
        if job_classify(run_state, cfg) in ("merged", "passed"):
            job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
            return
        # `ak run merge` runs fixer turns of its own, and one of them can end the run
        # `blocked`: that word is the run's, and nothing here turns it into a delivery that
        # failed -- the same rule the ladder's last word obeys below. A stop between
        # the merge and this line keeps its word the same way.
        if run_state.get("state") == "stopped":
            job_settle(cfg, job_dir, job, task, run_dir, run_state, log, lock)
            return
        blocked = run_state.get("state") == "blocked"
        task["state"] = "blocked" if blocked else "failed"
        task.update(finished_at=time.time(),
                    verdict_line=(job_verdict_line(task, run_state) if blocked else
                                  f"{task['name']}: PASS, delivery failed: needs you"),
                    findings=(run_state.get("merge_note") or run_state.get("error") or ""))
        with lock:
            save_job(job_dir, job)
        log(task["verdict_line"])
        return
    # a FAIL at its round budget gets no more rounds: three is the budget.  One its reviews
    # failed goes back to the seat with its findings, as a single run's does, to be split
    # or re-scoped.  One a check or integration left behind -- or an `exhausted` that is
    # really a spent round budget -- starts once more on the next executor model in
    # worker-list order
    if not task.get("rerun_attempted") and job_classify(run_state, cfg) == "failed" \
            and (failed_at_budget(run_state) or job_round_shortfall(run_state)) \
            and not review_failed(run_state):
        nxt = job_next_executor(cfg, task.get("executor") or run_state.get("executor"),
                                run_workers(cfg, run_state))
        if nxt:
            # Keep the job's reviewer when legal; otherwise the fresh run picks from live budgets.
            task.pop("review_override", None)
            task["rerun_attempted"] = True
            task["rerun_executor"] = nxt
            task.setdefault("executor_history", []).append(
                {"at": time.time(), "from": run_state.get("executor"), "to": nxt,
                 "reason": "budget-failover"})
            job.setdefault("executor_history", []).append(
                {"task": task["name"], "from": run_state.get("executor"), "to": nxt})
            with lock:
                save_job(job_dir, job)
            log(f"{task['name']}: still failing, rerunning on {nxt}")
            branch = run_state.get("branch")
            task["starting_branch"] = branch
            task["exec_override"] = nxt
            task["run_id"] = None
            with lock:
                save_job(job_dir, job)
            try:
                run_dir2, run_opts2 = job_start_task(cfg, job_dir, task, job["opts"], log)
            except (config.Error, OSError) as exc:
                task.update(state="failed", finished_at=time.time(),
                            verdict_line=f"{task['name']}: FAIL: needs you ({exc})")
                with lock:
                    save_job(job_dir, job)
                log(task["verdict_line"])
                return
            task["run_id"] = run_dir2.name
            # a new run starts new episodes: the old outage counts stay with the old run
            for key in ("exhausted_waits", "transport_waits", "transport_rounds",
                        "retry_after", "budget_wait"):
                task.pop(key, None)
            with lock:
                save_job(job_dir, job)
            box = {}
            job_drive(cfg, run_dir2, run_opts2, box, job_scoped(job))
            run_state2 = box.get("state") or read_state(run_dir2) or {}
            task["executor"] = run_state2.get("executor") or nxt
            task["reviewer"] = run_state2.get("reviewer") or task.get("reviewer")
            log(job_exit_line(task, run_dir2, run_state2, box.get("rc", 1)))
            if job_wait_login(job_dir, job, task, log, lock, run_state2, "on rerun"):
                return
            if run_state2.get("state") == "exhausted" \
                    and not job_round_shortfall(run_state2):
                error2 = run_state2.get("error") or "no reason was recorded"
                if job_budget_exhausted(error2) or job_transport_exhausted(error2):
                    job_wait_budget(job_dir, job, task, log, lock, error2, "on rerun",
                                    rounds=len(run_state2.get("round_summaries") or []))
                    return
            if job_classify(run_state2, cfg) in ("merged", "passed"):
                job_settle(cfg, job_dir, job, task, run_dir2, run_state2, log, lock)
                return
            run_state = run_state2
    # a blocked run keeps its own word here: nothing above it resumed or reran one, and
    # nothing below it should read it as a FAIL that another round might have carried.
    # A stopped run keeps its word the same way.
    if run_state.get("state") == "stopped":
        task["state"] = "stopped"
    else:
        task["state"] = "blocked" if run_state.get("state") == "blocked" else "failed"
    task.update(finished_at=time.time(), verdict_line=job_verdict_line(task, run_state),
                findings=(run_state.get("findings") or run_state.get("error") or ""))
    with lock:
        save_job(job_dir, job)
    log(task["verdict_line"])


def job_fresh_worker(cfg, job_dir, job, task, run_dir, run_opts, lock, log):
    """A task's whole ladder -- initial drive, resume, rerun -- inside its own thread.

    The scheduler stays a scheduler while retries run for hours: it keeps starting queued
    tasks, reaping finished ones and unblocking `after:` dependants.
    """
    box = {}
    job_drive(cfg, run_dir, run_opts, box, job_scoped(job))
    try:
        job_ladder(cfg, job_dir, job, task, run_dir,
                   box.get("state") or read_state(run_dir) or {}, box.get("rc", 1), log, lock)
    except (OSError, ValueError, KeyError, TypeError):
        task.update(state="failed", finished_at=time.time(),
                    verdict_line=f"{task['name']}: FAIL: needs you")
        with lock:
            save_job(job_dir, job)
        log(task["verdict_line"])


def job_adopt_worker(cfg, job_dir, job, task, run_dir, lock, log):
    """A run from before a kill, resumed and settled inside its own thread.

    Finished attempts go straight to the ladder with their result kept; genuinely
    unfinished ones resume through the existing run resume. Nothing is re-executed from
    scratch here, so a branch is never delivered twice and the ladder bookkeeping stands.

    A run parked on an expired login is not one of the unfinished ones: nothing here can
    log anybody in, so a resume from this thread would park it again before it reached a
    model and spend a launch on a wall every pass.  It goes to the ladder, which waits for
    it the way it waits for spent budget, and the tick resumes it when the login is back.
    """
    try:
        with job_adopting(run_dir.name):
            run_state = reap(run_dir, read_state(run_dir) or {})
        if (run_state.get("state") == "queued" and run_state.get("slot_waiting") and
                not process_active(run_state)) or run_state.get("state") in (
                "interrupted", "exhausted", "stalled") or (
                needs_recovery(run_state) and run_state.get("state") not in ENDED
                and run_state.get("state") != "waiting_login"):
            # a scoped job resumes it in a run scope of its own and follows it there
            scoped = job_scoped(job)
            with job_adopting(run_dir.name), job_muted():
                cmd_resume([run_dir.name, "--bg"] if scoped else [run_dir.name])
            run_state = job_await(run_dir) if scoped else read_state(run_dir) or run_state
        if run_state.get("state") in ("running", "queued"):
            # `reap` declined it (inside its grace) or it is parked: pace the next look at
            # the once-a-minute rate and keep the run, so adopt hands back instead of spinning
            task["retry_after"] = time.time() + JOB_PICKER_INTERVAL
            task["state"] = "queued" if not task.get("after") else "waiting"
            with lock:
                save_job(job_dir, job)
            return
        job_ladder(cfg, job_dir, job, task, run_dir, run_state,
                   0 if job_classify(run_state, cfg) in ("merged", "passed") else 1, log, lock)
    except config.Error as exc:
        # the kept run refuses resume (e.g. a budget FAIL rerun from scratch is the ladder's
        # job, not this adoption's): clear it and let the scheduler start the task over with
        # its ladder flags intact
        log(f"{task['name']}: resume refused: {exc}")
        task["run_id"] = None
        task["state"] = "queued" if not task.get("after") else "waiting"
        with lock:
            save_job(job_dir, job)
    except (OSError, ValueError, KeyError, TypeError):
        task.update(state="failed", finished_at=time.time(),
                    verdict_line=f"{task['name']}: FAIL: needs you")
        with lock:
            save_job(job_dir, job)
        log(task["verdict_line"])


def reap_job(job_dir, job):
    """Whether the job's launcher is still alive: a dead one is the tick's to relaunch when
    `job_admission` says so, and otherwise needs `ak run resume <job>`."""
    if job.get("finished_at"):
        return True
    try:
        return process_active(job)
    except (TypeError, ValueError, AttributeError):
        return True  # uncertainty is never evidence of an exit


def job_admission(job_dir, job, now=None):
    """Why the tick may relaunch this job whose launcher is gone, or nothing: a person's.

    `tick_admission`'s bounds, for a job: a seat launched it, that seat's session -- by its
    name now -- still exists and its owner did not close it, no run of an unfinished task that
    stopped short of its ending was handed back, carded or acknowledged, and the launcher was
    alive under a day ago.  A launcher dies without writing an ending, so its heartbeat -- the
    last write in the job's directory, which none of the tick's run passes touch -- stands in
    for one.  The directory it was launched from must still be there: a task that names no
    repo finds its checkout from it.  A job with a task its owner stopped stays as it is.  So
    does one the tick relaunched twice in the hour before it died again: a third death parks
    it, as a run's does.
    """
    try:
        seat = config.resolve_session(job["seat"]) if job.get("seat") else None
        if not seat or not config.session_path(seat).is_file() \
                or watch.seat_closed_by_owner(seat):
            return ""
    except config.Error:
        return ""
    if not job.get("cwd") or not Path(job["cwd"]).is_dir():
        return ""
    for task in job["tasks"]:
        run_state = (read_state(config.RUNS / task["run_id"]) if task.get("run_id") else None) or {}
        if "stopped" in (task.get("state"), run_state.get("state")):
            return ""
        if (task.get("state") not in JOB_TERMINAL and run_state.get("state") not in ENDED
                and any(run_state.get(key) for key in (
                    "handed_back", "recovery_notified", "recovery_acknowledged_at"))):
            return ""
    now = time.time() if now is None else now
    alive_at = watch.run_last_write(job_dir)
    if not 0 <= now - alive_at < 86400:
        return ""
    relaunches = [at for at in job.get("relaunches") or []
                  if isinstance(at, (int, float)) and 0 <= alive_at - at < watch.DEAD_WINDOW]
    if len(relaunches) >= 2:
        return ""
    return f"session {seat} exists; alive under 24h ago; no task stopped"


def job_gone_line(job_dir, job):
    """The line under a job whose launcher is gone: whose it is to continue."""
    admission = job_admission(job_dir, job)
    if admission:
        return f"  launcher gone; the next tick relaunches it · {admission}"
    return f"  launcher gone; ak run resume {job_dir.name} to continue"


def run_job_loop(cfg, job_dir, job, to_file=True):
    """Start ready tasks at once up to `--parallel`, hold `after:` tasks, skip failed deps."""
    job_dir = Path(job_dir)
    log = job_logger(job_dir, to_file)
    lock = threading.Lock()
    threads = {}  # name -> worker Thread
    last_picker = [0.0]
    opts = job.get("opts") or {}
    parallel = job.get("parallel")
    limit = config.max_runs()
    if limit:
        parallel = min(parallel, limit) if parallel else limit
    # This process owns the receipt from here on, so a kill reads as unfinished, not
    # running. Under the recovery lock a `--bg` child starts only after its launcher's
    # handoff save, the way a run child waits on its own receipt.
    with recovery_lock(job_dir):
        job.update(process_owner())
        with lock:
            save_job(job_dir, job)

    def save():
        with lock:
            save_job(job_dir, job)

    while True:
        for name, thread in list(threads.items()):
            if thread.is_alive():
                continue
            threads.pop(name)
            task = job_task_by_name(job, name)
            if task["state"] == "running":
                # its worker died mid-flight with the run still open; requeue, run kept
                task["state"] = "queued" if not task.get("after") else "waiting"
                save()
                log(f"{name}: worker died; requeued")
        # running tasks with no thread own a run from before a kill: adopt it in a worker
        for task in job["tasks"]:
            if task["state"] != "running" or task["name"] in threads:
                continue
            if parallel is not None and len(threads) >= parallel:
                break
            now = time.time()
            if task.get("retry_after", 0) > now:
                continue  # a live record elsewhere is re-checked at most once a minute
            run_id = task.get("run_id")
            rundir = config.RUNS / run_id if run_id else None
            if rundir is None or not (rundir / "run.json").exists():
                task["state"] = "queued" if not task.get("after") else "waiting"
                task["run_id"] = None
                save()
                continue
            with job_adopting(rundir.name):
                state = reap(rundir, read_state(rundir) or {})
            if state.get("state") in ("running", "queued") and process_active(state):
                # alive elsewhere; its own scheduler owns it: look again in a minute,
                # not every tick (the reap takes the run's lock each time)
                task["retry_after"] = now + JOB_PICKER_INTERVAL
                save()
                continue
            thread = threading.Thread(target=job_adopt_worker,
                                      args=(cfg, job_dir, job, task, rundir, lock, log),
                                      daemon=True)
            threads[task["name"]] = thread
            thread.start()
        # waiting tasks whose dependencies settled move to queued or skipped
        for task in job["tasks"]:
            if task["state"] != "waiting":
                continue
            states = {dep: (job_task_by_name(job, dep) or {}).get("state") for dep in task["after"]}
            if any(state in (*JOB_UNDELIVERED, "skipped") for state in states.values()):
                bad = next(dep for dep in task["after"]
                           if (job_task_by_name(job, dep) or {}).get("state")
                           in (*JOB_UNDELIVERED, "skipped"))
                task.update(state="skipped", finished_at=time.time(), skipped_dep=bad,
                            verdict_line=f"{task['name']}: skipped: {bad} did not merge")
                save()
                log(task["verdict_line"])
            elif states and all(state in ("merged", "passed") for state in states.values()):
                task["state"] = "queued"
                task.pop("from_pass", None)
                save()
            else:
                unmerged = [dep for dep, state in states.items() if state not in ("merged", "passed")]
                start = job_passed_branch(cfg, job, task, unmerged[0]) if len(unmerged) == 1 else None
                if start:
                    task.update(state="queued", from_pass=start)
                    save()
                    log(f"{task['name']}: starts from {start['task']}'s passed branch "
                        f"({start['tip'][:12]}); lands after it merges")
        running = sum(1 for task in job["tasks"] if task["state"] == "running")
        # queued tasks with no brake start at once; dependencies and provider budgets only
        for task in job["tasks"]:
            if task["state"] != "queued" or task["name"] in threads:
                continue
            if parallel is not None and running >= parallel:
                break
            now = time.time()
            if task.get("retry_after", 0) > now:
                continue  # paced waits (budget, grace) retry at most once a minute
            if task.get("budget_wait") and now - last_picker[0] < JOB_PICKER_INTERVAL:
                continue
            try:
                providers = collect_usage(cfg)
                pick_models(cfg, providers, opts.get("--exec"), opts.get("--review"), lambda _: None)
            except Exhausted:
                # a pair no budget can make is not waited for: the task's run refuses it at launch
                if not pair_refusal(cfg, providers, config.workers(cfg), opts.get("--exec"),
                                    opts.get("--review")):
                    task["budget_wait"] = True
                    task["retry_after"] = now + JOB_PICKER_INTERVAL
                    last_picker[0] = now
                    save()
                    continue
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                task["budget_wait"] = True
                task["retry_after"] = now + JOB_PICKER_INTERVAL
                last_picker[0] = now
                save()
                continue
            except config.Error as exc:
                task.update(state="failed", finished_at=time.time(),
                            verdict_line=f"{task['name']}: FAIL: needs you ({exc})")
                save()
                log(task["verdict_line"])
                continue
            task.pop("budget_wait", None)
            kept = task.get("run_id")
            kept_dir = config.RUNS / kept if kept else None
            if kept_dir is not None and (kept_dir / "run.json").exists():
                # an exhausted or interrupted run kept across ticks: reap it here so a live
                # record is never adopted, then resume it in a worker, never redo it
                with job_adopting(kept_dir.name):
                    kept_state = reap(kept_dir, read_state(kept_dir) or {})
                if kept_state.get("state") in ("running", "queued") \
                        and process_active(kept_state):
                    # alive elsewhere; its own scheduler owns it: back off like every wait
                    task["retry_after"] = now + JOB_PICKER_INTERVAL
                    save()
                    continue
                task["state"] = "running"
                save()
                thread = threading.Thread(target=job_adopt_worker,
                                          args=(cfg, job_dir, job, task, kept_dir, lock, log),
                                          daemon=True)
                threads[task["name"]] = thread
                thread.start()
                running += 1
                continue
            task["state"] = "running"
            task["started_at"] = time.time()
            save()
            try:
                run_dir, run_opts = job_start_task(cfg, job_dir, task, opts, log)
            except StopRequested:
                # A stop landed during preflight: the receipt already says so, so
                # the task keeps the run's word and nothing is launched to carry on.
                task.update(state="stopped", finished_at=time.time(),
                            verdict_line=f"{task['name']}: stopped")
                save()
                log(task["verdict_line"])
                continue
            except (config.Error, OSError) as exc:
                task.update(state="failed", finished_at=time.time(),
                            verdict_line=f"{task['name']}: FAIL: needs you ({exc})")
                save()
                log(task["verdict_line"])
                continue
            task["run_id"] = run_dir.name
            save()
            thread = threading.Thread(target=job_fresh_worker,
                                      args=(cfg, job_dir, job, task, run_dir, run_opts,
                                            lock, log),
                                      daemon=True)
            threads[task["name"]] = thread
            thread.start()
            running += 1
        if all(task["state"] in JOB_TERMINAL for task in job["tasks"]) and not threads:
            break
        # the launcher's heartbeat: however long a task runs, the last write in this directory
        # says when this process was last alive, which the tick reads once it is gone
        try:
            os.utime(job_dir / "job.json")
        except OSError:
            pass
        time.sleep(JOB_TICK)
    if job.get("finished_at") and job.get("card_sent"):
        log(f"job {job['job_id']}: already finished; card already sent")
        orch.stop_scope(job.get("scope"), log, wait=False)
        return 1 if any(task["state"] in JOB_UNDELIVERED for task in job["tasks"]) else 0
    job["finished_at"] = time.time()
    save()
    failed = [task for task in job["tasks"] if task["state"] in JOB_UNDELIVERED]
    seat = job.get("seat")
    if failed:
        findings = next((task.get("findings") or "" for task in failed if task.get("findings")), "")
        text = f"job {job['job_id']}: {len(failed)} task(s) need you" + (f": {findings[:200]}" if findings else "")
        for task in failed:
            if task.get("findings"):
                log(f"{task['name']} findings:\n{task['findings']}")
        log(f"job {job['job_id']}: Needs you")
        line = (f"{text}. Result: {job_dir / 'log.txt'}. Decide the next step.")
        # the seat that launched the job is there, so the failures are its to act on and the
        # owner is never asked about them -- the same rule a single run's ending obeys.  Under
        # the job's own delivery lock, because a tick may be holding a line this loop left
        # pending on an earlier pass: one of them types it, and only one.
        with delivery_lock(job_dir):
            answer = job_hand_back(seat, line, log, job.get("handback_typed"),
                                   lambda mark: mark_job_delivery(job_dir, job, handback_typed=mark)
                                   ) if seat else "gone"
            if not seat:
                log("no seat launched this job, so nothing is sent; "
                    "the result is here and in `ak run status`")
            elif answer == "sent":
                mark_job_delivery(job_dir, job, handback_pending=None, handback_card=None,
                                  handback_typed=None,
                                  card_sent={"kind": "handback", "at": job["finished_at"]})
                orch.stop_scope(job.get("scope"), log, wait=False)
                return 1
            elif answer == "busy":
                mark_job_delivery(job_dir, job, handback_pending=line, handback_card=text)
                log(f"job {job['job_id']}: its seat is not at its prompt; the tick hands it back")
                orch.stop_scope(job.get("scope"), log, wait=False)
                return 1
            elif notify.shaped("needs", text, session=seat,
                               event_id=f"job:{job['job_id']}:{job['finished_at']}") != 0:
                mark_job_delivery(job_dir, job, card_pending=True)
                log("WARN job card was not accepted; retry required")
                orch.stop_scope(job.get("scope"), log, wait=False)
                return 1
            job["card_sent"] = {"kind": "needs", "at": job["finished_at"]}
    else:
        text = f"job {job['job_id']}: all {len(job['tasks'])} tasks finished"
        log(f"job {job['job_id']}: Done")
        if not seat:
            log("no seat launched this job, so nothing is sent; "
                "the result is here and in `ak run status`")
        elif notify.shaped("done", text, session=seat,
                           event_id=f"job:{job['job_id']}:{job['finished_at']}") != 0:
            job["card_pending"] = True
            save()
            log("WARN job card was not accepted; retry required")
            orch.stop_scope(job.get("scope"), log, wait=False)
            return 1
        job["card_sent"] = {"kind": "done", "at": job["finished_at"]}
    save()
    orch.stop_scope(job.get("scope"), log, wait=False)
    return 1 if failed else 0


def spawn_job_bg(job_dir, relaunch=None):
    """Detach the job the way a single run detaches; the child resumes it in the background.

    `relaunch` is the receipt the tick found with its launcher gone.  It must still be that
    receipt under the lock, the relaunch is stamped on it for `job_admission` to count, and
    the child is given the job's seat: a tick from cron has none, and the tasks the job starts
    belong to the seat that launched it.
    """
    job_dir = Path(job_dir)
    log_path = job_dir / "log.txt"
    env = dict(os.environ, **{config.JOB_DIR_ENV: str(job_dir)})
    if relaunch is not None:
        env[config.SESSION_ENV] = relaunch["seat"]
    child = [sys.executable, str(config.REPO / "bin" / "ak"), "run", "resume", job_dir.name]
    with recovery_lock(job_dir):
        try:
            job = read_job(job_dir) or {}
            if relaunch is not None:
                if job != relaunch:
                    raise config.Error(f"{job_dir.name} changed while the tick read it")
                job["relaunches"] = [*(job.get("relaunches") or []), time.time()]
            unit = f"agentkit-job-{job_dir.name}"
            if scope_is_real(job.get("scope")):
                unit = orch.next_scope_unit(unit)   # an old launcher's scope may linger
            placement = {}
            cap, properties = run_scope_limits()
            pid = orch.start_in_slice(
                child, unit, env, log_path,
                log=note_in(log_path), target_slice=orch.run_slice_name(),
                properties=properties,
                nice=True, placement=placement)
            # The child waits on this lock before adopting the receipt. The parent can never
            # overwrite a running child's tasks, and reaping sees the child, not its launcher.
            job.update(process_owner(pid), scope=placement.get("scope"),
                       scope_reason=placement.get("scope_reason"))
            remember_memory_cap(job, placement, cap)
            save_job(job_dir, job)
        except OSError as exc:
            raise config.Error(f"could not launch the job: {exc}") from exc
    print(job_dir.name)
    print(job_dir / "job.json")
    return 0


def cmd_job_resume(argv):
    """Restart an interrupted job: finished tasks keep their result, the rest start again."""
    background = "--bg" in argv
    argv = [arg for arg in argv if arg != "--bg"]
    # `--rounds` is a single-run option; a job keeps each task's own budget, and one over
    # the rule is refused here exactly as a run's is
    if len(argv) >= 3 and argv[1] == "--rounds":
        if not (len(argv) == 3 and argv[2].isdigit() and int(argv[2]) > 0):
            raise config.Error("usage: ak run resume ID [--rounds N] [--bg]")
        refusal = rounds_refusal(argv[2], "--rounds")
        if refusal:
            raise config.Error(refusal)
        argv = [argv[0]]
    if len(argv) != 1 or Path(argv[0]).name != argv[0] or argv[0] in (".", ".."):
        raise config.Error("usage: ak run resume ID [--rounds N] [--bg]")
    job_dir = config.JOBS / argv[0]
    if not (job_dir / "job.json").exists():
        return None
    # Read under the handoff lock so a `--bg` child never decides on a receipt its
    # launcher is still writing: the parent holds this lock across Popen and its pid
    # save, and the child adopts the receipt under it on its first tick.
    with recovery_lock(job_dir):
        job = read_job(job_dir)
    if not job or not isinstance(job.get("tasks"), list):
        raise config.Error(f"no resumable job: {argv[0]} (looked in {config.JOBS})")
    try:
        launcher_alive = not job.get("finished_at") and bool(process_active(job))
    except (TypeError, ValueError, AttributeError, OSError):
        launcher_alive = False  # an old receipt with no pid to check is resumable, not live
    own_child = (launcher_alive and os.environ.get(config.JOB_DIR_ENV) == str(job_dir)
                 and job.get("pid") == os.getpid())
    if launcher_alive and not own_child:
        raise config.Error(f"{argv[0]} is still running as pid {job['pid']}")
    if background:
        return spawn_job_bg(job_dir)
    if all(task["state"] in JOB_TERMINAL for task in job["tasks"]):
        job_block = job_block_line(job)
        print(f"{job_block} (already finished)")
        return 1 if any(task["state"] in JOB_UNDELIVERED for task in job["tasks"]) else 0
    # A task that names no repo inherits the checkout the job was launched from, and neither a
    # tick from cron nor a detached child starts there: the job goes back to it first.
    if job.get("cwd") and Path(job["cwd"]).is_dir():
        os.chdir(job["cwd"])
    cfg = config.load()
    to_file = os.environ.get(config.JOB_DIR_ENV) != str(job_dir)
    # Finished tasks keep their result with their run and ladder flags intact. Anything
    # running without a live worker is left running: the loop adopts its kept run in a
    # worker, resuming it through the existing run resume, so no branch runs twice. Only
    # tasks that never started are re-derived here; unstarted tasks start under the same
    # rules as a fresh job.
    for task in job["tasks"]:
        if task["state"] in JOB_TERMINAL or task["state"] == "running":
            continue
        task["state"] = "queued" if not task.get("after") else "waiting"
    # dependencies that have since settled decide waiting before the first tick
    for task in job["tasks"]:
        if task["state"] != "waiting":
            continue
        states = {dep: (job_task_by_name(job, dep) or {}).get("state") for dep in task["after"]}
        if any(state in (*JOB_UNDELIVERED, "skipped") for state in states.values()):
            bad = next(dep for dep in task["after"]
                       if (job_task_by_name(job, dep) or {}).get("state")
                       in (*JOB_UNDELIVERED, "skipped"))
            task.update(state="skipped", finished_at=time.time(), skipped_dep=bad,
                        verdict_line=f"{task['name']}: skipped: {bad} did not merge")
    save_job(job_dir, job)
    return run_job_loop(cfg, job_dir, job, to_file=to_file)


HELP = command_help.render("run")


def main(argv):
    if command_help.show("run", argv):
        return 0
    if argv[:1] == ["status"]:
        return cmd_status(argv[1:])
    if argv[:1] == ["show"]:
        # The same screen as naming a run in status: deaths are listed there.
        return cmd_status(argv[1:])
    if argv[:1] == ["clean"]:
        return cmd_clean(argv[1:])
    if argv[:1] == ["gc"]:
        return cmd_gc(argv[1:])
    if argv[:1] == ["resume"]:
        return cmd_resume(argv[1:])
    if argv[:1] == ["merge"]:
        return cmd_merge(argv[1:])
    if argv[:1] == ["stop"]:
        return cmd_stop(argv[1:])
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
    refusal = rounds_refusal(opts["--rounds"], "--rounds")
    if refusal:
        raise config.Error(refusal)
    parallel = None
    if opts["--parallel"] is not None:
        if not (str(opts["--parallel"]).isdigit() and int(opts["--parallel"]) > 0):
            raise config.Error(f"--parallel must be a positive integer (got {opts['--parallel']!r})")
        parallel = int(opts["--parallel"])
    config.ensure_dirs()
    opts.update(flags)
    cfg = config.load()
    if not opts["--review-pr"] and len(positional) == 1 and parallel is not None:
        raise config.Error("usage: ak run <task.md> [--rounds N] [--exec MODEL] [--review MODEL] "
                           "[--anyway] [--first] [--no-worktree] [--no-merge] [--bg]: --parallel "
                           "needs more than one task file")
    if not opts["--review-pr"] and len(positional) > 1:
        job_dir, job = job_create(cfg, positional, opts, parallel)
        if opts["--bg"]:
            return spawn_job_bg(job_dir)
        to_file = os.environ.get(config.JOB_DIR_ENV) != str(job_dir)
        log = job_logger(job_dir, to_file)
        log(f"job {job_dir.name}: {len(positional)} tasks")
        return run_job_loop(cfg, job_dir, job, to_file=to_file)

    resumed = os.environ.get(config.RUN_DIR_ENV)
    if resumed and not queued(Path(resumed)):
        receipt = read_state(Path(resumed)) or {}
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
        meta, body, title = parse_task(task_path)
        # reject malformed commands before allocating a run directory, as well as a task
        # bigger than one behaviour or over the round budget, which nothing waives, and a
        # job that looks already under way in the same repository -- unless --anyway says
        # to start regardless.  A run's own child launch never runs the already-under-way
        # check.
        cmds = done_when(body, task_path)
        refusal = task_size_refusal(body, cmds)
        if refusal:
            print(f"ak run: {refusal}; split it into one behaviour per task", file=sys.stderr)
            return 2
        refusal = rounds_refusal(meta.get("rounds"), "task rounds")
        if refusal:
            print(f"ak run: {refusal}", file=sys.stderr)
            return 2
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
            prepare(run_dir, opts, logger(run_dir, True), cfg, task_file=task_path)
        except StopRequested:
            # A stop landed during preflight: the receipt already says so, and the
            # stopper printed the line -- this end names it and stands down alike.
            print(stop_line(run_dir.name, None, False))
            return 1
        if opts["--bg"]:
            try:
                executor, reviewer = preset_models(cfg, opts, logger(run_dir, True), run_dir)
            except StopRequested:
                print(stop_line(run_dir.name, None, False))
                return 1
            rc = spawn_bg(run_dir, argv)
            if executor and reviewer and launch_session(run_dir):
                # the seat's terminal sees the launch line; the child's stdout is the log
                print(launch_line(run_dir.name, title, executor, reviewer))
            return rc

    log = logger(run_dir, not resumed)
    log(f"run {run_dir.name}: {task_path}")
    return drive(cfg, run_dir, opts, log)
