"""Doctor reports each gate's last hold from history, even after its run was collected.

Black-box: the history is written into a throwaway HOME's history.db with sqlite3, as ak keeps
it, dated back from the real clock; a live run's process is one this test starts and ends, and a
line checker's wait file is locked by this test, so any ak `AK_BIN` names is judged by its line.
"""

from contextlib import closing
import fcntl
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, owner

DAY = 86400
WAIT = 60       # seconds each wait in history lasted
# history.db as ak keeps a run's waits: the run's row, and a phase row per wait, ended where it
# was last counted, a slot wait's with the reason it waited.
TABLES = ("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, repo TEXT, final_state TEXT, "
          "started_at REAL, finished_at REAL, slot_wait_seconds REAL, suite_wait_seconds REAL, "
          "lander_wait_seconds REAL)",
          "CREATE TABLE IF NOT EXISTS phases (run_id TEXT, phase TEXT, started_at REAL, "
          "ended_at REAL, wait_kind TEXT, PRIMARY KEY (run_id, phase, started_at))")


class DoctorGatesLine(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.home.ticked()

    def doctor(self):
        done = self.home.ak("doctor")
        self.assertEqual(done.code, 0, done.out + done.err)
        lines = [line for line in done.out.splitlines() if line.startswith("gates  ")]
        self.assertEqual(len(lines), 1, done.out)
        return lines[0]

    def history(self, run_id, wait, ended, kind=None, *, finished=True):
        """Run `run_id`'s row, with one `wait` wait (`slot`, `suite` or `lander`) counted up to
        `ended`, the run finished there unless it goes on."""
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            for table in TABLES:
                db.execute(table)
            db.execute("INSERT INTO runs (run_id, repo, final_state, started_at, finished_at, "
                       f"{wait}_wait_seconds) VALUES (?, 'acme', ?, ?, ?, ?)",
                       (run_id, "pass" if finished else "running", ended - 2 * WAIT,
                        ended if finished else None, WAIT))
            db.execute("INSERT INTO phases VALUES (?, ?, ?, ?, ?)",
                       (run_id, f"{wait} wait", ended - WAIT, ended, kind))

    def keeper(self):
        """A live run's process, recorded as `ak run` records itself: one this test owns, in the
        Home, so the Home's reaper ends it should the test die first."""
        proc = subprocess.Popen(["sleep", "3600"], env=self.home.env, start_new_session=True)
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        return owner(proc.pid)

    def test_memory_last_held_three_days_ago_and_suite_turns_hold_now(self):
        now = time.time()
        held = now - 3.5 * DAY      # half a day clear of 3 and of 4 days idle
        self.history("fix-api", "slot", held, "memory")     # its run since collected: no record
        self.history("fix-ui", "suite", now - 5, finished=False)
        run = self.keeper()
        self.home.write(".agentkit/runs/fix-ui/run.json", {
            "run_id": "fix-ui", "state": "running", **run,
            "gate_turn": {"pid": run["pid"], "since": now - 20, "of": "acme"}})
        line = self.doctor()
        # the Home's local time is UTC
        self.assertIn(f"memory 3 days idle, last held "
                      f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(held))}", line)
        self.assertIn("suite turns holding now", line)
        self.assertIn("admission never held", line)

    def test_before_any_history_all_three_gates_never_held(self):
        self.assertEqual(self.doctor(), "gates  admission never held · suite turns never held · memory never held")
        self.assertFalse((self.home.path / ".agentkit/history.db").exists())

    def test_a_lander_wait_counts_as_suite_turns(self):
        self.history("fix-api", "lander", time.time() - 1.5 * DAY)
        line = self.doctor()
        self.assertIn("suite turns 1 day idle", line)
        self.assertIn("admission never held", line)
        self.assertIn("memory never held", line)

    def test_a_finished_wait_at_the_clock_is_idle(self):
        self.history("fix-api", "suite", time.time())
        self.assertIn("suite turns 0 days idle", self.doctor())

    def test_current_slot_waits_name_the_gate_holding_them(self):
        run = self.keeper()
        for kind, gate, behind in (("count", "admission", False), ("load", "admission", False),
                                  ("memory", "memory", False), ("unit memory", "memory", False),
                                  ("memory", "admission", True), ("unit memory", "admission", True)):
            with self.subTest(kind=kind, behind=behind):
                self.home.write(".agentkit/runs/.slots.queue", {
                    "at": time.time(), "running": 0,
                    "queue": ["urgent-fix", "fix-api"] if behind else []})
                self.home.write(".agentkit/runs/fix-api/run.json", {
                    "run_id": "fix-api", "state": "queued", **run,
                    "slot_waiting": True, "slot_wait_kind": kind})
                line = self.doctor()
                self.assertIn(f"{gate} holding now", line)
                self.assertIn(f"{'memory' if gate == 'admission' else 'admission'} never held", line)

    def test_a_line_checkers_locked_wait_is_live_until_it_leaves(self):
        wait = self.home.path / ".agentkit/runs/.landing-wait-fixture"
        wait.parent.mkdir(parents=True, exist_ok=True)
        with wait.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            held.write("{}")
            held.flush()
            self.assertIn("suite turns holding now", self.doctor())
        self.assertIn("suite turns never held", self.doctor())
        self.assertTrue(wait.exists())


if __name__ == "__main__":
    unittest.main()
