"""A review answers through hand-in records, including the findings handed back."""

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

PROSE = ("VERDICT: PASS\n\n## Findings\n- api.py:1 - prose finding - breaks callers\n\n"
         "## Follow-ups\n- api.py:1 - prose follow-up - existed before\n")
FINDING = ["finding", "api.py:1", "handed-in defect", "breaks callers", "--quote", "wrong answer"]


class ReviewerTextIgnored(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-reviewer-text-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name, value in ((run, "collect_usage", {}), (run, "ready_order", []),
                                    (run, "note_turn_meters", None), (run, "history_role_tokens", None),
                                    (run, "memory_cap_note", None), (run.history, "update_run", None)):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        config.ensure_dirs()
        workspace = self.root / "acme"
        workspace.mkdir()
        (workspace / "api.py").write_text("wrong answer\n")
        directory = self.root / "run"
        directory.mkdir()
        state = {"run_id": "reviewer-text", "title": "Review fixture", "state": "running",
                 "scratch": True, "repo": "none", "worktree": str(workspace),
                 "base": "main", "base_sha": "abc123", "branch": "ak/fix-api",
                 "executor": "opus", "reviewer": "astra", "rounds": 3, "round_summaries": []}
        self.lp = run.Loop(config.load(), directory, state, {}, lambda _s: None, workspace,
                           "# Fixture", ["true"], "", [])
        self.lp.rnd = 1
        self.calls = []

    def review(self, *plan):
        responses = iter(plan)

        def turn(_cfg, _model, body, cwd, out, _role, sid=None, **_kw):
            text, commands = next(responses)
            self.calls.append((body, sid))
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text(text)
            (out / "session_id").write_text("fixture-session")
            if commands is not None:
                file = hand_in.start(out, cwd)
                with patch.dict(os.environ, {hand_in.ENV: file}):
                    for args in commands:
                        hand_in.main(args)
            return 0, text, "fixture-session", False

        def extra(*args, **kwargs):
            return (*turn(*args, **kwargs), False)

        with patch.object(run, "call_retrying", side_effect=turn), \
                patch.object(worker, "turn", side_effect=extra):
            return run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]")

    def test_prose_without_a_channel_is_asked_once_more_then_exhausted(self):
        with self.assertRaisesRegex(run.Exhausted, "gave no verdict twice"):
            self.review((PROSE, None), (PROSE, None))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1], (run.NO_VERDICT_ASK, "fixture-session"))
        self.assertIsNone(self.lp.state["verdict"])
        self.assertEqual(self.lp.state["round_summaries"], [])

    def test_only_the_reasked_done_passes_without_prose_findings_or_followups(self):
        verdict = self.review((PROSE, None), (PROSE, [["done"]]))
        self.assertEqual(verdict, "PASS")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][0], run.NO_VERDICT_ASK)
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 0)
        self.assertEqual(self.lp.state["followups"], [])

    def test_fail_handback_keeps_the_handed_in_finding_when_reports_change_or_disappear(self):
        self.assertEqual(self.review((PROSE, [FINDING, ["done"]])), "FAIL")
        self.lp.state["state"] = "fail"
        source = Path(self.lp.state["findings_file"])
        for text in ("VERDICT: PASS\n", "VERDICT: FAIL\n## Findings\n- fabricated\n", None):
            with self.subTest(text=text):
                if text is None:
                    source.unlink()
                    (source.parent / hand_in.FILE).unlink()
                else:
                    source.write_text(text)
                self.lp.state["findings"] = text or ""
                self.lp.save()
                state = run.read_state(self.lp.run_dir)
                self.assertTrue(run.review_failed(state))
                reason = run.handback_reason(state)
                self.assertIn("api.py:1 - handed-in defect - breaks callers", reason)
                self.assertNotIn("prose finding", reason)
                self.assertNotIn("fabricated", reason)

    def test_fail_prose_without_records_does_not_make_a_review_fail(self):
        self.assertFalse(run.review_failed({"findings": "VERDICT: FAIL\n## Findings\n- fabricated\n"}))


if __name__ == "__main__":
    unittest.main()
