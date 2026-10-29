"""A launch waiting behind the first in line for a slot, in a process holding next to no memory.

Only the first in line can be admitted, so a run behind it only reads `.slots.queue`.  Its
launch execs into this script (`run.pickup_while_queued`), run as `python3 -I -S`: it imports
nothing of agentkit, so the waiting process holds a few megabytes instead of a whole `ak run`.
It counts its wait in history as it polls, as `gate.count_wait` does, and execs the same launch
back, keeping the pid and so the receipt and its place in line, once it may be first or the
installed agentkit moved.  What both need to know lives here, for ak to import.

    AK_SLOT_WAIT="<began> <monotonic since>" python3 -I -S waiter.py \
        QUEUE DATABASE RUN_ID POLL REPO VERSION LAUNCH...
"""

import contextlib
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

# The wait counted up to the exec into the waiter, and back: "<began> <monotonic since>".
SLOT_WAIT_ENV = "AK_SLOT_WAIT"


def stale_after(place, poll):
    """How old the queue gets before the run at `place` in it counts it again: its first polls
    every poll, and once it stops or dies the run next in line comes back after two, a poll later
    the one behind it, and so on: one comes back to count it, never the whole line.  A line of
    110 coming back at once held the slot lock for minutes and about 3 G of memory, several times
    an hour (28 Oct 2026)."""
    return (1 + place) * poll


def behind_first(queue, run_id, now, poll):
    """Whether the queue file still has this run waiting behind its first, who alone can be
    admitted, and not yet stale for it (`stale_after`)."""
    try:
        with open(queue, encoding="utf-8") as file:
            saved = json.load(file)
        at, waiting = float(saved["at"]), [str(run_id) for run_id in saved["queue"]]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return run_id in waiting[1:] and 0 <= now - at < stale_after(waiting.index(run_id), poll)


def offset(queue, run_id, poll):
    """How far into each interval on the clock the run polls, its place's share of the line: runs
    at different places in it poll at different moments.  None when the queue does not list it."""
    try:
        with open(queue, encoding="utf-8") as file:
            waiting = list(map(str, json.load(file)["queue"]))
        return poll * waiting.index(run_id) / len(waiting)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def head(repo, env=None):
    """The checkout at `repo` as a short commit, or "" when it cannot be read.

    A read that fails or runs slow is no version, never a failed run: the checkout may
    be no checkout at all, or git waiting on a prompt or a network nobody here can answer.
    """
    try:
        proc = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"],
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=10, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


@contextlib.contextmanager
def writing(database, wait=True):
    """One writer of history.db at a time, across processes: runs, the tick and the menu each
    write, and sqlite's own wait gives up after its timeout and the write would be lost.
    Without `wait`, BlockingIOError while another writer has it."""
    with Path(database).with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        yield


def add_wait(connection, run_id, wait, seconds, began, at):
    """Add a wait's seconds to its column and end its phase row, the one begun at `began`, at
    `at`."""
    column = f"{wait}_wait_seconds"
    connection.execute(f"UPDATE runs SET {column}={column}+? WHERE run_id=?", (seconds, run_id))
    phase(connection, run_id, f"{wait} wait", began, max(began, at))


def phase(connection, run_id, name, started_at, ended_at):
    """Write the phase row, or move its end: the one under way ends at its last checkpoint."""
    connection.execute(
        "INSERT INTO phases (run_id, phase, started_at, ended_at) "
        "SELECT run_id, ?, ?, ? FROM runs WHERE run_id=? "
        "ON CONFLICT(run_id, phase, started_at) DO UPDATE SET ended_at=excluded.ended_at",
        (name, started_at, ended_at, run_id))


def count(database, run_id, began, since):
    """Add the wait since the monotonic `since` to the run's history, so a waiter that dies
    loses at most the polls since it found history free; the moment it is counted to.  One that
    finds another writer on it counts at a later poll: a hundred waiters queued on the lock
    behind a busy disk's flushes held the first in line for minutes (29 Oct 2026).  History
    never ends the wait."""
    now = time.monotonic()
    try:
        with writing(database, wait=False), contextlib.closing(
                sqlite3.connect(database, timeout=2)) as connection:
            add_wait(connection, run_id, "slot", max(0.0, now - since), began, time.time())
            connection.commit()
    except BlockingIOError:
        return since
    except (OSError, sqlite3.Error):
        pass
    return now


def main(argv):
    queue, database, run_id, poll, repo, version, *launch = argv
    poll = float(poll)
    began, since = map(float, os.environ[SLOT_WAIT_ENV].split())
    while True:
        # Polled from when each came back, the waiters one install move brought back together
        # all saw the next at one poll: 62 came back within five seconds, 1.7 G (29 Oct 2026).
        at = offset(queue, run_id, poll)
        time.sleep(poll if at is None else poll - (time.time() - at) % poll)
        since = count(database, run_id, began, since)
        if (not behind_first(queue, run_id, time.time(), poll)
                or version and head(repo) not in ("", version)):
            os.environ[SLOT_WAIT_ENV] = f"{began} {since}"
            os.execv(launch[0], launch)


if __name__ == "__main__":
    main(sys.argv[1:])
