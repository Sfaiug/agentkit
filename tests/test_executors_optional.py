"""A session's executors are optional: with none, its orchestrator builds everything.

The record and the defaults may name no executor once they name reviewers; a task launch is
refused before any run exists; the session's own PR is still reviewed, and starts no follow-up
workers; the last executor may be let go on the screens while the last reviewer may not; and
with nobody marked to build every exec mark is drawn open, the orchestrator's too.

Offline: throwaway HOME, fake launch/drive/tmux, and invented GitHub responses.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import re
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, gitcall, menu, orch, plan, run, staffing, terminal, usage
from agentkit import record


class ExecutorsOptional(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            config.RUN_DIR_ENV: "", config.SESSION_ENV: "fix-api",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(record, "process_owner", return_value={}))
        self.stack.enter_context(patch.object(run, "history_start"))
        self.stack.enter_context(patch.object(usage, "unready", return_value=""))
        config.save_session(self.cfg, "fix-api", "opus", [],
                            {"reviewers": ["astra"], "cwd": str(self.root), "created": 100})
        # a seat launches only with an open line in its plan
        plan.write("fix-api", [plan.compose("Fix the api", "check: `false`", "acme",
                                            "2026-10-23 09:00", None)])
        self.task = self.root / "task.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the endpoint\n\n"
                             "## Done when\n```bash\ntrue\n```\n")

    def selected(self):
        found = config.load_session(self.cfg, "fix-api")
        return {"orchestrator": found["orchestrator"], "workers": list(found["workers"]),
                "reviewers": list(found["reviewers"])}

    def test_record_without_executor_or_reviewers_loads_and_legacy_still_needs_one(self):
        self.assertEqual(config.load_session(self.cfg, "fix-api")["workers"], [])
        with self.assertRaisesRegex(config.Error, "workers must be a non-empty list"):
            config.save_session(self.cfg, "legacy", "opus", [])
        config.save_session(self.cfg, "empty", "opus", [], {"reviewers": []})
        loaded = config.load_session(self.cfg, "empty")
        self.assertEqual((loaded["workers"], loaded["reviewers"]), ([], []))
        config.save_session(self.cfg, "no-rev", "opus", ["opus"], {"reviewers": []})
        self.assertEqual(config.load_session(self.cfg, "no-rev")["reviewers"], [])
        # [defaults] cannot hold an empty reviewer list yet: remember_defaults leaves it as it stands
        before = config.load()["defaults"].get("reviewers")
        self.assertEqual(config.remember_defaults(loaded), "")
        self.assertEqual(config.load()["defaults"].get("reviewers"), before)
        self.assertTrue(record.review_off({"reviewers": []}))
        self.assertTrue(record.review_off({"reviewers": [], "review_pr": "https://github.com/acme/api/pull/7", "own_pr": True}))
        self.assertFalse(record.review_off({"reviewers": [], "review_pr": "https://github.com/acme/api/pull/7", "own_pr": False}))
        self.assertFalse(record.review_off({"reviewers": [], "own_pr": False}))
        self.assertFalse(record.review_off({"reviewers": [], "job_id": "batch"}))
        self.assertFalse(record.review_off({"workers": ["opus"]}))
        self.assertFalse(record.review_off({"reviewers": ["astra"]}))

    def test_task_launch_is_refused_before_any_run_or_job_exists(self):
        config.remember_defaults(config.load_session(self.cfg, "fix-api"))
        with patch.object(run, "prepare") as prepare, \
                patch.object(run, "spawn_bg", return_value=0) as spawn, \
                patch.object(run.jobs, "job_create", return_value=(self.root, {})) as job, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for session, reason in (("fix-api", "fix-api has no executor"),
                                    ("", "defaults have no executor")):
                with patch.dict(os.environ, {config.SESSION_ENV: session}):
                    for args in ([str(self.task)], [str(self.task), "--bg", "--anyway"],
                                 [str(self.task), "--exec", "opus"],
                                 [str(self.task), str(self.task), "--parallel", "2"],
                                 [str(self.task), str(self.task), "--bg"]):
                        with self.subTest(session=session, args=args):
                            with self.assertRaises(config.Error) as refused:
                                run.main(args)
                            sentence = str(refused.exception)
                            self.assertEqual(len(sentence.splitlines()), 1)
                            # a seat naming a model or a place is refused for that first, alike
                            flagged = session and {"--anyway", "--exec"} & set(args)
                            self.assertIn("not a seat's" if flagged else reason, sentence)
                            self.assertEqual(list(config.RUNS.iterdir()), [])
            prepare.assert_not_called()
            spawn.assert_not_called()
            job.assert_not_called()

    def test_empty_defaults_are_refused_instead_of_waiting_for_budget(self):
        config.remember_defaults(config.load_session(self.cfg, "fix-api"))
        with patch.dict(os.environ, {config.SESSION_ENV: ""}):
            cfg = config.load()
            self.assertEqual(cfg["defaults"]["workers"], [])
            with self.assertRaises(run.QuotaDry):
                run.pick_models(cfg, {}, None, None, lambda _: None, quiet=True)
            self.assertTrue(staffing.pair_refusal(cfg, {}, None))
            self.assertTrue(staffing.pair_refusal(cfg, {}, []))

    def test_own_pr_review_still_launches_without_executors(self):
        url = "https://github.com/acme/api/pull/7"
        info = {"title": "Fix the endpoint", "author": "acme-owner",
                "baseRefName": "main", "headRefOid": "f" * 40}

        def drive(cfg, directory, opts, log, job=None, **_kw):
            receipt = record.read_state(directory)
            self.assertTrue(receipt["own_pr"])
            self.assertEqual(receipt["own_orchestrator"], "opus")
            self.assertEqual((receipt["workers"], receipt["reviewers"]), ([], ["astra"]))
            return job()

        # the launch's size check reads the PR's checkout (`test_own_pr_size_before_slot`)
        with patch.object(run, "checkout_for", return_value=self.root), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "origin_default", return_value="main"), \
                patch.object(run, "git", return_value=""), \
                patch.object(run, "own_pr_first_review", return_value=None), \
                patch.object(run, "unanswered_head", return_value=None), \
                patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "viewer_login", return_value="acme-owner"), \
                patch.object(run, "drive", side_effect=drive), \
                patch.object(run, "review_pr", return_value=0) as review, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["--review-pr", url]), 0)
        review.assert_called_once()
        self.assertEqual(review.call_args.args[2], url)

    def test_own_pr_starts_no_followup_workers(self):
        self.assertEqual(orch.role_refusal(self.cfg, self.selected(), {}), "")
        with patch.object(usage, "unready", return_value="not logged in"):
            self.assertEqual(orch.role_refusal(self.cfg, self.selected(), {}),
                             "no allowed executor/reviewer pair")
        directory = config.RUNS / "review"
        directory.mkdir()
        state = {"run_id": "review", "launched_session": "fix-api", "repo": str(self.root),
                 "base": "main", "merged": True, "review_pr": "https://github.com/acme/api/pull/7",
                 "own_pr": True, "followups": ["Fix the other endpoint"]}
        record.save_state(directory, state)
        with patch.object(gitcall, "main_checkout") as checkout, patch.object(run, "spawn_bg") as spawn:
            self.assertIsNone(run.start_followups(state, directory, lambda _: None, self.cfg))
        checkout.assert_not_called()
        spawn.assert_not_called()

    def test_last_executor_may_go_and_the_last_reviewer_may_not(self):
        config.save_session(self.cfg, "fix-api", "opus", ["fable"], {"reviewers": ["astra"]})
        selected = self.selected()
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {}), "")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["workers"], [])
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "astra", 2, {}),
                         "at least one model reviews")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["reviewers"], ["astra"])

    def test_every_exec_mark_is_open_while_nobody_is_marked(self):
        marks = "●○■□"
        with patch.object(terminal, "layout_width", return_value=100), \
                patch.object(terminal, "colour_depth", return_value=8), \
                patch.object(terminal, "utf8", return_value=True):
            lines, _ = menu.config_body(self.cfg, selected=self.selected())
            rows = {re.split(r" [[●○■□]", terminal.plain(line).lstrip("› "))[0]: line
                    for line in lines if any(char in marks for char in terminal.plain(line))}
            self.assertEqual(tuple("".join(char for char in terminal.plain(rows[name])
                                           if char in marks) for name in ("Opus 5.5", "6 Astra")),
                             ("●□□", "○□■"))

    def test_defaults_without_executor_stay_without_on_the_new_session_screen(self):
        self.cfg["defaults"] = {"orchestrator": "opus", "workers": [], "reviewers": ["astra"]}
        config._fall_back(self.cfg["defaults"], list(self.cfg["models"]))
        self.assertEqual(self.cfg["defaults"]["workers"], [])
        with patch.object(orch, "spent_note", return_value=""):
            chosen = orch.default_crew(self.cfg, {}, "opus")
        self.assertEqual(chosen, {"orchestrator": "opus", "workers": [], "reviewers": ["astra"]})


    def outside_a_seat(self):
        return patch.dict(os.environ, {config.SESSION_ENV: ""})

    def test_defaults_that_never_name_executors_keep_the_fallback(self):
        self.cfg["defaults"] = {"orchestrator": "opus", "reviewers": ["astra"]}
        (config.HOME / config.CONFIG_NAME).write_text(config.dump(self.cfg))
        self.assertTrue(config.load()["defaults"]["workers"])     # nobody chose an empty group
        with self.outside_a_seat(), patch.object(run.box, "check"), \
                patch.object(run, "prepare"), patch.object(run, "place_here"), \
                patch.object(run, "drive", return_value=0) as drive, redirect_stdout(io.StringIO()):
            self.assertEqual(run.main([str(self.task), "--no-merge"]), 0)
        drive.assert_called_once()

    def test_a_queued_run_carries_on_with_the_executors_it_saved(self):
        directory = config.RUNS / "queued-task"
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(self.task.read_text())
        (directory / "log.txt").touch()
        record.save_state(directory, {"run_id": directory.name, "state": "queued",
                                      "launched_session": None, "workers": ["opus"],
                                      "reviewers": ["astra"]})
        # the defaults lost their executors after the launch prepared it
        self.cfg["defaults"] = {"orchestrator": "opus", "workers": [], "reviewers": ["astra"]}
        (config.HOME / config.CONFIG_NAME).write_text(config.dump(self.cfg))
        with self.outside_a_seat(), patch.dict(os.environ, {config.RUN_DIR_ENV: str(directory)}), \
                patch.object(run.box, "check"), patch.object(run, "prepare") as prepare, \
                patch.object(run, "drive", return_value=0) as drive, redirect_stdout(io.StringIO()):
            self.assertEqual(run.main([str(task)]), 0)
        self.assertEqual(drive.call_args.args[1], directory)
        prepare.assert_not_called()

    def test_a_review_out_of_quota_resumes_on_its_reviewer_with_no_executor(self):
        self.cfg["defaults"] = {"orchestrator": "opus", "workers": [], "reviewers": ["astra"]}
        (config.HOME / config.CONFIG_NAME).write_text(config.dump(self.cfg))
        cfg, now = config.load(), 10000
        meter = lambda name: {"name": name, "used": 10, "pace": -40, "elapsed": 50,
                              "window_secs": 604800, "resets_at": now + 302400}
        providers = usage.Readings({name: {"meters": [meter(n) for n in
                                                      ("weekly", "weekly_all", "weekly_scoped")],
                                           "resets": 0} for name in cfg["providers"]})
        directory = config.RUNS / "review-refilled"
        directory.mkdir()
        record.save_state(directory, {
            "run_id": directory.name, "state": "exhausted", "quota_dry": True, "workers": [],
            "reviewers": ["astra"], "executor": None, "reviewer": "astra",
            "worktree": str(self.root), "launched_session": "fix-api",
            "review_pr": "https://github.com/acme/api/pull/7", "own_pr": True,
            "own_orchestrator": "opus"})
        from agentkit import watch
        with self.outside_a_seat(), patch.object(usage, "readiness", return_value=providers), \
                patch.object(run, "spawn_bg", return_value=0) as spawn:
            watch.resume_exhausted(cfg, providers, log=lambda _: None, now=now)
        spawn.assert_called_once()

    def test_no_reviewer_run_stays_bound_to_its_receipt_and_leaves_jobs_and_other_prs_alone(self):
        import json
        from contextlib import nullcontext
        from types import SimpleNamespace
        from agentkit import job as jobs

        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"reviewers": []})
        # a job task does not inherit the seat's empty reviewers list
        batch_dir = self.root / "batch"
        policy = {key: row[0] for key, row in config.POLICY.items()}
        policy["review_rounds"] = 3
        with patch.object(run, "launch_policy", return_value=policy), patch.object(run, "preflight"), \
                patch.object(run, "redress_seat"), patch.object(run.gate, "claim_slot"):
            job_run, _ = jobs.job_start_task(
                self.cfg, batch_dir, {"name": "task.md", "task_file": str(self.task)},
                {}, lambda _: None)
        job_receipt = record.read_state(job_run)
        self.assertEqual(job_receipt["job_id"], "batch")
        self.assertFalse(record.review_off(job_receipt))

        # capture a task receipt and an own-PR receipt, then corrupt/edit the live seat
        task_dir, pr_dir = config.RUNS / "bound-task", config.RUNS / "bound-pr"
        task_dir.mkdir()
        pr_dir.mkdir()
        with patch.object(run.gate, "admission", nullcontext), patch.object(run.gate, "claim_slot"), \
                patch.object(run, "redress_seat"):
            run.capture_launch(task_dir, cfg=self.cfg)
            config.save_session(self.cfg, "fix-api", "opus", [], {"reviewers": []})
            run.capture_launch(pr_dir, opts={"--review-pr": "https://github.com/acme/api/pull/7"}, cfg=self.cfg)
        task_receipt = {**record.read_state(task_dir), "policy": {"review_rounds": 3}}
        pr_receipt = {**record.read_state(pr_dir), "policy": {"review_rounds": 3}}

        live = config.session_path("fix-api")
        broken = json.loads(live.read_text())
        broken["reviewers"] = ["opus", "opus"]
        live.write_text(json.dumps(broken))
        with patch.object(run.run_record, "read_state", return_value=task_receipt), \
                patch.object(run, "refused"), patch.object(run, "collect_usage", return_value={}), \
                patch.object(staffing, "ready_order", return_value=["opus"]), \
                patch.object(staffing, "refuse_unready"):
            self.assertEqual(
                run.preset_models(self.cfg, {"--exec": None, "--review": None}, lambda _: None, task_dir),
                ("opus", None))

        class Reached(Exception):
            pass

        with patch.object(run.run_record, "read_state", return_value=pr_receipt), \
                patch.object(config, "load_session", wraps=config.load_session) as loaded, \
                patch.object(run, "pr_view", side_effect=Reached):
            with self.assertRaises(Reached):
                run.review_pr_round(self.cfg, pr_dir, "https://github.com/acme/api/pull/7", {}, lambda _: None)
            loaded.assert_not_called()

        config.save_session(self.cfg, "fix-api", "astra", [], {"reviewers": []})
        with patch.object(run, "viewer_login", return_value="acme"):
            own, writer, _ = run.pr_writer(self.cfg, pr_receipt, pr_receipt["launched_session"], "acme")
        self.assertEqual((own, writer), (True, "opus"))

        live.write_text("invalid JSON")
        with patch.dict(os.environ, {config.RUN_DIR_ENV: str(pr_dir)}), \
                patch.object(run, "depth_refused", return_value=False), \
                patch.object(run.box, "check", side_effect=Reached):
            with self.assertRaises(Reached):
                run.main(["--review-pr", "https://github.com/acme/api/pull/7"])

        # external PR with reviewers: [] and review_rounds: 3 still offers to inbox, never merges
        info = {"title": "Fix", "author": "other-dev", "headRefOid": "a" * 40, "state": "OPEN"}
        ext_state = {"verdict": "PASS", "head_sha": info["headRefOid"], "own_pr": False,
                     "workers": ["opus"], "reviewers": [], "policy": {"review_rounds": 3}}
        lp = SimpleNamespace(cfg={}, run_dir=pr_dir, state=ext_state, log=lambda _: None,
                             cmds=[], write=lambda: None)
        with patch.object(run, "restore_review_checkout"), patch.object(run, "post_review", return_value=True), \
                patch.object(run, "checks", return_value=(True, None)), patch.object(run, "pr_view", return_value=info), \
                patch.object(run.watch, "ask_inbox", return_value=0), patch.object(run, "write_result"), \
                patch.object(run, "merge_own_pr") as merge:
            run.settle_pr_round(lp, "https://github.com/acme/api/pull/7", info)
        merge.assert_not_called()

        # review_rounds: 0 with explicit reviewers still refuses an out-of-group --review
        zero_receipt = {"reviewers": ["astra"], "workers": ["opus"], "policy": {"review_rounds": 0},
                        "launched_session": None}
        with patch.object(run.run_record, "read_state", return_value=zero_receipt), \
                patch.object(run, "pr_view", side_effect=AssertionError("should refuse")):
            with self.assertRaisesRegex(config.Error, "not a reviewer of this run"):
                run.review_pr_round(self.cfg, pr_dir, "https://github.com/acme/api/pull/7",
                                    {"--review": "opus"}, lambda _: None)

if __name__ == "__main__":
    unittest.main()
