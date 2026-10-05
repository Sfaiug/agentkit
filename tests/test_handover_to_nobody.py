"""A handover that finds nobody to take the work leaves no handover in the run's record."""

import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import config, status, run  # noqa: E402
from agentkit import record


class HandoverToNobody(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-handover-to-nobody-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, self.root / key.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "nobody-test",
            "TMUX_TMPDIR": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}))
        stack.enter_context(patch.object(config, "active_session", return_value=None))
        config.ensure_dirs()

    def test_a_flake_nobody_can_take_reads_as_the_same_worker(self):
        # bravo is the only other worker and reviews: taking the work would leave it
        # reviewing itself, so alpha waits out the flake and carries on
        cfg = {"defaults": {"orchestrator": "alpha", "workers": ["alpha", "bravo"]},
               "models": {name: {"harness": "test", "model": name, "effort": "high",
                                 "provider": provider}
                          for name, provider in (("alpha", "pa"), ("bravo", "pb"))},
               "providers": {"pa": {}, "pb": {}}}
        providers = {name: {"meters": [{"name": "weekly", "used": 10, "pace": -40,
                                        "elapsed": 50, "window_secs": 604800,
                                        "resets_at": time.time() + 302400}], "resets": 0}
                     for name in ("pa", "pb")}
        run_dir, workspace = self.root / "run", self.root / "workspace"
        run_dir.mkdir()
        workspace.mkdir()
        (run_dir / "log.txt").touch()
        state = {"run_id": "fixture", "state": "running", "verdict": None,
                 "executor": "alpha", "reviewer": "bravo", "repo": None, "scratch": True,
                 "worktree": str(workspace), "base": None, "rounds": 2,
                 "round_summaries": [], "findings": "", "workers": ["alpha", "bravo"]}
        lp = run.Loop(cfg, run_dir, state, {}, lambda line: None, workspace,
                      "Review the work.", [], "Fixture", [])
        lp.rnd = 1
        answers = [(1, "API Error: 500 Internal server error\n"),
                   (1, "API Error: 503 Service unavailable\n"),
                   (0, "## Summary\nDone after the outage.\n")]

        def call(*args, **_kw):
            code, text = answers.pop(0)
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text(text)
            (out / "session_id").write_text("sess-a")
            return code, text, "sess-a", False

        with patch.object(run.worker, "call", side_effect=submitting(call)), \
                patch.object(run.time, "sleep"), \
                patch.object(run, "collect_usage", return_value=providers):
            run.execute(lp, "executor", "Do the thing.", "executor")
        saved = record.read_state(run_dir)
        self.assertEqual(saved["executor"], "alpha")
        self.assertEqual(saved.get("executor_history") or [], [])
        self.assertEqual(status.executor_line(saved), "alpha")

    def test_an_attempt_that_went_nowhere_does_not_lend_its_reason(self):
        # a record that already holds such an attempt behind a real handover
        state = {"executor": "spark",
                 "executor_history": [
                     {"from": "astra", "to": "spark", "reason": "dry",
                      "model": "astra", "rounds": [1], "why": "ran dry"},
                     {"from": "spark", "to": "spark", "reason": "dry (no other provider)",
                      "model": "spark", "rounds": [1, 2], "why": "transient"}]}
        self.assertEqual(status.executor_line(state), "astra → spark (ran dry)")
        state["executor_history"] = state["executor_history"][1:]
        self.assertEqual(status.executor_line(state), "spark")


if __name__ == "__main__":
    unittest.main()
