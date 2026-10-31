"""A run waiting behind the first in line for a slot holds next to no memory.

On 27 Oct 2026 91 runs waited for a slot, each in its whole `ak run` process: 2.3 G of a 10.9 G
slice spent on waiting, while admission waited on that same memory.  Only the first in line can
be admitted, so a run behind it waits holding less than a third of the first's private memory,
keeps its pid and `queued_at` and so its place in line, is admitted in order, and still stops.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on
projects from gitrig.py with scripted harnesses from fakeadapter.py; the host readings injected
(AK_HOST_READINGS) and a run's peak kept in a history database hold admission on the unit's room,
and each first in line is let in on a stall, the queue's own clock set back two hours.
"""

import fcntl
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# 3.8 of the slice's 4 G held, a run's peak 1 G: the room check holds, while the host is calm.
CALM = {"free_mb": 6000, "mem_total_mb": 16000, "cpus": 8, "load": 0.1,
        "slice_cpu_pressure": 0, "slice_memory_pressure": 0,
        "slice_memory_used_mb": 3800, "slice_memory_high_mb": 4096}
COLUMNS = ("run_id TEXT PRIMARY KEY", "repo TEXT", "executor TEXT", "reviewer TEXT",
           "rounds_used INTEGER", "final_state TEXT", "verdict TEXT", "started_at REAL",
           "finished_at REAL", "executor_seconds REAL", "done_when_seconds REAL",
           "reviewer_seconds REAL", "merge_seconds REAL", "total_seconds REAL",
           "executor_tokens INTEGER", "reviewer_tokens INTEGER", "peak_rss_mb REAL",
           "session TEXT")
PROJECTS = ("widgets", "gadgets", "gizmos")


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


def private_kb(pid):
    """The process's private memory, in RAM and in swap."""
    rollup = Path(f"/proc/{pid}/smaps_rollup").read_text()
    return sum(int(line.split()[1]) for line in rollup.splitlines()
               if line.split(":")[0] in ("Private_Clean", "Private_Dirty", "Swap"))


class QueuedRunHoldsNoMemory(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        del self.home.env["AK_MAX_RUNS"]
        self.home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(CALM))
        now = time.time()
        database = sqlite3.connect(self.home.path / ".agentkit" / "history.db")
        database.execute(f"CREATE TABLE runs ({', '.join(COLUMNS)})")
        database.execute("INSERT INTO runs (run_id, repo, final_state, verdict, started_at, "
                         "finished_at, peak_rss_mb) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ("20261020-1200-fix-api", "acme", "pass", "PASS", now - 7200,
                          now - 3600, 1024))
        database.commit()
        database.close()
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="work", codex="pass")
        self.runs = []
        for name in PROJECTS:
            rig = Rig(self.home, name)
            done = self.home.ak("run", str(taskfile.write(self.home, rig.path, f"Add {name}")),
                                "--no-merge", "--bg")
            self.assertEqual(done.code, 0, done.out + done.err)
            run = next(run for run in taskfile.runs(self.home) if run not in self.runs)
            wait(lambda: self.queue()[-1:] == [run.name], f"{run.name} in line")
            self.runs.append(run)
        self.held = [self.state(run) for run in self.runs]
        self.assertEqual(self.queue(), [run.name for run in self.runs])

    def queue(self):
        try:
            return json.loads((self.runs_dir() / ".slots.queue").read_text())["queue"]
        except (OSError, ValueError, KeyError):
            return []

    def runs_dir(self):
        return self.home.path / ".agentkit" / "runs"

    def state(self, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    def stall(self, run):
        """Whether the run is let in; until it is, the run first in line two hours, past half an
        hour, the stall's floor, and the queue polled just now.  A poll long after the last
        starts a new wait (`gate.first_in_line`), and every poll after the stall may come that
        late on a loaded host at AK_SLOT_POLL=0.5: a whole `ak run`, the first back from its
        waiter, or the one behind it back from a waiter that found the queue stale.  Under the
        slot lock, where admission writes the queue and the record together."""
        with (self.runs_dir() / ".slots.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.state(run).get("state") != "queued":
                return True
            path = self.runs_dir() / ".slots.queue"
            queue = json.loads(path.read_text())
            self.assertEqual(queue["queue"][0], run.name)
            now = time.time()
            path.write_text(json.dumps({**queue, "since": now - 7200, "at": now}))
            return False

    def test_runs_behind_the_first_hold_a_third_of_its_memory_and_go_in_in_order(self):
        first, *behind = [state["pid"] for state in self.held]

        def small():
            return all(3 * private_kb(pid) < private_kb(first) for pid in behind)

        wait(small, "the runs behind the first holding less than a third of its memory", 30)
        for run in self.runs:
            wait(lambda: self.stall(run), f"{run.name} let in on a stall")
        for run, held in zip(self.runs, self.held):
            wait(lambda: self.state(run).get("state") not in ("queued", "running"),
                 f"{run.name} ended")
            state = self.state(run)
            self.assertEqual(state.get("verdict"), "PASS", run.name)
            self.assertEqual((state["pid"], state["queued_at"]),
                             (held["pid"], held["queued_at"]), run.name)
        started = [self.state(run)["slot_started_at"] for run in self.runs]
        self.assertEqual(started, sorted(started))

    def test_a_run_stopped_while_it_waits_behind_the_first_is_stopped(self):
        third = self.runs[2]
        pid = self.held[2]["pid"]
        wait(lambda: 3 * private_kb(pid) < private_kb(self.held[0]["pid"]),
             "the third waiting in next to no memory", 30)
        done = self.home.ak("run", "stop", third.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        wait(lambda: not Path(f"/proc/{pid}").exists(), "the third's process gone", 30)
        self.assertEqual(self.state(third).get("state"), "stopped")
        done = self.home.ak("run", "status", third.name)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("stopped", done.out)


if __name__ == "__main__":
    unittest.main()
