"""The tick resumes only what is its own: never a job's run.

A job settles its own task's `error` and conflict FAIL -- skips its `after:` dependants or
reruns it elsewhere -- so the tick's `resume_errored` and `resume_waiting` leave such a run
to its job, which resumes its own merge wait.
Offline: run records in a temporary HOME, a fake resume, a stubbed upstream sha.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, job as jobs, run, watch
from agentkit import record

CONFLICT_NOTE = "the fixer did not finish the rebase of origin/main; it was aborted"
TASK = "# Fix the parser\n\n## Done when\n\n```bash\ntest -f deliverable\n```\n"


class TickResumeScope(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-tick-scope-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "seat", "fable", ["opus", "astra"])
        self.now = time.time()
        self.logs, self.spawned = [], []
        self.stack.enter_context(patch.object(
            run, "spawn_bg", side_effect=lambda d, a, **_kw: self.spawned.append(d.name) or 0))

    def receipt(self, name, **extra):
        """An admitted ending of the seat's: under a day old, its worktree and task there."""
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(TASK)
        (wt := self.root / f"wt-{name}").mkdir()
        record.save_state(run_dir, {
            "run_id": name, "title": f"Task {name}", "state": "error", "verdict": None,
            "executor": "astra", "reviewer": "opus", "rounds": 3, "round_summaries": [],
            "launched_session": "seat", "repo": str(config.CODE / "acme"),
            "worktree": str(wt), "branch": f"ak/{name}", "base": "main",
            "base_sha": "0" * 40, "error": "executor astra died on API/transport errors",
            "started_at": self.now - 600, "finished_at": self.now - 120, **extra})
        return run_dir

    def test_a_jobs_error_is_never_scheduled_or_retried(self):
        for job in (None, "20261001-0100-job"):
            with self.subTest(job=job):
                run_dir = self.receipt(f"20261001-0101-err-{bool(job)}", job_id=job)
                state = run.park_error(run_dir, record.read_state(run_dir), now=self.now)
                # the control without a job is born scheduled: the fixture is admitted
                self.assertEqual("error_retry_at" in state, not job)
                # an older record's due stamp is no licence either: its job settles it
                record.save_state(run_dir, {**state, "error_retry_at": self.now - 1,
                                         "error_retries": 0})
                self.spawned.clear()
                watch.resume_errored(log=self.logs.append, now=self.now)
                self.assertEqual(self.spawned, [] if job else [run_dir.name])
                self.assertEqual("error_retry_at" in record.read_state(run_dir), not job)
                self.assertEqual(run.going(record.read_state(run_dir), now=self.now), not job)

    def test_b_jobs_conflict_fail_is_never_parked(self):
        for job in (None, "20261001-0100-job"):
            with self.subTest(job=job):
                run_dir = self.receipt(f"20261001-0102-conflict-{bool(job)}", job_id=job,
                                       state="fail", verdict="FAIL", error=None,
                                       merge_note=CONFLICT_NOTE,
                                       round_summaries=[{"round": 1}])
                (run_dir / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
                self.assertEqual(run.parkable_conflict(record.read_state(run_dir), run_dir,
                                                       now=self.now), not job)
                with patch.object(run, "upstream_sha", return_value="1" * 40):
                    watch.resume_waiting(log=self.logs.append, now=self.now)
                self.assertEqual(record.read_state(run_dir)["state"],
                                 "fail" if job else "waiting")

    def test_c_a_jobs_wait_is_resumed_by_its_job_never_by_the_tick(self):
        wait = {"state": "waiting", "verdict": "PASS", "error": CONFLICT_NOTE,
                "merge_note": CONFLICT_NOTE, "waiting_on": {"ref": "origin/main", "sha": "0" * 40}}
        lone = self.receipt("20261001-0103-lone", **wait)
        mine = self.receipt("20261001-0103-mine", job_id="20261001-0100-job", **wait)
        resumed = lambda d, a, **_kw: record.save_state(d, {**record.read_state(d), "state": "queued"})
        with patch.object(run, "upstream_sha", return_value="1" * 40), \
                patch.object(run, "spawn_bg", side_effect=resumed) as spawn:
            watch.resume_waiting(log=self.logs.append, now=self.now)
            self.assertEqual([call.args[0] for call in spawn.call_args_list], [lone])
            # the job follows its own wait and resumes it once main moved
            with patch.object(run.time, "sleep"), \
                    patch.object(jobs, "job_await", side_effect=lambda directory, **_kw:
                                 record.read_state(directory)), \
                    patch.object(jobs, "job_wait_login", return_value=True):
                jobs.job_ladder(self.cfg, None, {}, {"name": "fix-api"}, mine,
                               record.read_state(mine), 0, self.logs.append, None)
            self.assertEqual([call.args[0] for call in spawn.call_args_list], [lone, mine])


if __name__ == "__main__":
    unittest.main()
