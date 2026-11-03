"""Resume admits the ordinary pick's capacity and preserves an executor's login failure."""

from contextlib import nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_worker_list as fixtures
from agentkit import config, record, run, transitions, usage, watch


class ResumeEligibility(unittest.TestCase):
    providers = fixtures.WorkerList.providers

    def setUp(self):
        fixtures.WorkerList.setUp(self)
        self.readings = usage.Readings(self.providers())
        self.stack.enter_context(patch.object(config, "load", return_value=self.cfg))
        self.stack.enter_context(patch.object(run, "collect_usage", side_effect=lambda cfg:
                                              self.readings))
        self.stack.enter_context(patch.object(run.box, "check"))
        self.stack.enter_context(patch.object(run, "place_here", return_value=None))
        self.stack.enter_context(patch.object(run, "run_slot", side_effect=lambda *a, **kw:
                                              nullcontext()))
        self.stack.enter_context(patch.object(run.history, "Sampler"))
        self.stack.enter_context(patch.object(run.history, "sample_rss", return_value=None))
        self.stack.enter_context(patch.object(run.history, "close_step"))
        self.stack.enter_context(patch.object(run.gc, "before_run"))
        self.stack.enter_context(patch.object(run.worktrees, "settle_run"))
        self.stack.enter_context(patch.object(run, "rounds", side_effect=AssertionError(
            "an unavailable executor must never reach a round")))
        for name in ("started_on", "join_session_project", "history_start", "history_finish",
                     "record_result", "announce", "stop_run_tree", "redress_seat"):
            self.stack.enter_context(patch.object(run, name))

    def receipt(self, name, quota=True):
        directory = config.RUNS / name
        directory.mkdir()
        work = self.root / "work"
        work.mkdir(exist_ok=True)
        (directory / "task.md").write_text(
            "---\nrepo: none\n---\n# Acme work\n\n## Done when\n```bash\ntrue\n```\n")
        record.save_state(directory, {
            "run_id": name, "title": "Acme work", "state": "exhausted" if quota else "interrupted",
            "quota_dry": quota, "step": "executor", "executor": "alpha", "reviewer": "delta",
            "workers": ["alpha"], "reviewers": ["delta"], "scratch": True, "repo": None,
            "worktree": str(work), "rounds": 2, "round_summaries": [], "verdict": None})
        return directory

    def test_tick_and_explicit_resume_admit_credits_and_session_capacity(self):
        for kind in ("credits", "session"):
            with self.subTest(kind=kind):
                provider = self.readings["a"]
                provider["credits"] = 20 if kind == "credits" else 0
                provider["meters"][0].update(
                    used=100 if kind == "credits" else 10,
                    window_secs=604800 if kind == "credits" else 18000)
                self.assertEqual(run.pick_models(
                    self.cfg, self.readings, None, None, None, quiet=True,
                    workers=["alpha"], reviewers=["delta"]), ("alpha", "delta"))
                directory = self.receipt(kind)
                with patch.object(run, "spawn_bg") as spawn:
                    watch.resume_exhausted(self.cfg, self.readings, log=self.logs.append)
                spawn.assert_called_once()
                with patch.object(run, "drive", return_value=0) as drive:
                    self.assertEqual(run.resume_run([directory.name]), 0)
                drive.assert_called_once()

    def test_an_expired_executor_login_stays_an_error_without_a_window_wait(self):
        self.readings.harnesses = {("claude", provider): "claude is not logged in"
                                   for provider in self.cfg["providers"]}
        directory = self.receipt("login", quota=False)
        with self.assertRaisesRegex(config.Error, "claude is not logged in"):
            run.resume_run([directory.name])
        state = record.read_state(directory)
        self.assertEqual(state["state"], "error")
        self.assertFalse(state.get("quota_dry"))
        self.assertFalse(transitions.going(state))


if __name__ == "__main__":
    unittest.main()
