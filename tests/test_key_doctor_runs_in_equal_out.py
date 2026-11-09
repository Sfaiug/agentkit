"""Doctor's runs line: every run started in the last day ended, is going, or is named lost.

Jobs in equals jobs out (write-up row 43).  A run is lost the way the tick's dead-loop pass reads
a dead loop: its record says it is going while no process of it runs and nothing holds it, and
the pass has had a tick to resume it -- its last write is older than three minutes and twice the
last tick.  Doctor then exits 1.

Black-box through AK_BIN in a temporary HOME, on the real clock and the real process table: the
records and the tick's stamps are written set back from now, each boundary with a minute's
margin on either side, and the process that keeps a run going is one this test starts and ends,
as is the one a lost run recorded.  No tick resumes anything here: doctor only reads.
"""

from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, Home, owner


class DoctorRunsInEqualOut(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.runs = self.home.path / ".agentkit/runs"
        self.tick()

    def tick(self, took=10):
        """The last tick: it ended 10 s back, after `took` seconds."""
        ended = time.time() - 10
        self.home.write(".agentkit/state/watch.json", {"tick": {
            "started_at": ended - took, "ended_at": ended,
            "slowest": {"pass": "dead loops", "seconds": took}}})

    def run_record(self, name, state="running", ago=240, started=10000, **fields):
        """A run started `started` seconds back, its last write `ago` seconds back; a running
        one's loop is a process that has ended unless `fields` name another."""
        now = time.time()
        record = {"run_id": name, "title": "Fix api", "state": state,
                  "started_at": now - started, "launched_session": "acme", **fields}
        if state in ("pass", "fail", "blocked", "stopped"):
            record.setdefault("finished_at", now - ago)
        if "pid" not in record:
            record.update(self.ended())
        return self.home.write(f".agentkit/runs/{name}/run.json", record, ago=ago).parent

    def going(self):
        """The pid and identity of a loop that runs until the test ends."""
        proc = subprocess.Popen(["sleep", "600"], stdin=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        return owner(proc.pid)

    def ended(self):
        """The pid and identity a loop recorded for itself, that loop since ended."""
        proc = subprocess.Popen(["true"])
        proc.wait()
        return {"pid": proc.pid, "process_identity": {"boot": "gone", "ticks": 0}}

    def doctor(self, code, line):
        """`ak doctor` exits `code`, with `line` as its runs line, after the full report, and
        writes nothing."""
        tick = self.home.path / ".agentkit/state/watch.json"

        def kept():
            return {path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in [*self.runs.rglob("*"), tick] if path.is_file()}

        before = kept()
        done = self.home.run(AK, "doctor")
        self.assertEqual(done.code, code, done.out + done.err)
        self.assertIn(f"runs  {line}", done.out.splitlines())
        self.assertTrue(done.out.splitlines()[-1].startswith("rented machines: "), done.out)
        self.assertEqual(kept(), before, "doctor must leave the run and tick records alone")

    def test_a_run_neither_ended_nor_going_is_named(self):
        self.run_record("said", "pass", handed_back=True)
        self.run_record("moving", **self.going())
        self.run_record("lost")
        self.doctor(1, "3 started in the last day · 1 ended · 1 going · 0 endings owed · "
                       "lost: lost (4m since last write)")

    def test_a_dead_loop_is_lost_once_past_three_minutes_and_twice_the_last_tick(self):
        for took, age, lost in ((10, 120, False), (10, 240, True), (150, 240, False),
                                (150, 360, True)):
            with self.subTest(took=took, age=age):
                self.tick(took)
                self.run_record("lost", ago=age)
                if lost:
                    self.doctor(1, "1 started in the last day · 0 ended · 0 going · "
                                   f"0 endings owed · lost: lost ({age // 60}m since last write)")
                else:
                    self.doctor(0, "1 started in the last day · 0 ended · 1 going · "
                                   "0 endings owed")

    def test_a_wait_holds_a_run_whose_loop_is_gone(self):
        now = time.time()
        self.run_record("quota", "exhausted")
        self.run_record("parked", "interrupted",
                        deaths=[{"at": now - 900, "pid": 1, "parked": True}])
        self.run_record("told", "interrupted")
        self.run_record("ordered", stall_resume_at=now - 300)
        died = self.ended()
        self.run_record("backoff", **died, resume_after=now + 300, deaths=[
            {"at": now - 600, "pid": 1, "resumed_at": now - 500},
            {"at": now - 300, "pid": died["pid"]}])
        self.doctor(0, "5 started in the last day · 0 ended · 5 going · 0 endings owed")

    def test_only_runs_started_in_the_last_day_count_and_every_owed_ending_does(self):
        self.run_record("old", "fail", ago=10, started=3 * 86400,
                        finished_at=time.time() - 2 * 86400)
        self.run_record("new", "pass", ago=600)
        self.run_record("said", "blocked", handed_back=True)
        self.run_record("stopped", "stopped")
        self.run_record("days", started=2 * 86400, **self.going())
        self.doctor(0, "3 started in the last day · 3 ended · 0 going · "
                       "2 endings owed, oldest 2d")


if __name__ == "__main__":
    unittest.main()
