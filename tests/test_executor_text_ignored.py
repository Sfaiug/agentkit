"""Executor prose cannot close a turn or skip its checks and review."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker


class ExecutorTextIgnored(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-executor-text-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name in ((run, "note_turn_meters"), (run, "history_role_tokens"),
                             (run, "memory_cap_note"), (run.history, "update_run"),
                             (run, "pickup_new_code")):
            self.stack.enter_context(patch.object(module, name, return_value=None))
        self.stack.enter_context(patch.object(run, "transient_wait",
                                             side_effect=AssertionError("unexpected wait")))
        config.ensure_dirs()
        workspace = self.root / "acme"
        workspace.mkdir()
        directory = self.root / "run"
        directory.mkdir()
        state = {"run_id": "executor-text", "title": "Fixture", "state": "running",
                 "scratch": True, "repo": "none", "worktree": str(workspace),
                 "base": "main", "base_sha": "abc123", "branch": "ak/fix-api",
                 "executor": "opus", "reviewer": "astra", "rounds": 1, "round_summaries": []}
        self.lp = run.Loop(config.load(), directory, state, {}, lambda _s: None, workspace,
                           "# Fixture", ["true"], "Do the task.", [])
        self.calls = []

    def turn(self, _cfg, _model, body, cwd, out, role, sid=None, env=None, **_kw):
        self.calls.append((body, sid))
        self.assertLessEqual(len(self.calls), 2, "the executor is asked only once more")
        out.mkdir(parents=True, exist_ok=True)
        (out / "prompt.md").write_text(worker.PREAMBLES[role].format(workspace=cwd) + "\n\n" + body)
        (out / "final.md").write_text(self.text)
        (out / "session_id").write_text("fixture-session")
        return 0, self.text, "fixture-session", False, False

    def checked(self):
        with patch.object(worker, "turn", side_effect=self.turn), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")) as checks, \
                patch.object(run, "review", return_value="PASS") as review:
            run.rounds(self.lp)
        checks.assert_called_once_with(self.lp)
        review.assert_called_once()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][1], "fixture-session")
        self.assertIn("ak hand-in", self.calls[1][0])
        self.assertNotIn("not_needed", self.lp.state)

    def test_blocked_heading_without_hand_in_is_asked_once_then_checked(self):
        self.text = "## Blocked"
        self.checked()

    def test_followup_not_needed_prose_without_hand_in_is_asked_once_then_checked(self):
        self.lp.state["followup"] = {"place": "api.py:1"}
        self.text = "not needed: gone"
        self.checked()


if __name__ == "__main__":
    unittest.main(verbosity=2)
