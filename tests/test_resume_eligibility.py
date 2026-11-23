"""Resume admits the ordinary pick's capacity and preserves an executor's login failure, but
asks nothing of a saved executor that cannot run while a pair can, the reviewer's lab building
while another lab's marked reviewer's executor is spent, and keeps an executor whose refusal names
a moment still to come out of the tick's pick, admission and the resumed round's alike, before any
rule reads the list."""

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

    # alpha alone reviews, so beta, of another lab, builds while it has room, else alpha
    marks = {"step": "executor", "reviewer": "alpha", "reviewers": ["alpha"]}

    def test_a_login_failure_is_no_refusal_while_another_executor_can_run(self):
        self.cfg["models"]["gamma"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        state = {**self.marks, "executor": "gamma", "workers": ["alpha", "beta", "gamma"]}
        spent = usage.readiness(self.cfg, usage.Readings(self.providers(b=100)))
        self.assertEqual(run.resume_models(self.cfg, spent, state), ("alpha", "alpha"))
        refilled = usage.readiness(self.cfg, usage.Readings(self.providers()))
        self.assertEqual(run.resume_models(self.cfg, refilled, state), ("beta", "alpha"))

    def test_a_dropped_executor_is_refused_by_name(self):
        config.remove_provider(self.cfg, "c")
        state = {**self.marks, "executor": "delta", "workers": ["alpha", "beta", "delta"]}
        for used in (100, 10):
            with self.assertRaisesRegex(config.Error, "unknown model 'delta'"):
                run.resume_models(self.cfg, self.providers(b=used), state)

    def refused(self, marks, model="alpha"):
        """A parked run `model` refused until ten minutes on, marked `marks`."""
        directory = self.receipt("refused")
        state = record.read_state(directory)
        state.update(marks, no_merge=True, base=None, branch=None, base_sha=None, findings="",
                     refusal_retry={"model": model, "at": self.now + 600})
        record.save_state(directory, state)
        return directory

    def resumed_past_a_refusal(self, marks, ticked=None, then=None):
        """The pairs the rounds run of a run alpha refused until ten minutes on, marked `marks`,
        once a tick reading `ticked` resumes it on beta and the readings turn `then`."""
        directory = self.refused(marks)
        with patch.object(run, "spawn_bg") as spawn, patch.object(run, "rounds") as rounds:
            watch.resume_exhausted(self.cfg, ticked or self.readings, log=self.logs.append,
                                   now=self.now)
            spawn.assert_called_once()
            self.assertEqual(record.read_state(directory)["executor"], "beta")
            self.readings.update(then or {})
            run.resume_run([directory.name])
        return [(call.args[0].executor, call.args[0].reviewer) for call in rounds.call_args_list]

    def test_a_refused_executor_takes_no_turn_of_the_resume_before_its_moment(self):
        marks = {"workers": ["alpha", "beta"], "reviewers": ["beta"], "reviewer": "beta"}
        self.assertEqual(self.resumed_past_a_refusal(marks), [("beta", "beta")])

    def test_a_refused_subscription_keeps_no_payg_builder_out_of_the_resumed_round(self):
        self.cfg["providers"]["b"]["mode"] = self.cfg["providers"]["c"]["mode"] = "payg"
        marks = {"workers": ["alpha", "beta", "delta"], "reviewers": ["beta"], "reviewer": "beta"}
        self.assertEqual(self.resumed_past_a_refusal(marks, ticked=self.providers(c=100)),
                         [("delta", "beta")])

    def test_admission_parks_before_a_slot_when_only_the_refused_executor_has_room(self):
        self.assertEqual(self.resumed_past_a_refusal({"workers": ["alpha", "beta"]},
                                                     then=self.providers(b=100)), [])
        run.run_slot.assert_not_called()
        self.assertEqual(record.read_state(config.RUNS / "refused")["state"], "exhausted")

    def test_a_refused_executor_the_config_dropped_since_hands_an_explicit_resume_on(self):
        directory = self.refused({"executor": "delta", "workers": ["delta", "beta"],
                                  "reviewers": ["beta"], "reviewer": "beta",
                                  "models": dict(self.cfg["models"])}, "delta")
        config.remove_provider(self.cfg, "c")
        with patch.object(run, "rounds") as rounds:
            run.resume_run([directory.name])
        self.assertEqual([(call.args[0].executor, call.args[0].reviewer)
                          for call in rounds.call_args_list], [("beta", "beta")])


if __name__ == "__main__":
    unittest.main()
