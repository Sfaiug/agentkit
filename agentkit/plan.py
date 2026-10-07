"""A session's plan: one line per outcome, with the check that proves it.

`ak plan add "<outcome>" --check '<cmd>'` runs the check on a clean checkout of the project's
default branch and refuses one that already passes there: a check that passes before the work
proves nothing, and one that never finishes there could never tick.  `--eye` is an outcome only
the owner can judge; `ak plan tick <n>` ticks it on their word.  `ak plan check <n> '<cmd>'`
puts another check in a line's place -- the seat's own test where a review follow-up came
checked by the reviewer's probe -- when it failed on the default branch as that was when the
line was written.  `ak plan` ticks each check line whose check now passes on its project's
default branch, then lists the lines, numbered, and `ak notify done` runs every check again and
waits for every line.  The plan is the seat's `plan-<seat>.md`, the
file the menu's bar counts, and a line names its outcome, its check (or `your eye`), the
project and when it was written:

    - [ ] each session sees its project · check: `python3 tests/test_x.py` · agentkit · written 2026-10-02 12:40
"""

import fcntl
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import command_help, config, terminal

CHECK_LIMIT = 600    # an unfinished check proves nothing
EYE = "your eye"
LINE = re.compile(r"^- \[(?P<mark>[ x])\] (?P<what>.+?) · (?:check: `(?P<check>[^`]+)`|"
                  + EYE + r") · (?P<project>.+?) · written (?P<when>\d{4}-\d\d-\d\d \d\d:\d\d)"
                  r"(?: · done (?P<done>.+))?$")


def seat():
    name = config.current_session()
    if not name:
        raise config.Error("ak plan belongs to a session; run it inside one")
    return config.resolve_session(name)


def names(name):
    """The names a seat's plan is read under: the one it goes by now, then every name whose
    rename pointer leads there."""
    current = config.resolve_session(name)
    return [current, *(old for old, now in config.session_aliases().items() if now == current)]


def forget(name):
    """Remove every plan the name reads (`path`): a seat that takes a name -- made under it,
    or renamed into a free one -- starts without the plan a gone seat left there."""
    for each in names(name):
        config.plan_path(each).unlink(missing_ok=True)


def path(name):
    """The session's plan file: of its name and the names it was renamed from, the one
    written last -- a seat renamed still writes under the name it was launched with.  Read
    for the name the seat goes by now, and looked for again if a rename lands meanwhile."""
    while True:
        current, *_ = every = names(name)
        found = []
        for each in every:
            try:
                plan = config.plan_path(each)
                found.append((plan.stat().st_mtime, plan))
            except (FileNotFoundError, config.Error):
                continue
            except OSError as exc:      # a plan nothing can look at proves nothing done
                raise config.Error(f"cannot read the plan {plan}: {exc}") from None
        if config.resolve_session(name) == current:
            return max(found)[1] if found else config.plan_path(current)


_HELD = threading.local()


@contextmanager
def held(name):
    """The plan's lock, held from a read to its write by every writer -- `add`, `tick` and
    `verify` -- so none writes back a plan another changed meanwhile.  It is the seat's own
    lock (`notify.session_lock`), which a rename takes too and which settles on the name the
    seat goes by now: under it no rename moves the plan, and that name is what it yields.
    A writer inside it that took it again would wait on itself forever: that is an error."""
    from . import notify
    taken = getattr(_HELD, "names", set())
    if config.resolve_session(name) in taken:
        raise config.Error(f"the plan of {name} is already held here; a plan write cannot nest")
    with notify.session_lock(name) as current:
        _HELD.names = taken | {current}
        try:
            yield current
        finally:
            _HELD.names = taken


def lines(name):
    """The plan's lines; none when it has no plan, and an error when it has one nothing can
    read -- an unread plan proves nothing done."""
    plan = path(name)
    try:
        return plan.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise config.Error(f"cannot read the plan {plan}: {exc}") from None


def open_lines(name):
    """The plan's open lines `ak plan` wrote, each naming the project it is on, read under the
    plan's lock so a rename never moves the plan out from under the read."""
    with held(name) as current:
        return [line.strip() for line in lines(current)
                if LINE.match(line.strip()) and is_open(line)]


def write(name, text_lines):
    path_ = path(name)
    path_.parent.mkdir(parents=True, exist_ok=True)
    fresh = path_.with_name(path_.name + ".new")
    fresh.write_text("".join(f"{line}\n" for line in text_lines), encoding="utf-8")
    fresh.replace(path_)


def project_of(name):
    """The checkout the seat is filed under, read under the seat's lock with the name it goes
    by now -- a rename takes the same lock: a line it writes names that project."""
    with held(name) as current:
        record = config.session_records().get(current) or {}
    repo = record.get("repo")
    if not repo or not (Path(repo) / ".git").exists():
        raise config.Error(f"{name} is filed under no project; run `ak orch project <checkout>` "
                           "first")
    return Path(repo)


def git_env():
    """The environment git and a check run in: nothing inherited routes them to another
    repository or brings back seat variables."""
    dropped = {"BASH_ENV", "ENV", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
               "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}
    env = {key: value for key, value in config.child_env().items()
           if key not in dropped and not key.startswith(("AGENTKIT_", "AK_"))}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def root(repo, rev="HEAD"):
    """The repository a checkout holds, as no other one can: the root commit of `rev` there
    (the first of several), abbreviated; None where it has none to read."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-list", "--max-parents=0", rev],
                             capture_output=True, text=True, timeout=30, env=git_env(),
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    roots = sorted(out.stdout.split()) if out.returncode == 0 else []
    return roots[0][:12] if roots else None


def named(repo, found=None):
    """How a line names the checkout it was written under, for good: its path (`~` for home)
    and the repository there, by its root commit -- `found`, read in the checkout its check
    ran in, where it has one."""
    path = repo.resolve()
    try:
        shown = f"~/{path.relative_to(Path.home().resolve())}"
    except ValueError:
        shown = str(path)
    found = found or root(repo)
    return f"{shown}#{found}" if found else shown


def place(name, project):
    """Where a line's check runs: the checkout it names, wherever the seat is filed now, and
    only while that checkout's repository still holds the root commit the line recorded -- a
    path moved or reused, a name another checkout shares, proves nothing, and a branch
    checked out there changes nothing.  A line from before lines
    named a path names the seat's checkout by name."""
    if "/" not in project:
        try:
            repo = project_of(name)
        except config.Error:
            return None
        return repo if project == repo.name else None
    shown, _, written = project.rpartition("#") if "#" in project else (project, "", "")
    path = Path(shown).expanduser()
    if not path.is_absolute() or not (path / ".git").exists():
        return None
    return path if written and holds(path, written) else None


def holds(repo, commit, history=None):
    """Does that checkout's repository hold that commit -- the root its line recorded --
    whichever branch is checked out there?  With `history`, that revision must descend from
    it: a remote changed to another repository brings that one's history into the same
    objects, the old root still among them, so what a check runs on is held to its own."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return False
    test = (["merge-base", "--is-ancestor", commit, history] if history
            else ["cat-file", "-e", f"{commit}^{{commit}}"])
    try:
        return subprocess.run(["git", "-C", str(repo), *test],
                              capture_output=True, timeout=30, env=git_env(),
                              stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@contextmanager
def verifying(name):
    """One verification of the seat's plan at a time, from its read to its write-back, so a
    later one starts from the plan the last one left and on main as it is by then -- an older
    listing's result never lands over a newer one's.  The lock is a seat file a rename moves;
    one moved meanwhile is taken again where it is now."""
    while True:
        path = config.seat_file("verify", config.resolve_session(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            # checked under the seat's lock, which a rename holds from its new name to its
            # last move: the file held is the one the seat's name reaches, never one a rename
            # is about to replace
            with held(name) as current:
                try:
                    now = config.seat_file("verify", current).stat()
                    mine = os.fstat(fh.fileno())
                    same = (now.st_dev, now.st_ino) == (mine.st_dev, mine.st_ino)
                except OSError:
                    same = False
            if same:
                yield
                return


@contextmanager
def default_branch(repo, written=None):
    """(its commit as `<sha12> <subject>`, the environment a check runs in, `checkout`): the
    project's current default branch, fetched first -- or, with `written` (a line's
    `%Y-%m-%d %H:%M`), its last commit by the end of that minute.  `checkout()` is a clean
    checkout of that commit made for one check and removed after it, so nothing one check writes or
    moves -- files, HEAD, a submodule -- is there for the next.  A check gets the project's
    env file (`config.repo_env`), as a run's checks do: what git does not hold, such as the
    project's interpreter, it names there (ATLAS's `ATLAS_PYTHON`)."""
    env = {**git_env(), **config.repo_env(repo)}

    def git(*args, cwd=repo):
        try:
            result = subprocess.run(["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", *args],
                                    env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, errors="replace", timeout=60)
        except subprocess.TimeoutExpired:
            raise config.Error(f"cannot check {repo.name}'s default branch: git did not finish") from None
        if result.returncode:
            raise config.Error(f"cannot check {repo.name}'s default branch: {result.stderr.strip()}")
        return result.stdout.strip()

    git("fetch", "-q", "origin")
    git("remote", "set-head", "origin", "--auto")
    base = git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    sha = git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if written:
        sha = git("rev-list", "-1", "--first-parent", f"--before={written}:59", sha)
        if not sha:
            raise config.Error(f"{repo.name}'s default branch has no commit from {written}")
    commit = git("log", "-1", "--format=%h %s", "--abbrev=12", sha)
    config.TMP.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def checkout():
        with tempfile.TemporaryDirectory(dir=config.TMP, prefix="plan-") as tmp:
            tree = Path(tmp) / "main"
            try:
                git("worktree", "add", "--detach", str(tree), sha)
                yield tree
            finally:
                if tree.exists():
                    try:
                        git("worktree", "remove", "--force", str(tree))
                    except config.Error:
                        # one a check put a submodule in: git will not remove it, so it goes
                        shutil.rmtree(tree, ignore_errors=True)
                        git("worktree", "prune")

    def stop(signum, _frame):
        # Tool timeouts send SIGTERM; repeated requests must let cleanup finish.
        signal.signal(signum, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield commit, env, checkout
    finally:
        signal.signal(signal.SIGTERM, previous)


def fails(tree, cmd, env):
    """Whether `cmd` fails in `tree`; one that does not finish within CHECK_LIMIT is an error."""
    proc = subprocess.Popen(["bash", "-c", cmd], cwd=tree, env=env, text=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        proc.wait(timeout=CHECK_LIMIT)
    except subprocess.TimeoutExpired:
        raise config.Error(f"this check did not finish within {CHECK_LIMIT} s; "
                           "an unfinished check proves nothing") from None
    finally:
        # No child may outlive the checkout, including after an interruption.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    return proc.returncode != 0


def fails_on_main(repo, cmd, written=None):
    """(Whether `cmd` fails on a clean checkout of the project's default branch, now or as it
    was when a line was `written`, that checkout's root commit): the repository a line names
    is the one its check ran in."""
    with default_branch(repo, written) as (_commit, env, checkout), checkout() as tree:
        return fails(tree, cmd, env), root(tree)


# a list line with a box, however it is spelled: `- [ ]`, `* [X]`, `1.  [done]` -- any
# bracket opening an item, a link's `[text](url)` aside
BOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[^\]\n]*\](?!\()")
# what marks a line `ak plan` wrote, however its spacing was changed by hand since
WRITTEN = re.compile(r"\bcheck\s*:|·\s*written\b|·\s*your\s+eye\b|·\s*done\b", re.I)
# the done each proof stamps: an eye line's the owner's yes (`ak plan tick`), a check line's
# the commit its check passed on
YES = re.compile(r"your yes \d{4}-\d\d-\d\d \d\d:\d\d$")
PASSED_ON = re.compile(r"[0-9a-f]{7,40}(?: |$)")


def is_open(line):
    """A box line that does not read as done.  Done is `- [x] ` and then either a line
    `ak plan` wrote with the done its proof stamped -- its check's commit, or the owner's yes
    on an eye line (`ak plan tick`) -- or a hand-kept line with none of its fields; every other
    box -- unticked, ticked by hand past its proof, or spelled any other way -- is open, since
    nothing proved it.  A line with no box is no plan line."""
    line = line.strip()
    found = LINE.match(line)
    if found:
        stamp = YES if found["check"] is None else PASSED_ON
        return found["mark"] != "x" or not stamp.match(found["done"] or "")
    if line.startswith("- [x] ") and not WRITTEN.search(line):
        return False
    return bool(BOX.match(line))


def undone(line, found):
    """The stripped line without its trailing done field: the one `LINE` parsed, never a
    ` · done ` that a check command itself holds."""
    return line[:found.start("done") - len(" · done ")] if found["done"] is not None else line


def identity(line):
    """A check line's own words -- outcome, check, project, when written -- without its box
    and done field, which a tick changes; None for any other line."""
    found = LINE.match(line.strip())
    return undone(line.strip(), found)[6:] if found and found["check"] else None


def verify(name, every=False):
    """The open lines left once the plan's checks ran (`_verify`)."""
    return _verify(name, every)[0]


def _verify(name, every):
    """Run the open check lines on their project's default branch now: each that passes is
    ticked, naming that commit, each check from a clean checkout of it.  With `every`, ticked
    check lines run too, and one that fails there -- or does not finish, or names a project
    this host has no checkout of -- is open again: a tick is what its check says today, not
    what a line's text claims.  The results are written onto the plan as it reads after the
    checks, each onto its own line however another listing ticked it meanwhile, so a line
    added meanwhile stays and these results are the ones the open lines are counted from.
    Returns the plan's open lines left."""
    with verifying(name):
        return _verify_held(name, every)


def _verify_held(name, every):
    checks = {}
    with held(name) as current:
        snapshot = lines(current)
    for line in snapshot:
        found = LINE.match(line.strip())
        if found and found["check"] and (every or is_open(line)):
            # lines alike are one check, run once: its result is every one of theirs
            checks.setdefault(found["project"], {})[identity(line)] = found
    results = {}
    for project_, group in checks.items():
        repo = place(name, project_)
        if repo is None:
            for bare in group if every else ():
                results[bare] = f"- [ ] {bare}"
            continue
        written = project_.rpartition("#")[2] if "#" in project_ else None
        with default_branch(repo) as (commit, env, checkout):
            for bare, found in group.items():
                try:
                    with checkout() as tree:     # its own: never another check's leftovers
                        # the repository the line recorded, in the very tree it runs in
                        passed = ((not written or holds(tree, written, "HEAD"))
                                  and not fails(tree, found["check"], env))
                except config.Error:
                    passed = False
                results[bare] = f"- [x] {bare} · done {commit}" if passed else f"- [ ] {bare}"
    # the checks ran outside the lock; the write-back reads the plan again inside it
    with held(name) as current:
        present = lines(current)
        text = [results.get(identity(line), line) for line in present]
        # only onto the plan it checked: one that lost those lines is never written over,
        # let alone with an empty plan
        if any(identity(line) in results for line in present):
            write(current, text)
    # for done, a check line that arrived after the snapshot was proved by nobody here
    unproven = [line for line in text if every and identity(line) and identity(line) not in results]
    return [line.strip() for line in text if is_open(line) or line in unproven], results


def require_done(name):
    """Refuse a done while the plan still has open lines, after running every check once more;
    the check lines those checks proved, for `still_done`."""
    left, results = _verify(name, every=True)
    if left:
        raise config.Error(f"{len(left)} plan line(s) still open, first: {left[0]}; "
                           "a check line is done when its check passes on the default branch "
                           "(one that no longer tests the outcome takes your own test: "
                           "`ak plan check N`), an eye line on the user's word (`ak plan tick N`)")
    return {bare for bare, line in results.items() if line.startswith("- [x]")}


def still_done(name, proven):
    """Run under the seat's lock as its done is recorded: the plan as it reads now has no
    open line and no check line the done's own checks did not prove -- one added or ticked
    while they ran is not done."""
    left = [line.strip() for line in lines(name) if is_open(line)
            or (identity(line) and identity(line) not in proven)]
    if left:
        raise config.Error(f"{len(left)} plan line(s) open or unproven since the checks ran, "
                           f"first: {left[0]}; run `ak notify done` again")


def add(name, what, check=None, repo=None, proven=None):
    """Append an open line to the seat's plan, or return the open line that already holds this
    check in this project.  A review follow-up names the run's project as `repo`, and as
    `proven` the commit its check already failed on (the review's base): the check is not run
    again first, and that commit's history names the repository, whatever is checked out."""
    what = " ".join(what.split())
    if not what or "·" in what:
        raise config.Error("an outcome is plain words without `·`")
    repo = Path(repo) if repo else project_of(name)
    found = None
    if check is not None:
        check = one_command(check)
        if proven:
            found = root(repo, proven)
            if not found:
                raise config.Error(f"{repo.name} does not hold {proven[:12]}, the commit this "
                                   "check failed on")
        else:
            failing, found = fails_on_main(repo, check)
            if not failing:
                raise config.Error(f"this check already passes on {repo.name}'s default "
                                   "branch, so it proves nothing; write one that fails until "
                                   "the work is done")
    where = named(repo, found)
    if "·" in where:
        raise config.Error(f"{where}: a project a line names holds no `·`")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    proof = f"check: `{check}`" if check is not None else EYE
    line = f"- [ ] {what} · {proof} · {where} · written {stamp}"
    with held(name) as current:
        text = lines(current)
        for old in text:
            parsed = LINE.match(old.strip())
            if (check is not None and parsed and is_open(old)
                    and parsed["check"] == check and parsed["project"] == where):
                return old.strip()     # an open line already holds this check here
        write(current, [*text, line])
    return line


def one_command(check):
    check = check.strip()
    if len(check.splitlines()) != 1 or "`" in check:
        raise config.Error("a check is one shell command without backticks or line breaks")
    return check


def numbered(text, number):
    """Where plan line `number`, as `ak plan` lists them, is in the plan's `text`."""
    listed = [at for at, line in enumerate(text) if line.lstrip().startswith("- [")]
    if not 1 <= number <= len(listed):
        raise config.Error(f"no plan line {number}; `ak plan` lists them")
    return listed[number - 1]


def recheck(name, number, check):
    """Put `check` in place of plan line `number`'s check, the line open again until it
    passes.  It must have failed where the line's check had to: on the line's project as its
    default branch was when the line was written -- the code before the work, however long ago
    the work landed."""
    check = one_command(check)
    with held(name) as current:
        text = lines(current)
        line = text[numbered(text, number)].strip()
    found = LINE.match(line)
    if not (found and found["check"]):
        raise config.Error("only a check line takes another check")
    repo = place(name, found["project"])
    if not repo:
        raise config.Error(f"this host has no checkout of {found['project']}")
    if not fails_on_main(repo, check, found["when"])[0]:
        raise config.Error(f"this check already passed on {repo.name}'s default branch when "
                           "the line was written, so it proves nothing; write one that failed "
                           "until the work was done")
    # the line as it reads, open and with only its check changed
    new = "- [ ] " + line[6:found.start("check")] + check + undone(line, found)[found.end("check"):]
    with held(name) as current:
        text = lines(current)
        same = [at for at, old in enumerate(text) if old.strip() == line]
        if not same:
            raise config.Error(f"plan line {number} changed while its new check ran; "
                               "run `ak plan check` again")
        text[same[0]] = text[same[0]][:len(text[same[0]]) - len(text[same[0]].lstrip())] + new
        write(current, text)
    return new


def tick(name, number):
    with held(name) as current:
        return _tick(current, number)


def _tick(name, number):
    text = lines(name)
    at = numbered(text, number)
    found = LINE.match(text[at].strip())
    if not found or found["check"]:
        raise config.Error("only a --eye line can be ticked on the owner's word")
    if not text[at].lstrip().startswith("- [ ]"):
        raise config.Error(f"plan line {number} is already done")
    # a line reopened by hand keeps the done it had: this yes replaces it
    line = text[at].strip()
    if found["done"] is not None:
        line = line[:found.start("done")].removesuffix(" · done ")
    text[at] = (text[at][:len(text[at]) - len(text[at].lstrip())]
                + line.replace("- [ ]", "- [x]", 1)
                + f" · done your yes {time.strftime('%Y-%m-%d %H:%M')}")
    write(name, text)
    return text[at]


def main(argv):
    if command_help.show("plan", argv):
        return 0
    name = seat()
    if not argv:
        verify(name)
        listed = [line.strip() for line in lines(name) if line.lstrip().startswith("- [")]
        number_width = max(2, len(str(len(listed))))
        room = max(1, terminal.width() - number_width - 2)
        for number, line in enumerate(listed, 1):
            wrapped = terminal.wrap(line, room)
            print(terminal.table_row([str(number), wrapped[0]], [number_width, room], right=(0,)))
            for continuation in wrapped[1:]:
                print(" " * (number_width + 2) + continuation)
        return 0
    if argv[0] == "add" and len(argv) == 4 and argv[2] == "--check":
        print(add(name, argv[1], argv[3]))
        return 0
    if argv[0] == "add" and len(argv) == 3 and argv[2] == "--eye":
        print(add(name, argv[1]))
        return 0
    if argv[0] == "tick" and len(argv) == 2 and argv[1].isdigit():
        print(tick(name, int(argv[1])))
        return 0
    if argv[0] == "check" and len(argv) == 3 and argv[1].isdigit():
        print(recheck(name, int(argv[1]), argv[2]))
        return 0
    raise config.Error(command_help.COMMANDS["plan"][0])
