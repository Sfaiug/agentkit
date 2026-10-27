"""A launch waiting behind the first in line for a slot, in a process holding next to no memory.

Only the first in line can be admitted, so a run behind it only reads `.slots.queue`.  Its
launch execs into this script (`run.pickup_while_queued`), run as `python3 -I -S`: it imports
nothing of agentkit, so the waiting process holds a few megabytes instead of a whole `ak run`.
It execs the same launch back, keeping the pid and so the receipt and its place in line, once
it may be first or the installed agentkit moved.

    python3 -I -S waiter.py QUEUE RUN_ID POLL REPO VERSION LAUNCH...
"""

import json
import os
import subprocess
import sys
import time


def behind_first(queue, run_id, now, poll):
    """Whether the queue file still has this run waiting behind its first, who alone can be
    admitted.  A queue no poll rewrote for two polls -- its first stopped or died -- is counted
    again by whoever polls next."""
    try:
        saved = json.loads(open(queue, encoding="utf-8").read())
        at, waiting = float(saved["at"]), [str(run_id) for run_id in saved["queue"]]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return 0 <= now - at < 2 * poll and run_id in waiting[1:]


def head(repo):
    """The installed agentkit as a short commit, or "" when it cannot be read."""
    try:
        proc = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def main(argv):
    queue, run_id, poll, repo, version, *launch = argv
    poll = float(poll)
    while True:
        time.sleep(poll)
        if (not behind_first(queue, run_id, time.time(), poll)
                or version and head(repo) not in ("", version)):
            os.execv(launch[0], launch)


if __name__ == "__main__":
    main(sys.argv[1:])
