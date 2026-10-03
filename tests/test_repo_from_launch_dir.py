"""Detached starts and resumes keep the repository chosen in the launching checkout.

The installed CLI path starts a fake detached child from another directory. Git makes
real worktrees in a temporary HOME; the loop stops before asking a model to do anything.
"""

from contextlib import chdir, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, orch, record, run, worker


class BeforeModel(Exception):
    pass


class RepoFromLaunchDir(Sandbox):
    def setUp(self):
        super().setUp()
        for name in (worker.RUN_MARKER, "AK_PARENT_RUN", "AK_RUN_LOG", config.RUN_DIR_ENV,
                     config.JOB_DIR_ENV, config.SESSION_ENV, config.UNATTENDED_ENV):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            # The sandbox is inside this checkout; its untracked folders must not inherit it.
            "GIT_CEILING_DIRECTORIES": str(REPO)}))
        self.stack.enter_context(patch.object(config, "JOBS", self.root / "jobs"))
        self.stack.enter_context(patch.object(sys, "argv", [str(REPO / "bin" / "ak"), "run"]))
        self.stack.enter_context(patch.object(run.box, "check"))
        self.stack.enter_context(patch.object(run, "history_start"))
        self.stack.enter_context(patch.object(run, "refresh_seat_tally"))
        self.stack.enter_context(patch.object(run, "join_session_project"))
        self.stack.enter_context(patch.object(run.gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "run_placement", return_value=("fixture", None, ())))
        self.stack.enter_context(patch.object(run, "place_here", side_effect=AssertionError("parent scope")))
        self.stack.enter_context(patch.object(run, "collect_usage", side_effect=BeforeModel))
        self.stack.enter_context(patch.object(run, "drive", side_effect=self.begin))
        self.starts = self.stack.enter_context(patch.object(orch, "start_in_slice", side_effect=self.start))
        self.follows = self.stack.enter_context(patch.object(run, "follow_run", side_effect=self.follow))
        self.pending = None
        self.acme, self.other = self.checkout("acme"), self.checkout("other")
        self.task = self.root / "fix-api.md"
        self.task.write_text("# Fix API\n\n## Done when\n```bash\ntrue\n```\n")

    def checkout(self, name):
        path = self.root / name
        subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-q", "--allow-empty",
                        "-m", "fixture"], check=True)
        return path

    def start(self, argv, _unit, env, _output, **_kw):
        self.assertEqual(argv[:3], [sys.executable, str(REPO / "bin" / "ak"), "run"])
        self.assertIsNone(self.pending)
        self.pending = (argv[3:], env, Path(env[config.RUN_DIR_ENV]))
        return os.getpid()

    def child(self, cwd=None):
        argv, env, directory = self.pending
        self.pending = None
        with chdir(cwd or self.root), patch.dict(os.environ, env, clear=True), \
                (directory / "log.txt").open("a") as output, redirect_stdout(output):
            self.assertEqual(run.main(argv), 0)
        return directory

    def follow(self, directory, _cfg, _offset):
        self.assertEqual(self.pending[2], directory)
        self.child()
        return 0

    def begin(self, cfg, directory, opts, log, prior=None, **_kw):
        with self.assertRaises(BeforeModel):
            run.loop(cfg, directory, directory / "task.md", opts, log, prior)
        return 0

    def launch(self, background=True, cwd=None):
        self.starts.reset_mock()
        self.follows.reset_mock()
        argv = [str(self.task), *(["--bg"] if background else [])]
        with chdir(cwd or self.acme), redirect_stdout(io.StringIO()):
            self.assertTrue(run.foreground_cli(config.RUNS / "probe"))
            self.assertEqual(run.main(argv), 0)
        self.starts.assert_called_once()
        if background:
            self.follows.assert_not_called()
            return self.pending[2]
        self.follows.assert_called_once()
        return self.follows.call_args.args[0]

    def assert_checkout(self, directory):
        state = record.read_state(directory)
        self.assertEqual(state["repo"], str(self.acme))
        self.assertFalse(state["scratch"])
        self.assertFalse(state["no_merge"])
        self.assertTrue(state["branch"].startswith("ak/"))
        wt = Path(state["worktree"])
        self.assertEqual(run.git(wt, "branch", "--show-current"), state["branch"])
        self.assertEqual(Path(run.git(wt, "rev-parse", "--git-common-dir")).resolve(),
                         self.acme / ".git")
        return state

    def test_foreground_and_background_keep_the_launch_checkout(self):
        nested = self.acme / "src"
        nested.mkdir()
        for background in (False, True):
            with self.subTest(background=background):
                directory = self.launch(background, nested)
                if background:
                    self.assertEqual(record.read_state(directory)["repo"], str(self.acme))
                    self.child()
                self.assert_checkout(directory)

    def resume(self, directory, background):
        state = record.read_state(directory)
        run.interrupt(state, "fixture interrupted")
        state["pid"] = None
        record.save_state(directory, state)
        self.starts.reset_mock()
        self.follows.reset_mock()
        # Neither the terminal doing the resume nor its child stands in the launch checkout.
        with chdir(self.other), redirect_stdout(io.StringIO()), \
                patch.object(run, "task_repo", side_effect=AssertionError("repository rediscovered")):
            self.assertEqual(run.resume_run([directory.name, *(["--bg"] if background else [])]), 0)
            if background:
                self.follows.assert_not_called()
                self.child()
            else:
                self.follows.assert_called_once()
        self.starts.assert_called_once()

    def test_resume_before_worktree_keeps_the_launch_checkout(self):
        for background in (False, True):
            with self.subTest(background=background):
                directory = self.launch()
                self.pending = None  # the launcher died before its child could start
                self.assertNotIn("worktree", record.read_state(directory))
                self.resume(directory, background)
                self.assert_checkout(directory)

    def test_resume_keeps_the_existing_worktree_and_branch(self):
        directory = self.launch(False)
        before = self.assert_checkout(directory)
        self.resume(directory, True)
        after = self.assert_checkout(directory)
        self.assertEqual((after["worktree"], after["branch"]), (before["worktree"], before["branch"]))

    def test_relative_repo_is_resolved_at_launch(self):
        self.task.write_text("---\nrepo: .\n---\n" + self.task.read_text())
        directory = self.launch()
        self.child()
        self.assert_checkout(directory)

    def test_scratch_decision_survives_a_child_starting_in_a_checkout(self):
        for front, cwd in (("", self.root), ("---\nrepo: none\n---\n", self.acme)):
            with self.subTest(front=front):
                self.task.write_text(front + "# Fix API\n\n## Done when\n```bash\ntrue\n```\n")
                directory = self.launch(cwd=cwd)
                self.child(self.other)
                state = record.read_state(directory)
                self.assertIsNone(state["repo"])
                self.assertTrue(state["scratch"])
                self.assertTrue(state["no_merge"])
                self.assertIsNone(state["branch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
