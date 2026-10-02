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
from agentkit import config, hand_in, run, worker


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
        self.closing = None
        self.background = False
        self.background_on_ask = False
        self.channel = False

    def turn(self, _cfg, _model, body, cwd, out, role, sid=None, env=None, **_kw):
        self.calls.append((body, sid))
        self.assertLessEqual(len(self.calls), 2, "the executor is asked only once more")
        out.mkdir(parents=True, exist_ok=True)
        (out / "prompt.md").write_text(worker.PREAMBLES[role].format(workspace=cwd) + "\n\n" + body)
        (out / "final.md").write_text(self.text)
        (out / "session_id").write_text("fixture-session")
        if self.channel or len(self.calls) == 2 and self.closing:
            file = hand_in.start(out, cwd, (env or {}).get(hand_in.CONTINUE), role=role)
            if len(self.calls) == 2 and self.closing:
                with patch.dict(os.environ, {hand_in.ENV: file}):
                    hand_in.main(self.closing)
        unfinished = (self.background and len(self.calls) == 1
                      or self.background_on_ask and len(self.calls) == 2)
        return 0, self.text, "fixture-session", False, unfinished

    def checked(self):
        with patch.object(worker, "turn", side_effect=self.turn), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")) as checks, \
                patch.object(run, "review", return_value="PASS") as review:
            run.rounds(self.lp)
        checks.assert_called_once_with(self.lp)
        review.assert_called_once()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][1], "fixture-session")
        self.assertIn(run.NO_CLOSING_ASK, self.calls[1][0])
        self.assertNotIn("not_needed", self.lp.state)
        self.assertEqual(run.continuation(self.lp), "done-when")

    def test_blocked_heading_without_hand_in_is_asked_once_then_checked(self):
        self.text = "## Blocked"
        self.checked()

    def test_followup_not_needed_prose_without_hand_in_is_asked_once_then_checked(self):
        self.lp.state["followup"] = {"place": "api.py:1"}
        self.text = "not needed: gone"
        self.checked()

    def test_fixer_without_hand_in_is_asked_once(self):
        self.lp.rnd = 1
        self.text = "## Blocked"
        with patch.object(worker, "turn", side_effect=self.turn):
            self.assertEqual(run.execute(self.lp, "fixer", "Fix the task.", "fixer"), self.text)
        self.assertEqual(len(self.calls), 2)
        self.assertIn(run.NO_CLOSING_ASK, self.calls[1][0])
        self.assertEqual(self.calls[1][1], "fixture-session")
        self.assertEqual(run.continuation(self.lp), "done-when")

    def test_task_quoting_the_closing_ask_still_needs_hand_in(self):
        self.text = "## Blocked"
        self.lp.context = "Document this prompt: " + run.NO_CLOSING_ASK
        self.checked()

    def test_empty_record_channel_still_needs_the_extra_ask(self):
        self.text = "## Blocked"
        self.channel = True
        self.checked()

    def test_completed_prose_after_host_interruption_still_needs_the_extra_ask(self):
        self.text = "## Blocked"
        self.lp.rnd = 1
        self.turn(self.lp.cfg, self.lp.executor, "Do the task.", self.lp.wt,
                  self.lp.dir("executor"), self.lp.role("executor"))
        self.lp.rnd = 0
        self.checked()
        self.assertIn(run.NO_CLOSING_ASK, self.calls[1][0])

    def test_restart_after_a_resumed_turn_and_its_ask_does_not_ask_again(self):
        self.text = "## Summary\nwork"
        self.lp.rnd = 1
        cut = self.lp.dir("executor")
        cut.mkdir(parents=True)
        (cut / "session_id").write_text("fixture-session")
        with patch.object(worker, "turn", side_effect=self.turn), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")) as checks, \
                patch.object(run, "review", return_value="PASS") as review:
            for _ in range(2):
                self.lp.rnd = 0
                self.lp.state["step"] = "done-when"
                run.rounds(self.lp)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(checks.call_count, 2)
        self.assertEqual(review.call_count, 2)
        self.assertEqual(run.continuation(self.lp), "done-when")
        for call in review.call_args_list:
            self.assertIn(self.text, call.args[1])

    def test_restart_after_a_handover_and_its_ask_does_not_ask_again(self):
        self.text = "## Summary\nwork"
        call_retrying = run.call_retrying

        def call(cfg, model, body, cwd, out, *args, **kw):
            if model == "opus":
                out.mkdir(parents=True)
                (out / "final.md").write_text("fixture harness cannot run")
                raise run.CannotRun(model, "fixture harness cannot run")
            return call_retrying(cfg, model, body, cwd, out, *args, **kw)

        def handover(lp, *_args, **_kw):
            lp.executor, lp.exec_sid = "fable", None
            return lp.executor

        with patch.object(run, "call_retrying", side_effect=call), \
                patch.object(run, "hand_executor", side_effect=handover), \
                patch.object(worker, "turn", side_effect=self.turn), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")) as checks, \
                patch.object(run, "review", return_value="PASS") as review:
            for _ in range(2):
                self.lp.rnd = 0
                self.lp.state["step"] = "done-when"
                run.rounds(self.lp)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(checks.call_count, 2)
        self.assertEqual(review.call_count, 2)
        self.assertEqual(run.continuation(self.lp), "done-when")
        for call in review.call_args_list:
            self.assertIn(self.text, call.args[1])

    def test_work_summary_survives_the_closing_ask_and_a_restart(self):
        work = "## Summary\nChanged api.py and added a regression test."
        texts = (work, "Closed.")
        self.closing = ["done"]

        def turn(*args, **kw):
            self.text = texts[min(len(self.calls), 1)]
            return self.turn(*args, **kw)

        for role, background in (("executor", False), ("fixer", False), ("executor", True)):
            with self.subTest(role=role, background=background):
                self.calls = []
                self.background = background
                self.lp.rnd = 1
                with patch.object(worker, "turn", side_effect=turn):
                    summary = run.execute(self.lp, role, "Do the task.", role)
                self.assertIn(work, summary)
                self.lp.rnd = 0
                self.lp.state["step"] = "done-when"
                with patch.object(worker, "turn", side_effect=turn), \
                        patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")), \
                        patch.object(run, "review", return_value="PASS") as review:
                    run.rounds(self.lp)
                self.assertIn(work, review.call_args.args[1])
                self.assertEqual(len(self.calls), 2)

    def test_review_checkout_left_after_interruption_cannot_hide_the_work_summary(self):
        for name in ("executor", "fixer", "final-fixer", "executor-fable-attempt2"):
            with self.subTest(worker=name):
                # Each worker case represents a separate interrupted run.
                self.lp.run_dir = self.root / name
                work = f"## Summary\nChanged api.py in the {name} turn."
                self.lp.rnd = 1
                answered = self.lp.dir(name)
                answered.mkdir(parents=True)
                (answered / "final.md").write_text(work)
                role = "executor" if name.startswith("executor") else "fixer"
                file = hand_in.start(answered, self.lp.wt, role=role)
                with patch.dict(os.environ, {hand_in.ENV: file}):
                    self.assertEqual(hand_in.main(["done"]), 0)
                # Equal mtimes expose answers leaking between independent cases.
                os.utime(answered, ns=(1_000_000_000, 1_000_000_000))
                (self.lp.round_dir / "donewhen.log").write_text("$ true\n[exit 0]\n")
                # The host stopped before reviewer_checkout could remove its copy.
                stale = self.lp.dir("review-checkout")
                stale.mkdir(exist_ok=True)
                (stale / f"{name}.py").write_text("print(1)\n")
                for step in ("reviewer", "done-when"):
                    with self.subTest(step=step):
                        self.lp.rnd = 0
                        self.lp.state["step"] = step
                        with patch.object(worker, "turn", side_effect=AssertionError(
                                "the worker already closed")) as turns, \
                                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")), \
                                patch.object(run, "review", return_value="PASS") as review:
                            run.rounds(self.lp)
                        turns.assert_not_called()
                        self.assertIn(work, review.call_args.args[1])

    def test_host_interruption_during_the_extra_ask_resumes_it_without_another_ask(self):
        work = "## Summary\nChanged api.py and added a regression test."
        self.text = "Closed."
        self.lp.rnd = 1
        first = self.lp.dir("executor")
        first.mkdir(parents=True)
        (first / "final.md").write_text(work)
        asked = self.lp.dir("executor-retry-hand-in")
        asked.mkdir()
        (asked / "session_id").write_text("fixture-session")
        self.lp.rnd = 0
        with patch.object(worker, "turn", side_effect=self.turn), \
                patch.object(run, "verify_work", return_value=(True, "$ true\n[exit 0]")) as checks, \
                patch.object(run, "review", return_value="PASS") as review:
            run.rounds(self.lp)
        checks.assert_called_once_with(self.lp)
        review.assert_called_once()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1], "fixture-session")
        self.assertIn(run.NO_CLOSING_ASK, self.calls[0][0])
        self.assertEqual(run.continuation(self.lp), "done-when")
        self.assertIn(work, review.call_args.args[1])

    def test_background_recovery_includes_the_closing_ask_without_a_third_turn(self):
        self.text = "## Blocked"
        self.background = True
        self.checked()
        self.assertIn(run.FINISH_IN_FOREGROUND, self.calls[1][0])

    def test_extra_closing_turn_leaving_background_work_does_not_buy_a_third_turn(self):
        self.text = "## Blocked"
        self.background_on_ask = True
        self.checked()

    def test_extra_turn_can_hand_in_blocked(self):
        self.text = "## Summary\nWork cannot finish."
        self.closing = ["blocked", "the task requires an unavailable file"]
        self.lp.rnd = 1
        with patch.object(worker, "turn", side_effect=self.turn), \
                self.assertRaisesRegex(run.Blocked, self.closing[1]):
            run.execute(self.lp, "executor", "Do the task.", "executor")
        self.assertIn(run.NO_CLOSING_ASK, self.calls[1][0])
        self.assertEqual(self.calls[1][1], "fixture-session")

    def test_extra_followup_turn_can_hand_in_not_needed(self):
        self.text = "## Summary\nChecked the target."
        self.closing = ["not-needed", "gone on the target"]
        self.lp.state["followup"] = {"place": "api.py:1"}
        self.lp.rnd = 1
        with patch.object(worker, "turn", side_effect=self.turn), \
                self.assertRaisesRegex(run.NotNeeded, self.closing[1]):
            run.execute(self.lp, "executor", "Do the task.", "executor")
        self.assertIn(run.NO_CLOSING_ASK, self.calls[1][0])
        self.assertEqual(self.calls[1][1], "fixture-session")


if __name__ == "__main__":
    unittest.main(verbosity=2)
