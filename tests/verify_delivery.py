"""Run the task's done-when commands on a new checkout of the branch the run merged into, fetched:
the one `origin/HEAD` names, as the run took it for a task naming no `base:`."""

from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import run
from agentkit import task as taskfile


def verify(repo, task, checkout):
    def command(args, cwd):
        print(f"$ {shlex.join(args)} (cwd={cwd})", flush=True)
        result = subprocess.run(args, cwd=cwd)
        print(f"[exit {result.returncode}]", flush=True)
        return result.returncode

    commands = taskfile.done_when(task.read_text(), task)
    if not commands:
        raise ValueError(f"no done-when commands in {task}")
    # Fetch explicitly: an old local remote-tracking ref is not delivery evidence.
    branch = run.default_base(repo, print).removeprefix("origin/")
    if command(["git", "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"], repo):
        return 1
    sha = run.git(repo, "rev-parse", f"origin/{branch}")
    print(f"delivered revision: {sha}", flush=True)
    if command(["git", "worktree", "add", "--detach", str(checkout), sha], repo):
        return 1
    failed = False
    for cmd in commands:
        if command(["bash", "-o", "pipefail", "-c", cmd], checkout):
            failed = True
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(verify(*(Path(arg).resolve() for arg in sys.argv[1:])))
    except (OSError, ValueError, run.config.Error) as exc:
        print(f"delivery verification: {exc}", file=sys.stderr)
        sys.exit(1)
