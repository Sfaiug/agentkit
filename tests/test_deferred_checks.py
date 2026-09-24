"""Deferred done-when commands are explained to reviewers and in result.md."""

from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run, worker


class DeferredChecks(unittest.TestCase):
    def review_fixture(self, once=()):
        root = Path(tempfile.mkdtemp(prefix=".deferred-checks-", dir=REPO))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        workspace = root / "workspace"
        workspace.mkdir()
        round_dir = root / "round-1"
        round_dir.mkdir()

        class Fixture:
            def __init__(self):
                self.cfg = {}
                self.run_dir = root
                self.wt = workspace
                self.body = "# Fixture task"
                self.cmds = ["true", *once]
                self.every = ["true"]
                self.scratch = True
                self.state = {"round_summaries": [], "executor": "executor", "reviewer": "reviewer"}
                self.rnd = 1
                self.round_dir = round_dir
                self.reviewer = "reviewer"
                self.executor = "executor"
                self.review_sid = None
                self.spares = []
                self.findings = ""
                self.artifacts = set()
                self.validation = {}
                self.once = list(once)
                self.turn_limit = 1

            def save(self):
                pass

            def log(self, _message):
                pass

            def role(self, name):
                return name

            def dir(self, name):
                return self.round_dir / name

        return root, Fixture()

    def reviewer_prompt(self, once=()):
        _root, lp = self.review_fixture(once)
        with patch.object(run, "review_providers", return_value=("provider-a", "provider-b")), \
                patch.object(run, "call_retrying",
                             return_value=(0, "VERDICT: PASS\n## Findings\n- none", None, False)) as call:
            self.assertEqual(run.review(lp, "Fixture summary", True, "$ true\n[exit 0]"), "PASS")
        return call.call_args.args[2]

    def test_reviewer_body_lists_each_deferred_command_and_explanation(self):
        prompt = self.reviewer_prompt(("bash tests/smoke.sh", "python3 tests/test_extra.py"))
        first = "deferred to the final check on the shipping commit: bash tests/smoke.sh"
        second = "deferred to the final check on the shipping commit: python3 tests/test_extra.py"
        sentence = "These run after this review passes; their absence here is by design and is never a finding."
        self.assertIn(first, prompt)
        self.assertIn(second, prompt)
        self.assertIn(sentence, prompt)
        output = prompt.index("## Done-when output")
        self.assertLess(prompt.index(first), prompt.index("```", output))
        self.assertLess(prompt.index(second), prompt.index(sentence))

    def test_review_without_deferred_commands_adds_no_deferred_note(self):
        prompt = self.reviewer_prompt()
        self.assertNotIn("deferred to the final check", prompt)
        self.assertNotIn("Their absence here is by design", prompt)

    def test_reviewer_preambles_explain_deferred_commands(self):
        clause = "except the commands marked deferred, which run on the shipping commit after your PASS"
        self.assertIn(clause, worker.PREAMBLES["reviewer"])
        self.assertIn(clause, worker.PREAMBLES["reviewer-scratch"])

    def test_result_marks_once_command_as_final_check(self):
        root = Path(tempfile.mkdtemp(prefix=".deferred-result-", dir=REPO))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        state = {"title": "Fixture", "verdict": "PASS", "round_summaries": [], "rounds": 1,
                 "scratch": True, "worktree": str(root), "executor": "executor",
                 "reviewer": "reviewer"}
        with patch.object(run, "delivery", return_value="PASS, delivered"):
            run.write_result(root, state, ["true", "bash tests/smoke.sh # once"])
        result = (root / "result.md").read_text()
        self.assertIn("true\nbash tests/smoke.sh (once, final check)", result)
        self.assertNotIn("bash tests/smoke.sh # once", result)


if __name__ == "__main__":
    unittest.main()
