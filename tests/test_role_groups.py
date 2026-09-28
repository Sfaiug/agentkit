"""Role selections survive every pick; all homes, meters, harnesses and turns are fake."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import unittest
from unittest.mock import patch

import test_worker_list as fixtures
from agentkit import config, run, usage, watch


class RoleGroups(unittest.TestCase):
    # Reuse the offline sandbox, not its tests: it also clears the hosting run's markers.
    setUp = fixtures.WorkerList.setUp
    providers = fixtures.WorkerList.providers
    loop = fixtures.WorkerList.loop
    turn = fixtures.WorkerList.turn
    refused = fixtures.WorkerList.refused

    def groups(self, workers=("alpha", "beta"), reviewers=("gamma", "delta")):
        self.wide.update(workers=list(workers), reviewers=list(reviewers))
        self.cfg["defaults"].update(workers=list(workers), reviewers=list(reviewers))

    def pick(self, executor=None, reviewer=None, **kwargs):
        return run.pick_models(self.cfg, self.providers(a=30, b=10, c=0),
                               executor, reviewer, self.logs.append, **kwargs)

    def capture(self, name="fixture"):
        directory = config.RUNS / name
        directory.mkdir()
        with patch.object(run, "refresh_seat_tally"), \
                patch.object(run, "history_start"), patch.object(run, "claim_slot"):
            run.capture_launch(directory, cfg=self.cfg)
        return directory, run.read_state(directory)

    def test_defaults_and_session_round_trip_without_adding_an_omitted_field(self):
        config.save(self.cfg)
        before = (config.HOME / config.CONFIG_NAME).read_bytes()
        loaded = config.load()
        self.assertNotIn("reviewers", loaded["defaults"])
        config.save(loaded)
        self.assertEqual((config.HOME / config.CONFIG_NAME).read_bytes(), before)
        old = config.save_session(self.cfg, "old", "seat", ["alpha", "beta"])
        self.assertNotIn("reviewers", old)
        self.groups()
        config.save(self.cfg)
        self.assertEqual(config.load()["defaults"]["reviewers"], ["gamma", "delta"])
        config.save_session(self.cfg, "new", "seat", ["alpha"], {"reviewers": ["delta"]})
        self.assertEqual(config.load_session(self.cfg, "new")["reviewers"], ["delta"])
        for name, extra in (("named", {}), ("unnamed", {"unnamed": True}),
                            ("automatic", {"conversation": "fixture"})):
            config.save_session(self.cfg, name, "seat", ["alpha"], extra)
            self.assertEqual(config.load_session(self.cfg, name)["reviewers"], ["gamma", "delta"])
        with patch.object(config, "active_session", return_value=old):
            self.assertEqual(config.reviewers(self.cfg), ["alpha", "beta"])
        with patch.object(config, "active_session", return_value=None):
            self.assertEqual(config.reviewers(self.cfg), ["gamma", "delta"])

    def test_invalid_reviewers_are_rejected_in_both_records(self):
        config.save(self.cfg)
        path = config.HOME / config.CONFIG_NAME
        original = path.read_text()
        for bad in (None, "alpha", [], ["missing"], ["alpha", "alpha"], [3], [{}]):
            with self.subTest(reviewers=bad):
                if bad is not None:  # TOML has no null; each of these is valid TOML.
                    path.write_text(original.replace(
                        "[defaults]", f"[defaults]\nreviewers = {json.dumps(bad)}"))
                    with self.assertRaisesRegex(config.Error, r"\[defaults\].reviewers"):
                        config.load()
                record = {"orchestrator": "seat", "workers": ["alpha"], "reviewers": bad}
                config.session_path("bad").write_text(json.dumps(record))
                with self.assertRaises(config.Error):
                    config.load_session(self.cfg, "bad")
                with self.assertRaises(config.Error):
                    config.save_session(self.cfg, "bad", "seat", ["alpha"], {"reviewers": bad})

    def test_removed_models_leave_valid_explicit_defaults(self):
        self.groups(reviewers=("delta",))
        config.remove_model(self.cfg, "delta")
        config.save(self.cfg)
        self.assertEqual(config.load()["defaults"]["reviewers"], ["seat"])

    def test_each_group_ranks_by_budget_and_cross_company_still_wins(self):
        self.groups()
        self.assertEqual(self.pick(), ("beta", "delta"))
        self.assertEqual(usage.pick_order(self.cfg, self.providers(), role="reviewer"),
                         ["gamma", "delta"])
        # A same-company reviewer has more budget, but the other company reviews first.
        self.wide["reviewers"] = ["beta", "alpha"]
        self.assertEqual(self.pick(), ("beta", "alpha"))
        self.wide["reviewers"] = ["gamma"]
        self.assertEqual(self.pick(), ("beta", "gamma"))
        self.cfg["models"]["gamma"]["reviews_own_provider"] = False
        self.assertEqual(self.pick(), ("alpha", "gamma"))

    def test_overlapping_groups_never_allow_the_executors_model_to_review(self):
        self.groups(workers=("beta", "alpha"), reviewers=("beta",))
        self.assertEqual(self.pick(), ("alpha", "beta"))
        with self.assertRaisesRegex(config.Error, "same model"):
            self.pick(reviewer="beta")
        self.cfg["models"]["alpha"].update(provider="b", model="beta")
        with self.assertRaises(run.QuotaDry):
            self.pick()

    def test_explicit_models_stay_in_their_groups_even_on_resume_or_without_a_seat(self):
        self.groups()
        for session in (self.wide, None):
            with patch.object(config, "active_session", return_value=session):
                for resuming in (False, True):
                    for executor, reviewer, role in (("delta", None, "worker"),
                                                      (None, "alpha", "reviewer"),
                                                      ("seat", "gamma", "worker")):
                        with self.subTest(session=session, resuming=resuming, role=role):
                            with self.assertRaisesRegex(config.Error, f"not a {role}") as error:
                                self.pick(executor, reviewer, resuming=resuming)
                            self.assertNotIn("\n", str(error.exception))

    def test_unpairable_groups_name_both_but_spent_groups_wait(self):
        self.groups(workers=("beta",), reviewers=("gamma",))
        self.assertIsNone(run.pair_refusal(self.cfg, self.providers(b=100), None))
        self.cfg["models"]["gamma"]["reviews_own_provider"] = False
        reason = run.pair_refusal(self.cfg, self.providers(), None)
        self.assertIn("workers beta and reviewers gamma", reason)
        self.assertNotIn("\n", reason)
        self.cfg["models"]["gamma"]["reviews_own_provider"] = True
        readings = usage.Readings(self.providers())
        self.cfg["models"]["gamma"]["harness"] = "codex"
        self.why["codex"] = "codex is not logged in"
        readings = usage.readiness(self.cfg, readings)
        self.assertIn("gamma: codex is not logged in",
                      run.pair_refusal(self.cfg, readings, None))

    def test_launch_freezes_session_and_standalone_default_groups(self):
        self.groups()
        for seat in ("wide", ""):
            with patch.dict(os.environ, {"AGENTKIT_SESSION": seat}), \
                    patch.object(config, "active_session",
                                 return_value=self.wide if seat else None):
                directory, state = self.capture(seat or "defaults")
                self.assertEqual(state["workers"], ["alpha", "beta"])
                self.assertEqual(state["reviewers"], ["gamma", "delta"])
            self.cfg["defaults"]["reviewers"] = ["seat"]
            self.wide["reviewers"] = ["seat"]
            self.assertEqual(run.run_reviewers(self.cfg, state), ["gamma", "delta"])
            self.groups()
        legacy = {"workers": ["alpha", "beta"], "launched_session": "wide"}
        self.assertEqual(run.run_reviewers(self.cfg, legacy), ["alpha", "beta"])

    def test_legacy_launch_receipt_omits_reviewers(self):
        for seat in ("wide", ""):
            with patch.dict(os.environ, {"AGENTKIT_SESSION": seat}):
                _, state = self.capture(seat or "defaults")
            self.assertNotIn("reviewers", state)
            self.assertEqual("workers" in state, bool(seat))

    def test_legacy_unbound_explicit_and_saved_models_ignore_default_worker_changes(self):
        lp = self.loop("gamma", "delta", ["gamma", "delta"])
        lp.state.pop("workers")
        lp.state.update(title="Legacy", no_merge=True, branch=None, base_sha=None)
        task = lp.run_dir / "task.md"
        task.write_text("---\nrepo: none\nrounds: 1\n---\n# Legacy\n\n"
                        "## Done when\n```bash\ntrue\n```\n")
        self.cfg["defaults"]["workers"] = ["alpha", "beta"]
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        with patch.object(config, "active_session", return_value=None), \
                patch.object(run, "rounds"), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run, "collect_usage", return_value=self.providers()), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(self.pick("gamma", "delta"), ("gamma", "delta"))
            self.assertIsNone(run.pair_refusal(self.cfg, self.providers(), None, "gamma", "delta"))
            run.save_state(lp.run_dir, lp.state)
            self.assertEqual(run.preset_models(
                self.cfg, {**opts, "--exec": "gamma", "--review": "delta"},
                self.logs.append, lp.run_dir), ("gamma", "delta"))
            state = run.loop(self.cfg, lp.run_dir, task, opts, self.logs.append, prior=lp.state)
            self.assertEqual(state["executor"], "gamma")
            self.assertNotIn("workers", state)
            self.assertNotIn("reviewers", state)

    def test_legacy_review_flag_alone_still_refuses_the_same_model_pair(self):
        with patch.object(config, "active_session", return_value=None):
            with self.assertRaisesRegex(config.Error, "same model"):
                self.pick(reviewer="delta")

    def test_status_and_preflight_show_saved_reviewers_only_when_present(self):
        for separate in (False, True):
            if separate:
                self.groups()
            directory, state = self.capture(f"status-{separate}")
            (directory / "task.md").write_text(
                "---\nrepo: none\nrounds: 1\n---\n# Status\n\n"
                "## Done when\n```bash\ntrue\n```\n")
            opts = {"--review-pr": None, "--no-merge": True, "--no-worktree": True}
            with redirect_stdout(io.StringIO()):
                run.preflight(directory, opts, run.logger(directory, True))
            with patch.object(run, "alive_line", return_value=""):
                details = "\n".join(run.status_details(directory, state))
            for output in ((directory / "log.txt").read_text(), details):
                if separate:
                    self.assertIn("workers: alpha, beta", output)
                    self.assertIn("reviewers: gamma, delta", output)
                else:
                    self.assertNotIn("reviewers:", output)

    def test_background_preset_uses_frozen_groups_and_refuses_an_impossible_pair(self):
        self.groups(workers=("alpha",), reviewers=("gamma",))
        directory, state = self.capture()
        self.groups()
        opts = {"--exec": None, "--review": None}
        with patch.object(run, "collect_usage", return_value=self.providers()):
            self.assertEqual(run.preset_models(self.cfg, opts, self.logs.append, directory),
                             ("alpha", "gamma"))
            self.cfg["models"]["gamma"].update(provider="a", model="alpha")
            with patch.object(run, "refused") as refused, \
                    self.assertRaisesRegex(config.Error, "workers alpha and reviewers gamma"):
                run.preset_models(self.cfg, opts, self.logs.append, directory)
            refused.assert_called_once()

    def test_handover_and_refusal_keep_each_role_in_its_own_group(self):
        self.groups()
        lp = self.loop("alpha", "gamma", ["alpha", "beta"])
        lp.state["reviewers"] = ["gamma", "delta"]
        with patch.object(run, "collect_usage", return_value=self.providers(c=0)):
            self.assertEqual(run.handover_executor(lp.state, self.cfg, "stalled"), "beta")
            self.assertEqual(lp.state["reviewer"], "delta")
            self.assertEqual(run.hand_executor(lp, "refused", "transport", set()), "beta")
            self.assertEqual(lp.reviewer, "delta")
            self.assertEqual(lp.spares, ["gamma"])
        lp.executor = "alpha"
        calls, fake = self.turn({"alpha": (1, "usage limit reached", "old", False)})
        with patch.object(run.worker, "call", side_effect=fake), \
                self.refused(self.providers(c=0)), \
                patch.object(run.time, "sleep"), redirect_stderr(io.StringIO()):
            self.assertEqual(run.execute(lp, "fixer", "Fix it.", "fixer"), "## Summary\nDone.")
        self.assertEqual(calls, ["alpha", "beta"])
        self.assertEqual(lp.reviewer, "delta")

    def test_first_pick_and_resume_use_the_snapshot_for_review_and_spares(self):
        self.groups(workers=("alpha", "beta"), reviewers=("gamma", "delta"))
        directory, _ = self.capture()
        task = directory / "task.md"
        task.write_text("---\nrepo: none\nrounds: 1\n---\n# Fix API\n\n"
                        "## Done when\n```bash\ntrue\n```\n")
        opts = {"--rounds": None, "--exec": None, "--review": None, "--review-pr": None,
                "--no-merge": True, "--no-worktree": True, "--bg": False}
        self.groups(workers=("seat",), reviewers=("seat",))
        with patch.object(run, "rounds") as rounds, \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run, "collect_usage", return_value=self.providers(c=0)) as collect, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            state = run.loop(self.cfg, directory, task, opts, self.logs.append)
            self.assertEqual((state["executor"], state["reviewer"]), ("alpha", "delta"))
            self.assertEqual(rounds.call_args.args[0].spares, ["gamma"])
            collect.return_value = self.providers(a=100, c=0)
            state = run.loop(self.cfg, directory, task, opts, self.logs.append, prior=state)
            self.assertEqual((state["executor"], state["reviewer"]), ("beta", "delta"))
            self.assertEqual(rounds.call_args.args[0].spares, ["gamma"])

    def test_tick_repicks_with_both_saved_groups_after_quota_or_transport_failure(self):
        for quota in (True, False):
            with self.subTest(quota=quota):
                directory = config.RUNS / f"20260928-0000-recovery-{quota}"
                directory.mkdir()
                state = {"run_id": directory.name, "state": "exhausted", "executor": "alpha",
                         "reviewer": "gamma", "worktree": str(self.root), "quota_dry": quota,
                         "workers": ["alpha", "beta"] if quota else ["alpha"],
                         "reviewers": ["gamma", "delta"],
                         "error": "reviewer gamma died on API/transport errors and no eligible "
                                  "reviewer is left to review; waiting for review"}
                run.save_state(directory, state)
                with patch.object(run, "spawn_bg") as spawn:
                    watch.resume_exhausted(self.cfg, self.providers(a=100 if quota else 10, c=0),
                                           log=self.logs.append, now=self.now)
                spawn.assert_called_once()
                saved = run.read_state(directory)
                if quota:
                    self.assertEqual((saved["executor"], saved["reviewer"]), ("beta", "delta"))
                else:
                    self.assertIn(f"resumed {directory.name}: reviewer delta eligible again",
                                  self.logs)

    def test_reviewer_silence_transient_and_quota_fallback_ignore_foreign_spares(self):
        self.groups()
        for failure in ("silence", "transient", "quota"):
            with self.subTest(failure=failure):
                lp = self.loop("alpha", "gamma", ["alpha", "beta"])
                lp.state["reviewers"] = ["gamma", "delta"]
                lp.spares = ["beta", "delta"]
                calls = []

                def call(cfg, name, *args, **kwargs):
                    calls.append(name)
                    if name == "gamma":
                        if failure == "transient":
                            new = kwargs["handover"]("transport")
                            raise run.TransientHandover(name, new, None, "transport")
                        if failure == "quota":
                            raise run.RanDry(name, "b", 1, "usage limit reached", None,
                                             self.now + 3600, "quota", True)
                        return 0, "No verdict.", None, False
                    return 0, "VERDICT: PASS\n\n## Findings\n- none", None, False

                with patch.object(run, "call_retrying", side_effect=call), \
                        patch.object(run.worker, "call", side_effect=call), \
                        patch.object(run, "collect_usage", return_value=self.providers(c=0)):
                    self.assertEqual(run.review(lp, "Done.", True, "passed"), "PASS")
                self.assertEqual(lp.reviewer, "delta")
                self.assertNotIn("beta", calls)
                self.assertEqual(calls[-1], "delta")

    def test_review_pr_parent_and_child_use_only_bound_reviewers(self):
        self.groups(workers=("alpha",), reviewers=("gamma", "delta"))
        url = "https://github.com/acme/fix-api/pull/1"
        opts = {"--review": None, "--review-pr": url}
        directory, _ = self.capture()
        wt = self.root / "checkout"
        wt.mkdir()
        info = {"state": "OPEN", "title": "Fix API", "author": "contributor",
                "baseRefName": "main", "headRefOid": "abc123"}
        with patch.object(run, "collect_usage", return_value=self.providers(c=0)), \
                patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "own_pr_orchestrator", return_value=(False, None)), \
                patch.object(run, "checkout_for", return_value=wt), \
                patch.object(run, "git", return_value=""), \
                patch.object(run, "make_worktree", return_value=(wt, "ak/fix-api")), \
                patch.object(run, "exclude_junk"), \
                patch.object(run, "disk_pressure", return_value=False), \
                patch.object(run, "post_review", return_value=True), \
                patch.object(run, "review", return_value="FAIL") as review, \
                patch.object(run, "restore_review_checkout"), redirect_stdout(io.StringIO()):
            self.assertEqual(run.preset_review_model(self.cfg, opts, ["gamma", "delta"]), "delta")
            with self.assertRaisesRegex(config.Error, "not a reviewer"):
                run.preset_review_model(self.cfg, {**opts, "--review": "alpha"}, ["gamma", "delta"])
            self.wide["reviewers"] = ["alpha"]
            state = run.review_pr(self.cfg, directory, url, opts, self.logs.append)
            self.assertEqual(state["reviewer"], "delta")
            self.assertEqual(review.call_args.args[0].spares, ["gamma"])
            with self.assertRaisesRegex(config.Error, "not a reviewer"):
                run.review_pr(self.cfg, directory, url, {**opts, "--review": "alpha"},
                              self.logs.append)
            # Without reviewers, an old unbound PR review still accepts an explicit model
            # outside the defaults, in both the background parent and the child.
            self.cfg["defaults"].pop("reviewers")
            with patch.object(config, "active_session", return_value=None):
                legacy, _ = self.capture("legacy-review")
                explicit = {**opts, "--review": "delta"}
                self.assertEqual(run.preset_review_model(self.cfg, explicit), "delta")
                state = run.review_pr(self.cfg, legacy, url, explicit, self.logs.append)
                self.assertEqual(state["reviewer"], "delta")


if __name__ == "__main__":
    unittest.main()
