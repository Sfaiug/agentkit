"""Checked review records, exercised through the CLI and a real worker.call with a fake adapter."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker


class HandIn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-hand-in-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "checkout"
        self.workspace.mkdir()
        (self.workspace / "api.py").write_text("first line\nwrong answer\n")
        self.file = self.root / "hand-in.jsonl"
        self.file.write_text(json.dumps({"kind": "turn", "workspace": str(self.workspace)}) + "\n")
        self.env = {**os.environ, "HOME": str(self.root), "AK_HAND_IN": str(self.file),
                    "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
                    "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}

    def cli(self, *args, **env):
        return subprocess.run([sys.executable, str(REPO / "bin/ak"), "hand-in", *args],
                              cwd=self.workspace, env={**self.env, **env},
                              capture_output=True, text=True, timeout=30)

    def rows(self):
        return [json.loads(line) for line in self.file.read_text().splitlines()]

    def test_a_checked_finding_is_appended_and_done_closes_the_review(self):
        result = self.cli("finding", "api.py:2", "wrong result", "breaks callers",
                          "--quote", "wrong answer")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli("done")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row["kind"] for row in self.rows()], ["turn", "finding", "done"])
        self.assertEqual(self.rows()[1]["path"], "api.py")
        self.assertEqual(self.rows()[1]["line"], 2)

    def test_malformed_calls_leave_no_record_and_explain_the_fix_in_one_line(self):
        cases = [
            (("finding", "missing.py:1", "what", "why", "--quote", "line"), "checkout"),
            (("finding", "api.py:0", "what", "why", "--quote", "first line"), "line"),
            (("finding", "api.py:3", "what", "why", "--quote", "first line"), "line"),
            (("finding", "api.py:two", "what", "why", "--quote", "first line"), "path:line"),
            (("finding", "api.py:1", "what", "why", "--quote", "absent"), "quote"),
            (("finding", "api.py:1", "what", "why"), "evidence"),
            (("finding", "api.py:1", "what", "why", "--run", " "), "evidence"),
            (("finding", "api.py:1", "", "why", "--quote", "first line"), "what"),
            (("follow-up", "api.py:1", "what", "why", "--quote", "first line"), "--before"),
            (("done", "extra"), "done"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                before = self.file.read_bytes()
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                self.assertEqual(self.file.read_bytes(), before)

    def test_outside_a_turn_is_refused(self):
        for file in ("", str(self.root / "absent.jsonl")):
            result = self.cli("done", AK_HAND_IN=file)
            self.assertEqual(result.returncode, 2)
            self.assertIn("review turn", result.stderr)

    def test_evidence_runs_in_the_checkout_and_keeps_its_output_and_exit_status(self):
        result = self.cli("finding", "api.py:2", "wrong result", "breaks callers",
                          "--run", "cat api.py; exit 7")
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.rows()[1]["evidence"]
        self.assertEqual(evidence["returncode"], 7)
        self.assertIn("wrong answer", evidence["output"])

    def test_a_followup_requires_and_keeps_its_preexisting_evidence(self):
        result = self.cli("follow-up", "api.py:2", "wrong result", "breaks callers",
                          "--quote", "wrong answer", "--before", "base abc123 has the same defect")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()[1]["kind"], "follow-up")
        self.assertIn("abc123", self.rows()[1]["before"])

    def test_a_path_or_symlink_outside_the_checkout_is_refused(self):
        (self.root / "outside.py").write_text("outside\n")
        (self.workspace / "link.py").symlink_to(self.root / "outside.py")
        for path in ("../outside.py", "link.py"):
            result = self.cli("finding", f"{path}:1", "what", "why", "--quote", "outside")
            self.assertEqual(result.returncode, 2)
            self.assertIn("checkout", result.stderr)

    def test_done_refuses_later_records(self):
        self.assertEqual(self.cli("done").returncode, 0)
        before = self.file.read_bytes()
        result = self.cli("finding", "api.py:1", "what", "why", "--quote", "first line")
        self.assertEqual(result.returncode, 2)
        self.assertIn("done", result.stderr)
        self.assertEqual(self.file.read_bytes(), before)

    def review(self, *plan, ok=True, once_ok=True):
        """The adapter invokes bin/ak, so these turns cross the real record-file boundary."""
        directory = self.root / "run"
        directory.mkdir()
        responses = self.root / "plan.json"
        responses.write_text(json.dumps(list(plan)))
        adapter = self.root / "adapter"
        adapter.write_text(f'''#!{sys.executable}
import json, os, pathlib, subprocess, sys
plan = pathlib.Path({str(responses)!r})
rows = json.loads(plan.read_text())
row = rows.pop(0)
plan.write_text(json.dumps(rows))
out = pathlib.Path(sys.argv[6])
with pathlib.Path({str(self.root / "calls.jsonl")!r}).open("a") as fh:
    fh.write(json.dumps({{"session": sys.argv[7:], "prompt": pathlib.Path(sys.argv[5]).read_text(),
                         "records": os.environ["AK_HAND_IN"]}}) + "\\n")
for args in row.get("commands", []):
    subprocess.run([sys.executable, {str(REPO / "bin/ak")!r}, "hand-in", *args], check=True)
(out / "final.md").write_text(row.get("text", "Handed in."))
(out / "session_id").write_text("fixture-session")
(out / "events.jsonl").write_text('{{"type":"complete"}}\\n')
sys.exit(row.get("code", 0))
''')
        adapter.chmod(0o755)
        logs = []
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.env))
            for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
                stack.enter_context(patch.object(config, key, self.root / key.lower()))
            config.ensure_dirs()
            cfg = config.load()
            for module, name, value in ((config, "adapter", adapter), (worker, "auth_ok", (True, "fixture")),
                                        (worker, "marked_pids", []), (run, "collect_usage", {}),
                                        (run, "ready_order", ["spark"]), (run, "note_turn_meters", None),
                                        (run, "history_role_tokens", None), (run, "memory_cap_note", None),
                                        (run.usage, "account", (None, True)), (run.history, "update_run", None)):
                stack.enter_context(patch.object(module, name, return_value=value))
            state = {"run_id": directory.name, "title": "Hand-in fixture", "state": "running",
                     "base": "origin/main", "base_sha": "abc123", "branch": "ak/fix-api",
                     "rounds": 3, "round_summaries": [], "executor": "opus", "reviewer": "astra",
                     "scratch": True, "repo": str(self.workspace), "worktree": str(self.workspace)}
            lp = run.Loop(cfg, directory, state, {}, logs.append, self.workspace,
                          "# Fixture", ["true"], "", ["spark"])
            lp.rnd = 1
            lp.once_ok = once_ok
            lp.save()
            verdict = run.review(lp, "## Summary\nFixture", ok, "$ true\n[exit 0]")
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        return verdict, lp, calls, logs

    def test_records_override_a_contradictory_pass_in_the_harness_text(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        verdict, lp, calls, _ = self.review({"commands": [finding, ["done"]], "text": "VERDICT: PASS"})
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertIn("wrong result", run.saved_findings(lp.run_dir, lp.state))
        self.assertIn("wrong answer", run.saved_findings(lp.run_dir, lp.state))
        self.assertTrue(lp.state["findings_file"].endswith("review.md"))
        self.assertEqual(len(calls), 1)

    def test_done_without_findings_passes_even_when_the_harness_text_says_fail(self):
        verdict, lp, _, _ = self.review({"commands": [["done"]], "text": "VERDICT: FAIL"})
        self.assertEqual(verdict, "PASS")
        self.assertEqual(lp.state["round_summaries"][0]["finding_count"], 0)

    def test_a_missing_done_is_reasked_in_the_same_session_and_keeps_earlier_findings(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        verdict, lp, calls, _ = self.review({"commands": [finding], "text": "VERDICT: PASS"},
                                           {"commands": [["done"]]})
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertEqual(calls[1]["session"], ["fixture-session"])
        self.assertNotEqual(calls[0]["records"], calls[1]["records"])
        self.assertIn("ak hand-in done", calls[1]["prompt"])

    def test_two_missing_done_turns_fall_back_without_recording_a_round_for_them(self):
        verdict, lp, calls, _ = self.review({"text": "VERDICT: PASS"}, {"text": "VERDICT: FAIL"},
                                           {"commands": [["done"]]})
        self.assertEqual(verdict, "PASS")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1]["session"], ["fixture-session"])
        self.assertEqual(calls[2]["session"], [])
        self.assertEqual(lp.reviewer, "spark")
        self.assertEqual(len(lp.state["round_summaries"]), 1)

    def test_a_followup_does_not_block_and_keeps_the_evidence_for_its_fix_run(self):
        followup = ["follow-up", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer",
                    "--before", "base abc123 has the same defect"]
        verdict, lp, _, _ = self.review({"commands": [followup, ["done"]]})
        self.assertEqual(verdict, "PASS")
        self.assertEqual(len(lp.state["followups"]), 1)
        self.assertIn("api.py:2", lp.state["followups"][0])
        self.assertIn("wrong answer", lp.state["followups"][0])
        self.assertIn("abc123", lp.state["followups"][0])
        self.assertIn(lp.state["followups"][0].replace("\n", "\n  "), run.pr_body(lp.state))

    def test_a_passing_hand_in_still_cannot_override_failing_checks(self):
        verdict, lp, _, _ = self.review({"commands": [["done"]]}, ok=False)
        self.assertEqual(verdict, "FAIL")
        self.assertIn("done-when is failing", lp.state["review"]["overridden"])

    def test_recorded_failure_words_are_never_harness_diagnostics(self):
        self.cli("finding", "api.py:1", "API Error: quota exceeded", "capacity refusal",
                 "--quote", "first line")
        for code in (False, True):
            said = run.harness_said(self.root, "", "codex", failures_only=code)
            self.assertNotIn("API Error", said)
            self.assertNotIn("quota exceeded", said)

    def test_all_reviewer_prompts_ask_only_for_hand_in(self):
        for role, text in worker.PREAMBLES.items():
            if role.startswith("reviewer"):
                self.assertIn("ak hand-in finding", text)
                self.assertIn("ak hand-in follow-up", text)
                self.assertIn("ak hand-in done", text)
                for old in ("VERDICT:", "## Findings", "## Follow-ups"):
                    self.assertNotIn(old, text)


if __name__ == "__main__":
    unittest.main()
