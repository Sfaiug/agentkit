"""A worker that fails on the provider twice hands its turn to the next worker."""

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
from agentkit import config, run, usage  # noqa: E402


class TransientHandover(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".transient-handover-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "handover-test",
            "TMUX_TMPDIR": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}))
        self.stack.enter_context(patch.object(config, "active_session", return_value=None))
        config.ensure_dirs()
        self.cfg = {"defaults": {"orchestrator": "alpha",
                                 "workers": ["alpha", "bravo", "charlie"]},
                    "models": {}, "providers": {"pa": {}, "pb": {}, "pc": {}}}
        for name, provider in (("alpha", "pa"), ("bravo", "pb"), ("charlie", "pc")):
            self.cfg["models"][name] = {"harness": "test", "model": name,
                                        "effort": "high", "provider": provider}
        self.providers = {name: {"meters": [{"name": "weekly", "used": 10, "pace": -40,
                                             "elapsed": 50, "window_secs": 604800,
                                             "resets_at": time.time() + 302400}],
                                  "resets": 0}
                          for name in ("pa", "pb", "pc")}
        self.logs = []

    def worker(self, answers):
        """A fake worker.call playing `answers` back: (code, text, session) each."""
        calls = []

        def call(*args, **kwargs):
            code, text, session = answers[min(len(calls), len(answers) - 1)]
            calls.append(args)
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "prompt.md").write_text("You are the worker.\n")
            (out / "final.md").write_text(text)
            (out / "stderr.log").write_text("")
            (out / "events.jsonl").write_text("")
            (out / "session_id").write_text(session)
            return code, text, session, False

        return calls, call

    def loop(self, executor="alpha", reviewer="bravo", spares=()):
        run_dir = self.root / "run"
        run_dir.mkdir(exist_ok=True)
        (run_dir / "log.txt").touch(exist_ok=True)
        workspace = self.root / "work"
        workspace.mkdir(exist_ok=True)
        state = {"run_id": "fixture", "state": "running", "verdict": None,
                 "executor": executor, "reviewer": reviewer, "repo": None,
                 "scratch": True, "worktree": str(workspace), "base": None,
                 "rounds": 2, "round_summaries": [], "findings": "",
                 "workers": ["alpha", "bravo", "charlie"]}
        lp = run.Loop(self.cfg, run_dir, state, {}, self.logs.append, workspace,
                      "Review the work.", [], "Fixture", list(spares))
        lp.rnd = 1
        return lp

    def test_executor_failing_twice_hands_the_round_to_the_next_worker(self):
        lp = self.loop(executor="alpha", reviewer="bravo", spares=["charlie"])
        calls, fake = self.worker([
            (1, "API Error: 500 Internal server error\n", "sess-a"),
            (1, "API Error: 503 Service unavailable\n", "sess-a"),
            (0, "## Summary\nDone by the next worker.\n", "sess-b"),
        ])
        sleeps = []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append), \
                patch.object(run, "collect_usage", return_value=self.providers):
            summary = run.execute(lp, "executor", "Do the thing.", "executor")
        self.assertIn("Done by the next worker.", summary)
        self.assertEqual([args[1] for args in calls], ["alpha", "alpha", "bravo"])
        # the second failure hands over at once: only the first wait is spent
        self.assertEqual(sleeps, [60])
        # the new model is told another model started the round
        self.assertIn("Another model started this round", calls[2][2])
        self.assertIn("alpha began this round", calls[2][2])
        self.assertIn("Do the thing.", calls[2][2])
        self.assertEqual(lp.executor, "bravo")
        # the failed provider joins this round's refused set, recorded as the move
        history = lp.state.get("executor_history") or []
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["from"], "alpha")
        self.assertEqual(history[0]["to"], "bravo")
        self.assertEqual(history[0]["why"], "transient")
        # a fresh session and a fresh out dir beside the failed attempt's
        self.assertEqual([args[6] for args in calls], [None, "sess-a", None])
        outs = [Path(args[4]) for args in calls]
        self.assertEqual(outs[0].parent.name, "round-1")
        self.assertNotEqual(outs[0], outs[2])
        self.assertTrue(any("sess-a" in line for line in self.logs))

    def test_reviewer_failing_twice_falls_back_to_a_spare(self):
        lp = self.loop(executor="charlie", reviewer="alpha", spares=["bravo"])
        calls, fake = self.worker([
            (1, "API Error: 500 Internal server error\n", "sess-r"),
            (1, "Overloaded: the provider is busy\n", "sess-r"),
            (0, "VERDICT: PASS\n\n## Findings\n- none\n", "sess-s"),
        ])
        sleeps = []
        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append), \
                patch.object(run, "collect_usage", return_value=self.providers):
            verdict = run.review(lp, "Work done.", True, "$ true\n[exit 0]")
        self.assertEqual(verdict, "PASS")
        self.assertEqual([args[1] for args in calls], ["alpha", "alpha", "bravo"])
        self.assertEqual(sleeps, [60])
        self.assertEqual(lp.reviewer, "bravo")
        self.assertTrue(any("fell back to bravo" in line for line in self.logs),
                        self.logs)
        outs = [Path(args[4]).name for args in calls]
        self.assertIn("reviewer-bravo", outs)

    def test_no_other_worker_retries_the_same_session_with_the_growing_waits(self):
        lp = self.loop(executor="alpha", reviewer="bravo", spares=[])
        calls, fake = self.worker([
            (1, "API Error: 500 Internal server error\n", "sess-a"),
            (1, "API Error: 503 Service unavailable\n", "sess-a"),
            (1, "Overloaded: the provider is busy\n", "sess-a"),
            (0, "## Summary\nDone after the outage.\n", "sess-a"),
        ])
        sleeps, handed = [], []

        def hand(lp_, why, detail, dry):
            handed.append((lp_.executor, why))
            self.assertEqual(why, "transient")
            return None

        with patch.object(run.worker, "call", side_effect=fake), \
                patch.object(run.time, "sleep", side_effect=sleeps.append), \
                patch.object(run, "hand_executor", side_effect=hand):
            summary = run.execute(lp, "executor", "Do the thing.", "executor")
        self.assertIn("Done after the outage.", summary)
        self.assertEqual([args[1] for args in calls], ["alpha"] * 4)
        # the handover is tried once, after the second failure; then the same
        # session is retried with the growing waits, as today
        self.assertEqual(handed, [("alpha", "transient")])
        self.assertEqual(sleeps, [60, 300, 900])
        self.assertEqual([args[6] for args in calls],
                         [None, "sess-a", "sess-a", "sess-a"])
        self.assertTrue(any("no other worker" in line for line in self.logs),
                        self.logs)


if __name__ == "__main__":
    unittest.main()
