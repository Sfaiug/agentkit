"""A session's plan: one line per outcome, with the check that proves it.

`ak plan add "<outcome>" --check '<cmd>'` runs the check on a clean checkout of the project's
default branch and refuses one that already passes there: a check that passes before the work
proves nothing, and one that runs past CHECK_LIMIT there is refused too: it could never tick.
`--eye` is an outcome only the owner can judge; `ak plan tick <n>` ticks it on their word.  `ak plan` lists the lines, numbered.  The plan is the seat's `plan-<seat>.md`, the
file the menu's bar counts, and a line names its outcome, its check (or `your eye`), the
project and when it was written:

    - [ ] each session sees its project · check: `python3 tests/test_x.py` · agentkit · written 2026-10-02 12:40
"""

import os
import re
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import command_help, config

CHECK_LIMIT = 600    # seconds a check may take on the default branch; past it, it proves nothing
EYE = "your eye"
LINE = re.compile(r"^- \[(?P<mark>[ x])\] (?P<what>.+?) · (?:check: `(?P<check>[^`]+)`|"
                  + EYE + r") · (?P<project>[^·]+?) · written (?P<when>\d{4}-\d\d-\d\d \d\d:\d\d)"
                  r"(?: · done (?P<done>.+))?$")


def seat():
    name = config.current_session()
    if not name:
        raise config.Error("ak plan belongs to a session; run it inside one")
    return config.resolve_session(name)


def lines(name):
    try:
        return config.plan_path(name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def write(name, text_lines):
    path = config.plan_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = path.with_name(path.name + ".new")
    fresh.write_text("".join(f"{line}\n" for line in text_lines), encoding="utf-8")
    fresh.replace(path)


def project(name):
    """The checkout the seat is filed under: a line it writes names that project."""
    record = config.session_records().get(name) or {}
    repo = record.get("repo")
    if not repo or not (Path(repo) / ".git").exists():
        raise config.Error(f"{name} is filed under no project; run `ak orch project <checkout>` "
                           "first")
    return Path(repo)


def checkouts():
    """Every project a line may name, by name: the checkouts seats are filed under, and those
    in the code directory.  A line runs its check on the project it names, wherever the seat
    is filed now."""
    found = {git.parent.name: git.parent for git in sorted(config.CODE.glob("*/.git"))}
    for record in config.session_records().values():
        repo = record.get("repo")
        if repo and (Path(repo) / ".git").exists():
            found[Path(repo).name] = Path(repo)
    return found


@contextmanager
def default_branch(repo):
    """(checkout, its commit as `<sha12> <subject>`): a clean checkout of the default branch,
    fetched first, removed after."""
    from . import run   # here, not at the top: run is the loop, this a seat's small verb
    try:
        run.git_out(repo, "fetch", "-q", "origin", timeout=60)
    except run.Stopped:
        pass                     # an old origin ref still names a default branch to check on
    base = run.default_base(repo, lambda _line: None)
    config.TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.TMP, prefix="plan-") as tmp:
        tree = Path(tmp) / "main"
        run.git(repo, "worktree", "add", "--detach", str(tree), base)
        try:
            yield tree, run.git(tree, "log", "-1", "--format=%h %s", "--abbrev=12")
        finally:
            run.git_out(repo, "worktree", "remove", "--force", str(tree))


def fails(tree, cmd):
    """(failed, its last output line) for `cmd` run in `tree` without the seat's variables;
    a check stopped at CHECK_LIMIT has failed with the last line None."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AGENTKIT_", "AK_"))}
    proc = subprocess.Popen(["bash", "-c", cmd], cwd=tree, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=CHECK_LIMIT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return True, None
    last = next((line for line in reversed(out.splitlines()) if line.strip()), "")
    return proc.returncode != 0, last


def is_open(line):
    """Not done: unticked, or a check line ticked by hand rather than by its check."""
    line = line.strip()
    found = LINE.match(line)
    return line.startswith("- [ ]") or bool(
        found and found["check"] and found["mark"] == "x" and not found["done"])


def verify(name, every=False):
    """Run the open check lines on their project's default branch now: each that passes is
    ticked, naming that commit.  With `every`, ticked check lines run too, and one that fails
    there is open again: a tick is what its check says today, not what a line's text claims.
    Returns the plan's open lines left."""
    text = lines(name)
    checks = {}
    for at, line in enumerate(text):
        found = LINE.match(line.strip())
        if found and found["check"] and (every or is_open(line)):
            checks.setdefault(found["project"], []).append((at, found))
    places = checkouts() if checks else {}
    for named, group in checks.items():
        if named not in places:
            continue                 # a project this host has no checkout of proves nothing
        with default_branch(places[named]) as (tree, commit):
            for at, found in group:
                bare = re.sub(r" · done .+$", "", text[at].strip()[6:])
                passed = not fails(tree, found["check"])[0]
                text[at] = (f"- [x] {bare} · done {commit}" if passed else f"- [ ] {bare}")
    if checks:
        write(name, text)
    return [line.strip() for line in text if is_open(line)]


def require_done(name):
    """Refuse a done while the plan still has open lines, after running every check once more."""
    left = verify(name, every=True)
    if left:
        raise config.Error(f"{len(left)} plan line(s) still open, first: {left[0]}; "
                           "a check line is done when its check passes on the default branch, "
                           "an eye line on the user's word (`ak plan tick N`)")


def add(name, what, check=None):
    what = " ".join(what.split())
    if not what or "·" in what:
        raise config.Error("an outcome is plain words without `·`")
    repo = project(name)
    if check is not None:
        check = " ".join(check.split("\n")).strip()
        if not check or "`" in check:
            raise config.Error("a check is one shell command without backticks")
        with default_branch(repo) as (tree, _):
            failed, last = fails(tree, check)
        if last is None:
            raise config.Error(f"this check did not finish within {CHECK_LIMIT} s on "
                               f"{repo.name}'s default branch, so it could never tick; name "
                               "the specific test that proves this outcome")
        if not failed:
            raise config.Error(f"this check already passes on {repo.name}'s default branch, so "
                               "it proves nothing; write one that fails until the work is done")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    proof = f"check: `{check}`" if check is not None else EYE
    line = f"- [ ] {what} · {proof} · {repo.name} · written {stamp}"
    write(name, [*lines(name), line])
    return line


def tick(name, number):
    text = lines(name)
    open_lines = [at for at, line in enumerate(text) if line.lstrip().startswith("- [")]
    if not 1 <= number <= len(open_lines):
        raise config.Error(f"no plan line {number}; `ak plan` lists them")
    at = open_lines[number - 1]
    found = LINE.match(text[at].strip())
    if found and found["check"]:
        raise config.Error("a line with a check is ticked by ak once its check passes on the "
                           "default branch")
    if not text[at].lstrip().startswith("- [ ]"):
        raise config.Error(f"plan line {number} is already done")
    line = text[at].replace("- [ ]", "- [x]", 1)
    text[at] = line + (f" · done your yes {time.strftime('%Y-%m-%d %H:%M')}" if found else "")
    write(name, text)
    return text[at]


def main(argv):
    if command_help.show("plan", argv):
        return 0
    name = seat()
    if not argv:
        verify(name)
        for number, line in enumerate((line for line in lines(name)
                                       if line.lstrip().startswith("- [")), 1):
            print(f"{number:>2}  {line.strip()}")
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
    raise config.Error(command_help.COMMANDS["plan"][0])
