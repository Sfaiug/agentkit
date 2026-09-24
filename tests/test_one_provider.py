"""Review pairs with one subscription, fake budgets and no model calls."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, terminal, usage


class OneProvider(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".one-provider-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Silent fake reviewers leave no children; their fallback must never sweep
        # processes carrying the hosting run's inherited marker.
        self.stack.enter_context(patch.object(run.worker, "kill_marked", return_value=True))
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.cfg = {"defaults": {"orchestrator": "seat",
                                 "workers": ["alpha", "beta", "gamma", "delta"]},
                    "models": {}, "providers": {"a": {}, "b": {}}}
        for name, provider in (("seat", "a"), ("alpha", "a"), ("beta", "a"),
                               ("gamma", "b"), ("delta", "b")):
            self.cfg["models"][name] = {"harness": "test", "model": name,
                                         "effort": "high", "provider": provider}
        self.providers = self.meters()
        self.logs = []

    def meters(self, a=10, b=70):
        return {name: {"meters": [{"name": "weekly", "used": used, "pace": used - 50,
                                  "elapsed": 50,
                                  "window_secs": 604800, "resets_at": time.time() + 302400}],
                       "resets": 0}
                for name, used in (("a", a), ("b", b))}

    def pick(self, executor=None, reviewer=None):
        return run.pick_models(self.cfg, self.providers, executor, reviewer, self.logs.append)

    def loop(self, executor="alpha", reviewer="beta", spares=()):
        directory = self.root / "run"
        directory.mkdir()
        workspace = self.root / "work"
        workspace.mkdir()
        state = {"run_id": "fixture", "state": "running", "verdict": None,
                 "executor": executor, "reviewer": reviewer, "repo": None,
                 "scratch": True, "worktree": str(workspace), "base": None,
                 "rounds": 2, "round_summaries": [], "findings": ""}
        lp = run.Loop(self.cfg, directory, state, {}, self.logs.append, workspace,
                      "Review the work.", [], "Fixture", list(spares))
        lp.rnd = 1
        lp.round_dir.mkdir()
        return lp

    def evidence(self):
        return {"verdict": "PASS", "state": "pass", "executor": "alpha",
                "reviewer": "beta", "scratch": True,
                "review": {"executor": "alpha", "executor_provider": "a",
                           "reviewer": "beta", "reviewer_provider": "a",
                           "returncode": 0, "verdict": "PASS", "done_when": True}}

    def test_two_providers_prefer_another_company_over_more_budget(self):
        self.assertEqual(self.pick(), ("alpha", "gamma"))
        self.providers = self.meters(a=70, b=10)
        self.assertEqual(self.pick(), ("gamma", "alpha"))

    def test_reviewers_keep_budget_order_within_each_company_preference(self):
        self.cfg["models"]["gamma"]["meter"] = "smaller"
        self.providers["b"]["meters"].append(
            {**self.providers["b"]["meters"][0], "name": "smaller", "used": 95})
        self.cfg["models"]["delta"]["meter"] = "weekly"
        self.assertEqual(self.pick("alpha"), ("alpha", "delta"))
        self.cfg["models"]["gamma"]["reviews_own_provider"] = False
        self.assertEqual(self.pick("beta"), ("beta", "delta"))
        self.providers["a"] = self.providers["b"]
        for name in ("gamma", "delta"):
            self.cfg["models"][name]["provider"] = "a"
        self.cfg["defaults"]["workers"] = ["alpha", "gamma", "delta"]
        self.assertEqual(self.pick("alpha"), ("alpha", "delta"))

    def test_shipped_fable_opts_out_of_same_company_reviews(self):
        cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        self.assertIs(cfg["models"]["fable"]["reviews_own_provider"], False)

    def test_one_provider_two_models_pick_the_other(self):
        self.providers = self.meters(b=100)
        self.assertEqual(self.pick(), ("alpha", "beta"))
        self.assertEqual(self.pick("beta"), ("beta", "alpha"))

    def test_one_provider_one_model_is_quota_dry(self):
        self.cfg["defaults"]["workers"] = ["alpha"]
        with self.assertRaises(run.QuotaDry):
            self.pick()
        self.assertIsNone(usage.review_pair(self.cfg, self.providers))

    def test_opt_out_blocks_own_company_but_allows_other_companies(self):
        self.cfg["models"]["beta"]["reviews_own_provider"] = False
        self.providers = self.meters(b=100)
        with self.assertRaises(run.QuotaDry):
            self.pick("alpha")
        with self.assertRaisesRegex(config.Error, "reviews_own_provider"):
            self.pick("alpha", "beta")
        self.assertEqual(run.review_providers(self.cfg, "gamma", "beta"), ("b", "a"))
        self.providers = self.meters()
        self.cfg["defaults"]["workers"] = ["beta", "gamma"]
        self.assertEqual(self.pick("gamma"), ("gamma", "beta"))

    def test_auto_pair_can_execute_on_the_model_that_cannot_review_its_company(self):
        self.providers = self.meters(b=100)
        self.cfg["models"]["beta"]["reviews_own_provider"] = False
        self.assertEqual(self.pick(), ("beta", "alpha"))

    def test_same_model_and_aliases_are_never_reviewers(self):
        with self.assertRaisesRegex(config.Error, "same model"):
            self.pick("alpha", "alpha")
        self.cfg["models"]["beta"]["model"] = "alpha"
        self.providers = self.meters(b=100)
        with self.assertRaises(run.QuotaDry):
            self.pick()
        with self.assertRaisesRegex(config.Error, "same model"):
            self.pick("alpha", "beta")

    def unready(self, **why):
        """The read a pick starts from, with each named harness's answer beside it."""
        self.providers = usage.Readings(self.meters())
        self.providers.harnesses = why

    def test_a_harness_not_installed_or_not_logged_in_is_skipped_with_one_line(self):
        for name in ("gamma", "delta"):
            self.cfg["models"][name]["harness"] = "other"
        for words in ("not logged in", "not installed"):
            with self.subTest(words=words):
                self.logs[:] = []
                self.unready(other=f"other is {words}")
                # the cheaper company is out of reach: its models are never given a role,
                # and one provider's two models run the work, never the same one twice
                self.assertEqual(self.pick(), ("alpha", "beta"))
                self.assertEqual(self.pick("alpha"), ("alpha", "beta"))
                self.assertNotIn("gamma", run.ready_order(self.cfg, self.providers,
                                                          role="reviewer"))
                # the ranking itself keeps it; only a pick leaves it out
                self.assertIn("gamma", usage.pick_order(self.cfg, self.providers))
                self.assertEqual(self.logs, [f"skipped gamma: other is {words}",
                                             f"skipped delta: other is {words}"] * 2)
                # a model named outright is refused at launch, never handed the work
                with self.assertRaisesRegex(config.Error,
                                            f"^gamma cannot run here: other is {words}$"):
                    self.pick("gamma")
                with self.assertRaisesRegex(config.Error, "^delta cannot run here"):
                    self.pick("alpha", "delta")
                # ... and so is a saved one a resume would hand the work back to
                with self.assertRaisesRegex(config.Error, "^gamma cannot run here"):
                    run.pick_models(self.cfg, self.providers, "gamma", "alpha",
                                    self.logs.append, resuming=True)
        # a harness that answered nothing is withheld from nothing
        self.unready(other=None)
        self.assertEqual(self.pick(), ("alpha", "gamma"))

    def test_every_harness_is_asked_on_every_pick_whatever_its_meters_say(self):
        self.cfg["models"]["gamma"]["harness"] = "other"
        self.cfg["models"]["delta"]["harness"] = "gone"
        # a provider the usage snapshot does not carry yet is a provider a pick can reach
        self.cfg["providers"]["c"] = {}
        self.cfg["models"]["late"] = {"harness": "late", "model": "late", "effort": "high",
                                      "provider": "c"}
        asked = []

        def auth(harness):
            asked.append(harness)
            return harness != "other", "fixture"
        with patch.object(config, "adapter", return_value=REPO / "adapters/claude.sh"), \
                patch.object(config, "harness_binary", side_effect=lambda name: name != "gone"), \
                patch.object(usage.worker, "auth_ok", side_effect=auth):
            read = usage.readiness(self.cfg, usage.Readings(self.providers))
        # every harness, once, beside meters that read fine, and the providers themselves
        # exactly as the usage read had them
        self.assertEqual(sorted(asked), ["late", "other", "test"])
        self.assertEqual(read, self.providers)
        self.assertEqual(usage.unready(self.cfg, "gamma", read), "other is not logged in")
        # a harness whose manifest names no `[update] version` is looked for by its own name
        self.assertEqual(usage.unready(self.cfg, "delta", read), "gone is not installed")
        self.assertIsNone(usage.unready(self.cfg, "alpha", read))
        self.assertIsNone(usage.unready(self.cfg, "late", read))
        # a harness with no adapter is not installed, whatever its credentials
        read = usage.readiness(self.cfg, usage.Readings(self.providers))
        self.assertEqual(usage.unready(self.cfg, "alpha", read), "test is not installed")
        # a stand-in for the usage layer is taken as it stands
        with patch.object(usage.worker, "auth_ok", side_effect=AssertionError("asked")):
            self.assertIs(usage.readiness(self.cfg, self.providers), self.providers)

    def test_a_subscription_nobody_can_run_keeps_no_payg_provider_out(self):
        self.cfg["providers"]["b"]["mode"] = "payg"
        for name in ("gamma", "delta"):
            self.cfg["models"][name]["harness"] = "other"
        self.unready(test="test is not logged in")
        self.assertEqual(run.ready_order(self.cfg, self.providers), ["gamma", "delta"])
        self.assertEqual(self.pick(), ("gamma", "delta"))

    def test_only_claude_logged_in_pairs_two_anthropic_models_as_configured(self):
        cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        cfg["defaults"]["workers"] = ["opus", "fable", "astra", "spark", "grok"]
        meter = self.providers["a"]["meters"][0]
        providers = usage.Readings({name: {"meters": [], "error": "unknown: no login"}
                                    for name in cfg["providers"]})
        providers.harnesses = {harness: f"{harness} is not logged in"
                               for harness in ("codex", "muse", "grokbuild")}
        providers["anthropic"] = {"resets": 0, "meters": [
            {**meter, "name": "weekly_all"}, {**meter, "name": "weekly_scoped"}]}
        # the shipped Fable reviews only another company's work, so Opus reviews Fable
        self.assertEqual(run.pick_models(cfg, providers, None, None, self.logs.append),
                         ("fable", "opus"))
        self.assertEqual(self.logs, ["skipped astra: codex is not logged in",
                                     "skipped spark: muse is not logged in",
                                     "skipped grok: grokbuild is not logged in"])
        # a user who lets Fable review has it review Opus
        cfg["models"]["fable"]["reviews_own_provider"] = True
        self.assertEqual(run.pick_models(cfg, providers, None, None, self.logs.append),
                         ("opus", "fable"))

    def test_a_launch_with_no_allowed_pair_is_refused_in_one_sentence(self):
        self.cfg["defaults"]["workers"] = ["alpha", "gamma"]
        self.cfg["models"]["gamma"]["harness"] = "other"
        self.unready(other="other is not logged in")
        with self.assertRaises(run.QuotaDry):
            self.pick()
        self.assertEqual(run.pair_refusal(self.cfg, self.providers, None),
                         "no two of the workers alpha, gamma make an allowed executor and "
                         "reviewer (gamma: other is not logged in); log in to another harness "
                         "or add another model to the workers")
        self.assertIsNone(run.pair_refusal(self.cfg, self.providers, ["alpha", "beta", "gamma"]))
        # a spent meter refills; a list of one model never grows a second, in a session or not
        self.providers = self.meters(b=100)
        self.assertIsNone(run.pair_refusal(self.cfg, self.providers, None))
        refusal = ("no two of the workers alpha make an allowed executor and reviewer; "
                   "log in to another harness or add another model to the workers")
        self.assertEqual(run.pair_refusal(self.cfg, self.providers, ["alpha"]), refusal)
        self.cfg["defaults"]["workers"] = ["alpha"]
        self.assertEqual(run.pair_refusal(self.cfg, self.providers, None), refusal)

    def test_handover_to_reviewers_provider_repicks_and_records_the_pair(self):
        lp = self.loop(reviewer="gamma")
        self.providers = self.meters(a=100, b=10)
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "gamma")
        self.assertEqual((lp.executor, lp.reviewer), ("gamma", "delta"))
        saved = run.read_state(lp.run_dir)
        self.assertEqual((saved["executor"], saved["reviewer"]), ("gamma", "delta"))
        self.assertIsNone(saved["review_session"])
        self.assertTrue(any("reviewer re-picked" in line for line in self.logs))

    def test_handover_skips_executor_without_a_legal_reviewer(self):
        lp = self.loop(reviewer="gamma")
        self.providers = self.meters(a=100, b=10)
        self.cfg["models"]["delta"]["reviews_own_provider"] = False
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "delta")
        self.assertEqual(lp.reviewer, "gamma")

    def test_handover_cannot_leave_a_single_model_to_review_itself(self):
        lp = self.loop(reviewer="gamma")
        self.providers = self.meters(a=100, b=10)
        self.cfg["defaults"]["workers"].remove("delta")
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertIsNone(run.hand_executor(lp, "ran dry", "refused", set()))
        self.assertEqual((lp.executor, lp.reviewer), ("alpha", "gamma"))

    def test_handover_keeps_an_unchanged_reviewers_session(self):
        lp = self.loop(reviewer="gamma")
        lp.review_sid = "existing-review"
        self.cfg["providers"]["c"] = {}
        self.cfg["models"]["delta"]["provider"] = "c"
        self.providers = self.meters(a=100, b=10)
        # delta is the cheaper executor, so the re-picked pair keeps gamma reviewing it
        self.providers["c"] = self.meters(b=5)["b"]
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "delta")
        self.assertEqual((lp.reviewer, lp.review_sid), ("gamma", "existing-review"))
        self.assertEqual(run.read_state(lp.run_dir)["review_session"], "existing-review")
        self.assertFalse(any("reviewer re-picked" in line for line in self.logs))

    def test_only_the_default_orchestrator_can_resume_as_an_unselected_worker(self):
        session = {"name": "fixture", "orchestrator": "gamma", "workers": ["alpha", "beta"]}
        with patch.object(config, "active_session", return_value=session):
            for resuming in (False, True):
                with self.assertRaisesRegex(config.Error, "not a worker"):
                    run.pick_models(self.cfg, self.providers, "gamma", "alpha",
                                    self.logs.append, resuming=resuming)
            session["orchestrator"] = "seat"
            self.assertEqual(run.pick_models(self.cfg, self.providers, "seat", "alpha",
                                             self.logs.append, resuming=True), ("seat", "alpha"))

    def test_lag_preference_and_display_use_same_company_pair_policy(self):
        cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        # the fixture below answers for three companies, so the default workers are scoped
        # to them and the scenario stays what it says
        cfg["defaults"]["workers"] = [m for m in cfg["defaults"]["workers"]
                                      if cfg["models"][m]["provider"] in
                                      ("anthropic", "openai", "meta")]
        meter = self.providers["a"]["meters"][0]
        providers = {
            "anthropic": {"meters": [{**meter, "name": "weekly_all", "used": 80},
                                      {**meter, "name": "weekly_scoped", "used": 53}]},
            "openai": {"meters": [{**meter, "used": 100}]},
            "meta": {"meters": [{**meter, "used": 100}]}}
        usage._gate_flags(providers, time.time(), cfg)
        order = usage.pick_order(cfg, providers, quiet=True)
        self.assertEqual(order, ["fable", "opus"])
        with patch.object(terminal, "width", return_value=100):
            text = usage.render(cfg, providers, order)
        self.assertIn("preferring Fable as executor", text)
        self.assertIn("pick order: fable, opus\nreview: fable by opus", text)
        self.assertIn("one provider: reviewer on the same company", text)
        cfg["models"]["opus"]["reviews_own_provider"] = False
        self.assertFalse(usage._fable_pair_available(cfg, providers, order))
        cfg["models"]["opus"]["reviews_own_provider"] = True
        cfg["models"]["opus"]["model"] = cfg["models"]["fable"]["model"]
        self.assertFalse(usage._fable_pair_available(cfg, providers, order))

    def resume_integration(self, reviewer="beta"):
        lp = self.loop(reviewer=reviewer)
        identity = {"head_sha": "reviewed-head", "tree_sha": "reviewed-tree"}
        lp.state.update(state="fail", verdict="FAIL", repo=str(lp.wt), scratch=False,
                        branch="ak/fixture", base="main", base_sha="base", merge_note="race",
                        round_summaries=[{"verdict": "PASS", "done_when": True, **identity}])
        (lp.run_dir / "task.md").write_text(
            "---\nrepo: none\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        (lp.run_dir / "log.txt").write_text("not merged: integration race\n")
        lp.save()
        with ExitStack() as stack:
            for key in ("HOME", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE", "JOBS"):
                stack.enter_context(patch.object(config, key, self.root / key.lower()))
            stack.enter_context(patch.object(config, "RUNS", self.root))
            stack.enter_context(patch.object(config, "load", return_value=self.cfg))
            stack.enter_context(patch.object(run, "commit_identity", return_value=identity))
            drive = stack.enter_context(patch.object(run, "drive", return_value=0))
            stack.enter_context(redirect_stdout(io.StringIO()))
            self.assertEqual(run.resume_run([lp.run_dir.name]), 0)
        return drive.call_args.kwargs["prior"]

    def test_integration_resume_restores_same_company_review_evidence(self):
        state = self.resume_integration()
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertNotIn("review_pending", state)
        self.assertEqual(state["review"]["head_sha"], "reviewed-head")

    def test_integration_resume_does_not_restore_forbidden_same_company_review(self):
        self.cfg["models"]["beta"]["reviews_own_provider"] = False
        state = self.resume_integration()
        self.assertFalse(run.review_pass(state, self.cfg))
        self.assertIn("review_pending", state)

    def test_integration_resume_does_not_restore_self_review(self):
        state = self.resume_integration(reviewer="alpha")
        self.assertFalse(run.review_pass(state, self.cfg))
        self.assertIn("review_pending", state)

    def test_reports_keep_the_runs_config_without_reloading_it(self):
        lp = self.loop()
        state = {**lp.state, **self.evidence(), "title": "Fixture", "finished_at": time.time()}
        with patch.object(config, "load", side_effect=AssertionError("must use the run's config")):
            run.write_result(lp.run_dir, state, [], cfg=self.cfg)
            self.assertTrue((lp.run_dir / "result.md").read_text().startswith("# PASS, delivered"))
            # No task file: the fallback writer must use the same config as the full report.
            run.record_result(lp.run_dir, state, cfg=self.cfg)
            self.assertTrue((lp.run_dir / "result.md").read_text().startswith("# PASS, delivered"))
            self.assertEqual(run.verdict_word(state, self.cfg), "PASS")
            self.assertIn("PASS", run.summary_line(state, self.cfg))
            self.assertEqual(run.status_word(state, self.cfg), "delivered")
            self.assertEqual(run.job_classify(state, self.cfg), "passed")
            with patch.object(run, "announce") as announce:
                self.assertEqual(run.finish(state, lp.run_dir, self.logs.append, self.cfg), 0)
            announce.assert_called_once_with(state, lp.run_dir, self.logs.append, self.cfg)
            with patch.object(run, "launched_session", return_value="orphan"), \
                    patch.object(run, "launcher_watched", return_value=False), \
                    patch.object(run.watch, "seat_closed", return_value=False), \
                    patch.object(run.watch, "revive", return_value=None) as revive:
                run.announce(state, lp.run_dir, self.logs.append, self.cfg)
            self.assertIn("finished PASS", revive.call_args.args[1])

    def test_fallback_result_survives_an_unreadable_config(self):
        lp = self.loop()
        state = {**lp.state, "title": "Fixture", "state": "error", "error": "original failure"}
        with patch.object(config, "load", side_effect=config.Error("invalid TOML")):
            run.record_result(lp.run_dir, state, self.logs.append)
            self.assertEqual(run.delivery(self.evidence()), "FAIL")
        result = (lp.run_dir / "result.md").read_text()
        self.assertIn("original failure", result)
        self.assertIn("relaunch:", result)

    def test_job_rerun_defers_usage_collection_to_the_run_picker(self):
        lp = self.loop()
        state = {**lp.state, "state": "fail", "verdict": "FAIL", "rounds": 1,
                 "round_summaries": [{}]}
        task_path = self.root / "task.md"
        task_path.write_text("---\nrepo: none\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        rerun_dir = self.root / "rerun"
        rerun_dir.mkdir()
        for reviewer, reviews_own_provider, wanted in (
            ("gamma", True, "gamma"), ("alpha", True, "alpha"), ("beta", True, None),
            ("alpha", False, None), (None, True, None),
        ):
            self.cfg["models"]["alpha"]["reviews_own_provider"] = reviews_own_provider
            task = {"name": "fixture", "task_file": str(task_path), "resume_attempted": True,
                    "review_override": "delta"}
            job = {"opts": {"--review": reviewer}}
            with self.subTest(reviewer=reviewer, reviews_own_provider=reviews_own_provider), \
                    patch.object(run, "collect_usage", side_effect=AssertionError("no new probe")), \
                    patch.object(run, "job_allocate_run_dir", return_value=rerun_dir), \
                    patch.object(run, "prepare", side_effect=config.Error("fixture stop")) as prepare:
                run.job_ladder(self.cfg, self.root, job, task, lp.run_dir, state,
                               1, self.logs.append, threading.Lock())
                prepare.assert_called_once()
                opts = prepare.call_args.args[1]
                self.assertEqual(opts["--review"], wanted)
                self.assertEqual(self.pick(opts["--exec"], opts["--review"]),
                                 ("beta", wanted or "gamma"))
                self.assertNotIn("review_override", task)
                self.assertTrue(task["rerun_attempted"])

    def test_job_start_keeps_explicit_reviewer_with_an_empty_override(self):
        directory = self.root / "run"
        directory.mkdir()
        task_path = self.root / "task.md"
        task_path.write_text("---\nrepo: none\n---\n# Fixture\n\n## Done when\n```bash\ntrue\n```\n")
        task = {"name": "fixture", "task_file": str(task_path), "review_override": None}
        with patch.object(run, "job_allocate_run_dir", return_value=directory), \
                patch.object(run, "prepare"):
            _, opts = run.job_start_task(self.cfg, self.root, task, {"--review": "gamma"},
                                         self.logs.append)
        self.assertEqual(opts["--review"], "gamma")

    def fallback(self, lp, silent):
        calls = []
        def call(cfg, model, body, workspace, out, *args, **kwargs):
            calls.append(model)
            out.mkdir(parents=True)
            return 0, "No verdict yet." if model == silent else "VERDICT: PASS", "sid", False
        with patch.object(run, "collect_usage", return_value=self.providers), \
                patch.object(run, "call_retrying", side_effect=call), \
                patch.object(run.worker, "call", side_effect=call):
            self.assertEqual(run.review(lp, "Work done.", True, "passed"), "PASS")
        return calls

    def test_silent_fallback_prefers_cross_company_over_same_company(self):
        lp = self.loop(reviewer="gamma", spares=["alpha", "beta", "delta"])
        self.assertEqual(self.fallback(lp, "gamma"), ["gamma", "gamma", "delta"])

    def test_silent_fallback_can_use_same_company_and_obeys_opt_out(self):
        lp = self.loop(reviewer="gamma", spares=["alpha", "beta", "delta"])
        self.cfg["models"]["delta"]["provider"] = "a"
        self.cfg["models"]["beta"]["reviews_own_provider"] = False
        self.assertEqual(self.fallback(lp, "gamma"), ["gamma", "gamma", "delta"])
        self.assertTrue(run.review_pass(lp.state, self.cfg))

    def test_review_pr_fallback_can_use_another_model_on_one_provider(self):
        lp = self.loop(executor=None, reviewer="alpha", spares=["beta"])
        lp.state["review_pr"] = "https://github.com/example/repo/pull/1"
        self.providers = self.meters(b=100)
        self.assertEqual(self.fallback(lp, "alpha"), ["alpha", "alpha", "beta"])
        self.assertTrue(run.review_pass(lp.state, self.cfg))

    def test_delivery_passes_cfg_and_rechecks_the_reviewer_policy(self):
        state = self.evidence()
        with patch.object(run, "review_pass", wraps=run.review_pass) as check:
            self.assertEqual(run.delivery(state, self.cfg), "PASS, delivered")
        check.assert_called_once_with(state, self.cfg)
        self.cfg["models"]["beta"]["reviews_own_provider"] = False
        self.assertFalse(run.review_pass(state, self.cfg))
        with patch.object(config, "load", return_value=self.cfg):
            self.assertEqual(run.delivery(state), "FAIL")
        state["review"]["reviewer"] = state["reviewer"] = "alpha"
        self.assertFalse(run.review_pass(state, self.cfg))

    def test_usage_text_prints_pair_and_one_provider_note_after_order(self):
        with patch.object(terminal, "width", return_value=100):
            self.providers = self.meters(b=100)
            rendered = usage.render(self.cfg, self.providers, ["alpha", "beta"])
        self.assertIn("pick order: alpha, beta\nreview: alpha by beta\n"
                      "one provider: reviewer on the same company", rendered)
        self.assertNotIn("one provider:", usage.render(self.cfg, self.meters(), ["alpha"]))

    def test_pairing_display_accepts_meters_without_reported_pace(self):
        for provider in self.providers.values():
            for meter in provider["meters"]:
                meter.pop("pace")
        self.assertIn("review: alpha by gamma",
                      usage.render(self.cfg, self.providers, ["alpha", "beta", "gamma", "delta"]))
        # A partial report can mix meters with and without pace on the same provider.
        self.providers["a"]["meters"].append(
            {**self.providers["a"]["meters"][0], "name": "extra", "pace": 10})
        self.assertIn("review: alpha by gamma",
                      usage.render(self.cfg, self.providers, ["alpha", "beta", "gamma", "delta"]))

    def test_usage_json_carries_the_pair_from_the_cli(self):
        home = self.root / ".agentkit"
        (home / "state").mkdir(parents=True)
        cfg = ['[tiers]', 'A = ["seat"]', 'B = ["alpha", "beta"]']
        for name in ("seat", "alpha", "beta"):
            cfg += [f'[models.{name}]', 'harness = "claude"', f'model = "{name}"',
                    'effort = "high"', 'provider = "a"']
        cfg += ['[providers.a]', 'mode = "subscription"']
        (home / "config.toml").write_text("\n".join(cfg))
        providers = {"a": self.providers["a"]}
        now = time.time()
        (home / "state/usage.json").write_text(json.dumps(
            {"fetched_at": now, "reset_checked_at": now, "providers": providers}))
        env = {**os.environ, "HOME": str(self.root), "AGENTKIT_HOME": str(home),
               "AGENTKIT_SESSION": "", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(REPO / "bin/ak"), "usage", "--json"],
                                env=env, capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        data = json.loads(result.stdout)
        self.assertEqual(data["pick_order"], ["alpha", "beta"])
        self.assertEqual(data["review"], {"executor": "alpha", "reviewer": "beta",
                                          "same_provider": True})


if __name__ == "__main__":
    unittest.main()
