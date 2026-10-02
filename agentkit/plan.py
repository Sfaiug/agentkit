"""A session's plan: one line per outcome, with the check that proves it.

`ak plan add "<outcome>" --check '<cmd>'` runs the check on a clean checkout of the project's
default branch and refuses one that already passes there: a check that passes before the work
proves nothing.  `--eye` is an outcome only the owner can judge; `ak plan tick <n>` ticks it on
their word.  `ak plan` lists the lines, numbered.  The plan is the seat's `plan-<seat>.md`, the
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
    """The checkout the seat is filed under: its plan's checks run on that project."""
    record = config.session_records().get(name) or {}
    repo = record.get("repo")
    if not repo or not (Path(repo) / ".git").exists():
        raise config.Error(f"{name} is filed under no project; run `ak orch project <checkout>` "
                           "first")
    return Path(repo)


def fails_on_main(repo, cmd):
    """Whether `cmd` fails on a clean checkout of the project's current default branch."""
    # Inherited routing and startup files can redirect a check or restore seat variables.
    dropped = {"BASH_ENV", "ENV", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
               "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}
    env = {key: value for key, value in config.child_env().items()
           if key not in dropped and not key.startswith(("AGENTKIT_", "AK_"))}
    env["GIT_TERMINAL_PROMPT"] = "0"

    def git(*args):
        try:
            result = subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
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
    config.TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.TMP, prefix="plan-") as tmp:
        tree = Path(tmp) / "main"
        git("worktree", "add", "--detach", str(tree), base)
        try:
            proc = subprocess.Popen(["bash", "-c", cmd], cwd=tree, env=env, text=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True)
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
        finally:
            git("worktree", "remove", "--force", str(tree))
    return proc.returncode != 0


def add(name, what, check=None):
    what = " ".join(what.split())
    if not what or "·" in what:
        raise config.Error("an outcome is plain words without `·`")
    repo = project(name)
    if check is not None:
        check = check.strip()
        if len(check.splitlines()) != 1 or "`" in check:
            raise config.Error("a check is one shell command without backticks or line breaks")
        if not fails_on_main(repo, check):
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
    if not found or found["check"]:
        raise config.Error("only a --eye line can be ticked on the owner's word")
    if not text[at].lstrip().startswith("- [ ]"):
        raise config.Error(f"plan line {number} is already done")
    line = text[at].replace("- [ ]", "- [x]", 1)
    text[at] = line + f" · done your yes {time.strftime('%Y-%m-%d %H:%M')}"
    write(name, text)
    return text[at]


def main(argv):
    if command_help.show("plan", argv):
        return 0
    name = seat()
    if not argv:
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
    raise config.Error(command_help.COMMANDS["plan"][0])
