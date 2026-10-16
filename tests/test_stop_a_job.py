"""`ak run stop <job>` ends the whole job: its run still going is stopped, a task that never
started is recorded stopped, and status reads the job ended with no `launcher gone` line.

Offline: a throwaway HOME, the launcher and the runs' loops gone by an injected
`process_active`, and kills, checkouts and systemd injected.
"""

from contextlib import redirect_stdout
import io
import os
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
sys.path.insert(0, str(REPO))
from agentkit import (box, browser, config, gc, handback, job as jobs, orch, record, run,
                      stop, turns, watch, worktrees)

JOB = "20261016-090000-acme-job"
LAUNCHER = 4240


class StopAJob(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "acme-api", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        for name in ("acme-api", "acme-ui"):
            config.save_session(self.cfg, name, "opus", ["opus", "astra"])
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.kill = self.stack.enter_context(patch.object(watch, "kill_tree"))
        self.stack.enter_context(patch.object(stop, "marker_pids", return_value=[]))
        self.stack.enter_context(patch.object(worktrees, "stop_checkout", return_value=True))
        self.stack.enter_context(patch.object(browser, "close_owned"))
        self.stack.enter_context(patch.object(handback, "redress_seat"))
        self.stack.enter_context(patch.object(turns, "stop_run_tree"))
        self.alive = set()   # the pids still running: none, unless a test says so
        self.stack.enter_context(patch.object(
            record, "process_active", side_effect=lambda state: state.get("pid") in self.alive))
        self.ended("fix-api-1", owner="acme-api", merged=True, job_id=JOB)
        self.running = config.RUNS / "fix-api-2"
        self.running.mkdir()
        record.save_state(self.running, {
            "run_id": "fix-api-2", "state": "running", "pid": 4241, "started_at": 9000,
            "launched_session": "acme-api", "job_id": JOB, "branch": "ak/fix-api-2"})
        self.job_dir = config.JOBS / JOB
        self.job_dir.mkdir(parents=True)
        jobs.save_job(self.job_dir, {
            "job_id": JOB, "seat": "acme-api", "pid": LAUNCHER, "started_at": 9000,
            "finished_at": None, "tasks": [
                {"name": "fix-api-1.md", "state": "merged", "run_id": "fix-api-1",
                 "finished_at": 9990, "verdict_line": "fix-api-1.md: merged"},
                {"name": "fix-api-2.md", "state": "running", "run_id": "fix-api-2"},
                {"name": "fix-api-3.md", "state": "queued", "run_id": None}]})

    def ak(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.main(list(argv)), 0)
        return out.getvalue()

    def test_stopping_a_job_whose_launcher_is_gone_ends_it(self):
        self.assertIn("launcher gone", self.ak("status", JOB))
        said = self.ak("stop", JOB)
        self.assertIn(f"stopped {JOB}", said)
        self.assertIn("stopped fix-api-2: branch ak/fix-api-2", said)
        self.assertEqual(record.read_state(self.running)["state"], "stopped")
        self.assertEqual(record.read_state(config.RUNS / "fix-api-1")["state"], "pass")
        job = jobs.read_job(self.job_dir)
        self.assertEqual([task["state"] for task in job["tasks"]],
                         ["merged", "stopped", "stopped"])
        self.assertTrue(job["finished_at"])
        for argv in ([JOB], []):
            with self.subTest(argv=argv):
                text = self.ak("status", *argv)
                self.assertIn(f"job {JOB}: 1 merged, 2 stopped", text)
                self.assertNotIn("launcher gone", text)
        self.kill.assert_not_called()   # nothing was left running to end by its tree
        self.assertIn(f"{JOB} is already stopped", self.ak("stop", JOB))
        later = time.time() + gc.GC_AGE + 60
        collected = [item["job"] for item in gc.gc_candidates(now=later)
                     if item.get("kind") == "finished-job"]
        self.assertEqual(collected, [str(self.job_dir)])

    def test_a_live_launcher_is_ended_before_the_receipt_is_written(self):
        self.alive.add(LAUNCHER)

        def killed(pid, _log):
            self.assertIsNone(jobs.read_job(self.job_dir)["finished_at"])
            self.alive.discard(pid)
        self.kill.side_effect = killed
        self.ak("stop", JOB)
        self.kill.assert_called_once()
        self.assertEqual(self.kill.call_args.args[0], LAUNCHER)
        self.assertEqual(record.read_state(self.running)["state"], "stopped")
        self.assertTrue(jobs.read_job(self.job_dir)["finished_at"])

    def test_a_launcher_its_scope_stop_ended_is_not_signalled_by_its_old_pid(self):
        # once the scope stop has ended the launcher, its pid may be another process's
        self.alive.add(LAUNCHER)
        with patch.object(orch, "stop_scope",
                          side_effect=lambda *_a, **_kw: self.alive.discard(LAUNCHER)):
            self.ak("stop", JOB)
        self.kill.assert_not_called()
        self.assertTrue(jobs.read_job(self.job_dir)["finished_at"])

    def test_a_run_not_yet_filed_on_the_receipt_is_stopped_with_its_job(self):
        # its launcher stopped mid-preflight: only the run's own record names the job
        preflight = config.RUNS / "fix-api-3"
        preflight.mkdir()
        record.save_state(preflight, {"run_id": "fix-api-3", "state": "queued", "pid": LAUNCHER,
                                      "launched_session": "acme-api", "job_id": JOB})
        self.ak("stop", JOB)
        self.assertEqual(record.read_state(preflight)["state"], "stopped")

    def test_a_resume_that_read_the_receipt_before_the_stop_cannot_undo_it(self):
        scheduler = self.stack.enter_context(patch.object(jobs, "run_job_loop", return_value=0))
        # the resume has read the receipt and let go of its lock when the stop lands
        out = io.StringIO()
        with patch.object(box, "check", side_effect=lambda: self.ak("stop", JOB)), \
                patch.object(config, "load", return_value={}), redirect_stdout(out):
            self.assertEqual(run.main(["resume", JOB]), 1)
        self.assertIn(f"{JOB} was stopped; nothing to resume", out.getvalue())
        self.assertTrue(jobs.read_job(self.job_dir)["finished_at"])
        scheduler.assert_not_called()

    def test_a_run_whose_receipt_cannot_be_read_is_left_as_it_is(self):
        torn = b'{"state": "pass", "merged": true, "branch": "ak/fix-api-2",'
        (self.running / "run.json").write_bytes(torn)
        self.assertIn("fix-api-2: cannot read", self.ak("stop", JOB))
        self.assertEqual((self.running / "run.json").read_bytes(), torn)
        self.assertTrue(jobs.read_job(self.job_dir)["finished_at"])

    def test_a_seat_cannot_stop_another_seats_job(self):
        os.environ[config.SESSION_ENV] = "acme-ui"
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with redirect_stdout(io.StringIO()), self.assertRaises(config.Error) as refused:
            run.main(["stop", JOB])
        self.assertIn("owned by seat acme-api; a seat stops only its own runs",
                      str(refused.exception))
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents, path)
        self.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
