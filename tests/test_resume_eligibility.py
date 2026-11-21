"""Resume admits the ordinary pick's capacity and preserves an executor's login failure, but
asks nothing of the saved executor while it waits for one another lab's marked reviewer can
review."""

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

    # alpha alone reviews, so beta, of another lab, builds: a saved executor beside it that
    # cannot run is no refusal while beta can run here once it refills
    marks = {"step": "executor", "reviewer": "alpha", "reviewers": ["alpha"]}

    def test_a_login_failure_waits_while_another_labs_reviewer_s_executor_is_spent(self):
        self.cfg["models"]["gamma"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        state = {**self.marks, "executor": "gamma", "workers": ["alpha", "beta", "gamma"]}
        spent = usage.readiness(self.cfg, usage.Readings(self.providers(b=100)))
        with self.assertRaises(run.QuotaDry):
            run.resume_models(self.cfg, spent, state)
        refilled = usage.readiness(self.cfg, usage.Readings(self.providers()))
        self.assertEqual(run.resume_models(self.cfg, refilled, state), ("beta", "alpha"))

    def test_a_dropped_executor_waits_so_and_is_refused_by_name_once_nothing_is_waited_for(self):
        config.remove_provider(self.cfg, "c")
        state = {**self.marks, "executor": "delta", "workers": ["alpha", "beta", "delta"]}
        with self.assertRaises(run.QuotaDry):
            run.resume_models(self.cfg, self.providers(b=100), state)
        with self.assertRaisesRegex(config.Error, "unknown model 'delta'"):
            run.resume_models(self.cfg, self.providers(), state)


if __name__ == "__main__":
    unittest.main()
