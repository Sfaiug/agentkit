"""A delivery retry parks a dry landing reviewer on its provider window. Offline."""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run


class DeliveryRetryDry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-delivery-retry-dry-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(run.history, "Sampler"))
        self.stack.enter_context(patch.object(run, "finish", return_value=1))
        self.stack.enter_context(patch.object(run, "stop_run_tree"))
        self.wt = self.root / "checkout"
        self.wt.mkdir()
        run.git(self.wt, "init", "--initial-branch=main")
        run.git(self.wt, "config", "user.name", "fixture")
        run.git(self.wt, "config", "user.email", "fixture@localhost")
        (self.wt / "work.txt").write_text("done\n")
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-m", "task work")

    def merge_retry(self, exc, stale=False):
        run_dir = config.RUNS / "fix-api"
        run_dir.mkdir(exist_ok=True)
        (run_dir / "task.md").write_text("# Fix API\n\n## Done when\n```bash\ntrue\n```\n")
        head = run.git(self.wt, "rev-parse", "HEAD")
        tree = run.git(self.wt, "rev-parse", "HEAD^{tree}")
        run.save_state(run_dir, {
            "run_id": run_dir.name, "title": "Fix API", "state": "pass", "verdict": "PASS",
            "executor": "opus", "reviewer": "astra", "rounds": 1,
            "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                 "summary": "Done."}],
            "review": {"executor": "opus", "executor_provider": "anthropic",
                       "reviewer": "astra", "reviewer_provider": "openai",
                       "returncode": 0, "verdict": "PASS", "done_when": True,
                       "head_sha": head, "tree_sha": tree},
            "repo": str(self.wt), "worktree": str(self.wt), "branch": "ak/fix-api",
            "base": "main", "base_sha": head, "scratch": False,
            "merge_failed": True, "merge_note": "pushing failed", "findings": ""})

        def landing_review(lp, **_kw):
            if stale:
                lp.state.update(quota_dry=True, refusal_retry=123)
            return run.review(lp, "Done.", True, "$ true\n[exit 0]\n", record=False)

        def reviewer_turn(cfg, name, body, workspace, out, role, session, log, limit=None, **_kw):
            self.assertEqual(role, "reviewer")
            raise exc

        with patch.object(run, "merge", side_effect=landing_review), \
                patch.object(run, "call_retrying", side_effect=reviewer_turn) as turn, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(run.cmd_merge([run_dir.name]), 1)
        self.assertEqual(turn.call_count, 1)
        saved = run.read_state(run_dir)
        self.assertEqual(saved["state"], "exhausted")
        self.assertEqual(saved["error"], str(exc))
        self.assertIs(saved["review_pending"]["record"], False)
        return saved

    def test_dry_landing_reviewer_waits_on_window(self):
        saved = self.merge_retry(run.QuotaDry("You've hit your weekly limit; no reviewer is left"))
        self.assertEqual(run.exhausted_wait(saved), "window")
        self.assertTrue(saved["quota_dry"])

    def test_other_landing_review_stops_clear_stale_quota(self):
        for exc in (run.Exhausted("reviewer returned no verdict"),
                    config.Error("git stopped: timed out")):
            with self.subTest(exc=type(exc).__name__):
                saved = self.merge_retry(exc, stale=True)
                self.assertEqual(run.exhausted_wait(saved), "")
                self.assertNotIn("quota_dry", saved)
                self.assertNotIn("refusal_retry", saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
