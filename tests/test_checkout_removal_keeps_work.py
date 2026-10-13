"""Every removal keeping a run's branch saves its work there, or leaves the checkout.

Real Git repositories; workers, GitHub, seats and process readings are fixtures.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, gc, orch, record, roundloop, run, turns, worktrees
from fixtures.own_pr import OwnPr

DAY = 86400


class CheckoutRemoval(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-checkout-removal-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE", "JOBS"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(gc.retention, "process_paths", return_value=set()))
        self.stack.enter_context(patch.object(gc.retention, "writer_active", return_value=False))
        self.stack.enter_context(patch("agentkit.browser.close_owned"))
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "tracked.txt").write_text("base\n")
        (self.repo / "deleted.txt").write_text("delete me\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Base")

    def git(self, repo, *args, check=True):
        result = subprocess.run(["git", "-C", str(repo), *args], check=check,
                                capture_output=True, text=True)
        return result.stdout.strip() if check else result

    def checkout(self, name="fix-api", **extra):
        directory, wt, branch = config.RUNS / name, config.WT / name, f"ak/{name}"
        directory.mkdir()
        self.git(self.repo, "worktree", "add", "-qb", branch, str(wt))
        head = self.git(wt, "rev-parse", "HEAD")
        state = {"run_id": name, "title": "Fix API", "state": "blocked", "verdict": "BLOCKED",
                 "repo": str(self.repo), "worktree": str(wt), "branch": branch,
                 "pid": os.getpid(), "finished_at": time.time() - 60, "started_at": time.time() - 120,
                 "merged": False, "handed_back": True, "rounds": 3, "round_summaries": [],
                 "base": "main", "base_sha": head, "executor": "opus", "reviewer": "astra",
                 "findings": "", "artifacts": ["generated.txt"], **extra}
        record.save_state(directory, state)
        (directory / "task.md").write_text("# Fix API\n\n## Done when\n```bash\ntrue\n```\n")
        (directory / "log.txt").touch()
        return directory, wt, state

    def edit(self, wt):
        (wt / "tracked.txt").write_text("fixed\n")
        (wt / "deleted.txt").unlink()
        (wt / "new file.txt").write_text("new work\n")
        (wt / "staged.txt").write_text("staged work\n")
        (wt / "generated.txt").write_text("done-when output\n")
        (wt / ".ak-test-leftover").mkdir()
        (wt / ".ak-test-leftover" / "junk").write_text("sandbox\n")
        (wt / "venv").symlink_to(self.root)
        (wt / ".gitignore").write_text("ignored.txt\n")
        (wt / "ignored.txt").write_text("ignored\n")
        self.git(wt, "add", "staged.txt", "generated.txt", "venv")

    def assert_saved(self, wt, state):
        self.assertFalse(wt.exists())
        branch = state["branch"]
        self.assertEqual(self.git(self.repo, "show", f"{branch}:tracked.txt"), "fixed")
        self.assertEqual(self.git(self.repo, "show", f"{branch}:new file.txt"), "new work")
        self.assertEqual(self.git(self.repo, "show", f"{branch}:staged.txt"), "staged work")
        self.assertEqual(self.git(self.repo, "ls-tree", "--name-only", branch).splitlines(),
                         [".gitignore", "new file.txt", "staged.txt", "tracked.txt"])

    def test_blocked_task_fixer_saves_work_at_handback(self):
        directory, wt, state = self.checkout(state="running", verdict=None,
                                             round_summaries=[{"round": 1, "verdict": "FAIL"}])

        def fixer(lp, role, _text, _name):
            self.assertEqual(role, "fixer")
            self.edit(lp.wt)
            raise turns.Blocked("Task needs a decision", "## Blocked\n\nTask needs a decision")

        opts = {"--exec": None, "--review": None, "--rounds": None, "--no-worktree": False}
        with patch.object(run, "collect_usage", return_value={}), \
                patch.object(run, "ready_order", return_value=["opus", "astra"]), \
                patch.object(run, "pick_models", return_value=("opus", "astra")), \
                patch.object(run, "pickup_new_code"), \
                patch.object(roundloop, "execute", side_effect=fixer):
            ended = run.loop(self.cfg, directory, directory / "task.md", opts,
                             lambda _: None, prior=state)
        self.assertEqual(ended["state"], "blocked")
        ended["handed_back"] = True
        record.save_state(directory, ended)
        worktrees.settle_run(ended, directory)
        self.assert_saved(wt, state)

    def test_blocked_delivery_retry_saves_work(self):
        directory, wt, state = self.checkout(state="pass", verdict="PASS", merge_failed=True)

        def fixer(lp):
            self.edit(lp.wt)
            raise turns.Blocked("Cannot deliver this task", "## Blocked\n\nCannot deliver this task")

        def finish(state, directory, log, cfg):
            state["handed_back"] = True
            record.save_state(directory, state)
            worktrees.settle_run(state, directory, log)
            return 1

        with patch.object(run.box, "check"), patch.object(run, "review_pass", return_value=True), \
                patch.object(run, "require_review_pass"), \
                patch.object(run, "merge", side_effect=fixer), patch.object(run, "finish", side_effect=finish), \
                patch.object(run.history, "Sampler"), patch.object(run, "stop_run_tree"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_merge([directory.name]), 1)
        self.assertEqual(record.read_state(directory)["state"], "blocked")
        self.assert_saved(wt, state)

    def test_collector_after_handback_saves_work(self):
        directory, wt, state = self.checkout()
        self.edit(wt)
        self.assertIn(str(wt), gc.gc(lambda _: None))
        self.assertTrue(directory.exists())
        self.assert_saved(wt, state)

    def test_dependency_ending_uses_the_same_removal(self):
        directory, wt, state = self.checkout()
        self.edit(wt)
        deliver.end_on_dependency(self.cfg, directory, state, lambda _: None, "Dependency failed")
        self.assert_saved(wt, state)

    def test_hooks_cannot_rewrite_or_refuse_the_preservation_commit(self):
        for name, body in (("rewrite", "echo rewritten > tracked.txt\ngit add tracked.txt"),
                           ("refuse", "exit 1")):
            with self.subTest(hook=name):
                directory, wt, state = self.checkout(name)
                self.edit(wt)
                hooks = self.root / "hooks"
                hooks.mkdir(exist_ok=True)
                hook = hooks / "pre-commit"
                hook.write_text(f"#!/bin/sh\necho called > '{directory / 'hook-called'}'\n{body}\n")
                hook.chmod(0o755)
                self.git(self.repo, "config", "core.hooksPath", str(hooks))
                self.assertTrue(worktrees.stop_checkout(state, lambda _: None, keep_branch=True))
                self.assertFalse((directory / "hook-called").exists())
                self.assert_saved(wt, state)

    def test_commit_refusal_keeps_checkout_and_collector_respects_the_clock(self):
        directory, wt, state = self.checkout()
        self.edit(wt)
        lock = Path(self.git(wt, "rev-parse", "--git-path", f"refs/heads/{state['branch']}.lock"))
        lock.touch()
        self.assertFalse(worktrees.stop_checkout(state, lambda _: None, keep_branch=True))
        self.assertTrue(record.read_state(directory)["checkout_kept"])
        self.assertNotIn(str(wt), [item["path"] for item in gc.gc_plan()])
        self.assertEqual(gc.gc(lambda _: None), [])
        # An already-planned handback must re-read the hold too.
        candidate = {"action": "remove", "kind": "ended-worktree", "path": str(wt),
                     "run": str(directory), "loose": True, "final": True}
        with patch.object(gc, "gc_candidates", return_value=iter([candidate])):
            self.assertEqual(gc.gc(lambda _: None), [])
        state = record.read_state(directory)
        state["finished_at"] = time.time() - 8 * DAY
        record.save_state(directory, state)
        # Expiry retries saving, never forces away work whose commit still fails.
        self.assertNotIn(str(wt), gc.gc(lambda _: None))
        self.assertEqual((wt / "tracked.txt").read_text(), "fixed\n")
        lock.unlink()
        self.assertIn(str(wt), gc.gc(lambda _: None))
        self.assert_saved(wt, state)

    def test_work_only_in_the_index_is_kept(self):
        directory, wt, state = self.checkout()
        (wt / "tracked.txt").write_text("staged work\n")
        self.git(wt, "add", "tracked.txt")
        (wt / "tracked.txt").write_text("base\n")
        self.assertFalse(worktrees.stop_checkout(state, lambda _: None, keep_branch=True))
        self.assertEqual(self.git(wt, "show", ":tracked.txt"), "staged work")
        self.assertTrue(record.read_state(directory)["checkout_kept"])

    def test_off_branch_or_unfinished_git_operation_keeps_checkout(self):
        for mode in ("detached", "other-branch", "rebase", "merge"):
            with self.subTest(mode=mode):
                directory, wt, state = self.checkout(mode, finished_at=time.time() - 8 * DAY)
                original = self.git(wt, "rev-parse", "HEAD")
                if mode == "detached":
                    self.git(wt, "checkout", "--detach")
                elif mode == "other-branch":
                    self.git(wt, "checkout", "-qb", "other-work")
                else:
                    (self.repo / "tracked.txt").write_text(f"target changed during {mode}\n")
                    self.git(self.repo, "commit", "-qam", "Target change")
                    (wt / "tracked.txt").write_text("branch changed\n")
                    self.git(wt, "commit", "-qam", "Branch change")
                    result = self.git(wt, mode, "main", check=False)
                    self.assertNotEqual(result.returncode, 0)
                    original = self.git(self.repo, "rev-parse", state["branch"])
                (wt / "resolution.txt").write_text("unfinished work\n")
                self.assertFalse(worktrees.stop_checkout(state, lambda _: None, keep_branch=True))
                with patch.object(gc, "unremovable", return_value=True):
                    self.assertNotIn(str(wt), gc.gc(lambda _: None))
                self.assertEqual(self.git(self.repo, "rev-parse", state["branch"]), original)
                self.assertEqual((wt / "resolution.txt").read_text(), "unfinished work\n")
                self.assertTrue(record.read_state(directory)["checkout_kept"])

    def test_removal_dropping_branch_discards_work_as_before(self):
        for name, merged in (("stop", False), ("merged", True)):
            directory, wt, state = self.checkout(name, merged=merged, checkout_kept=True)
            self.edit(wt)
            self.git(wt, "checkout", "--detach")
            self.assertTrue(worktrees.drop_checkout(state, keep_branch=False))
            self.assertFalse(wt.exists())
            self.assertNotEqual(self.git(self.repo, "rev-parse", "--verify", state["branch"],
                                         check=False).returncode, 0)


class BlockedOwnPr(OwnPr):
    def test_blocked_own_pr_fixer_saves_work_at_handback(self):
        def blocked(lp):
            (lp.wt / "fence.txt").write_text("fixer work\n")
            (lp.wt / "new.txt").write_text("new work\n")
            raise turns.Blocked("Cannot fix this PR", "## Blocked\n\nCannot fix this PR")

        self.fix = blocked
        state = self.review(["FAIL"])
        wt = Path(state["worktree"])
        state["handed_back"] = True
        record.save_state(self.run_dir, state)
        worktrees.settle_run(state, self.run_dir)
        self.assertEqual(state["state"], "blocked")
        self.assertFalse(wt.exists())
        self.assertEqual(self.git("show", f"{state['branch']}:fence.txt"), "fixer work")
        self.assertEqual(self.git("show", f"{state['branch']}:new.txt"), "new work")
        self.assertEqual(self.remote_head(), self.heads[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
