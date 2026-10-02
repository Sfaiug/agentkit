"""A fixer disputes checked findings; the next review decides by handing them in again."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, hand_in, run, worker
from fixtures.hand_in import scripted

FINDING = ["finding", "api.py:1", "feature disabled", "task requires the feature",
           "--quote", "enabled = True"]
OTHER = ["finding", "api.py:2", "wrong answer", "breaks callers", "--quote", "answer = 0"]
WHY = "The feature is already enabled."
PROOF = "python3 -c " + shlex.quote(
    'import os, api; print("proof from " + os.environ.get("PROOF_ORIGIN", "loop")); assert api.enabled')


class DisputeHandIn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-dispute-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": "",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name, value in (
                (worker, "auth_ok", (True, "fixture")), (worker, "marked_pids", []),
                (worker, "kill_marked", True), (run, "marker_pids", []),
                (run.orch, "stop_scope", None), (run, "note_turn_meters", None),
                (run, "history_role_tokens", None), (run, "memory_cap_note", None),
                (run, "pickup_new_code", None), (run.history, "update_run", None)):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "api.py").write_text("enabled = False\nanswer = 1\nuntouched = True\n")
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", "Existing behaviour")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        self.directory = self.root / "run"
        self.directory.mkdir()
        self.plan = self.root / "plan.json"
        self.calls = self.root / "calls.jsonl"
        adapter = self.root / "adapter"
        body = f'''import json, os, pathlib, subprocess, sys
plan = pathlib.Path({str(self.plan)!r})
rows = json.loads(plan.read_text())
row = rows.pop(0)
plan.write_text(json.dumps(rows))
workspace = pathlib.Path(sys.argv[4])
for name, content in row.get("edits", {{}}).items():
    (workspace / name).write_text(content)
results = []
for args, expected in row.get("commands", []) + [(["done"], 0)]:
    result = subprocess.run([sys.executable, {str(REPO / "bin/ak")!r}, "hand-in", *args],
                            env={{**os.environ, "PROOF_ORIGIN": "fixer"}},
                            capture_output=True, text=True)
    results.append({{"args": args, "code": result.returncode, "error": result.stderr}})
out = pathlib.Path(sys.argv[6])
with pathlib.Path({str(self.calls)!r}).open("a") as fh:
    fh.write(json.dumps({{"prompt": pathlib.Path(sys.argv[5]).read_text(), "results": results,
                         "file": os.environ["AK_HAND_IN"]}}) + "\\n")
(out / "final.md").write_text("## Summary\\nHanded in; the summary carries no dispute evidence.")
(out / "session_id").write_text("fixture-session")
'''
        adapter.write_text(f"#!{sys.executable}\n{scripted(body)}")
        adapter.chmod(0o755)
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        state = {"run_id": self.root.name, "title": "Dispute fixture", "state": "running",
                 "base": "main", "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
                 "executor": "opus", "reviewer": "astra", "round_summaries": [],
                 "repo": str(self.wt), "worktree": str(self.wt), "findings": ""}
        self.logs = []
        self.lp = run.Loop(self.cfg, self.directory, state, {}, self.logs.append, self.wt,
                           "# Enable the feature and keep the answer correct", ["true"], "context", [])

    def rounds(self, evidence, review_commands=(), extra_disputes=()):
        plans = [
            {"edits": {"api.py": "enabled = True\nanswer = 0\nuntouched = True\n"}},
            {"commands": [(FINDING, 0), (OTHER, 0)]},
            {"edits": {"api.py": "enabled = True\nanswer = 1\nuntouched = True\n"}, "commands": [
                (["dispute", "api.py:2", WHY, "--run", "false"], 2),
                (["dispute", "api.py:1", WHY, *evidence], 0),
                (["dispute", "api.py:3", WHY, "--run", "touch unhanded-proof"], 2)]
                + [(args, 0) for args in extra_disputes]},
            {"commands": [(args, 0) for args in review_commands]}]
        self.plan.write_text(json.dumps(plans))
        self.lp.rnd = 0
        # An upheld finding needs no further executor turn in this fixture.
        self.lp.state["rounds"] = 2
        run.rounds(self.lp)
        self.assertEqual(run.git(self.wt, "status", "--porcelain"), "")
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 4, self.logs)
        for index, call in enumerate(calls):
            expected = [code for _, code in plans[index].get("commands", [])] + [0]
            self.assertEqual([row["code"] for row in call["results"]], expected, call["results"])
        self.assertIn("exit 0", calls[2]["results"][0]["error"])
        refused = calls[2]["results"][2]
        self.assertIn("api.py:1", refused["error"])
        self.assertIn("api.py:2", refused["error"])
        self.assertFalse((self.wt / "unhanded-proof").exists())
        self.assertIn("wrong answer", calls[2]["prompt"])
        self.assertIn("feature disabled", calls[2]["prompt"])
        self.assertIn("feature disabled", calls[3]["prompt"])
        self.assertIn(WHY, calls[3]["prompt"])
        self.assertNotIn("## Disputes", calls[1]["prompt"])
        self.assertEqual((self.wt / "api.py").read_text(), "enabled = True\nanswer = 1\nuntouched = True\n")
        run.write_result(self.directory, self.lp.state, ["true"], cfg=self.cfg)
        return calls, (self.directory / "result.md").read_text()

    def test_disputing_one_finding_and_fixing_another_delivers_the_loops_proof_and_dropped_dispute(self):
        calls, result = self.rounds(["--run", PROOF])
        self.assertEqual([r["finding_count"] for r in self.lp.state["round_summaries"]], [2, 0])
        self.assertEqual(self.lp.state["verdict"], "PASS")
        raw = hand_in.read(calls[2]["file"])
        self.assertIn("proof from fixer", raw.disputes[0]["evidence"]["output"])
        self.assertIn("\n  proof from loop", calls[3]["prompt"])
        self.assertNotIn("\n  proof from fixer", calls[3]["prompt"])
        disputes = result.split("## Disputes\n", 1)[1]
        for text in ("api.py:1", "feature disabled", WHY, "proof from loop", "[exit 0]"):
            self.assertIn(text, disputes)
        self.assertNotIn("wrong answer", disputes)

    def test_a_quote_dispute_is_checked_and_rendered_beside_the_finding(self):
        _, result = self.rounds(["--quote", "enabled = True"])
        self.assertIn("## Disputes", result)
        self.assertIn("Dispute: " + WHY, result)
        self.assertIn("Quote:\n  enabled = True", result)

    def test_handing_the_disputed_finding_in_again_upholds_it_and_is_weighed_normally(self):
        _, result = self.rounds(["--run", PROOF], [FINDING])
        self.assertEqual([r["finding_count"] for r in self.lp.state["round_summaries"]], [2, 1])
        self.assertEqual(self.lp.state["verdict"], "FAIL")
        self.assertNotIn("## Disputes", result)

    def test_rehanding_a_finding_cannot_bypass_the_loops_proof_weighing(self):
        command = 'if test "$PROOF_ORIGIN" = fixer; then exit 7; fi; echo "no defect in loop proof"'
        finding = [*FINDING[:4], "--run", command]
        _, result = self.rounds(["--run", PROOF], [finding])
        self.assertEqual(self.lp.state["verdict"], "PASS")
        self.assertIn("## Disputes", result)
        self.assertIn("no defect in loop proof", self.lp.state["notes"][0])

    def test_every_dispute_reaches_the_next_review_and_the_dropped_list(self):
        why = "The quoted assignment also proves it is enabled."
        calls, result = self.rounds(["--run", PROOF], extra_disputes=[
            ["dispute", "api.py:1", why, "--quote", "enabled = True"]])
        self.assertEqual(len(hand_in.read(calls[2]["file"]).disputes), 2)
        for text in (WHY, why, "proof from loop", "Quote:\n  enabled = True"):
            self.assertIn(text, calls[3]["prompt"])
            self.assertIn(text, result)

    def cli(self, file, *args):
        return subprocess.run([sys.executable, str(REPO / "bin/ak"), "hand-in", *args],
                              cwd=self.wt, env={**os.environ, hand_in.ENV: str(file)},
                              capture_output=True, text=True, timeout=30)

    def turn(self, role, out=None):
        file = Path(hand_in.start(out or self.directory, self.wt, role=role))
        header = json.loads(file.read_text())
        header["findings"] = [{"kind": "finding", "path": "api.py", "line": 1,
                               "what": "feature disabled", "why": "task requires it",
                               "evidence": {"quote": "enabled = False"}}]
        file.write_text(json.dumps(header) + "\n")
        return file

    def test_a_host_ended_fixer_keeps_its_disputes_and_handed_findings(self):
        self.lp.rnd = 2
        out = self.lp.dir("executor")
        out.mkdir(parents=True)
        file = self.turn("fixer", out)
        dispute = ["dispute", "api.py:1", "The disabled default is correct.", "--quote", "enabled = False"]
        result = self.cli(file, *dispute)
        self.assertEqual(result.returncode, 0, result.stderr)
        (out / "session_id").write_text("fixture-session")
        self.plan.write_text(json.dumps([{"commands": [(dispute, 0)]}]))
        run.execute(self.lp, "fixer", "Continue the fixes.", "executor")
        call = json.loads(self.calls.read_text())
        self.assertEqual([row["code"] for row in call["results"]], [0, 0], call["results"])
        submitted = hand_in.read(call["file"])
        self.assertTrue(submitted.done)
        self.assertEqual(len(submitted.disputes), 2)
        self.assertEqual(submitted.handed_findings, hand_in.read(file).handed_findings)

    def test_review_and_first_executor_turns_refuse_disputes_before_running_the_proof(self):
        for role in ("reviewer", "reviewer-pr", "reviewer-scratch", "executor", "executor-scratch"):
            with self.subTest(role=role):
                file = self.turn(role)
                before = file.read_bytes()
                result = self.cli(file, "dispute", "api.py:1", WHY, "--run", "touch wrong-role-proof")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("only for fixer", result.stderr)
                self.assertEqual(file.read_bytes(), before)
                self.assertFalse((self.wt / "wrong-role-proof").exists())

    def test_bad_quotes_and_missing_evidence_leave_no_dispute(self):
        for role in ("fixer", "fixer-scratch"):
            file = self.turn(role)
            for evidence, error in ((["--quote", "absent"], "quote"), ([], "evidence"),
                                    (["--run", " "], "evidence"), (["--run", "exit 7"], "exit 0")):
                with self.subTest(role=role, evidence=evidence):
                    before = file.read_bytes()
                    result = self.cli(file, "dispute", "api.py:1", WHY, *evidence)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(error, result.stderr)
                    self.assertEqual(file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
