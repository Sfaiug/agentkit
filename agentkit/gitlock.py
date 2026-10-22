"""The lock a killed git left, gone once a git names it, and that git run again.

Git takes a file by creating `<file>.lock` beside it and gives it back by renaming or removing
that; a git killed in between -- the host's memory killer prefers git -- leaves it, and every
git after it that needs the file fails with `Unable to create '<path>.lock': File exists.`,
the path absolute.  That line names the one file in the way, but a path git echoes can forge
it, so the file must also lie in the git directory git itself finds from where it lies,
whatever the repository's layout.  The lock is the dead git's once,
in a whole process table read after it was found, no git runs anywhere on the host and no
process holds the file: which repository each git works in would take every layout git has
(separate and linked git directories, worktrees, `GIT_DIR`) to tell, and on this host most
seconds have no git running at all.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

from . import retention

# git's own error line for a lock it found taken, on its stderr: the same words in a diff, a log
# or a hook's output on stdout name no lock; `.*`, as a checkout path may hold an apostrophe
NAMED = re.compile(r"^(?:fatal|error): .*Unable to create '(.*\.lock)': File exists\.$", re.M)

WAIT = 10   # seconds a named lock waits for a moment no git runs: one still running past it
            # keeps the lock, and the next git it stops asks again


def run(cmd, **kwargs):
    """`subprocess.run` of a git with its output captured, run again after each lock it failed
    on that a killed git left is gone -- each lock once, so one a living git takes again ends
    it as it failed."""
    gone = set()
    while True:
        proc = subprocess.run(cmd, **kwargs)
        said = proc.stderr or ""
        said = said.decode(errors="replace") if isinstance(said, bytes) else said
        lock = next(iter(NAMED.findall(said)), None) if proc.returncode else None
        if lock is None or lock in gone or not clear(Path(lock)):
            return proc
        gone.add(lock)


def at_work(row, lock):
    """Is this process a git, or does it hold the lock?"""
    name = Path(row["args"][0]).name if row["args"] else ""
    return name == "git" or name.startswith("git-") or retention.busy(lock, row["paths"])


def owned(lock):
    """Does the lock lie in the git directory git finds from the lock's own directory?  The
    common one, which holds a linked worktree's too."""
    where = lock.parent.resolve()
    proc = subprocess.run(["git", "-C", str(where), "rev-parse", "--path-format=absolute",
                           "--git-common-dir"], capture_output=True, text=True)
    # one path and its newline: a path may hold a newline itself
    return proc.returncode == 0 and where.is_relative_to(Path(proc.stdout[:-1]).resolve())


def clear(lock):
    """Remove that lock once it is a dead git's: True when it is gone, by this or its holder."""
    from . import gc
    try:
        found = lock.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not owned(lock):
        return False
    held = str(lock.resolve())
    deadline = time.monotonic() + WAIT
    while True:
        table = gc.tmp_processes()[1]
        if table is not None and not any(at_work(row, held) for row in table.values()):
            break
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)
    try:
        now = lock.lstat()
        # the same file still: one a git made after the dead one's went is a living git's
        if (now.st_ino, now.st_mtime_ns) != (found.st_ino, found.st_mtime_ns):
            return False
        lock.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    print(f"ak: removed {lock}, left by a git that has ended", file=sys.stderr, flush=True)
    return True
