"""Doctor's runs line: every run started in the last day ended, is going, or is named lost.

Jobs in equals jobs out (write-up row 43).  A run is lost the way the tick's dead-loop pass reads
a dead loop: its record says it is going while no process of it runs and nothing holds it, and
the pass has had a tick to resume it -- its last write is older than three minutes and twice the
last tick.  Doctor then exits 1.

Black-box through AK_BIN in a temporary HOME, on the real clock and the real process table: the
records and the tick's stamps are written set back from now, each boundary with a minute's
margin on either side, and every process that keeps a run going, or does not, is one this test
starts and ends.  No tick resumes anything here: doctor only reads.
"""

import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, Home, owner

MARKER = "AGENTKIT_RUN"     # carried by every process a run starts: its directory, or below it


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

    def start(self, *argv, run=None, executable=None):
        """A process in this Home, carrying `run` as its run marker, its input a pipe the test
        holds open; it ends with the test."""
        proc = subprocess.Popen(argv, executable=executable, cwd=self.home.path,
                                env={**self.home.env, **({MARKER: str(run)} if run else {})},
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (proc.kill(), proc.communicate()))
        return proc

    def going(self):
        """The pid and identity of a loop that runs until the test ends."""
        return owner(self.start("sleep", "600").pid)

    def ended(self, reap=True):
        """The pid and identity a loop recorded for itself, that loop since ended: reaped, or
        else left unreaped, a zombie."""
        proc = self.start("true")
        os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)
        recorded = owner(proc.pid)
        if reap:
            proc.wait()
        return recorded

    def resume(self, name, *options):
        """A real `ak run resume <name> [options]`, held still at its first bwrap, the check of
        its box, which comes before it records its pid; its command line, as `ps` shows it."""
        called = self.home.root / "tmp" / "bwrap-called"
        self.home.fake("bwrap", f"#!/bin/sh\n: > {shlex.quote(str(called))}\nexec sleep 600\n")
        proc = self.home.spawn("run", "resume", name, *options)
        deadline = time.monotonic() + 60
        while not called.exists():
            self.assertIsNone(proc.poll(), f"ak run resume {name} ended before calling bwrap")
            self.assertLess(time.monotonic(), deadline, f"ak run resume {name} never called bwrap")
            time.sleep(0.05)
        # stopped, not only waiting: ak gives its box's check seconds, then goes on without it
        os.killpg(proc.pid, signal.SIGSTOP)
        return Path(f"/proc/{proc.pid}/cmdline").read_text().split("\0")[:-1]

    def doctor(self, code, line, under=None):
        """`ak doctor` exits `code`, with `line` as its runs line, after the full report, and
        writes nothing; `under` is the run marker of a shell that calls it, as a worker's does."""
        tick = self.home.path / ".agentkit/state/watch.json"

        def kept():
            return {path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in [*self.runs.rglob("*"), tick] if path.is_file()}

        before = kept()
        # the shell waits for doctor rather than exec it, so it stays doctor's parent
        argv = ("sh", "-c", '"$@"; exit $?', "sh") if under else ()
        done = self.home.run(*argv, AK, "doctor", env={MARKER: str(under)} if under else None)
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

    def test_a_marked_worker_keeps_its_run_going_without_the_loop(self):
        self.start("sleep", "600", run=self.run_record("moving"))
        self.doctor(0, "1 started in the last day · 0 ended · 1 going · 0 endings owed")

    def test_a_marked_parent_keeps_its_run_going_when_it_calls_doctor(self):
        self.doctor(0, "1 started in the last day · 0 ended · 1 going · 0 endings owed",
                    under=self.run_record("moving") / "turn-acme")

    def test_a_resume_keeps_its_run_going_before_it_records_itself(self):
        self.run_record("moving")
        self.resume("moving", "--rounds", "3")
        self.doctor(0, "1 started in the last day · 0 ended · 1 going · 0 endings owed")

    def test_unrelated_commands_zombies_and_other_runs_do_not_hide_a_lost_run(self):
        directory = self.run_record("lost", **self.ended(reap=False))
        self.run_record("lost-other")
        resume = [*self.resume("lost-other")[:-1], "lost"]     # how lost's own would read
        self.start("sleep", "600", run=f"{directory}-other")
        self.start("tail", "-F", str(directory / "log.txt"))
        self.start("tail", "-F", *resume)
        # one reading as its resume with a word more: xargs, waiting on its input to run it
        self.start(*resume, "--extra", executable="xargs")
        self.doctor(1, "2 started in the last day · 0 ended · 1 going · 0 endings owed · "
                       "lost: lost (4m since last write)")


if __name__ == "__main__":
    unittest.main()
