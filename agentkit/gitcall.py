"""Git, gh and tool calls, and the checkouts they work in.

The run side's git, gh and tool calls go through here, with their stop handling: a tool
that times out or asks a question raises Stopped, never an empty answer.  Beside them,
what a run reads off a checkout -- the declared suite and rules, the front matter -- and what it
makes and cleans: worktrees, leftovers, sandboxes, the reviewer's copy and the probe checkouts.
The run's child environment, depth and logger live here too, as every leaf starts tools.
"""

import codecs
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
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import config, guard, record as run_record, sentences, task as taskfile, worker


# what a test run, a build or an editor drops next to the work, and no reviewer should ever see
JUNK = ("__pycache__/", "*.pyc", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
        "node_modules/", ".DS_Store", "*.swp")


# what the suites leave inside the checkout when a test is killed mid-way: every sandbox
# tests/smoke.sh and the test_*.py files create there is named under this one prefix, which
# tests/test_leftover_staged_and_sandboxes.py holds every one of them to.  The leftover sweep
# never commits these and the loop removes them before the next turn, whatever the
# repository's .gitignore says.
SANDBOX_PREFIX = ".ak-test-"


TOOL_CAP = 120                  # seconds allowed for each git or gh attempt
# seconds a timed-out git or gh gets between SIGTERM and SIGKILL, a ceiling: on SIGTERM git
# removes its index and ref locks and exits at once, where SIGKILL leaves them for the next
# git to fail on ("File exists"); one that ignores SIGTERM is killed when this ends
TOOL_GRACE = 5


# the line a fetch prints for a ref another process holds: the ref moved under it, or git's
# lock on it is held -- not a ref no retry can write, such as a stale name in its way; see
# `fetch`.  `.*`, not `[^']*`: a ref name or a checkout path may hold an apostrophe
REF_LOCKED = re.compile(r"error: cannot lock ref '.*': (?:is at \w+ but expected \w+|"
                        r"Unable to create '.*': File exists\.)")


# what git and gh say when the prompt they wanted was refused; each is a stop, never a wait
PROMPTED = re.compile(r"terminal prompts disabled|could not read (?:Username|Password)|"
                      r"prompts (?:are )?disabled|askpass", re.I)


LIST_CAP = 500                  # files a scratch run's reviewer is shown before it is told the count



FRONT = re.compile(r"^---\n(|.*?\n)---", re.S)  # `---\n---` is a fence holding nothing


_RUN_CONTEXT = threading.local()  # job threads export their own depth and slot owner


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


# the git commands that merge file contents, and so read a merge driver (`merge_config`)
MERGES = ("merge", "merge-tree", "rebase")


def merge_config(git, cwd, env, timeout):
    """`env` with ak's own git config after any it carries, for a `git` (with its own options) that
    merges: `*.md` merges sentence by sentence (`sentences`).  Git reads one global attributes
    file, so ak's names the driver for `*.md` first and then holds the file this call's git
    would have read, as it reads now: every line of it, a `*.md` one included, decides as
    before, and a repository's own `.gitattributes` before that.  The lookup is part of the
    call, under its timeout.  A file named by a relative path, one ak cannot read, or a state
    it cannot write merges by git's line rule, as before."""
    driver = f"merge.{sentences.NAME}.driver"
    count = int(env.get("GIT_CONFIG_COUNT") or 0)
    if driver in (env.get(f"GIT_CONFIG_KEY_{n}") for n in range(count)):
        return env
    named = run_capped([*git, "config", "--path", "--get", "core.attributesFile"], cwd=cwd,
                       text=True, stdin=subprocess.DEVNULL, timeout=timeout, env=env)
    if named.returncode not in (0, 1):
        return env
    # unset, git reads $XDG_CONFIG_HOME/git/attributes, or $HOME/.config/git/attributes
    own = named.stdout.rstrip("\n") if named.returncode == 0 else os.path.join(
        env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME", ""), ".config"), "git", "attributes")
    if not os.path.isabs(own):
        return env
    text = f"*.md merge={sentences.NAME}\n".encode()
    try:
        try:
            text += Path(own).read_bytes().removeprefix(codecs.BOM_UTF8)    # git skips it on line 1
        except FileNotFoundError:
            pass
        path = config.STATE / "merge-attributes" / hashlib.sha256(text).hexdigest()[:16]
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            fresh = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
            fresh.write_bytes(text)
            os.replace(fresh, path)
    except OSError:
        return env
    pairs = (("core.attributesFile", str(path)),
             (driver, f"{shlex.quote(sys.executable)} -I {shlex.quote(sentences.__file__)} %O %A %B %L"))
    for n, (key, value) in enumerate(pairs, count):
        env[f"GIT_CONFIG_KEY_{n}"], env[f"GIT_CONFIG_VALUE_{n}"] = key, value
    env["GIT_CONFIG_COUNT"] = str(count + len(pairs))
    return env


def run_capped(cmd, timeout, **popen):
    """subprocess.run's captured call, except that one stopped -- past `timeout`, or interrupted
    -- gets SIGTERM, and SIGKILL only after TOOL_GRACE.  Both go through the Popen holding the
    child, so neither reaches its pid once it is reaped."""
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except BaseException:
            proc.terminate()
            try:
                proc.wait(TOOL_GRACE)
            except subprocess.TimeoutExpired:
                pass
            finally:
                proc.kill()     # also when a second interrupt cuts the grace short
            raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def tool_run(cmd, cwd=None, timeout=None, env=None):
    """(exit code, stdout, stderr) for every git and gh call this module makes, in `tool_env`
    as `env` changes it (None drops a variable), with `merge_config` for a git that merges.

    Git's fetch, push and ls-remote, and gh get one timeout retry. Other calls stop so their
    callers can recover any unfinished checkout edits. The code is None on timeout;
    a refused prompt gets credential advice, no retry. The run's outcome names the next command.
    """
    timeout = TOOL_CAP if timeout is None else timeout
    # Repeating checkout edits can turn a timeout into an "already in progress" failure.
    start = 1
    while cmd[0] == "git" and start < len(cmd) and cmd[start].startswith("-"):
        start += 2 if cmd[start] in guard.GIT_VALUED else 1     # git's own options, `-C`, `-c`
    args = cmd[start:]
    retry = cmd[0] == "gh" or (cmd[0] == "git" and args and args[0] in ("fetch", "push", "ls-remote"))
    merges = cmd[0] == "git" and args and args[0] in MERGES
    for attempt in range(2):
        try:
            call = {name: value for name, value in {**tool_env(), **(env or {})}.items()
                    if value is not None}
            proc = run_capped(cmd, timeout=timeout, cwd=None if cwd is None else str(cwd),
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                              env=merge_config(cmd[:start], cwd, call, timeout) if merges else call)
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


# `git merge -s <name>` runs `git-merge-<name>` off PATH
STRATEGIES = config.REPO / "tools" / "merge"


def merge(wt, tip):
    """`git merge --no-edit tip` on the checked-out branch, as `git_out` answers it, with a
    clean merge's tree from `tip` as "ours" (`tools/merge/git-merge-target-first`): a
    union-merged file then reads the target's lines first, as a rebase onto it orders them.
    A merge that conflicts is git's own, as without it."""
    if git_out(wt, "merge-tree", "--write-tree", tip, "HEAD")[0]:
        return git_out(wt, "merge", "--no-edit", tip)
    path = os.pathsep.join((str(STRATEGIES), tool_env().get("PATH", os.defpath)))
    return git_out(wt, "merge", "--no-edit", "-s", "target-first", tip, env={"PATH": path})


def gh(cwd, *args, timeout=None):
    """(exit code, output); the code is None when the command ran out of time.

    The PR commands are handed the PR's own URL and run from the run directory rather than the
    worktree: outside a checkout `gh pr merge --delete-branch` has no local branch to switch
    away from, and deleting the branch out from under the run's own worktree is not what it means.

    A run's call that fails while GitHub's own count says its API allowance is spent waits
    for the reset and asks again, for as long as GitHub says spent, so a checks wait, merge,
    PR read or review post finishes late instead of failing.  Said once per reset.
    """
    said = None
    while True:
        code, out, err = tool_run(["gh", *args], cwd=cwd, timeout=timeout)
        reset = allowance_reset(cwd) if code else None
        if reset is None:
            return code, (out + err).strip()
        from . import turns     # turns imports this module
        run_dir = config.RUNS / _RUN_CONTEXT.state["run_id"]
        if reset != said:
            logger(run_dir)(f"waiting for GitHub's API allowance until "
                            f"{datetime.fromtimestamp(reset, timezone.utc):%H:%M} UTC")
            said = reset
        # a reset that looks past while GitHub still counts it spent is a clock apart from
        # GitHub's, asked again after a floor rather than at once
        turns.run_wait(run_dir, max(ALLOWANCE_FLOOR, reset - time.time()))


ALLOWANCE_FLOOR = 60    # seconds a run waits before asking a spent allowance again


def allowance_reset(cwd):
    """When the spent GitHub API allowance comes back, the latest reset of `core` and `graphql`
    with none left, or None: not a run's call (the tick asks again next tick), none spent, or
    no count to read.

    Read off GitHub's own count, whose read spends none of it, never gh's words.
    Every gh command spends one or both, and which is not mapped: a failure of another cause
    while one is spent waits for its reset once, then fails as before.
    """
    if not getattr(_RUN_CONTEXT, "state", {}).get("run_id"):
        return None
    code, out, _err = tool_run(["gh", "api", "rate_limit"], cwd=cwd)
    try:
        counts = json.loads(out)["resources"]
        spent = [float(counts[name]["reset"]) for name in ("core", "graphql")
                 if counts[name]["remaining"] == 0]
    except (ValueError, KeyError, TypeError):
        return None
    return max(spent) if code == 0 and spent else None


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


def round_commands(cmds, wt, target, *, scratch, landing):
    """The done-when as a round runs it, in one reading for preflight, which counts its checks
    (`task.checks_refusal`), and the loop, which runs them: a scratch task's lines with their
    `# once` marks stripped; else the task's lines with the target's suite as the one `# once`
    line when landing, however the task names it, and every line each round without a landing
    (`with_suite`, which reads `origin/<target>`'s `tests:` line, else the checkout's)."""
    if scratch:
        return [taskfile.split_once(cmd)[0] for cmd in cmds]
    return with_suite(cmds, wt, target, landing=landing)


def owner_name(url):
    """`owner/name`, lowercase, of a clone's URL or path: a GitHub slug, and a local origin's
    last two parts."""
    return "/".join(url.rstrip("/").removesuffix(".git").replace(":", "/").split("/")[-2:]).lower()


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


def origin_default(repo):
    """The branch origin calls default now, as origin answers: unlike `default_base`, never a
    tracking ref missing or left behind when origin's default moved, nor the current branch."""
    ref = git(repo, "ls-remote", "--symref", "origin", "HEAD").partition("\t")[0]
    if not ref.startswith("ref: refs/heads/"):
        raise config.Error(f"origin names no default branch for {repo}")
    return ref.removeprefix("ref: refs/heads/")


def dirty_paths(wt, env=None):
    """Every uncommitted path: tracked edits (staged or not) and untracked files, no ignored ones.

    Two plumbing calls rather than `status --porcelain`, whose output would have to be
    un-quoted and split off its status column; `-z` hands back the raw paths. `--no-renames`
    keeps both paths so a selected commit takes a rename's deletion too. `env` is the
    reader's: an index of its own (`GIT_INDEX_FILE`) for a checkout another process works in,
    whose own index is then neither locked nor rewritten.
    """
    tracked = git(wt, "diff", "--no-renames", "--name-only", "-z", "HEAD", check=False, env=env)
    untracked = git(wt, "ls-files", "--others", "--exclude-standard", "-z", check=False, env=env)
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
    from . import update, versions
    code, out, _ = tool_run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"])
    common = (Path(repo) / out.strip()).resolve() if code == 0 and out.strip() else None
    if common == versions.repository().resolve():
        return update.agentkit_dir()     # ak's own: each version of ~/agentkit is a worktree of it
    return common.parent if common else Path(repo)


def leftover_junk(path):
    """Match names, not targets: a dependency symlink is junk even when Git ignores only directories."""
    parts = path.rstrip("/").split("/")
    return (parts[0].startswith(SANDBOX_PREFIX)
            or any(part in (run_record.RECOVERY_LOCK, "delivery.lock", "node_modules", "venv", ".venv")
                   for part in parts))


def add_paths(wt, paths, env=None):
    """Stage selected work that still has a file or an entry in this index.

    A staged rename already removed its old entry, so add cannot match that path.
    An index read from HEAD still has it and must stage its deletion.
    """
    indexed = set(git(wt, "ls-files", "-z", env=env).split("\0"))
    selected = [f":(literal){path}" for path in paths
                if path in indexed or os.path.lexists(Path(wt) / path)]
    if selected:
        git(wt, "add", "--", *selected, env=env)


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
    real, sandbox = committable_paths(wt, artifacts)
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
            add_paths(wt, real)
        with tempfile.TemporaryDirectory() as tmp:
            index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            git(wt, "read-tree", "HEAD", env=index)
            if real:
                add_paths(wt, real, env=index)
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


def committable_paths(wt, artifacts=(), env=None):
    """(the dirty paths a commit of the checkout would take, the leftover junk it leaves): the
    one rule of what a run's uncommitted work is.  Test sandboxes, run locks and dependency
    trees (`leftover_junk`), whatever the repository's `.gitignore` names, and what the
    done-when generated (`artifacts`) are left.  `env` goes to every git read."""
    real, sandbox = [], []
    for path in dirty_paths(wt, env):
        if path in artifacts:
            continue
        if leftover_junk(path) or git_out(wt, "check-ignore", "-q", "--", path, env=env)[0] == 0:
            sandbox.append(path)
        else:
            real.append(path)
    return real, sandbox


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


@contextmanager
def repository_lock(repo, *, exclusive=False):
    # Lock the shared git directory itself: preparation waits for gc, and gc skips a
    # preparation in progress. No lock file or checkout-specific identity can drift apart.
    env = project_env(repo)
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", env=env)
    directory = os.open(common, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH)
        yield env
    finally:
        os.close(directory)


def no_auto_gc(repo):
    # Linked worktrees share this config: a turn's detached gc can lock all their HEADs,
    # then leave those locks behind when the worker stops its leftover processes.
    with repository_lock(repo) as env:
        for key, value in (("gc.auto", "0"), ("maintenance.auto", "false")):
            if git(repo, "config", "--local", "--get", key, check=False, env=env) != value:
                git(repo, "config", "--local", "--replace-all", key, value, env=env)
            if git(repo, "config", "--get", key, check=False, env=env) != value:
                git(repo, "config", "--worktree", "--replace-all", key, value, env=env)


def add_worktree(repo, path, *args, mark=None):
    """(exit code, output) of `git worktree add` making `path`, locked as `MAKING` until git
    has made it and, given `mark`, that file is in the checkout's own git directory."""
    with repository_lock(repo):
        no_auto_gc(repo)
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


def commit_identity(wt):
    return {"head_sha": git(wt, "rev-parse", "HEAD"),
            "tree_sha": git(wt, "rev-parse", "HEAD^{tree}")}


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


def run_depth():
    value = os.environ.get("AK_RUN_DEPTH", "0")
    if not value.isascii() or not value.isdigit():
        raise config.Error("AK_RUN_DEPTH must be a non-negative integer")
    return int(value)


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


def log_is_stdout(run_dir):
    """Detached wakes already write the log; following it would feed it back into itself."""
    try:
        return os.path.samefile(run_dir / "log.txt", sys.stdout.fileno())
    except (AttributeError, OSError, ValueError):
        return False


def say(message):
    """One line on standard output with its time, written through before this returns: a
    file there buffers whole blocks, and a log read while its process runs must be current."""
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    try:
        print(line, flush=True)
    except BrokenPipeError:
        # whoever read the launch stopped reading (`| head`): that ends the reading, never
        # the run, whose log keeps every line; later prints go nowhere
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return line


def logger(run_dir):
    def log(message):
        line = say(message)
        if not log_is_stdout(run_dir):
            with (run_dir / "log.txt").open("a") as fh:
                fh.write(line + "\n")
    return log


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


def patch_args(command, *args):
    """git's arguments for `command`'s patch (diff, log) as Git prints it itself, whatever the
    user's config says of quoting, prefixes, drivers and submodules, for `patch_files`."""
    return ("-c", "core.quotePath=false", command, "-U0", "--find-renames", "--no-color",
            "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/",
            "--submodule=short", *args)


def patch_files(patch):
    """Each file of a patch made with `patch_args`, as (old path, new path, its hunks' lines),
    a path None where that side is not a file.  A file's header names its sides, where Git
    quotes a name holding a quote, a backslash or a control character C-style and ends one
    holding a space with a tab, and its hunks hold the lines; a content line never starts a
    line of the patch bare, so neither the file split nor the first hunk's mark can land
    inside one."""
    for chunk in ("\n" + patch).split("\ndiff --git ")[1:]:
        header, _, body = chunk.partition("\n@@")
        yield _patch_name(header, "---", "a/"), _patch_name(header, "+++", "b/"), body.split("\n")


def _patch_name(header, mark, prefix):
    """The path a patch's file header gives the side `mark` names, or None for /dev/null."""
    found = re.search(rf"^{re.escape(mark)} (.*?)\t?$", header, re.M)
    name = found.group(1) if found else ""
    if name.startswith('"'):
        name = codecs.escape_decode(name[1:-1])[0].decode(errors="replace")
    return name[len(prefix):] if name.startswith(prefix) else None


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
