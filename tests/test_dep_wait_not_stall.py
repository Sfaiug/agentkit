"""A passed run waiting for its dependency to merge is waiting, never stalled. Offline.

Fake run receipts under a throwaway HOME; the stall pass reads them with a stubbed
last write and a stubbed loop, and `ak run status` reads them with the loop stubbed
live. Nothing here signals a process or reads the real ~/.agentkit.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, watch, worker

DEP = "alpha.md"
LIVE = 999999991
DEAD = 999999992
OLD_PID = 999999993
NEW_PID = 999999994


class DepWaitNotStall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".dep-wait-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "NO_COLOR": "1", "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()

    def record(self, name, pid, dep_wait, **extra):
        """A running receipt marked (or not) as waiting for DEP, with a log file."""
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "log.txt").touch()
        state = {"run_id": name, "title": f"Run {name}", "state": "running",
                 "pid": pid, "process_identity": None, "started_at": time.time() - 1300,
                 "round_summaries": [{}], "stalls": [], "silence_minutes": 20,
                 "executor": "opus", "reviewer": "astra", "rounds": 3, "branch": f"ak/{name}"}
        if dep_wait is not None:
            state["dep_wait"] = dep_wait
        state.update(extra)
        run.save_state(directory, state)
        return directory

    def passing(self, directory, alive):
        """The stall pass over one run, its loop stubbed alive or dead, its write old."""
        old = time.time() - 21 * 60
        stack = self.stack
        stack.enter_context(patch.object(run, "run_dirs", return_value=[directory]))
        stack.enter_context(patch.object(run, "process_active", return_value=alive))
        stack.enter_context(patch.object(watch, "run_last_write", return_value=old))
        stack.enter_context(patch.object(watch, "step_for_run",
                                         return_value=("none", "no child", None, [])))
        kill = stack.enter_context(patch.object(watch, "kill_tree"))
        resume = stack.enter_context(patch.object(watch, "launch_resume"))
        return old, kill, resume

    def test_live_dep_wait_is_not_stalled_after_twenty_minutes_of_silence(self):
        directory = self.record("live-wait", LIVE, {"pid": LIVE, "of": DEP})
        state = run.read_state(directory)
        self.assertEqual(run.dep_wait_note(state), f"waiting for {DEP} to merge")
        old, kill, resume = self.passing(directory, True)
        # without the mark the same silence is a stall; with it the clock starts now
        bare = {**state, "dep_wait": None}
        bare.pop("dep_wait")
        self.assertLess(watch.stall_clock(directory, bare), old + 1)
        self.assertGreater(watch.stall_clock(directory, state), time.time() - 60)
        watch.recover_runs({}, log=lambda _: None, now=time.time())
        kill.assert_not_called()
        resume.assert_not_called()
        self.assertEqual(run.read_state(directory)["stalls"], [])

    def test_dead_or_resumed_dep_wait_does_not_hold_the_clock(self):
        grace = worker.KILL_GRACE + 2 * worker.ACTIVITY_POLL
        cases = {
            # the loop died with the mark on the record: the silence is a stall
            "dead": (self.record("dead-wait", DEAD, {"pid": DEAD, "of": DEP}), False),
            # a resume carried the mark to a new process: the mark says nothing
            "resumed": (self.record("resumed-wait", NEW_PID, {"pid": OLD_PID, "of": DEP}),
                        True),
        }
        for name, (directory, alive) in cases.items():
            with self.subTest(name=name):
                state = run.read_state(directory)
                if name == "resumed":
                    self.assertEqual(run.dep_wait_note(state), "")
                old, kill, resume = self.passing(directory, alive)
                self.assertLess(watch.stall_clock(directory, state), old + 1)
                watch.recover_runs({}, log=lambda _: None,
                                   now=old + 20 * 60 + grace + 0.01)
                self.assertEqual(len(run.read_state(directory)["stalls"]), 1)
                if alive:
                    kill.assert_called_once()
                resume.assert_called_once()

    def test_status_names_the_dependency_it_waits_for(self):
        directory = self.record("status-wait", LIVE, {"pid": LIVE, "of": DEP})
        state = run.read_state(directory)
        self.assertIn(f"  waiting for {DEP} to merge",
                      run.status_details(directory, state))
        with patch.object(run, "process_active", return_value=True):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(run.cmd_status([]), 0)
            self.assertIn(f"waiting for {DEP} to merge", out.getvalue())
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(run.cmd_status([directory.name]), 0)
            self.assertIn(f"waiting for {DEP} to merge", out.getvalue())

    def test_wait_marks_the_record_while_it_waits(self):
        job_id = "20260925-140000-dep-wait"
        job_dir = config.JOBS / job_id
        job_dir.mkdir(parents=True)
        run.save_job(job_dir, {"job_id": job_id, "seat": None, "started_at": time.time(),
                               "finished_at": None, "pid": LIVE, "process_identity": None,
                               "tasks": [{"name": DEP, "state": "running"},
                                         {"name": "beta.md", "state": "running",
                                          "run_id": "beta-wait"}]})
        directory = config.RUNS / "beta-wait"
        directory.mkdir(parents=True)
        (directory / "log.txt").touch()
        state = {"run_id": "beta-wait", "title": "Beta", "state": "running",
                 **run.process_owner(), "started_at": time.time(),
                 "round_summaries": [{}], "job_id": job_id,
                 "from_pass": {"task": DEP, "branch": "ak/alpha", "tip": "abc"},
                 "base_sha": "abc"}
        run.save_state(directory, state)
        logs = []
        lp = SimpleNamespace(state=state, run_dir=directory, base_sha="abc",
                             log=logs.append)
        with patch.object(run, "JOB_TICK", 0.05):
            result = {}
            thread = threading.Thread(target=lambda: result.update(
                rc=run.wait_for_dependency(lp)), daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 20
                while not run.dep_wait_note(run.read_state(directory) or {}):
                    self.assertLess(time.monotonic(), deadline,
                                    "the wait never marked the record")
                    time.sleep(0.02)
                self.assertEqual(run.dep_wait_note(run.read_state(directory)),
                                 f"waiting for {DEP} to merge")
                job = run.read_job(job_dir)
                job["tasks"][0]["state"] = "merged"
                run.save_job(job_dir, job)
            finally:
                thread.join(20)
            self.assertFalse(thread.is_alive())
            self.assertTrue(result["rc"])
        self.assertEqual(run.dep_wait_note(run.read_state(directory)), "")
        self.assertNotIn("dep_wait", run.read_state(directory))
        self.assertTrue(any(f"waiting for {DEP} to merge" in line for line in logs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
