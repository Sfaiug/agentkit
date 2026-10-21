"""A review's fallback picks from the marked reviewers as they stand now: fake meters, no model calls."""

from contextlib import ExitStack, redirect_stderr
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import config, record, run, staffing, turns

MARKED = ["beta", "gamma", "delta", "alpha"]


class FreshFallback(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-fallback-fresh-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(run.worker, "kill_marked", return_value=True))
        stack.enter_context(patch.object(config, "active_session", return_value=None))
        stack.enter_context(patch.object(config, "STATE", self.root / "state"))
        stack.enter_context(redirect_stderr(io.StringIO()))
        # a review run in-process is no child of the run this test may be running under
        stack.enter_context(patch.dict(os.environ, {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        # one provider each, so one reviewer's meter moves without the others'
        self.cfg = {"defaults": {"orchestrator": "alpha", "workers": list(MARKED)},
                    "models": {name: {"harness": "test", "model": name, "effort": "high",
                                      "provider": name} for name in MARKED},
                    "providers": {name: {} for name in MARKED}}
        self.used = dict.fromkeys(MARKED, 10)
        stack.enter_context(patch.object(staffing, "collect_usage", side_effect=self.meters))

    def meters(self, _cfg):
        return {name: {"meters": [{"name": "weekly", "used": used, "pace": used - 50,
                                  "elapsed": 50, "window_secs": 604800,
                                  "resets_at": time.time() + 302400}], "resets": 0}
                for name, used in self.used.items()}

    def loop(self, state=None):
        directory, workspace = self.root / "run", self.root / "work"
        if state is not None:       # the run resumed from its saved record
            lp = run.Loop(self.cfg, directory, state, {}, lambda _: None, workspace,
                          "Review the work.", [], "Fixture")
            lp.rnd = 1
            return lp
        directory.mkdir()
        workspace.mkdir()
        state = {"run_id": "fixture", "state": "running", "verdict": None,
                 "executor": "alpha", "reviewer": "beta", "reviewers": list(MARKED),
                 "repo": None, "scratch": True, "worktree": str(workspace), "base": None,
                 "rounds": 2, "round_summaries": [], "findings": ""}
        lp = run.Loop(self.cfg, directory, state, {}, lambda _: None, workspace,
                      "Review the work.", [], "Fixture")
        lp.rnd = 1
        lp.round_dir.mkdir()
        return lp

    def review(self, lp, broken, before=None, killed=()):
        """One round's review, where each of `broken` cannot run and each of `killed` is
        interrupted; `before` moves the meters as a model is called.  Returns who was called,
        in order."""
        calls = []

        def call(cfg, model, body, workspace, out, *args, **kwargs):
            calls.append(model)
            (before or {}).get(model, lambda: None)()
            if model in broken:
                raise turns.CannotRun(model, "fixture harness cannot run")
            if model in killed:
                raise turns.Killed(f"{model} killed twice")
            out.mkdir(parents=True, exist_ok=True)
            return 0, "VERDICT: PASS", "sid", False
        with patch.object(turns, "call_retrying", side_effect=submitting(call)), \
                patch.object(run.worker, "call", side_effect=submitting(call)):
            try:
                run.review(lp, "Work done.", True, "passed")
            except (turns.CannotRun, turns.Killed):
                pass
        return calls

    def test_a_reviewer_passed_over_while_spent_reviews_once_refilled(self):
        lp = self.loop()
        spend = lambda: self.used.update(delta=100)
        refill = lambda: self.used.update(delta=10)
        calls = self.review(lp, {"beta", "gamma"}, {"beta": spend, "gamma": refill})
        self.assertEqual(calls, ["beta", "gamma", "delta"])
        self.assertEqual(lp.reviewer, "delta")

    def test_a_reviewer_that_failed_this_round_is_not_asked_again_in_it(self):
        lp = self.loop()
        self.used.update(delta=100, alpha=100)
        self.assertEqual(self.review(lp, {"beta", "gamma"}), ["beta", "gamma"])
        # the next round starts with nobody failed: beta, with room, reviews again
        lp.rnd = 2
        lp.round_dir.mkdir()
        self.assertEqual(self.review(lp, {"gamma"}), ["gamma", "beta"])

    def test_a_resumed_round_still_knows_who_failed_in_it(self):
        lp = self.loop()
        self.assertEqual(self.review(lp, {"beta"}, killed={"gamma"}), ["beta", "gamma"])
        resumed = self.loop(record.read_state(lp.run_dir))
        self.assertEqual(self.review(resumed, {"gamma"}), ["gamma", "delta"])


if __name__ == "__main__":
    unittest.main()
