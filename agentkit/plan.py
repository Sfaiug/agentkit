"""A session's plan: one line per outcome, with the check that proves it.

`ak plan add "<outcome>" --check '<cmd>'` runs the check on a clean checkout of the project's
default branch and refuses one that already passes there: a check that passes before the work
proves nothing, and one that never finishes there could never tick; in a turn that reached the
live host, one that passes is written done, the work being done there.  `ak plan check <n> '<cmd>'`
puts another check in a line's place -- the seat's own test where a review follow-up came
checked by the reviewer's probe -- when it fails on the commit the line's check was proven
failing on, which the line names (a line from before lines named one takes it unproven).  `ak plan` ticks each check line whose check now passes on
its project's default branch, then lists the lines, numbered; with none open the seat's work is
done (`finished`).  The plan is the seat's `plan-<seat>.md`, the
file the menu's bar counts, and a line names its outcome, its check, the project, when it was written and, for a check, the commit it failed on then:

    - [ ] each session sees its project · check: `python3 tests/test_x.py` · agentkit · written 2026-10-02 12:40 on 0123456789ab
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

from . import command_help, config, gitcall, guard, parsed, terminal

CHECK_LIMIT = 600    # an unfinished check proves nothing
# an eye line, from before every line had a check, reads done: how a change looks is the
# owner's to judge once it is live, never a line the seat waits on
EYE = "your eye"
DEFERRED = " · deferred"
STAMP = "%Y-%m-%d %H:%M"
LINE = re.compile(r"^- \[(?P<mark>[ x])\] (?P<what>.+?) · (?:check: `(?P<check>[^`]+)`|"
                  + EYE + r") · (?P<project>.+?)(?P<deferred>" + re.escape(DEFERRED) + r")? · written "
                  r"(?P<when>\d{4}-\d\d-\d\d \d\d:\d\d)"
                  r"(?: on (?P<base>[0-9a-f]{7,40}))?(?: · done (?P<done>.+))?$")


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


def _text(plan):
    return plan.read_text(encoding="utf-8")


def lines(name):
    """The plan's lines; none when it has no plan, and an error when it has one nothing can
    read -- an unread plan proves nothing done.  Read again only once it changed (`parsed`)."""
    plan = path(name)
    try:
        return parsed.read(plan, _text).splitlines()
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
    checked out there changes nothing."""
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
def default_branch(repo, at=None):
    """(its commit as `<sha12> <subject>`, the environment a check runs in, `checkout`): the
    project's current default branch, fetched first -- or, with `at`, that commit, the one a
    line's check was proven failing on.  `checkout()` is a clean checkout of that commit made
    for one check and removed after it, so nothing one check writes or moves -- files, HEAD, a
    submodule -- is there for the next.  It sits beside runs' checkouts in `config.WT`, as
    the landing line's do: ak's history counts a repository under `.agentkit/tmp` as a test
    suite's throwaway, so a test keeping its fixtures in its own checkout read differently
    there than in a run.  A check gets the project's env file
    (`config.repo_env`), as a run's checks do: what git does not hold, such as the project's
    interpreter, it names there (ATLAS's `ATLAS_PYTHON`)."""
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

    gitcall.no_auto_gc(repo)
    git("fetch", "-q", "origin")
    git("remote", "set-head", "origin", "--auto")
    base = git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    sha = git("rev-parse", "--verify", f"{at or base}^{{commit}}")
    commit = git("log", "-1", "--format=%h %s", "--abbrev=12", sha)
    config.WT.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def checkout():
        with tempfile.TemporaryDirectory(dir=config.WT, prefix="plan-") as tmp:
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


def fails_on_main(repo, cmd, at=None):
    """(Whether `cmd` fails on a clean checkout of the project's default branch, or of commit
    `at`, that checkout's root commit, its commit): the repository a line names is the one
    its check ran in, and the commit the one it failed on."""
    with default_branch(repo, at) as (commit, env, checkout), checkout() as tree:
        return fails(tree, cmd, env), root(tree), commit.split()[0]


# a list line with a box, however it is spelled: `- [ ]`, `* [X]`, `1.  [done]` -- any
# bracket opening an item, a link's `[text](url)` aside
BOX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[^\]\n]*\](?!\()")
# what marks a line `ak plan` wrote, however its spacing was changed by hand since
WRITTEN = re.compile(r"\bcheck\s*:|·\s*written\b|·\s*your\s+eye\b|·\s*done\b", re.I)
# the done a check line's proof stamps: the commit its check passed on
PASSED_ON = re.compile(r"[0-9a-f]{7,40}(?: |$)")


def is_open(line):
    """A box line that does not read as done.  Done is `- [x] ` and then either a check line
    `ak plan` wrote with the commit its check passed on, or a hand-kept line with none of its
    fields; an eye line is done however it is ticked (`EYE`); every other
    box -- unticked, ticked by hand past its proof, or spelled any other way -- is open, since
    nothing proved it.  A line with no box is no plan line."""
    line = line.strip()
    found = LINE.match(line)
    if found:
        return found["check"] is not None and (found["mark"] != "x"
                                               or not PASSED_ON.match(found["done"] or ""))
    if line.startswith("- [x] ") and not WRITTEN.search(line):
        return False
    return bool(BOX.match(line))


def deferred(line):
    """A line deferred to a run of its own (a review follow-up): open until its check passes,
    and what the seat owes only once no run has it (`taken`)."""
    found = LINE.match(line.strip())
    return bool(found and found["deferred"])


def owed(name, line):
    """Whether the seat owes the line, which holds its done and its turn (`stop.owed`): an
    open line, never a deferred one a run is on its way with (`taken`)."""
    return is_open(line) and not taken(name, line)


def taken(name, line, delivered=False):
    """Whether a deferred line is a run's: one of the seat's with the line's check in the
    line's project is on its way with it (`handback.open_followup`) or, with `delivered`, merged
    or found it not needed since the line was written, for the done's work (`outcomes`).
    Read with the line, never written at an ending: once the fix run ended, whichever way,
    the line is the seat's own until its check passes, which a delivery runs at once
    (`delivery`)."""
    found = LINE.match(line.strip())
    if not (found and found["deferred"]):
        return False
    repo = place(name, found["project"])
    written = time.mktime(time.strptime(found["when"], STAMP))
    from . import handback  # here, not at the top: the loop is heavy for a seat's small verb
    return bool(repo and handback.open_followup({"repo": str(repo.resolve()), "launched_session": name},
                                           "", check=found["check"],
                                           held=written if delivered else None))


def delivery(name, check):
    """A fix run of the seat delivered `check`'s line -- merged, or found it not needed: that
    line's check runs (`verify`), ticking it where its fix is on the default branch.  Where
    its check still fails, or could not run, no run has it and the seat owes it, which the
    line then says too, its deferred mark dropped as `recheck` drops it: built by the seat,
    the done lists it (`outcomes`), never taking it for that delivery's work (`taken`)."""
    try:
        verify(name, check=check)       # that line's check alone: the seat's others are its own
    except config.Error:
        pass        # unchecked: the line stays open
    mine = {line.strip() for line in lines(name) if deferred(line)
            and (LINE.match(line.strip())["check"] or "").strip() == check.strip()
            and owed(name, line)}
    if not mine:
        return
    with held(name) as current:
        text = lines(current)
        for at, line in enumerate(text):
            if line.strip() in mine:
                found = LINE.match(line.strip())
                lead = len(line) - len(line.lstrip())
                text[at] = line[:lead + found.start("deferred")] + line[lead + found.end("deferred"):]
        write(current, text)


def undone(line, found):
    """The stripped line without its trailing done field: the one `LINE` parsed, never a
    ` · done ` that a check command itself holds."""
    return line[:found.start("done") - len(" · done ")] if found["done"] is not None else line


def identity(line):
    """A check line's own words -- outcome, check, project, when written -- without its box
    and done field, which a tick changes; None for any other line."""
    found = LINE.match(line.strip())
    return undone(line.strip(), found)[6:] if found and found["check"] else None


def finished(name):
    """The words of the plan's last done line where the plan holds done work and owes none
    (`owed`): the seat's work is done, which ak reads here and nobody declares.  None for no
    plan, one with nothing done, one still owing a line, or one nothing can read."""
    try:
        text = lines(name)
    except config.Error:
        return None
    if any(owed(name, line) for line in text):
        return None
    done = _done(text)
    return done[-1] if done else None


def first_done(name):
    """The words of the plan's first done line, what the seat set out to do and did; None for no
    plan, nothing done or one nothing can read."""
    try:
        done = _done(lines(name))
    except config.Error:
        return None
    return done[0] if done else None


def _done(text):
    """The words of each done line of a plan's `text`, in order."""
    done = [line.strip() for line in text if BOX.match(line) and not is_open(line)]
    return [found["what"] if found else line.partition("] ")[2]
            for line, found in ((line, LINE.match(line)) for line in done)]


def outcomes(name, runs=True):
    """The plan's done work, independent of order, repetition, checks and renewed proof stamps;
    without `runs`, the lines a run has or delivered (`taken`) count too: every line ticked.

    An open line is no done work yet. Keep format knowledge here: old eye lines and hand-kept
    outcomes count as work too.
    """
    result = []
    for line in lines(name):
        line = line.strip()
        found = LINE.match(line)
        if found and (is_open(line) or runs and taken(name, line, delivered=True)):
            continue        # not done, or a run's: it has the line, or delivered it
        if found:
            result.append((found["project"], found["what"]))
        elif line.startswith("- [x] ") and not is_open(line):
            result.append(("", line[6:]))
    return sorted(set(result))


def verify(name, check=None):
    """Run the open check lines -- only those holding `check`, where one is given -- on their
    project's default branch now: each that passes is ticked, naming that commit, each check
    from a clean checkout of it.  The results are written onto the plan as it reads after the
    checks, each onto its own line however another listing ticked it meanwhile, so a line
    added meanwhile stays and these results are the ones the open lines are counted from.
    Returns the plan's open lines left."""
    with verifying(name):
        return _verify_held(name, check)


def _verify_held(name, check=None):
    checks = {}
    with held(name) as current:
        snapshot = lines(current)
    for line in snapshot:
        found = LINE.match(line.strip())
        if (found and found["check"] and is_open(line)
                and (check is None or found["check"].strip() == check.strip())):
            # lines alike are one check, run once: its result is every one of theirs
            checks.setdefault(found["project"], {})[identity(line)] = found
    results, passing = {}, {}
    for project_, group in checks.items():
        repo = place(name, project_)
        if repo is None:
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
                results[bare] = ticked(f"- [ ] {bare}", commit if passed else None)
                if passed:
                    passing[bare] = (repo, found, commit)
    # the checks ran outside the lock; the write-back reads the plan again inside it
    with held(name) as current:
        present = lines(current)
        text = [results.get(identity(line), line) for line in present]
        # only onto the plan it checked: one that lost those lines is never written over,
        # let alone with an empty plan
        if any(identity(line) in results for line in present):
            write(current, text)
        # only lines ticked here: one replaced while its check ran was never ticked
        ticks = [passing[bare] for bare in map(identity, present) if bare in passing]
    for repo, found, commit in ticks:
        retire(repo, found, commit)
    return [line.strip() for line in text if is_open(line)]


def retire(repo, found, commit):
    """End each run that only repeats a line just ticked on `commit`: one queued in the line's
    repository with the line's check as its follow-up's, that never held a slot
    (`slot_started_at`, which a requeue keeps), so never started -- it would keep its seat
    working until a slot frees, hours in a busy queue.  It ends as `ak run stop` ends one
    (`stop.end`); a run that started hands in not-needed."""
    from . import record, stop       # here, not at the top: the loop is heavy for a seat's small verb

    def repeats(state):
        return (state.get("state") == "queued" and state.get("slot_waiting")
                and not state.get("slot_started_at") and state.get("repo") == str(repo.resolve())
                and ((state.get("followup") or {}).get("check") or "").strip()
                == found["check"].strip())

    why = f"plan line \"{found['what']}\" ticked on {commit}: its check passes there"
    for directory in record.run_dirs():
        if repeats(record.read_state(directory) or {}):
            stop.end(directory, keep=False, why=why, only_if=repeats)


def compose(what, proof, where, deferred, stamp, base):
    """An open line as `add` writes it."""
    return (f"- [ ] {what} · {proof} · {where}" + (DEFERRED if deferred else "")
            + f" · written {stamp}" + (f" on {base}" if base else ""))


def add(name, what, check, repo=None, proven=None, deferred=False):
    """Append an open line to the seat's plan, or keep the open line that already holds this
    check in this project, deferred or the seat's own as this call asks.  A review follow-up
    names the run's project as `repo`, and as `proven` the commit its check already failed on
    (the review's base, or the reviewed commit for a defect of the change): the check is not
    run again first, and that commit's history names the repository, whatever is checked out;
    and it is `deferred` where a run has it, so the line holds no done, the seat's own where
    none has it any more."""
    what = " ".join(what.split())
    if not what or "·" in what:
        raise config.Error("an outcome is plain words without `·`")
    repo = Path(repo) if repo else project_of(name)
    check = one_command(check)
    holds_checkout(check, repo)
    passed = None
    if proven:
        found, base = root(repo, proven), proven[:12]
        if not found:
            raise config.Error(f"{repo.name} does not hold {proven[:12]}, the commit this "
                               "check failed on")
    else:
        failing, found, base = fails_on_main(repo, check)
        if not failing:
            # The owner, 26 Oct 2026: in a turn whose own ssh reached the live host, work done
            # there proves itself, so a check already passing is written done on that commit
            # and a job finished in that one turn reads `done`.
            if not guard.reached_live(name):
                raise config.Error(f"this check already passes on {repo.name}'s default "
                                   "branch, so it proves nothing; write one that fails until "
                                   "the work is done")
            passed, base = base, None
    where = named(repo, found)
    if "·" in where:
        raise config.Error(f"{where}: a project a line names holds no `·`")
    proof = f"check: `{check}`"
    with held(name) as current:
        text = lines(current)
        for index, old in enumerate(text):
            parsed = LINE.match(old.strip())
            if (parsed and is_open(old) and parsed["check"] == check
                    and parsed["project"] == where):
                # the open line already holding this check here is kept, its mark as asked
                kept = ticked(compose(parsed["what"], proof, where, deferred, parsed["when"],
                                       parsed["base"]), passed)
                if kept != old.strip():
                    write(current, [*text[:index], kept, *text[index + 1:]])
                return kept
        # on the clock a run's `finished_at` reads, which `taken` compares it with
        stamp = time.strftime(STAMP, time.localtime(time.time()))
        line = ticked(compose(what, proof, where, deferred, stamp, base), passed)
        write(current, [*text, line])
    return line


def ticked(line, commit):
    """An open `line` ticked as passing on `commit`; as it is without one."""
    return f"- [x] {line[6:]} · done {commit}" if commit else line


def one_command(check):
    check = check.strip()
    if len(check.splitlines()) != 1 or "`" in check:
        raise config.Error("a check is one shell command without backticks or line breaks")
    return check


def holds_checkout(check, repo):
    """Refuse a check whose text holds the path of the project's checkout `repo`: a check runs
    in a clean checkout of the default branch, and one that goes to `repo` tests what that
    checkout holds instead (uncommitted work, or ak's install behind main).  It reads text, not
    the shell: the path is looked for as written from `/`, `~`, `$HOME` or `${HOME}`, with every
    quote and backslash dropped from both, so any quoting of it is found and a longer name that
    starts with it (`acme-old`) is refused too.  A path the check builds as it runs (a variable,
    `..`, a link) is not seen."""
    home, paths = Path.home(), set()
    for path in {Path(repo), Path(repo).resolve()}:
        paths.add(str(path))
        for top in {home, home.resolve()}:
            if path.is_relative_to(top):
                paths |= {f"{lead}/{path.relative_to(top)}" for lead in ("~", "$HOME", "${HOME}")}
    drop = re.compile(r"[\"'\\]")
    if any(drop.sub("", path) in drop.sub("", check) for path in paths):
        shown = min(sorted(paths), key=len)
        raise config.Error(f"this check holds {shown}, the path of the project's checkout, but a "
                           "check runs in a clean checkout of its default branch: name paths "
                           "relative to the repository, as in `python3 tests/test_x.py`")


def numbered(text, number):
    """Where plan line `number`, as `ak plan` lists them, is in the plan's `text`."""
    listed = [at for at, line in enumerate(text) if line.lstrip().startswith("- [")]
    if not 1 <= number <= len(listed):
        raise config.Error(f"no plan line {number}; `ak plan` lists them")
    return listed[number - 1]


def recheck(name, number, check):
    """Put `check` in place of plan line `number`'s check, the line open again until it
    passes, and the seat's own: a line deferred to a fix run takes the seat's own test as the
    seat's, since no run has the new check.  It must fail where the line's check did: on the
    commit the line names -- the code before the work, however long ago the work landed.  A
    line from before lines named one takes it unproven, as it reads: nothing recorded where
    its check failed, and a missing proof never blocks (the owner, 7 Oct)."""
    check = one_command(check)
    with held(name) as current:
        text = lines(current)
        line = text[numbered(text, number)].strip()
    found = LINE.match(line)
    if not (found and found["check"]):
        raise config.Error("only a check line takes another check")
    repo = place(name, found["project"])
    if repo:
        holds_checkout(check, repo)
    if found["base"]:
        if not repo:
            raise config.Error(f"this host has no checkout of {found['project']}")
        if not fails_on_main(repo, check, found["base"])[0]:
            raise config.Error(f"this check already passes on {found['base']}, the commit line "
                               f"{number} names, so it proves nothing; write one that fails "
                               "until the work is done")
    # the line as it reads, open, the seat's own, with only its check changed
    new = compose(found["what"], f"check: `{check}`", found["project"], False, found["when"], found["base"])
    with held(name) as current:
        text = lines(current)
        same = [at for at, old in enumerate(text) if old.strip() == line]
        if not same:
            raise config.Error(f"plan line {number} changed while its new check ran; "
                               "run `ak plan check` again")
        text[same[0]] = text[same[0]][:len(text[same[0]]) - len(text[same[0]].lstrip())] + new
        write(current, text)
    return new


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
    if argv[0] == "check" and len(argv) == 3 and argv[1].isdigit():
        print(recheck(name, int(argv[1]), argv[2]))
        return 0
    raise config.Error(command_help.COMMANDS["plan"][0])
