"""A poll lets in as many runs as the host's room covers.

On 31 Oct 2026 32 runs waited in line on a host with 8.8 G free, against a gate needing 3.2 G and
a recent run's median peak of 0.78 G, and one went in every 31 to 61 s: after any run went in,
the first in line waited a poll for steady readings.  Readings lag what a run just let in will
use, so each run holding a slot counts what it may still grow by against the memory gates
instead: runs started together each go in at their first poll while the room covers them, and
one it does not cover waits.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py with scripted harnesses from
fakeadapter.py; the host readings and the slot poll are ak's own knobs (AK_HOST_READINGS,
AK_SLOT_POLL), and a history database holds finished runs that peaked at PEAK.
"""

from contextlib import closing
import json
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PEAK = 2000
COLUMNS = ("run_id TEXT PRIMARY KEY", "repo TEXT", "executor TEXT", "reviewer TEXT",
           "rounds_used INTEGER", "final_state TEXT", "verdict TEXT", "started_at REAL",
           "finished_at REAL", "executor_seconds REAL", "done_when_seconds REAL",
           "reviewer_seconds REAL", "merge_seconds REAL", "total_seconds REAL",
           "executor_tokens INTEGER", "reviewer_tokens INTEGER", "peak_rss_mb REAL",
           "session TEXT")
TITLES = ("Add retry file", "Bump alpha notes", "Trim beta notes")


def wait(test, what, bound):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


def state(run):
    try:
        return json.loads((run / "run.json").read_text())
    except (OSError, ValueError):
        return {}


def started_together(cls, readings, poll, count, ready):
    """The records, once all have ended, of `count` runs, each started once `ready` holds of the
    records of those before it: a run behind one that has not polled yet waits a poll for it.
    Each one's turn is held until `ready` holds of them all."""
    home = Home()
    cls.addClassCleanup(home.close)
    del home.env["AK_MAX_RUNS"]     # 0 turns admission off
    home.env.update(AK_SLOT_POLL=str(poll), AK_HOST_READINGS=json.dumps(readings))
    now = time.time()
    with closing(sqlite3.connect(home.path / ".agentkit" / "history.db")) as database, database:
        database.execute(f"CREATE TABLE runs ({', '.join(COLUMNS)})")
        database.executemany(
            "INSERT INTO runs (run_id, repo, final_state, verdict, started_at, finished_at, "
            "peak_rss_mb) VALUES (?, 'acme', 'pass', 'PASS', ?, ?, ?)",
            [(f"20261030-120{n}-fix-api", now - 7200, now - 3600, PEAK) for n in range(3)])
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus", "astra"])
    release = home.root / "adapters" / "release"
    hold = f"until [ -e {shlex.quote(str(release))} ]; do sleep 0.1; done"
    fakeadapter.install(home, claude={**fakeadapter.WORK, "sh": hold}, codex="pass")
    runs = []
    for title in TITLES[:count]:
        known = set(taskfile.runs(home))
        # --anyway: they check the same file, which reads as one change under way
        done = home.ak("run", str(taskfile.write(home, rig.path, title)), "--no-merge",
                       "--bg", "--anyway")
        assert done.code == 0, done.out + done.err
        runs.append((set(taskfile.runs(home)) - known).pop())
        wait(lambda: ready([state(run) for run in runs]), f"{runs[-1].name} ready", 300)
    release.touch()
    wait(lambda: all(state(run).get("state") not in ("queued", "running") for run in runs),
         "every run's end", 300)
    return [state(run) for run in runs]


class RoomForAll(unittest.TestCase):
    POLL = 30   # the shipped poll, far longer than a launch takes to reach its first

    @classmethod
    def setUpClass(cls):
        cls.runs = started_together(cls, {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8,
                                          "load": 0.1, "slice_cpu_pressure": 0,
                                          "slice_memory_pressure": 0}, cls.POLL, 3,
                                    lambda runs: all(run.get("state") == "running"
                                                     for run in runs))

    def test_every_run_passes(self):
        self.assertEqual([run.get("verdict") for run in self.runs], ["PASS"] * 3)

    def test_each_goes_in_at_its_first_poll(self):
        for run in self.runs:
            self.assertLess(run["slot_started_at"] - run["queued_at"], self.POLL)


class RoomForOne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The gate needs 3.2 G of 16 G: 4.5 G free lets one run past it, and with what that
        # one may still take counted, not a second.  Each holds its slot until the last has
        # gone in or says why it waits.
        cls.runs = started_together(cls, {"free_mb": 4500, "mem_total_mb": 16000, "cpus": 8,
                                          "load": 0.1, "slice_cpu_pressure": 0,
                                          "slice_memory_pressure": 0}, 1, 2,
                                    lambda runs: runs[-1].get("state") != "queued"
                                    or runs[-1].get("slot_wait_reason"))

    def test_every_run_passes(self):
        self.assertEqual([run.get("verdict") for run in self.runs], ["PASS"] * 2)

    def test_the_second_goes_in_once_the_first_holds_no_slot(self):
        first, second = self.runs
        self.assertGreaterEqual(second["slot_started_at"], first["finished_at"])


if __name__ == "__main__":
    unittest.main()
