"""A model may review its own work, but only as the last choice.

The reviewer is picked from the run's models in this order: another company,
then another model of the executor's company, then the executor's own model,
budget within each tier. Nothing refuses or parks a run only because the one
reviewer left is the executor's own, and the launch line and `ak run status`
say `self-reviewed` where a round was reviewed by the executor's own model.

Offline: invented models on two invented providers, fake budgets, fake worker
turns, a temporary HOME. No real adapter, pid or model call appears anywhere.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, run, usage


class SelfReviewLast(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".self-review-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(run.worker, "kill_marked", return_value=True))
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        self.stack.enter_context(patch.object(config, "HOME", self.root / "home"))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        (self.root / "home").mkdir()
        self.cfg = {"defaults": {"orchestrator": "seat",
                                 "workers": ["acme-one", "acme-two", "beta-one"]},
                    "models": {}, "providers": {"acme": {}, "beta": {}}}
        for name, provider in (("seat", "acme"), ("acme-one", "acme"),
                               ("acme-two", "acme"), ("beta-one", "beta")):
            self.cfg["models"][name] = {"harness": "test", "model": name,
                                        "effort": "high", "provider": provider}
        self.providers = self.meters()
        self.logs = []

    def meters(self, acme=10, beta=70):
        return {name: {"meters": [{"name": "weekly", "used": used, "pace": used - 50,
                                  "elapsed": 50,
                                  "window_secs": 604800, "resets_at": time.time() + 302400}],
                       "resets": 0}
                for name, used in (("acme", acme), ("beta", beta))}

    def pick(self, executor=None, reviewer=None):
        return run.pick_models(self.cfg, self.providers, executor, reviewer, self.logs.append)

    def loop(self, executor="acme-one", reviewer="beta-one", spares=()):
        directory = self.root / "run"
        directory.mkdir(exist_ok=True)
        workspace = self.root / "work"
        workspace.mkdir(exist_ok=True)
        state = {"run_id": "fixture", "state": "running", "verdict": None,
                 "executor": executor, "reviewer": reviewer, "repo": None,
                 "scratch": True, "worktree": str(workspace), "base": None,
                 "rounds": 2, "round_summaries": [], "findings": ""}
        lp = run.Loop(self.cfg, directory, state, {}, self.logs.append, workspace,
                      "Review the work.", [], "Fixture", list(spares))
        lp.rnd = 1
        lp.round_dir.mkdir(exist_ok=True)
        return lp

    def test_reviewer_order_is_other_company_then_same_then_own(self):
        order = ["acme-two", "beta-one", "acme-one"]
        self.assertEqual(run.reviewer_order(self.cfg, "acme-one", order),
                         ["beta-one", "acme-two", "acme-one"])
        # budget orders within each tier: the incoming order is kept inside it
        self.assertEqual(run.reviewer_order(self.cfg, "beta-one",
                                            ["acme-one", "acme-two", "beta-one"]),
                         ["acme-one", "acme-two", "beta-one"])
        self.assertEqual(run.reviewer_order(self.cfg, "acme-one", ["acme-one"]), ["acme-one"])
        # a review with no executor keeps budget order: nothing is anyone's own
        self.assertEqual(run.reviewer_order(self.cfg, None, order), order)

    def test_first_pick_reviews_itself_only_when_nothing_else_is_left(self):
        self.assertEqual(self.pick(), ("acme-one", "beta-one"))
        self.assertEqual(self.pick("acme-one"), ("acme-one", "beta-one"))
        self.providers = self.meters(beta=100)
        self.assertEqual(self.pick("acme-one"), ("acme-one", "acme-two"))
        self.cfg["defaults"]["workers"] = ["acme-one"]
        self.assertEqual(self.pick(), ("acme-one", "acme-one"))

    def test_a_reviewers_group_bounds_the_tiers(self):
        # where a reviewers group is set, the tiers rank its models, not the workers:
        # cross-company beta-one is out, so same-company acme-two reviews
        self.assertEqual(run.pick_models(self.cfg, self.providers, "acme-one", None,
                                         self.logs.append, reviewers=["acme-two"]),
                         ("acme-one", "acme-two"))
        self.assertEqual(run.pick_models(self.cfg, self.providers, "acme-one", None,
                                         self.logs.append, reviewers=["acme-one"]),
                         ("acme-one", "acme-one"))

    def test_best_pair_weighs_tier_then_executor_then_reviewer_budget(self):
        executors = ["acme-one", "acme-two", "beta-one"]
        self.assertEqual(run.best_pair(self.cfg, executors, ["acme-one"]),
                         ("beta-one", "acme-one"))
        self.assertEqual(run.best_pair(self.cfg, ["acme-one", "acme-two"], ["acme-one"]),
                         ("acme-two", "acme-one"))
        self.assertIsNone(run.best_pair(self.cfg, ["acme-one"], ["acme-one"],
                                        allow_self=False))
        self.assertIsNone(run.best_pair(self.cfg, [], ["acme-one"]))

    def test_first_pick_prefers_cross_over_self_across_executors(self):
        self.assertEqual(run.pick_models(self.cfg, self.providers, None, None,
                                         self.logs.append, reviewers=["acme-one"]),
                         ("beta-one", "acme-one"))

    def test_an_explicit_self_review_is_allowed(self):
        self.assertEqual(self.pick("acme-one", "acme-one"), ("acme-one", "acme-one"))
        self.assertEqual(run.review_providers(self.cfg, "acme-one", "acme-one"),
                         ("acme", "acme"))
        self.assertEqual(run.review_providers(self.cfg, "acme-one", "beta-one"),
                         ("acme", "beta"))

    def test_a_named_reviewer_takes_the_best_executor_for_it(self):
        self.assertEqual(run.pick_models(self.cfg, self.providers, None, "acme-one",
                                         self.logs.append), ("beta-one", "acme-one"))
        self.cfg["defaults"]["workers"] = ["acme-one"]
        self.assertEqual(run.pick_models(self.cfg, self.providers, None, "acme-one",
                                         self.logs.append), ("acme-one", "acme-one"))

    def test_an_alias_counts_as_the_executors_own_model(self):
        self.cfg["models"]["acme-two"]["model"] = "acme-one"
        self.assertEqual(run.reviewer_order(self.cfg, "acme-one",
                                            ["acme-two", "beta-one", "acme-one"]),
                         ["beta-one", "acme-two", "acme-one"])
        self.assertEqual(self.pick("acme-one"), ("acme-one", "beta-one"))
        self.providers = self.meters(beta=100)
        self.assertEqual(self.pick("acme-one"), ("acme-one", "acme-one"))
        self.assertEqual(self.pick("acme-two"), ("acme-two", "acme-one"))
        state = {"executor": "acme-two", "reviewer": "acme-one"}
        self.assertTrue(run.self_reviewed(state, self.cfg))
        self.assertFalse(run.self_reviewed(state))
        line = run.launch_line("id", "t", "acme-two", "acme-one",
                               self_review=run.same_model(self.cfg, "acme-two",
                                                          "acme-one"))
        self.assertIn("(acme-two/acme-one, self-reviewed)", line)

    def test_a_launch_with_one_worker_is_not_refused(self):
        self.assertIsNone(run.pair_refusal(self.cfg, self.providers, ["acme-one"]))
        self.assertIsNone(run.pair_refusal(self.cfg, self.providers, ["acme-one"],
                                           "acme-one", "acme-one"))
        # only a launch with no runnable worker is refused, in one sentence
        providers = usage.Readings(self.meters())
        providers.harnesses = {"test": "test is not logged in"}
        self.assertEqual(
            run.pair_refusal(self.cfg, providers, ["acme-one", "beta-one"]),
            "none of the workers acme-one, beta-one and reviewers acme-one, beta-one "
            "can run here (acme-one: test is not logged in; "
            "beta-one: test is not logged in); log in to another harness or add "
            "another model to the groups")

    def fallback(self, lp, silent):
        calls = []

        def call(cfg, model, body, workspace, out, *args, **kwargs):
            calls.append(model)
            out.mkdir(parents=True, exist_ok=True)
            return 0, "No verdict yet." if model == silent else "VERDICT: PASS", "sid", False

        with patch.object(run, "collect_usage", return_value=self.providers), \
                patch.object(run, "call_retrying", side_effect=call), \
                patch.object(run.worker, "call", side_effect=call):
            self.assertEqual(run.review(lp, "Work done.", True, "passed"), "PASS")
        return calls

    def test_a_spare_falls_back_to_same_company_before_own(self):
        lp = self.loop(reviewer="beta-one", spares=["acme-one", "acme-two"])
        self.assertEqual(self.fallback(lp, "beta-one"), ["beta-one", "beta-one", "acme-two"])
        self.assertEqual(lp.reviewer, "acme-two")

    def test_a_spare_falls_back_to_the_executors_own_model(self):
        lp = self.loop(reviewer="beta-one", spares=["acme-one"])
        self.assertEqual(self.fallback(lp, "beta-one"), ["beta-one", "beta-one", "acme-one"])
        self.assertTrue(run.review_pass(lp.state, self.cfg))
        self.assertTrue(run.self_reviewed(lp.state))

    def test_a_handover_repicks_to_self_review_when_nothing_else_is_left(self):
        lp = self.loop(reviewer="beta-one")
        self.cfg["defaults"]["workers"] = ["acme-one", "beta-one"]
        self.providers = self.meters(acme=100, beta=10)
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "beta-one")
        self.assertEqual((lp.executor, lp.reviewer), ("beta-one", "beta-one"))
        saved = run.read_state(lp.run_dir)
        self.assertEqual((saved["executor"], saved["reviewer"]), ("beta-one", "beta-one"))
        self.assertTrue(run.self_reviewed(saved))

    def test_a_stall_handover_hands_to_self_review_when_nothing_else_is_left(self):
        state = {"executor": "acme-one", "reviewer": "beta-one",
                 "workers": ["acme-one", "beta-one"]}
        self.providers = self.meters(acme=100, beta=10)
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.handover_executor(state, self.cfg, "stalled"), "beta-one")
        self.assertEqual((state["executor"], state["reviewer"]), ("beta-one", "beta-one"))

    def test_a_handover_prefers_a_better_tier_over_a_cheaper_self(self):
        lp = self.loop(executor="beta-one", reviewer="beta-one")
        lp.state["workers"] = ["acme-one", "acme-two", "beta-one"]
        lp.state["reviewers"] = ["acme-one"]
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.hand_executor(lp, "ran dry", "refused", set()), "acme-two")
        self.assertEqual((lp.executor, lp.reviewer), ("acme-two", "acme-one"))

    def test_a_stall_handover_prefers_a_better_tier_over_a_cheaper_self(self):
        state = {"executor": "beta-one", "reviewer": "beta-one",
                 "workers": ["acme-one", "acme-two", "beta-one"],
                 "reviewers": ["acme-one"]}
        with patch.object(run, "collect_usage", return_value=self.providers):
            self.assertEqual(run.handover_executor(state, self.cfg, "stalled"), "acme-two")
        self.assertEqual((state["executor"], state["reviewer"]), ("acme-two", "acme-one"))

    def test_own_pr_picks_against_the_orchestrator_with_self_last(self):
        opts = {"--review-pr": "https://example.com/acme/fix-api/pull/1", "--review": None}
        session = {"name": "seat", "orchestrator": "acme-one",
                   "workers": ["acme-one", "acme-two", "beta-one"]}
        with patch.object(run, "collect_usage", side_effect=lambda cfg: self.providers), \
                patch.object(config, "current_session", return_value="seat"), \
                patch.object(config, "load_session", return_value=session), \
                patch.object(run, "pr_view", return_value={"author": "owner"}), \
                patch.object(run, "viewer_login", return_value="owner"):
            self.assertEqual(run.preset_review_model(self.cfg, opts), "beta-one")
            self.providers = self.meters(beta=100)
            self.assertEqual(run.preset_review_model(self.cfg, opts), "acme-two")
            self.cfg["defaults"]["workers"] = ["acme-one"]
            self.assertEqual(run.preset_review_model(self.cfg, opts), "acme-one")
            # an explicit review by the writer's own model is allowed, not refused
            opts = {**opts, "--review": "acme-one"}
            self.assertEqual(run.preset_review_model(self.cfg, opts), "acme-one")

    def test_a_resume_keeps_a_self_review_pair(self):
        self.assertEqual(run.pick_models(self.cfg, self.providers, "acme-one", "acme-one",
                                         self.logs.append, resuming=True),
                         ("acme-one", "acme-one"))

    def test_a_saved_self_review_pass_is_evidence(self):
        state = {"verdict": "PASS", "executor": "acme-one", "reviewer": "acme-one",
                 "scratch": True,
                 "review": {"executor": "acme-one", "executor_provider": "acme",
                            "reviewer": "acme-one", "reviewer_provider": "acme",
                            "returncode": 0, "verdict": "PASS", "done_when": True}}
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertEqual(run.delivery(state, self.cfg), "PASS, delivered")
        self.assertTrue(run.self_reviewed(state))
        other = {"verdict": "PASS", "executor": "acme-one", "reviewer": "beta-one",
                 "scratch": True,
                 "review": {"executor": "acme-one", "executor_provider": "acme",
                            "reviewer": "beta-one", "reviewer_provider": "beta",
                            "returncode": 0, "verdict": "PASS", "done_when": True}}
        self.assertTrue(run.review_pass(other, self.cfg))
        self.assertFalse(run.self_reviewed(other))

    def test_the_setting_is_gone_but_a_stale_key_reads_without_error(self):
        self.assertNotIn("reviews_own_provider", (REPO / "config.default.toml").read_text())
        shipped = tomllib.loads((REPO / "config.default.toml").read_text())
        for entry in shipped["models"].values():
            self.assertNotIn("reviews_own_provider", entry)
        # a config that still carries the key reads, and the key is ignored
        (self.root / "home" / "config.toml").write_text(
            '[defaults]\norchestrator = "seat"\nworkers = ["acme-one", "acme-two"]\n'
            '[models.seat]\nharness = "test"\nmodel = "seat"\neffort = "high"\n'
            'provider = "acme"\n[models.acme-one]\nharness = "test"\nmodel = "acme-one"\n'
            'effort = "high"\nprovider = "acme"\n[models.acme-two]\nharness = "test"\n'
            'model = "acme-two"\neffort = "high"\nprovider = "acme"\n'
            'reviews_own_provider = false\n[providers.acme]\nmode = "subscription"\n')
        cfg = config.load()
        self.assertIs(cfg["models"]["acme-two"]["reviews_own_provider"], False)
        providers = self.meters(beta=100)
        self.assertEqual(run.pick_models(cfg, providers, "acme-one", None, self.logs.append),
                         ("acme-one", "acme-two"))
        self.assertEqual(run.pick_models(cfg, providers, "acme-one", "acme-one",
                                         self.logs.append), ("acme-one", "acme-one"))

    def test_the_model_screen_has_no_review_rule_row(self):
        self.assertEqual(menu.MODEL_ROWS, ("model id", "effort", "Remove"))
        lines, _ = menu.model_body(self.cfg, "acme-one")
        self.assertEqual(len(lines), 3)
        self.assertNotIn("Reviews its own company's work", "\n".join(lines))

    def test_the_launch_line_says_self_reviewed(self):
        line = run.launch_line("20260928-1200-fix-api", "Fix the API", "acme-one", "acme-one")
        self.assertIn("(acme-one/acme-one, self-reviewed)", line)
        line = run.launch_line("20260928-1200-fix-api", "Fix the API", "acme-one", "beta-one")
        self.assertNotIn("self-reviewed", line)
        self.assertIn("(acme-one/beta-one)", line)
        line = run.launch_line("20260928-1200-fix-api", "Review PR #1", None, "acme-one",
                               self_review=True)
        self.assertIn("(acme-one review, self-reviewed)", line)

    def test_status_says_self_reviewed(self):
        now = time.time()

        def state(executor, reviewer):
            return {"run_id": "20260928-1200-fix-api", "title": "Fix the API",
                    "state": "pass", "verdict": "PASS", "merged": True,
                    "executor": executor, "reviewer": reviewer, "rounds": 1,
                    "round_summaries": [{"verdict": "PASS"}],
                    "started_at": now - 60, "finished_at": now}

        class Directory:
            name = "20260928-1200-fix-api"

        _, groups = run.status_rows([(Directory(), state("acme-one", "acme-one"))], 120)
        self.assertIn("acme-one/acme-one self-reviewed", "\n".join(groups[0]))
        _, groups = run.status_rows([(Directory(), state("acme-one", "beta-one"))], 120)
        self.assertNotIn("self-reviewed", "\n".join(groups[0]))
        self.cfg["models"]["acme-two"]["model"] = "acme-one"
        _, groups = run.status_rows([(Directory(), state("acme-one", "acme-two"))], 120,
                                    None, self.cfg)
        self.assertIn("acme-one/acme-two self-reviewed", "\n".join(groups[0]))


if __name__ == "__main__":
    unittest.main()
