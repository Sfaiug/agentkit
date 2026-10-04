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
from agentkit import config, hand_in, run, worker


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
            self.assertIn("worker turn", result.stderr)

    def test_evidence_runs_in_the_checkout_and_keeps_its_output_and_exit_status(self):
        result = self.cli("finding", "api.py:2", "wrong result", "breaks callers",
                          "--run", "cat api.py; exit 7")
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.rows()[1]["evidence"]
        self.assertEqual(evidence["returncode"], 7)
        self.assertIn("wrong answer", evidence["output"])

    def test_a_finding_with_a_zero_exit_proof_is_refused_during_the_turn(self):
        before = self.file.read_bytes()
        result = self.cli("finding", "api.py:2", "wrong result", "breaks callers",
                          "--run", "echo wrong answer")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("fail while the defect exists", result.stderr)
        self.assertIn("--quote", result.stderr)
        self.assertEqual(self.file.read_bytes(), before)

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

    def test_executor_and_fixer_closings_require_a_why_and_refuse_later_records(self):
        for role in ("executor", "fixer", "executor-scratch", "fixer-scratch"):
            for kind in ("done", "blocked", "not-needed"):
                with self.subTest(role=role, kind=kind):
                    hand_in.start(self.root, self.workspace, role=role)
                    if kind != "done":
                        for args in ((kind,), (kind, " "), (kind, "why", "extra")):
                            before = self.file.read_bytes()
                            result = self.cli(*args)
                            self.assertEqual(result.returncode, 2, result.stderr)
                            self.assertIn("why", result.stderr)
                            self.assertEqual(self.file.read_bytes(), before)
                    args = [kind] + (["the task is already fixed"] if kind != "done" else [])
                    result = self.cli(*args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(hand_in.read(self.file).closing, self.rows()[-1])
                    if kind != "done":
                        self.assertEqual(self.rows()[-1]["why"], "the task is already fixed")
                    before = self.file.read_bytes()
                    for args in (("done",), ("blocked", "why"), ("not-needed", "why")):
                        result = self.cli(*args)
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn("closed", result.stderr)
                        self.assertEqual(self.file.read_bytes(), before)

    def test_records_are_refused_in_the_wrong_role_before_running_evidence(self):
        for role in worker.PREAMBLES:
            hand_in.start(self.root, self.workspace, role=role)
            commands = ([['blocked', 'why'], ['not-needed', 'why']] if role.startswith("reviewer") else
                        [['finding', 'api.py:1', 'what', 'why', '--run', 'touch proof-ran; exit 1'],
                         ['follow-up', 'api.py:1', 'what', 'why', '--run', 'touch proof-ran; exit 1',
                          '--before', 'base abc123']])
            for args in commands:
                with self.subTest(role=role, kind=args[0]):
                    before = self.file.read_bytes()
                    result = self.cli(*args)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("only for", result.stderr)
                    self.assertEqual(self.file.read_bytes(), before)
                    self.assertFalse((self.workspace / "proof-ran").exists())

    def test_all_worker_closings_establish_an_answer_without_hiding_terminal_errors(self):
        for role in worker.PREAMBLES:
            kinds = ("done",) if role.startswith("reviewer") else ("done", "blocked", "not-needed")
            for kind in kinds:
                with self.subTest(role=role, kind=kind):
                    hand_in.start(self.root, self.workspace, role=role)
                    result = self.cli(kind, *(["why"] if kind != "done" else []))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    text = "Handed in the rate limit parser result."
                    for harness in ("claude", "grokbuild", "muse"):
                        event = {"type": run.watch.terminal(harness), "result": text}
                        (self.root / "events.jsonl").write_text(json.dumps(event) + "\n")
                        for failures_only in (False, True):
                            self.assertEqual(run.harness_said(self.root, text, harness,
                                                              failures_only=failures_only), "")
                        event.update(is_error=True, error="rate limit")
                        (self.root / "events.jsonl").write_text(json.dumps(event) + "\n")
                        self.assertIn("rate limit", run.harness_said(self.root, text, harness,
                                                                    failures_only=True))

    def review(self, *plan, ok=True, reviewer="astra", prior=(), prior_suffix="", overrides=()):
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
(out / "events.jsonl").write_text("".join(json.dumps(event) + "\\n"
                                        for event in row.get("events", [{{"type":"complete"}}])))
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
                                        (run, "transient_wait", None), (run.update, "swap_end", None),
                                        (run.usage, "account", (None, True)), (run.history, "update_run", None)):
                stack.enter_context(patch.object(module, name, return_value=value))
            for override in overrides:
                stack.enter_context(override)
            state = {"run_id": directory.name, "title": "Hand-in fixture", "state": "running",
                     "base": "origin/main", "base_sha": "abc123", "branch": "ak/fix-api",
                     "rounds": 3, "round_summaries": [], "executor": "opus", "reviewer": reviewer,
                     "scratch": True, "repo": str(self.workspace), "worktree": str(self.workspace)}
            lp = run.Loop(cfg, directory, state, {}, logs.append, self.workspace,
                          "# Fixture", ["true"], "", ["spark"])
            lp.rnd = 1
            if prior:
                previous = directory / "round-1/reviewer"
                previous.mkdir(parents=True)
                if prior_suffix:
                    (previous / "final.md").write_text("API Error: 529 Overloaded")
                    previous = previous.with_name(previous.name + prior_suffix)
                    previous.mkdir()
                file = hand_in.start(previous, self.workspace)
                for args in prior:
                    result = self.cli(*args, AK_HAND_IN=file)
                    self.assertEqual(result.returncode, 0, result.stderr)
                (previous / "session_id").write_text("fixture-session")
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

    def test_a_followup_without_a_base_does_not_block_and_records_why_it_was_dropped(self):
        followup = ["follow-up", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer",
                    "--before", "base abc123 has the same defect"]
        verdict, lp, _, _ = self.review({"commands": [followup, ["done"]]})
        self.assertEqual(verdict, "PASS")
        self.assertEqual(lp.state["followups"], [])
        self.assertEqual(len(lp.state["notes"]), 1)
        self.assertIn("api.py:2", lp.state["notes"][0])
        self.assertIn("wrong answer", lp.state["notes"][0])
        self.assertIn("abc123", lp.state["notes"][0])
        self.assertIn("Dropped follow-up: no base commit", lp.state["notes"][0])
        self.assertIn(lp.state["notes"][0].replace("\n", "\n  "), run.pr_body(lp.state))

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

    def test_plain_closings_are_answers_when_records_were_handed_in(self):
        self.cli("finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer")
        self.cli("done")
        text = "Handed in one finding about the rate limit parsing at api.py:500, then ran ak hand-in done."
        for harness in ("claude", "grokbuild", "muse"):
            with self.subTest(harness=harness):
                terminal = run.watch.terminal(harness)
                for closing in (text, "## Summary\n" + text):
                    (self.root / "events.jsonl").write_text(json.dumps({"type": terminal, "result": closing}) + "\n")
                    for failures_only in (False, True):
                        said = run.harness_said(self.root, closing, harness, failures_only=failures_only)
                        self.assertEqual(run.harness_plugin(harness).failure(said), (None, None), said)
                    # A real terminal error still speaks, even after the worker handed in records.
                    (self.root / "events.jsonl").write_text(json.dumps({
                        "type": terminal, "is_error": True, "error": "rate limit"}) + "\n")
                    said = run.harness_said(self.root, closing, harness, failures_only=True)
                    self.assertIn("rate limit", said)

    def test_a_plain_closing_keeps_the_finding_without_parking_its_provider(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        text = "Handed in one finding about the rate limit parsing, then ran ak hand-in done."
        with patch.object(run.usage, "mark_exhausted", return_value=1) as parked, \
                patch.object(run.usage, "replenish", return_value=(False, 0)):
            verdict, lp, calls, _ = self.review(
                {"commands": [finding, ["done"]], "text": text,
                 "events": [{"type": "result", "result": text}]},
                {"commands": [["done"]]}, reviewer="opus")
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertEqual(len(calls), 1)
        parked.assert_not_called()

    def test_an_empty_channel_ignores_successful_terminal_prose_and_keeps_explicit_errors(self):
        text = "No blocking findings; the usage limit parsing looks correct."
        for harness in ("claude", "grokbuild", "muse"):
            with self.subTest(harness=harness):
                terminal = run.watch.terminal(harness)
                event = {"type": terminal, "result": text}
                (self.root / "events.jsonl").write_text(json.dumps(event) + "\n")
                self.assertEqual(run.harness_said(self.root, text, harness, failures_only=True), "")
                event.update(is_error=True, error="usage limit reached")
                (self.root / "events.jsonl").write_text(json.dumps(event) + "\n")
                self.assertIn("usage limit reached", run.harness_said(
                    self.root, text, harness, failures_only=True))

    def test_no_records_and_no_done_reasks_the_same_reviewer_without_parking(self):
        text = "No blocking findings; the usage limit parsing looks correct."
        with patch.object(run.usage, "mark_exhausted", return_value=1) as parked, \
                patch.object(run.usage, "replenish", return_value=(False, 0)):
            verdict, lp, calls, logs = self.review(
                {"text": text, "events": [{"type": "result", "subtype": "success", "result": text}]},
                {"commands": [["done"]]}, reviewer="opus")
        self.assertEqual(verdict, "PASS")
        self.assertEqual(lp.reviewer, "opus")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["session"], ["fixture-session"])
        self.assertTrue(any("asking once more" in line for line in logs), logs)
        parked.assert_not_called()

    def test_same_session_retries_keep_findings_and_followups(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        followup = ["follow-up", "api.py:1", "old defect", "breaks callers", "--quote", "first line",
                    "--before", "base abc123"]
        for reason in ("transient", "account", "refill", "swap", "signal", "foreground"):
            with self.subTest(reason=reason):
                case = self.root / reason
                case.mkdir()
                original = self.root
                self.root = case
                try:
                    code, text, overrides = 1, "API Error: 529 Overloaded", []
                    if reason in ("account", "refill"):
                        text = "Usage limit reached"
                        overrides.append(patch.object(run.usage, "mark_exhausted", return_value=1))
                        if reason == "account":
                            overrides.append(patch.object(run.usage, "account", side_effect=[
                                ("default", True), ("second", True), ("second", True)]))
                        else:
                            overrides.append(patch.object(run.usage, "replenish", return_value=(True, 1)))
                    elif reason == "swap":
                        overrides.append(patch.object(run.update, "swap_end", side_effect=[1, 0]))
                    elif reason == "signal":
                        code, text = -15, ""
                    elif reason == "foreground":
                        code, text = 0, "Handed in."
                        overrides.append(patch.object(run, "turn_unfinished", side_effect=[True, False]))
                    verdict, lp, calls, _ = self.review(
                        {"commands": [finding, followup], "text": text, "code": code},
                        {"commands": [["done"]]}, overrides=overrides)
                    self.assertEqual(verdict, "FAIL")
                    self.assertEqual(lp.state["round_summaries"][0]["finding_count"], 1)
                    self.assertEqual(calls[1]["session"], ["fixture-session"])
                    submitted = hand_in.read(calls[1]["records"])
                    self.assertEqual(len(submitted.followups), 1)
                finally:
                    self.root = original

    def test_a_host_ended_resume_keeps_the_records_of_its_session(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        for suffix in ("", "-retry2", "-retry2-retry-foreground"):
            with self.subTest(suffix=suffix):
                case = self.root / (suffix or "initial")
                case.mkdir()
                original = self.root
                self.root = case
                try:
                    verdict, lp, calls, _ = self.review({"commands": [["done"]]}, prior=[finding],
                                                        prior_suffix=suffix)
                    self.assertEqual(verdict, "FAIL")
                    self.assertEqual(lp.state["round_summaries"][0]["finding_count"], 1)
                    self.assertEqual(calls[0]["session"], ["fixture-session"])
                finally:
                    self.root = original

    def test_a_plain_closing_without_done_is_reasked_without_losing_records(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        text = "Handed in one finding about the rate limit parsing."
        verdict, _, calls, logs = self.review(
            {"commands": [finding], "text": text, "events": [{"type": "result", "result": text}]},
            {"commands": [["done"]]}, reviewer="opus")
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("asking once more" in line for line in logs), logs)

    def test_an_abandoned_resume_starts_with_no_records(self):
        finding = ["finding", "api.py:2", "wrong result", "breaks callers", "--quote", "wrong answer"]
        verdict, _, calls, logs = self.review({"text": "", "code": 1, "events": []},
                                            {"commands": [["done"]]}, prior=[finding])
        self.assertEqual(verdict, "PASS")
        self.assertEqual(calls[1]["session"], [])
        self.assertTrue(any("fresh conversation" in line for line in logs), logs)

    def test_run_evidence_and_published_bodies_are_bounded(self):
        command = "for ((i=0; i<3000; i++)); do printf 'evidence line %04d: wrong answer repeated\\n' \"$i\"; done; exit 7"
        result = self.cli("follow-up", "api.py:2", "wrong result", "breaks callers", "--run", command,
                          "--before", "base abc123")
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = self.rows()[1]["evidence"]
        self.assertLess(len(evidence["output"]), 10000)
        self.assertIn("truncated", evidence["output"])
        self.assertIn("0000", evidence["output"])
        self.assertIn("2999", evidence["output"])
        self.assertEqual(evidence["returncode"], 7)
        item = hand_in.item_text(self.rows()[1])
        state = {"round_summaries": [{"summary": "## Summary\nFixed the API"}], "verdict": "PASS",
                 "rounds": 1, "executor": "opus", "reviewer": "astra", "run_id": "fixture", "base": "main",
                 "followups": [item] * 30, "head_sha": "abc123"}
        self.assertLess(len(run.pr_body(state)), 65536)
        self.assertIn("truncated", run.pr_body(state))
        lp = run.Loop({}, self.root, state, {}, lambda *_: None, self.workspace, "", [], "", [])
        lp.findings = hand_in.Review([self.rows()[1]] * 30 + [{"kind": "done"}]).text
        with patch.object(run, "gh_json", return_value=({"headRefOid": "abc123", "state": "OPEN"}, "")), \
                patch.object(run, "gh", return_value=(0, "")), patch.object(lp, "write"):
            self.assertTrue(run.post_review(lp, "https://github.com/acme/api/pull/1", "PASS"))
        self.assertLess(len((self.root / "review.md").read_text()), 65536)
        self.assertIn("truncated", (self.root / "review.md").read_text())
        # Older text summaries and multibyte evidence must fit the same publication bound.
        state["round_summaries"][0]["summary"] = "## Summary\n" + "\U0001f600" * 70000
        self.assertLess(len(run.pr_body(state).encode("utf-8")), 65536)

    def test_all_reviewer_prompts_keep_hand_in_syntax_and_checked_refusals(self):
        for role, text in worker.PREAMBLES.items():
            if role.startswith("reviewer"):
                judgement = "\n".join(line for line in text.splitlines()
                                      if line.startswith("[worker judgement]"))
                for command in ("finding", "follow-up", "done"):
                    self.assertIn("ak hand-in " + command, judgement, role)
                self.assertIn("[checked by ak: tests/test_hand_in.py] ak refuses malformed "
                              "or evidence-free findings", text)
                for old in ("VERDICT:", "## Findings", "## Follow-ups"):
                    self.assertNotIn(old, text)

    def test_smokes_shared_fake_reviewer_completes_the_record_channel(self):
        source = (REPO / "tests/smoke.sh").read_text()
        factory = source[source.index("fakeadapter()"):source.index('cat >"$WORK/retry-task.md"')]
        adapters, out = self.root / "adapters", self.root / "out"
        adapters.mkdir()
        out.mkdir()
        made = subprocess.run(["bash", "-c", factory + '\nfakeadapter "$1" claude pass\n',
                               "fixture", str(adapters)], env={**self.env, "REPO": str(REPO)},
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(made.returncode, 0, made.stderr)
        file = hand_in.start(out, self.workspace)
        result = subprocess.run([str(adapters / "claude.sh"), "run", "fixture", "low", str(self.workspace),
                                 str(out / "prompt.md"), str(out)], cwd=self.workspace,
                                env={**self.env, "AK_HAND_IN": file},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(hand_in.read(file).verdict, "PASS")
        self.assertNotIn("VERDICT:", (out / "final.md").read_text())


if __name__ == "__main__":
    unittest.main()
