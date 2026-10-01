"""The tick resumes only what is its own: never a job's run, and never by a title's word.

A job settles its own task's `error` and conflict FAIL -- skips its `after:` dependants or
reruns it elsewhere -- so the tick's `resume_errored` and `resume_waiting` leave such a run
to its job.  And the suite's own run is the one `menu.smoke_run` names by where it lives:
an owner run titled `smoke-...` still supersedes, and still votes for its seat's project.
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
from agentkit import config, orch, run, watch

CONFLICT_NOTE = "the fixer did not finish the rebase of origin/main; it was aborted"
TASK = "# Fix the parser\n\n## Done when\n\n```bash\ntest -f deliverable\n```\n"


class TickResumeScope(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".tick-scope-", dir=REPO)
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
        run.save_state(run_dir, {
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
                state = run.park_error(run_dir, run.read_state(run_dir), now=self.now)
                # the control without a job is born scheduled: the fixture is admitted
                self.assertEqual("error_retry_at" in state, not job)
                # an older record's due stamp is no licence either: its job settles it
                run.save_state(run_dir, {**state, "error_retry_at": self.now - 1,
                                         "error_retries": 0})
                self.spawned.clear()
                watch.resume_errored(log=self.logs.append, now=self.now)
                self.assertEqual(self.spawned, [] if job else [run_dir.name])
                self.assertEqual("error_retry_at" in run.read_state(run_dir), not job)
                self.assertEqual(run.going(run.read_state(run_dir), now=self.now), not job)

    def test_b_jobs_conflict_fail_is_never_parked(self):
        for job in (None, "20261001-0100-job"):
            with self.subTest(job=job):
                run_dir = self.receipt(f"20261001-0102-conflict-{bool(job)}", job_id=job,
                                       state="fail", verdict="FAIL", error=None,
                                       merge_note=CONFLICT_NOTE,
                                       round_summaries=[{"round": 1}])
                (run_dir / "log.txt").write_text(f"not merged: {CONFLICT_NOTE}\n")
                self.assertEqual(run.parkable_conflict(run.read_state(run_dir), run_dir,
                                                       now=self.now), not job)
                with patch.object(run, "upstream_sha", return_value="1" * 40):
                    watch.resume_waiting(log=self.logs.append, now=self.now)
                self.assertEqual(run.read_state(run_dir)["state"],
                                 "fail" if job else "waiting")

    def smoke_titled_pair(self, state, **extra):
        """An owner's run titled `smoke-...`, replaced by a later merged one of that title."""
        title = "smoke-test the parser"
        old = self.receipt(f"20261001-0103-{run.slugify(title)}", title=title, state=state,
                           **extra)
        new = self.receipt(f"20261001-0104-{run.slugify(title)}", title=title, state="pass",
                           verdict="PASS", merged=True, finished_at=self.now - 30)
        self.assertIn("smoke-", old.name)
        return old, new

    def test_c_an_owner_smoke_titled_run_supersedes_its_errored_predecessor(self):
        old, new = self.smoke_titled_pair("error", error_retry_at=self.now - 1,
                                             error_retries=0)
        self.assertEqual(run.superseded_by(run.read_state(old)), new.name)
        watch.resume_errored(log=self.logs.append, now=self.now)
        self.assertEqual(self.spawned, [])
        self.assertNotIn("error_retry_at", run.read_state(old))

    def test_d_an_owner_smoke_titled_run_supersedes_its_exhausted_predecessor(self):
        old, _ = self.smoke_titled_pair("exhausted", quota_dry=True)
        watch.resume_exhausted(self.cfg, {}, workers=[], log=self.logs.append, now=self.now)
        self.assertTrue(run.read_state(old).get("replaced"))

    def test_e_an_owner_smoke_titled_run_votes_and_the_suites_own_does_not(self):
        config.save_session(self.cfg, "legacy", "fable", ["opus"])
        self.receipt("20261001-0105-smoke-test-the-parser", launched_session="legacy")
        sandbox = config.TMP / "smoke-20261001-0100"
        for n in (1, 2):
            self.receipt(f"20261001-010{5 + n}-probe", launched_session="legacy",
                         repo=str(sandbox / "repo"), task=str(sandbox / "task.md"))
        found = orch.session_projects(config.session_records())
        self.assertEqual(found["legacy"], str(config.CODE / "acme"))


if __name__ == "__main__":
    unittest.main()
