"""A session's executors are optional: with none, its orchestrator builds everything.

The record and the defaults may name no executor once they name reviewers; a task launch is
refused before any run exists; the session's own PR is still reviewed, and starts no follow-up
workers; the last executor may be let go on the screens while the last reviewer may not; and
the orchestrator's own exec mark is drawn filled and dim while nobody else is marked.

Offline: throwaway HOME, fake launch/drive/tmux, and invented GitHub responses.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, menu, orch, run, terminal, usage
from agentkit import record


class Keys:
    def take(self):
        return True

    def close(self):
        pass


class ExecutorsOptional(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            config.RUN_DIR_ENV: "", config.SESSION_ENV: "fix-api",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(run, "refresh_seat_tally"))
        self.stack.enter_context(patch.object(record, "process_owner", return_value={}))
        self.stack.enter_context(patch.object(run, "history_start"))
        self.stack.enter_context(patch.object(usage, "unready", return_value=""))
        config.save_session(self.cfg, "fix-api", "opus", [],
                            {"reviewers": ["astra"], "cwd": str(self.root), "created": 100})
        self.task = self.root / "task.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the endpoint\n\n"
                             "## Done when\n```bash\ntrue\n```\n")

    def selected(self):
        found = config.load_session(self.cfg, "fix-api")
        return {"orchestrator": found["orchestrator"], "workers": list(found["workers"]),
                "reviewers": list(found["reviewers"])}

    def test_record_without_executor_loads_and_one_without_reviewers_still_needs_one(self):
        self.assertEqual(config.load_session(self.cfg, "fix-api")["workers"], [])
        with self.assertRaisesRegex(config.Error, "workers must be a non-empty list"):
            config.save_session(self.cfg, "legacy", "opus", [])
        with self.assertRaisesRegex(config.Error, "reviewers must be a non-empty list"):
            config.save_session(self.cfg, "empty", "opus", [], {"reviewers": []})

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
                            self.assertIn(reason, sentence)
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
            self.assertTrue(run.pair_refusal(cfg, {}, None))
            self.assertTrue(run.pair_refusal(cfg, {}, []))

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

        with patch.object(run, "pr_view", return_value=info), \
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
        with patch.object(run, "main_checkout") as checkout, patch.object(run, "spawn_bg") as spawn:
            self.assertIsNone(run.start_followups(state, directory, lambda _: None, self.cfg))
        checkout.assert_not_called()
        spawn.assert_not_called()

    def test_last_executor_may_go_and_the_last_reviewer_may_not(self):
        config.save_session(self.cfg, "fix-api", "opus", ["fable"], {"reviewers": ["astra"]})
        selected = self.selected()
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {}), "")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["workers"], [])
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "astra", 2, {}),
                         "review needs one model")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["reviewers"], ["astra"])

    def test_orchestrator_exec_mark_is_filled_and_dim_while_nobody_else_is_marked(self):
        marks = "●○■□"
        with patch.object(terminal, "layout_width", return_value=100), \
                patch.object(terminal, "colour_depth", return_value=8), \
                patch.object(terminal, "utf8", return_value=True):
            lines, _ = menu.config_body(self.cfg, "fixture", selected=self.selected())
            picker, _, _ = orch.picker_lines(self.cfg, dict.fromkeys(config.offered(self.cfg), ""),
                                             self.selected(), None, 0, 100)
            for screen in (lines, picker):
                rows = {terminal.plain(line).lstrip("› ").split()[0]: line
                        for line in screen if any(char in marks for char in terminal.plain(line))}
                self.assertIn(terminal.styled(" ■ ", "dim"), rows["opus"])
                self.assertEqual(tuple("".join(char for char in terminal.plain(rows[name])
                                               if char in marks) for name in ("opus", "astra")),
                                 ("●■□", "○□■"))

    def test_defaults_without_executor_stay_without_on_the_new_session_screen(self):
        self.cfg["defaults"] = {"orchestrator": "opus", "workers": [], "reviewers": ["astra"]}
        config._fall_back(self.cfg["defaults"], list(self.cfg["models"]))
        self.assertEqual(self.cfg["defaults"]["workers"], [])
        with patch.object(terminal, "Keyboard", Keys), \
                patch.object(terminal, "read_key", side_effect=[terminal.Key("enter")]), \
                patch.object(orch, "spent_note", return_value=""), redirect_stdout(io.StringIO()):
            chosen = orch.pick(self.cfg, {}, "opus")
        self.assertEqual(chosen, ("opus", [], ["astra"]))


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

if __name__ == "__main__":
    unittest.main()
