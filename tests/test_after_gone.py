"""A task file naming `after:` is refused at launch, alone or in a job, before any receipt.

Offline: the bin/ak entry point with a temporary HOME and launch effects mocked out.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, job, record, run, task

AK_MAIN = runpy.run_path(str(REPO / "bin/ak"))["main"]


class AfterGone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-after-gone-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "JOBS"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": ""}))
        stack.enter_context(patch.object(config, "load", return_value={}))
        stack.enter_context(patch.object(config, "current_session", return_value=None))
        self.prepare = stack.enter_context(patch.object(run, "prepare"))
        self.drive = stack.enter_context(patch.object(run, "drive", return_value=0))
        self.job_loop = stack.enter_context(patch.object(job, "run_job_loop", return_value=0))

    def write(self, front, name):
        path = self.root / name
        path.write_text(f"---\nrepo: none\n{front}---\n# {name}\n\n## Done when\n```bash\ntrue\n```\n")
        return path

    def launch(self, *paths):
        err = io.StringIO()
        with patch.object(sys, "argv", [str(REPO / "bin/ak"), "run", *map(str, paths)]), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = AK_MAIN()
        return code, err.getvalue()

    def assert_nothing_started(self):
        self.assertFalse(config.RUNS.exists() and any(config.RUNS.iterdir()))
        self.assertFalse(config.JOBS.exists() and any(config.JOBS.iterdir()))
        self.prepare.assert_not_called()
        self.drive.assert_not_called()
        self.job_loop.assert_not_called()

    def test_a_single_task_with_after_is_refused(self):
        code, err = self.launch(self.write("after: base.md\n", "fix-api.md"))
        self.assertEqual(code, 2, err)
        self.assertIn("`after:` is gone", err)
        self.assert_nothing_started()

    def test_a_job_with_after_is_refused_before_its_receipt(self):
        first = self.write("", "base.md")
        second = self.write("after: base.md\n", "fix-api.md")
        code, err = self.launch(first, second, "--anyway")
        self.assertEqual(code, 2, err)
        self.assertIn(f"{second}: `after:` is gone", err)
        self.assert_nothing_started()

    def test_an_old_run_copy_with_after_still_parses(self):
        meta, _, title = task.parse_task(self.write("after: base.md\n", "fix-api.md"))
        self.assertEqual((meta["after"], title), ("base.md", "fix-api.md"))
        self.assertIn("`after:` is gone", task.launch_refusal(meta))

    def saved(self, name, **extra):
        """A record from before `after:` went: cut from a dependency's passed tip."""
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text("# Beta\n\n## Done when\n```bash\ntrue\n```\n")
        (wt := self.root / f"wt-{name}").mkdir()
        state = {"run_id": name, "title": "Beta", "state": "pass", "verdict": "PASS",
                 "rounds": 3, "round_summaries": [], "repo": None, "scratch": True,
                 "executor": "fixture", "reviewer": "fixture", "findings": "", "pr": None,
                 "merged": False, "merge_note": None, "no_merge": False, "reported": False,
                 "worktree": str(wt), "branch": "ak/beta", "base": "main", "target": "main",
                 "base_sha": "tip", "from_pass": {"task": "alpha.md", "tip": "tip"},
                 "merge_failed": True, "stalls": [], **extra}
        record.save_state(run_dir, state)
        return run_dir, state

    def test_which_saved_records_stand_on_a_dependency(self):
        after = {"task": "alpha.md", "tip": "tip"}
        for state, stands in (({"from_pass": after}, True),                     # never started
                              ({"from_pass": after, "base_sha": "tip"}, True),  # still on it
                              ({"from_pass": after, "base_sha": "main"}, False),  # integrated
                              ({"base_sha": "tip"}, False)):
            with self.subTest(state=state):
                self.assertEqual(bool(run.stands_on_dependency(state)), stands)

    def test_a_delivery_retry_refuses_a_branch_standing_on_a_dependency(self):
        run_dir, _ = self.saved("20261004-0700-beta")
        with self.assertRaisesRegex(config.Error, "relaunch with `from: ak/beta`"):
            run.cmd_merge([run_dir.name])

    def test_a_resume_ends_blocked_before_any_round(self):
        run_dir, state = self.saved("20261004-0701-beta", state="running", verdict=None,
                                    merge_failed=False)
        with patch.object(run, "collect_usage", side_effect=AssertionError("a model pick")), \
                patch.object(run, "rounds", side_effect=AssertionError("a round ran")), \
                patch.object(run, "integrate", side_effect=AssertionError("integrated")), \
                patch.object(run, "settle_run"):
            ended = run.loop({}, run_dir, run_dir / "task.md",
                             {"--exec": None, "--review": None, "--rounds": None,
                              "--no-worktree": False}, lambda _: None, prior=state)
        self.assertEqual(ended["state"], "blocked")
        self.assertIn("relaunch with `from: ak/beta`", ended["error"])
        self.assertEqual(record.read_state(run_dir)["state"], "blocked")
        self.assertIn("relaunch with `from: ak/beta`", (run_dir / "result.md").read_text())

    def test_an_unstarted_run_ends_blocked_before_its_checkout(self):
        run_dir = config.RUNS / "20261004-0702-beta"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text("# Beta\n\n## Done when\n```bash\ntrue\n```\n")
        record.save_state(run_dir, {"run_id": run_dir.name,
                                    "from_pass": {"task": "alpha.md", "tip": "tip"}})
        with patch.object(run, "make_worktree", side_effect=AssertionError("a checkout")), \
                patch.object(run, "settle_run"):
            ended = run.loop({}, run_dir, run_dir / "task.md", {"--no-worktree": False},
                             lambda _: None)
        self.assertEqual(ended["state"], "blocked")

if __name__ == "__main__":
    unittest.main(verbosity=2)
