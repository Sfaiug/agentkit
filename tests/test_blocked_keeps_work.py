"""A run that ends blocked puts its checkout's uncommitted work on its branch before the
hand-back's cleanup takes the checkout, so a relaunch `from:` that branch starts with it.

Offline: a real git repository in a temporary HOME; nothing is notified.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, record, turns, worktrees


class BlockedKeepsWork(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-blocked-keeps-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = self.root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "JOBS"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        identity = {f"GIT_{who}_{what}": value for who in ("AUTHOR", "COMMITTER")
                    for what, value in (("NAME", "acme"), ("EMAIL", "acme@localhost"))}
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "", **identity}))
        stack.enter_context(patch.object(config, "current_session", return_value=None))
        stack.enter_context(patch("agentkit.browser.close_owned"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def ended(self, name, wt, **extra):
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        base = self.git("rev-parse", "main")
        (run_dir / "task.md").write_text("# Fix api\n\n## Done when\n```bash\ntrue\n```\n")
        state = {"run_id": name, "title": "Fix api", "state": "running", "verdict": None,
                 "rounds": 3, "round_summaries": [], "repo": str(self.repo), "scratch": False,
                 "executor": "fixture", "reviewer": "fixture", "findings": "", "pr": None,
                 "merged": False, "worktree": str(wt), "branch": "ak/fix-api", "base": "main",
                 "target": "main", "base_sha": base, "pid": os.getpid(), **extra}
        record.save_state(run_dir, state)
        blocked = turns.Blocked("the shared ledger is read-only",
                                "## Blocked\n\nthe shared ledger is read-only")
        return run_dir, deliver.finish_blocked(run_dir, state, blocked, lambda _: None, {})

    def test_a_blocked_fixer_turns_edits_reach_the_branch_before_the_checkout_goes(self):
        wt = config.WT / "fix-api"
        wt.parent.mkdir(parents=True)
        self.git("worktree", "add", "-q", "-b", "ak/fix-api", str(wt))
        (wt / "app.py").write_text("round one\n")
        self.git("commit", "-qam", "round one", cwd=wt)
        # the fixer's turn: edits, a new file, and what the done-when generated, none committed
        (wt / "app.py").write_text("round two fix\n")
        (wt / "migration.py").write_text("renumbered\n")
        (wt / "report.xml").write_text("<done-when output/>\n")
        run_dir, state = self.ended("20261013-1600-fix-api", wt, artifacts=["report.xml"])
        self.assertEqual(state["state"], "blocked")
        self.assertEqual(state["error"], "the shared ledger is read-only")
        self.assertNotIn("checkout_kept", state)
        # the seat is told, and the hand-back's cleanup takes the checkout but not the work
        worktrees.settle_run({**record.read_state(run_dir), "handed_back": True}, run_dir)
        self.assertFalse(wt.exists())
        self.assertEqual(self.git("show", "ak/fix-api:app.py"), "round two fix")
        self.assertEqual(self.git("show", "ak/fix-api:migration.py"), "renumbered")
        self.assertNotIn("report.xml", self.git("ls-tree", "--name-only", "ak/fix-api"))

    def test_work_a_refused_commit_left_out_keeps_the_checkout(self):
        wt = config.WT / "fix-api"
        wt.parent.mkdir(parents=True)
        self.git("worktree", "add", "-q", "-b", "ak/fix-api", str(wt))
        (wt / ".gitignore").write_text("app.py\n")
        self.git("add", ".gitignore", cwd=wt)
        self.git("commit", "-qm", "ignore the generated app", cwd=wt)
        # the fixer's turn untracks the now-ignored file, and a hook refuses every commit
        self.git("rm", "-q", "--cached", "app.py", cwd=wt)
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        run_dir, state = self.ended("20261013-1602-fix-api", wt)
        self.assertTrue(state["checkout_kept"])
        self.assertRegex(state["error"], "could not be committed, so its checkout .* is kept")
        worktrees.settle_run({**record.read_state(run_dir), "handed_back": True}, run_dir)
        # the untracking waits in the kept checkout, for the seat to commit
        self.assertNotIn("app.py", self.git("ls-files", cwd=wt).splitlines())
        self.assertIn("app.py", self.git("ls-tree", "--name-only", "ak/fix-api").splitlines())

    def test_a_run_in_the_repository_itself_commits_nothing(self):
        (self.repo / "app.py").write_text("the owner's own edit\n")
        _run_dir, state = self.ended("20261013-1601-fix-api", self.repo, branch="main")
        self.assertEqual(state["state"], "blocked")
        self.assertEqual(self.git("log", "--format=%s"), "base")
        self.assertEqual((self.repo / "app.py").read_text(), "the owner's own edit\n")


if __name__ == "__main__":
    unittest.main()
