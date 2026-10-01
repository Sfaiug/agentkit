"""Solo persists on the seat: no task launch, but its own PR can still be reviewed.

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
from agentkit import config, orch, run


class SoloSwitch(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            config.RUN_DIR_ENV: "", config.SESSION_ENV: "fix-api",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(run, "refresh_seat_tally"))
        self.stack.enter_context(patch.object(run, "process_owner", return_value={}))
        self.stack.enter_context(patch.object(run, "history_start"))
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"cwd": str(self.root), "created": 100, "solo": True})
        self.task = self.root / "task.md"
        self.task.write_text("---\nrepo: none\n---\n# Fix the endpoint\n\n"
                             "## Done when\n```bash\ntrue\n```\n")

    def command(self, *args):
        with redirect_stdout(io.StringIO()):
            return orch.main(["solo", *args])

    def test_task_launch_is_refused_before_any_run_or_job_exists(self):
        with patch.object(run, "prepare") as prepare, \
                patch.object(run, "drive", return_value=0), \
                patch.object(run, "preset_models", return_value=("opus", "astra")), \
                patch.object(run, "spawn_bg", return_value=0) as spawn, \
                patch.object(run.jobs, "job_create", return_value=(self.root, {})) as job, \
                patch.object(run.jobs, "run_job_loop", return_value=0), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for args in ([str(self.task)], [str(self.task), "--bg", "--anyway"],
                         [str(self.task), str(self.task), "--parallel", "2"]):
                with self.subTest(args=args):
                    with self.assertRaises(config.Error) as refused:
                        run.main(args)
                    sentence = str(refused.exception)
                    self.assertEqual(len(sentence.splitlines()), 1)
                    self.assertIn("solo", sentence)
                    self.assertIn("ak orch solo fix-api off", sentence)
                    self.assertEqual(list(config.RUNS.iterdir()), [])
            prepare.assert_not_called()
            spawn.assert_not_called()
            job.assert_not_called()

    def test_own_pr_review_still_launches_while_solo_is_on(self):
        url = "https://github.com/acme/api/pull/7"
        info = {"title": "Fix the endpoint", "author": "acme-owner",
                "baseRefName": "main", "headRefOid": "f" * 40}

        def drive(cfg, directory, opts, log, job=None, **_kw):
            receipt = run.read_state(directory)
            self.assertEqual(receipt["launched_session"], "fix-api")
            self.assertTrue(receipt["own_pr"])
            self.assertEqual(receipt["own_orchestrator"], "opus")
            return job()

        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "viewer_login", return_value="acme-owner"), \
                patch.object(run, "drive", side_effect=drive), \
                patch.object(run, "review_pr", return_value=0) as review, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(["--review-pr", url]), 0)
        review.assert_called_once()
        self.assertEqual(review.call_args.args[2], url)
        self.assertTrue(config.load_session(self.cfg, "fix-api")["solo"])

    def test_command_sets_and_clears_only_this_sessions_switch(self):
        config.save_session(self.cfg, "other", "astra", ["opus"])
        before = config.load_session(self.cfg, "fix-api")
        self.assertEqual(self.command("fix-api", "off"), 0)
        self.assertEqual(config.load_session(self.cfg, "fix-api"), {**before, "solo": False})
        self.assertEqual(self.command("fix-api", "on"), 0)
        self.assertEqual(config.load_session(self.cfg, "fix-api"), before)
        self.assertNotIn("solo", config.load_session(self.cfg, "other"))
        orch.tmux_out.assert_not_called()

    def test_invalid_command_or_missing_session_changes_nothing(self):
        before = config.session_path("fix-api").read_bytes()
        for args in ((), ("fix-api",), ("fix-api", "yes"), ("missing", "on"),
                     ("fix-api", "on", "extra")):
            with self.subTest(args=args), self.assertRaises(config.Error):
                self.command(*args)
        self.assertEqual(config.session_path("fix-api").read_bytes(), before)
        self.assertFalse(config.session_path("missing").exists())

    def test_switch_survives_restart_and_model_change(self):
        self.assertEqual(self.command("fix-api", "on"), 0)
        with patch.object(orch, "fresh_command", return_value=(["fake-tui"], None)), \
                patch.object(orch, "launch") as launch, \
                patch.object(orch, "_switch_plan", return_value=("", None)), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(orch.resume(self.cfg, "fix-api", hand_over=False), "fresh")
            self.assertTrue(config.load_session(self.cfg, "fix-api")["solo"])
            self.assertEqual(orch.switch_orchestrator(self.cfg, "fix-api", "astra", {}), "")
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(config.load_session(self.cfg, "fix-api")["orchestrator"], "astra")
        self.assertTrue(config.load_session(self.cfg, "fix-api")["solo"])
        with patch.object(run, "prepare") as prepare, \
                self.assertRaisesRegex(config.Error, "ak orch solo fix-api off"):
            run.main([str(self.task)])
        prepare.assert_not_called()

    def test_old_session_name_keeps_the_switch_and_can_turn_it_off(self):
        config.rename_session("fix-api", "api-fix")
        with patch.object(run, "prepare"), patch.object(run, "drive", return_value=0), \
                self.assertRaisesRegex(config.Error, "ak orch solo api-fix off"):
            run.main([str(self.task)])
        self.assertEqual(self.command("fix-api", "off"), 0)
        self.assertFalse(config.load_session(self.cfg, "api-fix")["solo"])

    def test_tasks_still_launch_when_off_or_from_another_session(self):
        config.save_session(self.cfg, "other", "astra", ["opus"])
        for seat in ("other", "", "fix-api"):
            if seat == "fix-api":
                self.assertEqual(self.command(seat, "off"), 0)
            with self.subTest(seat=seat), patch.dict(os.environ, {config.SESSION_ENV: seat}), \
                    patch.object(run, "prepare") as prepare, \
                    patch.object(run, "drive", return_value=0), redirect_stdout(io.StringIO()):
                self.assertEqual(run.main([str(self.task)]), 0)
                prepare.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
