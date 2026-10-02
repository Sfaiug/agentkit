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

from . import command_help, config

CHECK_LIMIT = 600    # seconds a check may take on the default branch before it counts as failing
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
    """The checkout the seat is filed under: its plan's checks run on that project."""
    record = config.session_records().get(name) or {}
    repo = record.get("repo")
    if not repo or not (Path(repo) / ".git").exists():
        raise config.Error(f"{name} is filed under no project; run `ak orch project <checkout>` "
                           "first")
    return Path(repo)


def fails_on_main(repo, cmd):
    """(failed, its last output line) for `cmd` on a clean checkout of the default branch."""
    from . import run   # here, not at the top: run is the loop, this a seat's small verb
    try:
        run.git_out(repo, "fetch", "-q", "origin", timeout=60)
    except run.Stopped:
        pass                     # an old origin ref still names a default branch to check on
    base = run.default_base(repo, lambda _line: None)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AGENTKIT_", "AK_"))}
    config.TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=config.TMP, prefix="plan-") as tmp:
        tree = Path(tmp) / "main"
        run.git(repo, "worktree", "add", "--detach", str(tree), base)
        try:
            proc = subprocess.Popen(["bash", "-c", cmd], cwd=tree, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            try:
                out, _ = proc.communicate(timeout=CHECK_LIMIT)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                return True, f"stopped after {CHECK_LIMIT} s"
        finally:
            run.git_out(repo, "worktree", "remove", "--force", str(tree))
    last = next((line for line in reversed(out.splitlines()) if line.strip()), "")
    return proc.returncode != 0, last


def add(name, what, check=None):
    what = " ".join(what.split())
    if not what or "·" in what:
        raise config.Error("an outcome is plain words without `·`")
    repo = project(name)
    if check is not None:
        check = " ".join(check.split("\n")).strip()
        if not check or "`" in check:
            raise config.Error("a check is one shell command without backticks")
        failed, last = fails_on_main(repo, check)
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
