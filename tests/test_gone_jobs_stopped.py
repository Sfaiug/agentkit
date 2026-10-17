"""The retention pass stops a job whose launcher is gone once nothing it ran has written for
30 days: its unfinished tasks recorded stopped, its run still going ended, the job finished.
A job gone two days, and one whose task's run log was written yesterday, stay as they are.

Offline: a throwaway HOME, the clock pinned, every launcher and loop gone by an injected
`process_active`, and kills, checkouts and systemd injected.  gc runs from another seat,
which no ownership check may stop.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
sys.path.insert(0, str(REPO))
from agentkit import browser, config, gc, handback, job as jobs, orch, record, stop, watch, worktrees

DAY = 86400
GONE, RECENT, WRITTEN = ("20260901-090000-acme-gone", "20261015-090000-acme-recent",
                         "20260910-090000-acme-written")


class GoneJobsStopped(Sandbox):
    def setUp(self):
        self.now = time.time()
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", return_value=self.now))
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "acme-ui", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        config.save_session(self.cfg, "acme-ui", "opus", ["opus", "astra"])
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.kill = self.stack.enter_context(patch.object(watch, "kill_tree"))
        self.stack.enter_context(patch.object(stop, "marker_pids", return_value=[]))
        self.stack.enter_context(patch.object(worktrees, "stop_checkout", return_value=True))
        self.stack.enter_context(patch.object(browser, "close_owned"))
        self.stack.enter_context(patch.object(handback, "redress_seat"))
        self.stack.enter_context(patch.object(record, "process_active", return_value=False))
        # the merged task's run directory went with the old-run rule already
        self.job(GONE, 31, [{"name": "fix-api-1.md", "state": "merged", "run_id": "fix-api-1"},
                            {"name": "fix-api-2.md", "state": "running", "run_id": "fix-api-2"},
                            {"name": "fix-api-3.md", "state": "queued", "run_id": None}])
        self.job(RECENT, 2, [{"name": "fix-ui-1.md", "state": "running", "run_id": "fix-ui-1"}])
        # its run ended by its record, so the old-run rule takes it in the same pass
        self.job(WRITTEN, 35, [{"name": "fix-web-1.md", "state": "running", "run_id": "fix-web-1"}],
                 run_state="pass")
        log = config.RUNS / "fix-web-1" / "log.txt"
        log.write_text("still at it\n")
        os.utime(log, (self.now - DAY, self.now - DAY))
        self.before = {name: jobs.receipt_path(config.JOBS / name).read_bytes()
                       for name in (RECENT, WRITTEN)}

    def job(self, name, days, tasks, run_state="running"):
        """A job and its running tasks' runs, all last written `days` ago."""
        at = self.now - days * DAY
        directory = config.JOBS / name
        directory.mkdir(parents=True)
        jobs.save_job(directory, {"job_id": name, "seat": "gone-seat", "pid": 4240,
                                  "started_at": at, "finished_at": None, "tasks": tasks})
        (directory / "log.txt").write_text("started\n")
        written = [directory]
        for task in tasks:
            if task["state"] == "running":
                run_dir = config.RUNS / task["run_id"]
                run_dir.mkdir()
                record.save_state(run_dir, {
                    "run_id": task["run_id"], "state": run_state, "pid": 4241,
                    "started_at": at, "finished_at": None if run_state == "running" else at,
                    "launched_session": "gone-seat", "job_id": name,
                    "branch": f"ak/{task['run_id']}"})
                written.append(run_dir)
        for top in written:
            for path in (top, *top.rglob("*")):
                os.utime(path, (at, at))

    def test_a_job_nothing_has_written_to_for_30_days_is_stopped(self):
        said = []
        gc.gc(said.append)
        directory = config.JOBS / GONE
        self.assertIn(f"gc: stop gone-job {directory}: the job's launcher gone and nothing "
                      "written for 30 days", said)
        job = jobs.read_job(directory)
        self.assertEqual([task["state"] for task in job["tasks"]], ["merged", "stopped", "stopped"])
        self.assertEqual(job["finished_at"], self.now)
        ended = record.read_state(config.RUNS / "fix-api-2")
        self.assertEqual((ended["state"], ended["error"]),
                         ("stopped", "the job's launcher gone and nothing written for 30 days"))
        self.kill.assert_not_called()
        for name, receipt in self.before.items():
            self.assertEqual(jobs.receipt_path(config.JOBS / name).read_bytes(), receipt, name)
        self.assertFalse((config.RUNS / "fix-web-1").exists())   # the old-run rule's, after
        later = self.now + gc.GC_AGE + 60
        self.assertEqual([item["job"] for item in gc.gc_candidates(now=later)
                          if item.get("kind") == "finished-job"], [str(directory)])

    def test_a_job_written_to_after_the_plan_stays_as_it_is(self):
        directory = config.JOBS / GONE
        planned = [item for item in gc.gc_plan() if item["kind"] == "gone-job"]
        self.assertEqual([item["job"] for item in planned], [str(directory)])
        receipt = jobs.receipt_path(directory).read_bytes()
        (directory / "log.txt").write_text("resumed\n")
        with patch.object(gc, "gc_candidates", return_value=iter(planned)):
            self.assertEqual(gc.gc(lambda _message: None), [])
        self.assertEqual(jobs.receipt_path(directory).read_bytes(), receipt)
        self.assertEqual(record.read_state(config.RUNS / "fix-api-2")["state"], "running")

    def test_a_link_or_a_recent_half_save_holds_a_job_and_an_old_half_save_does_not(self):
        directory = config.JOBS / GONE
        receipt = jobs.receipt_path(directory).read_bytes()
        victim = self.root / "owner-notes.txt"
        victim.write_text("the owner's\n")
        os.utime(victim, (self.now - 31 * DAY, self.now - 31 * DAY))
        for planted in (directory / "job.tmp", config.RUNS / "fix-api-2" / "result.md"):
            with self.subTest(planted=planted.name):
                planted.symlink_to(victim)
                gc.gc(lambda _message: None)
                planted.unlink()
                self.assertEqual(jobs.receipt_path(directory).read_bytes(), receipt)
                self.assertEqual(victim.read_text(), "the owner's\n")
        for name, top in (("job.tmp", directory), ("run.tmp", config.RUNS / "fix-api-2")):
            with self.subTest(half_save=name):
                (top / name).write_text("{}")   # a save its writer never finished, yesterday
                os.utime(top / name, (self.now - DAY, self.now - DAY))
                gc.gc(lambda _message: None)
                self.assertEqual(jobs.receipt_path(directory).read_bytes(), receipt)
                os.utime(top / name, (self.now - 31 * DAY, self.now - 31 * DAY))
        gc.gc(lambda _message: None)
        self.assertTrue(jobs.read_job(directory)["finished_at"])
        self.assertEqual(record.read_state(config.RUNS / "fix-api-2")["state"], "stopped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
