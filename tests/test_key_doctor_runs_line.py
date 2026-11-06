"""Doctor counts runs and owed endings, and fails when a dead run outlasts two ticks.

Black-box through AK_BIN in a temporary HOME, on the real clock and the real process table: the
records and the tick's stamps are written set back from now, each boundary with a minute's
margin on either side, and every process that keeps a run alive, or does not, is one this test
starts and ends.  No tick resumes anything here: doctor only reads the records and reports what
is stuck.
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


def noon():
    """A zone where it is about noon now, so no ending written minutes back is yesterday's."""
    return f"Etc/GMT{round(time.time() % 86400 / 3600) - 12:+d}"


class DoctorRunsLine(unittest.TestCase):
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

    def run_record(self, name, state="running", ago=240, **fields):
        now = time.time()
        record = {"run_id": name, "title": "Fix api", "state": state,
                  "started_at": now - 10000, "launched_session": "acme", **fields}
        if state in ("pass", "fail", "blocked", "stopped"):
            record.setdefault("finished_at", now - ago)
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

    def ended(self, reap=True):
        """The pid and identity a loop recorded for itself, that loop since ended: reaped, or
        else left unreaped, a zombie."""
        proc = self.start("true")
        os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)
        recorded = owner(proc.pid)
        if reap:
            proc.wait()
        return recorded

    def resume(self, name):
        """A real `ak run resume <name>`, held still at its first bwrap, the check of its box,
        which comes before it records its pid; its command line, as `ps` shows it."""
        called = self.home.root / "tmp" / "bwrap-called"
        self.home.fake("bwrap", f"#!/bin/sh\n: > {shlex.quote(str(called))}\nexec sleep 600\n")
        proc = self.home.spawn("run", "resume", name)
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
        done = self.home.run(*argv, AK, "doctor",
                             env={"TZ": noon(), **({MARKER: str(under)} if under else {})})
        self.assertEqual(done.code, code, done.out + done.err)
        self.assertIn(f"runs  {line}", done.out.splitlines())
        self.assertTrue(done.out.splitlines()[-1].startswith("rented machines: "), done.out)
        self.assertEqual(kept(), before, "doctor must leave the run and tick records alone")

    def test_going_ended_and_owed_with_the_oldest_age(self):
        self.run_record("moving", ago=1000, **owner(self.start("sleep", "600").pid))
        self.run_record("said", "pass", ago=60, handed_back=time.time() - 50)
        self.run_record("owed", "blocked", ago=600, handback_pending=True)
        self.doctor(0, "1 going · 2 ended today · 1 ending owed, oldest 10m")

    def test_a_dead_run_fails_once_past_three_minutes_and_twice_the_last_tick(self):
        for took, age, code in ((10, 120, 0), (10, 240, 1), (150, 240, 0), (150, 360, 1)):
            with self.subTest(took=took, age=age):
                self.tick(took)
                self.run_record("lost", ago=age)
                self.doctor(code, "1 going · 0 ended today · 0 endings owed · "
                                  f"dead: lost ({age // 60}m since last write)")

    def test_old_endings_still_owed_are_shown_without_failing(self):
        self.run_record("old", "fail", ago=10, finished_at=time.time() - 2 * 86400)
        self.run_record("new", "pass", ago=600)
        self.run_record("reported", "pass", reported=True)
        self.run_record("said", "blocked", handed_back=True)
        self.run_record("stopped", "stopped")
        self.doctor(0, "0 going · 4 ended today · 2 endings owed, oldest 2d")

    def test_a_marked_worker_keeps_its_run_alive_without_the_loop(self):
        self.start("sleep", "600", run=self.run_record("moving"))
        self.doctor(0, "1 going · 0 ended today · 0 endings owed")

    def test_a_marked_parent_keeps_its_run_alive_when_it_calls_doctor(self):
        self.doctor(0, "1 going · 0 ended today · 0 endings owed",
                    under=self.run_record("moving", **self.ended()) / "turn-acme")

    def test_a_resume_keeps_its_run_alive_before_it_records_itself(self):
        self.run_record("moving", **self.ended())
        self.resume("moving")
        self.doctor(0, "1 going · 0 ended today · 0 endings owed")

    def test_unrelated_commands_zombies_and_other_runs_do_not_hide_a_dead_run(self):
        directory = self.run_record("lost", **self.ended(reap=False))
        self.run_record("lost-other")
        resume = [*self.resume("lost-other")[:-1], "lost"]     # how lost's own would read
        self.start("sleep", "600", run=f"{directory}-other")
        self.start("tail", "-F", str(directory / "log.txt"))
        self.start("tail", "-F", *resume)
        # one reading as its resume with a word more: xargs, waiting on its input to run it
        self.start(*resume, "--extra", executable="xargs")
        self.doctor(1, "2 going · 0 ended today · 0 endings owed · "
                       "dead: lost (4m since last write)")


if __name__ == "__main__":
    unittest.main()
