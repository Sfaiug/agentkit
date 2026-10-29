"""The run first in line for a slot past its stall time goes in while the host is calm.

From 25 Oct 2026 08:06 no run was admitted for 22 hours: the unit's room against a run's peak
read short while slice memory pressure was 0% and the host had 5.9 G available.  Once the first
in line has waited far past the last firsts' waits, only the host's available memory and the
kernel's own stall readings hold it: it goes in, and its log and `ak run status <id> --why` say
it went in on a stall past the check that held it.  Before then that check still holds it.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py, the host readings injected
(AK_HOST_READINGS) and a run's peak kept in a history database as an older ak made it.  The
stall's clock is the queue's own, set back two hours, not waited out.
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
ROOM = "waiting for the unit's memory"
COLUMNS = ("run_id TEXT PRIMARY KEY", "repo TEXT", "executor TEXT", "reviewer TEXT",
           "rounds_used INTEGER", "final_state TEXT", "verdict TEXT", "started_at REAL",
           "finished_at REAL", "executor_seconds REAL", "done_when_seconds REAL",
           "reviewer_seconds REAL", "merge_seconds REAL", "total_seconds REAL",
           "executor_tokens INTEGER", "reviewer_tokens INTEGER", "peak_rss_mb REAL",
           "session TEXT")


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class StalledQueueOpensWhileCalm(unittest.TestCase):
    def queued(self, readings, kind="unit memory", **env):
        """A run launched under `readings`, held first in line on `kind`."""
        home = Home()
        self.addCleanup(home.close)
        del home.env["AK_MAX_RUNS"]
        home.env.update(AK_SLOT_POLL="0.5", AK_HOST_READINGS=json.dumps(readings), **env)
        now = time.time()
        database = sqlite3.connect(home.path / ".agentkit" / "history.db")
        database.execute(f"CREATE TABLE runs ({', '.join(COLUMNS)})")
        database.execute("INSERT INTO runs (run_id, repo, final_state, verdict, started_at, "
                         "finished_at, peak_rss_mb) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         ("20261020-1200-fix-api", "acme", "pass", "PASS", now - 7200,
                          now - 3600, 1024))
        database.commit()
        database.close()
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--bg")
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(home)
        wait(lambda: self.state(run).get("slot_wait_kind") == kind, f"the run queued on {kind}")
        return home, run

    def state(self, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    def stall(self, run):
        """The run first in line two hours, past half an hour, the stall's floor, its queue last
        polled an hour ahead, so the run's next poll carries that wait on however late it comes:
        one more than four polls after the last starts a new wait (`gate.first_in_line`), and a
        loaded host's comes that late at AK_SLOT_POLL=0.5."""
        runs = run.parent
        with (runs / ".slots.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            queue = json.loads((runs / ".slots.queue").read_text())
            self.assertEqual(queue["queue"], [run.name])
            now = time.time()
            (runs / ".slots.queue").write_text(json.dumps({**queue, "since": now - 7200,
                                                           "at": now + 3600}))

    def held(self, run, why):
        time.sleep(2)     # four polls: still held
        state = self.state(run)
        self.assertEqual(state.get("state"), "queued")
        self.assertIn(why, state.get("slot_wait_reason", ""))
        self.assertNotIn("slot_stall", state)

    def test_a_stalled_first_goes_in_past_the_room_check_while_the_host_is_calm(self):
        home, run = self.queued(CALM)
        self.stall(run)
        wait(lambda: self.state(run).get("state") not in ("queued", "running"),
             "the run admitted on its stall, and its end")
        self.assertEqual(self.state(run).get("verdict"), "PASS")
        went = f"went in on a stall, past: {ROOM}"
        self.assertIn(went, (run / "log.txt").read_text().split("\n", 1)[0])
        done = home.ak("run", "status", run.name, "--why")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(went, done.out)

    def test_a_stalled_first_still_waits_while_its_slice_stalls_on_memory(self):
        _, run = self.queued({**CALM, "slice_memory_pressure": 30})
        self.stall(run)
        self.held(run, "pressure 30%, limit 10%")

    def test_a_stalled_first_goes_in_while_runs_stall_on_cpu(self):
        # A pinned load holds it first; the room is there, and the runs' CPU pressure holds
        # nothing: CPU is shared, and a check given less of it only runs slower.
        _, run = self.queued({**CALM, "slice_memory_used_mb": 1024, "slice_cpu_pressure": 90,
                              "load": 20}, kind="load", AK_MAX_LOAD="8")
        self.stall(run)
        wait(lambda: self.state(run).get("state") not in ("queued", "running"),
             "the run admitted on its stall, and its end")
        self.assertIn("went in on a stall, past: waiting for the host to calm",
                      (run / "log.txt").read_text().split("\n", 1)[0])

    def test_before_its_stall_time_the_room_check_still_holds_it(self):
        _, run = self.queued(CALM)
        self.held(run, ROOM)


if __name__ == "__main__":
    unittest.main()
