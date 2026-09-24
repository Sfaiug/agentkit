"""Run the task's done-when commands on a new checkout of the fetched remote main."""

from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import run


def verify(repo, task, checkout):
    def command(args, cwd):
        print(f"$ {shlex.join(args)} (cwd={cwd})", flush=True)
        result = subprocess.run(args, cwd=cwd)
        print(f"[exit {result.returncode}]", flush=True)
        return result.returncode

    commands = run.done_when(task.read_text(), task)
    if not commands:
        raise ValueError(f"no done-when commands in {task}")
    # Fetch explicitly: an old local remote-tracking ref is not delivery evidence.
    if command(["git", "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"], repo):
        return 1
    sha = run.git(repo, "rev-parse", "origin/main")
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
