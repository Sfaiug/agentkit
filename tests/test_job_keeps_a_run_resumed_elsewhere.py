"""A job adopting its kept run while another process changes that run keeps the run.

On 9 Nov a relaunched job adopted its interrupted member run while the tick's resume rung was
resuming that same run: the job's resume was refused for the record changing under it, the
state read as before, and the job started the task over -- two runs of one task, both spending
turns.  In-process and offline, because the change lands between the resume's read of the
record and its check of it, where no other process can be timed to put it.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import box, config, gate, job as jobs, record


class KeptRunChangedElsewhere(Sandbox):
    def setUp(self):
        super().setUp()
        # the resume's refusal stops the run named here: never the run this suite works in
        self.stack.enter_context(patch.dict(os.environ, {
            config.RUN_DIR_ENV: "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(box, "check"))

    def adopt(self, name, elsewhere=None, **saved):
        """The task after its job adopts its kept interrupted run `name`, with `elsewhere`
        written on that record after the resume read it and before it checked it."""
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text("# Fix api\n\n## Done when\n```bash\ntrue\n```\n")
        (run_dir / "log.txt").touch()
        record.save_state(run_dir, {
            "run_id": name, "title": "Fix api", "state": "interrupted", "verdict": None,
            "pid": None, "process_identity": None, "tree_stopped": [None, None],
            "interrupted_at": 9000, "launched_session": None, "executor": "opus",
            "reviewer": "astra", "rounds": 1, "round_summaries": [], **saved})
        job_dir = config.JOBS / f"20261109-120000-{name}"
        job_dir.mkdir(parents=True)
        task = {"name": "fix-api.md", "title": "Fix api", "state": "running", "run_id": name}
        job = {"job_id": job_dir.name, "seat": None, "started_at": 9000, "finished_at": None,
               "parallel": None, **record.process_owner(), "opts": {}, "tasks": [task]}
        jobs.save_job(job_dir, job)
        checked = gate.slot_lock

        @contextmanager
        def slot_lock():
            if elsewhere:
                record.save_state(run_dir, {**record.read_state(run_dir), **elsewhere})
            with checked():
                yield

        with patch.object(gate, "slot_lock", slot_lock):
            jobs.job_adopt_worker(self.cfg, job_dir, job, task, run_dir, threading.Lock(),
                                  lambda _: None)
        self.assertEqual(jobs.read_job(job_dir)["tasks"][0], task)
        return task

    def test_a_run_changed_elsewhere_while_its_state_reads_the_same_stays_the_tasks(self):
        # the tick's resume rung stamps its order on the record before its resume owns it
        task = self.adopt("20261109-0900-fix-api",
                          {"resume_notice": {"at": 9500, "role": "executor", "restarted": False}})
        self.assertEqual(task["run_id"], "20261109-0900-fix-api")
        self.assertEqual(task["state"], "queued")
        self.assertEqual(task["retry_after"], 10000 + jobs.JOB_PICKER_INTERVAL)

    def test_a_run_refusing_resume_with_nobody_changing_it_starts_the_task_over(self):
        task = self.adopt("20261109-0900-fix-gone", scratch=True,
                          worktree=str(self.root / "gone"))
        self.assertEqual(task["run_id"], None)
        self.assertEqual(task["state"], "queued")


if __name__ == "__main__":
    unittest.main()
