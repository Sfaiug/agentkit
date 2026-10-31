"""What a project needs of the machine ak runs on, made ready by the file its `setup:` names.

A copied home carries each project's checkout, never what the machine itself holds for it:
toolchains and packages built for its processor or installed by hand.  So a project's `setup:`
names one executable file in it, run with no arguments.  Hidden here: when a setup is due -- once
on each machine (`/etc/machine-id`) for each version of that line and of that file as the
default branch has them (`config.RULES_REF`), and on every tick after a try that failed --, how
it runs -- in the background, one at a time per project, from that commit's own files, in the
project's checkout -- and what it last did.
"""

import collections
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, gitcall, orch, owner

TAIL = 10   # the last lines of a failed setup's output that are kept
# A fresh clone read with no git setting but its own: neither the checkout's `.git` (attributes,
# filters, line-end conversion, sparse checkout) nor the user's (configuration, attributes file,
# GIT_ variables) changes what runs.
CLEAN = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_COUNT": "1",
         "GIT_CONFIG_KEY_0": "core.attributesFile", "GIT_CONFIG_VALUE_0": "/dev/null"}


def tick():
    """The tick's pass: each project's setup that is due here, started in the background."""
    for repo in orch.checkouts():
        held = _lock(repo)
        if held is None:
            continue            # its setup is running
        with held:
            due = _due(repo)
        if due:
            subprocess.Popen([sys.executable, "-m", "agentkit.machine_setup", str(repo)],
                             cwd=config.REPO, env=owner.unmarked(config.child_env()),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)


def run(repo):
    """`python3 -m agentkit.machine_setup <checkout>`: its setup, where it is due and none runs."""
    held = _lock(repo)
    if held is None:
        return
    with held:
        due = _due(repo)
        if due:
            version, commit = due
            failed = _run(repo, commit, *version[1:])
            orch.replace_file(_file(repo, ".json"), json.dumps(
                {"version": version, **({"failed": failed} if failed else {})}).encode())


def _file(repo, suffix):
    return config.STATE / "setup" / f"{Path(repo).name}{suffix}"


def _lock(repo):
    """The project's setup lock, held, or None while its setup runs."""
    path = _file(repo, ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    held = path.open("a")
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        held.close()
        return None
    return held


def _last(repo):
    try:
        return json.loads(_file(repo, ".json").read_text())
    except (OSError, ValueError):
        return {}


def _due(repo):
    """(the setup's version here, the default branch's commit) where it has yet to pass at that
    version on this machine, else None.  A project naming no setup forgets its last one."""
    env = gitcall.project_env(repo)
    commit = gitcall.git(repo, "rev-parse", "--verify", "--quiet", config.RULES_REF,
                         check=False, env=env)
    line = commit and gitcall.declared_at(repo, commit, "setup")
    if not line:
        _file(repo, ".json").unlink(missing_ok=True)
        return None
    # the mode, type and blob of the file the line names, "" where it names none: git reads
    # `..`, `.`, `//` and a path into the checkout as another path and descends no link, so
    # only an entry it names back as the line itself is a file of the commit's own
    named = gitcall.git(repo, "--literal-pathspecs", "ls-tree", "-z", "--full-tree", commit, "--",
                        line, check=False, env=env)
    entry, _, path = named.partition("\t")
    version = [Path("/etc/machine-id").read_text().strip(), line,
               entry if path == f"{line}\0" else ""]
    return None if _last(repo) == {"version": version} else (version, commit)


def _run(repo, commit, line, entry):
    """None where the file `line` names at `commit` ran in the checkout and passed, else its
    last lines.  It runs from a fresh clone of that commit, its `.git` removed, which is removed
    once it ends: what the commit records, whatever the checkout holds."""
    if not entry.startswith("100"):     # a link, a directory or nothing: no file of its own
        return [f"the default branch holds no {line}"]
    with tempfile.TemporaryDirectory(prefix="setup-", dir=config.TMP,
                                     ignore_cleanup_errors=True) as scratch:
        tree = Path(scratch) / "tree"
        env = {**dict.fromkeys(name for name in os.environ if name.startswith("GIT_")), **CLEAN}
        for at, args in ((repo, ("clone", "--quiet", "--shared", "--no-checkout", "--",
                                 str(repo), str(tree))),
                         (tree, ("checkout", "--quiet", "--detach", commit))):
            code, said = gitcall.git_out(at, *args, env=env)
            if code:
                return [f"{line} cannot start: git {args[0]} failed", *said.splitlines()[-TAIL:]]
        shutil.rmtree(tree / ".git")
        try:
            proc = subprocess.Popen([tree / line], cwd=repo, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as exc:
            return [f"{line} cannot start: {exc.strerror}"]
        with proc:
            tail = collections.deque(proc.stdout, TAIL)
    if proc.returncode == 0:
        return None
    return [f"{line} exited {proc.returncode}",
            *(said.decode(errors="replace").rstrip() for said in tail)]


if __name__ == "__main__":
    run(Path(sys.argv[1]))
