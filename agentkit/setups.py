"""Each project's `setup:`, the command in its AGENTS.md front matter that makes the machine ak
runs on ready for the project's work: `start` is the tick's pass, `failing` what `ak doctor` says.

Hidden here: when a setup is due -- once on each machine for each version, a version being the
line and every file it names as the default branch has them, so a new machine runs them all, a
changed setup runs again and a failed one on every tick until it passes; how it runs -- detached
in the project's checkout, one at a time per project, so the tick never waits for it; and what it
last did, in ~/.agentkit/state/setups/<project>.json beside its output.
"""

import fcntl
import hashlib
import json
import os
import posixpath
import shlex
import socket
import subprocess
import sys
from pathlib import Path

from . import config, gitcall, orch

DIR = config.STATE / "setups"
TAIL = 10       # lines of a failed setup's output `ak doctor` shows


def machine():
    """What tells this machine from the one its HOME was copied from."""
    try:
        return Path("/etc/machine-id").read_text().strip() or socket.gethostname()
    except OSError:
        return socket.gethostname()


def _due(checkout):
    """(line, version) of the setup `checkout`'s default branch names, or None without one."""
    line = gitcall.declared_at(checkout, config.RULES_REF, "setup")
    if not line:
        return None
    try:
        words = shlex.split(line, comments=True)
    except ValueError:
        words = line.split()
    paths = {posixpath.normpath(word) for word in words}
    paths = sorted(path for path in paths if not path.startswith("/")
                   and path.split("/")[0] != "..")
    listed = gitcall.git(checkout, "--literal-pathspecs", "ls-tree", "-z", "--full-tree",
                         config.RULES_REF, "--", *paths, check=False) if paths else ""
    files = sorted(entry for entry in listed.split("\0")
                   if entry.startswith("100") and entry.partition("\t")[2] in paths)
    return line, hashlib.sha256("\0".join([line, *files]).encode()).hexdigest()


def _record(name):
    try:
        return json.loads((DIR / f"{name}.json").read_text())
    except (OSError, ValueError):
        return {}


def start(log):
    """The tick's pass: start each project's setup that is due and not already running."""
    DIR.mkdir(parents=True, exist_ok=True)
    here = machine()
    for checkout in orch.checkouts():
        due = _due(checkout)
        record = _record(checkout.name)
        if not due or (record.get("machine"), record.get("version"), record.get("exit")) == (
                here, due[1], 0):
            continue
        # the running setup holds its output file's lock until it ends, through the descriptor
        # handed to it here: no gap in which a second one could start
        out = os.open(DIR / f"{checkout.name}.log", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(out, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(out)
            continue
        try:
            os.ftruncate(out, 0)
            subprocess.Popen([sys.executable, "-m", "agentkit.setups", str(checkout), *due],
                             cwd=config.REPO, env=config.child_env(), stdin=subprocess.DEVNULL,
                             stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
            log(f"{checkout.name}: its setup started")
        except OSError as exc:
            log(f"WARN {checkout.name}: its setup did not start: {exc}")
        finally:
            os.close(out)


def failing():
    """[(project, exit code, its output's last lines)] for each setup that failed on this
    machine at the version its project's default branch has now."""
    here, found = machine(), []
    for checkout in orch.checkouts():
        record, due = _record(checkout.name), _due(checkout)
        if due and record.get("exit") and (record.get("machine"), record.get("version")) == (
                here, due[1]):
            found.append((checkout.name, record["exit"], record.get("tail", [])))
    return found


def _run(checkout, line, version):
    """Run the setup in `checkout`, its output on this process's own, and record how it ended."""
    code = subprocess.call(["bash", "-c", line], cwd=checkout, stdin=subprocess.DEVNULL)
    name = Path(checkout).name
    with open(DIR / f"{name}.log", "rb") as out:
        cut = out.seek(max(0, out.seek(0, os.SEEK_END) - 8192))
        lines = out.read().decode(errors="replace").splitlines()[1 if cut else 0:]
    orch.replace_file(DIR / f"{name}.json", json.dumps(
        {"machine": machine(), "version": version, "exit": code, "tail": lines[-TAIL:]}).encode())


if __name__ == "__main__":
    _run(*sys.argv[1:])
