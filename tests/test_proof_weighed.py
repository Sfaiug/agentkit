"""The loop weighs review records against the commit and base, outside the reviewer's copy."""

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


def finding(site, what, command=None, quote=None, kind="finding"):
    args = [kind, site, what, "breaks callers", "--run" if command else "--quote",
            command if command else quote]
    return args + (["--before", "base already has this defect"] if kind == "follow-up" else [])


class ProofWeighed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-proof-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "", "PYTHONPYCACHEPREFIX": "",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        for module, name, value in (
                (worker, "auth_ok", (True, "fixture")), (worker, "marked_pids", []),
                (worker, "kill_marked", True), (run, "marker_pids", []),
                (run.orch, "stop_scope", None), (run, "note_turn_meters", None),
                (run, "history_role_tokens", None), (run, "memory_cap_note", None),
                (run.history, "update_run", None)):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "api.py").write_text(
            'mode = "base"\nold_bug = True\nstable = True\nremoved = True\nborder = True\ntail = True\n')
        (self.wt / "legacy.py").write_text("old_bug = True\n")
        (self.wt / "keep.txt").write_text("keep\n")
        (self.wt / "same.py").write_text('value = "base"\n')
        (self.wt / ".gitignore").write_text("__pycache__/\n")
        (self.wt / "tests").mkdir()
        (self.wt / "tests/removed.py").write_text("assert True\n")
        self.commit("Existing behaviour")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        (self.wt / "api.py").write_text(
            'mode = "branch"\nold_bug = True\nstable = True\nborder = True\ntail = True\n')
        (self.wt / "tests/removed.py").unlink()
        (self.wt / "same.py").write_text('value = "head"\n')
        (self.wt / "tests/proof [1].py").write_text(
            'from pathlib import Path\nimport api\nprint("proof on", api.mode)\n'
            'assert not Path("tests/removed.py").exists()\nassert api.mode == "base"\n')
        self.commit("Introduce a defect and its check")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.directory = self.root / "run"
        self.directory.mkdir()
        self.plan = self.root / "plan.json"
        adapter = self.root / "adapter"
        body = f'''import json, pathlib, subprocess, sys
plan = pathlib.Path({str(self.plan)!r})
rows = json.loads(plan.read_text())
row = rows.pop(0) if len(rows) > 1 else rows[0]
plan.write_text(json.dumps(rows))
workspace = pathlib.Path(sys.argv[4])
for name, content in row.get("edits", {{}}).items():
    (workspace / name).write_text(content)
for args in row.get("commands", []) + [["done"]]:
    subprocess.run([sys.executable, {str(REPO / "bin/ak")!r}, "hand-in", *args], check=True)
out = pathlib.Path(sys.argv[6])
(out / "final.md").write_text("Handed in.")
(out / "session_id").write_text("fixture-session")
'''
        adapter.write_text(f"#!{sys.executable}\n{scripted(body)}")
        adapter.chmod(0o755)
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        state = {"run_id": "proof-fixture", "title": "Weigh evidence", "state": "running",
                 "base": "main", "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
                 "executor": "opus", "reviewer": "astra", "round_summaries": [],
                 "repo": str(self.wt), "worktree": str(self.wt)}
        self.logs = []
        self.lp = run.Loop(self.cfg, self.directory, state, {}, self.logs.append, self.wt,
                           "# Fixture", ["true"], "context", [])
        self.lp.rnd = 1
        self.lp.validation = run.commit_identity(self.wt)
        self.fails = "python3 -c " + shlex.quote('import api; print("proof on", api.mode); exit(7)')
        self.regression = "PYTHONPATH=. python3 'tests/proof [1].py'"

    def commit(self, message):
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", message)

    def review(self, *commands, edits=None):
        self.plan.write_text(json.dumps([{"commands": commands, "edits": edits or {}}]))
        verdict = run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]")
        self.assert_restored()
        return verdict

    def assert_restored(self):
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.head)
        self.assertEqual(run.git(self.wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(run.git(self.wt, "status", "--porcelain"), "")
        self.assertNotIn("probe_checkout", self.lp.state)

    def test_changed_lines_and_both_borders_of_a_removal_block_even_if_base_fails(self):
        commands = [finding(f"api.py:{line}", f"defect at {line}", self.fails)
                    for line in (1, 3, 4)]
        commands.append(finding("tests/proof [1].py:5", "defect on an added line", self.fails))
        self.assertEqual(self.review(*commands), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 4)
        self.assertIn("proof on branch", self.lp.findings)
        self.assertIn("proof on base", self.lp.findings)

    def test_an_unchanged_site_blocks_when_the_changed_test_passes_on_base(self):
        self.assertEqual(self.review(finding("legacy.py:1", "new regression", self.regression)), "FAIL")
        self.assertIn(self.head, self.lp.findings)
        self.assertIn(self.base, self.lp.findings)
        self.assertIn("proof on branch", self.lp.findings)
        self.assertIn("proof on base", self.lp.findings)
        self.assertIn("[exit 0]", self.lp.findings)

    def test_replays_do_not_share_bytecode_across_commits_or_findings(self):
        # Same-size sources and equal whole-second mtimes make stale bytecode look valid.
        python = 'import os; os.utime("same.py", (1700000000, 1700000000)); import same; '
        old = "python3 -c " + shlex.quote(python + 'print("saw", same.value); exit(9)')
        new = "python3 -c " + shlex.quote(
            python + 'print("saw", same.value); exit(7 if same.value == "head" else 0)')
        self.assertEqual(self.review(finding("legacy.py:1", "old defect", old),
                                     finding("keep.txt:1", "same-size regression", new)),
                         "FAIL", self.lp.findings)
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertIn("saw head", self.lp.findings)
        self.assertIn("saw base", self.lp.findings)
        self.assertIn("[exit 0]", run.findings_section(self.lp.findings))

    def test_replays_ignore_preexisting_bytecode_from_the_base(self):
        (self.wt / "same.py").write_text('value = "base"\n')
        python = 'import os; os.utime("same.py", (1700000000, 1700000000)); import same; '
        subprocess.run([sys.executable, "-c", python + 'assert same.value == "base"'],
                       cwd=self.wt, check=True)
        self.assertTrue(list((self.wt / "__pycache__").glob("same.*.pyc")))
        run.git(self.wt, "reset", "--hard", "HEAD")
        command = "if test -f reviewer-only; then exit 7; fi; python3 -c " + shlex.quote(
            python + 'print("saw", same.value); exit(7 if same.value == "head" else 0)')
        self.assertEqual(self.review(finding("keep.txt:1", "same-size regression", command),
                                     edits={"reviewer-only": "defect\n"}), "FAIL", self.lp.findings)
        self.assertEqual(self.lp.state["notes"], [])
        self.assertIn("saw head", self.lp.findings)
        self.assertIn("saw base", self.lp.findings)

    def test_old_failures_and_quotes_join_the_reviewers_followups_without_rerunning_them(self):
        own = "echo 'reviewer follow-up proof'; exit 9"
        with patch.object(worker, "limited", wraps=worker.limited) as limited:
            verdict = self.review(
                finding("api.py:2", "old failure in a changed file", self.fails),
                finding("legacy.py:1", "old failure in an untouched file", self.fails),
                finding("api.py:5", "old quoted defect", quote="tail = True"),
                finding("legacy.py:1", "reviewers own follow-up", own, kind="follow-up"))
        self.assertEqual(verdict, "PASS")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 0)
        self.assertEqual(len(self.lp.state["followups"]), 4)
        self.assertIn("proof on base", self.lp.state["followups"][0])
        self.assertFalse(any(call.args[0] == ["bash", "-c", own] for call in limited.call_args_list))

    def test_quotes_on_changed_lines_and_removal_borders_block(self):
        self.assertEqual(self.review(
            finding("api.py:1", "changed quote", quote='mode = "branch"'),
            finding("api.py:4", "removal quote", quote="border = True")), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 2)

    def test_a_proof_that_passes_outside_the_reviewers_edit_is_only_a_note(self):
        command = ("if test -f reviewer-only; then echo 'reviewer output'; exit 7; fi; "
                   "echo 'loop proof passes'")
        self.assertEqual(self.review(finding("api.py:1", "unproven defect", command),
                                     edits={"reviewer-only": "defect\n"}), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), 1)
        self.assertIn("loop proof passes", self.lp.state["notes"][0])
        self.assertNotIn("\nreviewer output", self.lp.state["notes"][0])
        self.assertIn(self.base, self.lp.state["notes"][0])
        run.write_result(self.directory, self.lp.state, ["true"], cfg=self.cfg)
        for report in ((self.directory / "result.md").read_text(), run.pr_body(self.lp.state)):
            self.assertIn("## Notes", report)
            self.assertIn("unproven defect", report)

    def test_a_proof_that_does_not_finish_on_the_commit_is_only_a_note(self):
        self.lp.done_when_limit = 0.05
        command = ("if test -f reviewer-only; then exit 7; fi; "
                   "echo 'unfinished proof'; sleep 10")
        self.assertEqual(self.review(finding("api.py:1", "unfinished defect", command),
                                     edits={"reviewer-only": "defect\n"}), "PASS")
        self.assertEqual(len(self.lp.state["notes"]), 1)
        self.assertIn("did not finish", self.lp.state["notes"][0])

    def test_a_signal_ended_proof_is_only_a_note(self):
        command = "if test -f reviewer-only; then exit 7; fi; kill -TERM $$"
        self.assertEqual(self.review(finding("legacy.py:1", "interrupted defect", command),
                                     edits={"reviewer-only": "defect\n"}), "PASS")
        self.assertEqual(len(self.lp.state["notes"]), 1)

    def test_clean_proof_replays_do_not_hide_a_checkout_changed_by_the_suite(self):
        def dirty_suite(lp):
            (lp.wt / "api.py").write_text('mode = "suite edit"\n')

        with patch.object(run, "join_suite", side_effect=dirty_suite):
            self.assertEqual(self.review(finding("api.py:1", "proven defect", self.fails)), "FAIL")
        self.assertEqual(self.lp.state["review"]["overridden"], "the checkout changed after verification")
        self.assertIn("proof on branch", self.lp.findings)
        self.assertNotIn("proof on suite edit", self.lp.findings)

    def test_scratch_has_no_base_and_every_proven_finding_blocks(self):
        self.lp.scratch = self.lp.state["scratch"] = True
        self.lp.state["base_sha"] = ""
        self.assertEqual(self.review(
            finding("legacy.py:1", "proven scratch defect", self.fails),
            finding("legacy.py:1", "quoted scratch defect", quote="old_bug = True")), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 2)
        self.assertNotIn("proof on base", self.lp.findings)

    def test_proof_edits_are_discarded_between_runs_and_afterwards(self):
        command = ("cat keep.txt; echo dirty > keep.txt; echo new > proof-output; "
                   "python3 -c " + shlex.quote('import api; print("proof on", api.mode); exit(7)'))
        self.assertEqual(self.review(finding("api.py:1", "proof makes files", command)), "FAIL")
        self.assertEqual((self.wt / "keep.txt").read_text(), "keep\n")
        self.assertFalse((self.wt / "proof-output").exists())
        self.assertGreaterEqual(self.lp.findings.count("\n  keep\n"), 2)

    def test_interrupted_probes_restore_the_branch_before_propagating(self):
        original = worker.limited

        def interrupt(cmd, *args, **kwargs):
            if cmd == ["bash", "-c", self.fails]:
                (self.wt / "keep.txt").write_text("dirty\n")
                (self.wt / "proof-output").write_text("new\n")
                raise run.Stopped("fixture stop")
            return original(cmd, *args, **kwargs)

        with patch.object(worker, "limited", side_effect=interrupt):
            with self.assertRaisesRegex(run.Stopped, "fixture stop"):
                self.review(finding("api.py:1", "interrupted proof", self.fails))
        self.assert_restored()

    def rounds(self, plans):
        self.plan.write_text(json.dumps(plans))
        self.lp.rnd = 0
        calls = []

        def execute(lp, role, body, *_args, **_kw):
            lp.round_dir.mkdir(parents=True, exist_ok=True)
            calls.append((role, body))
            return "## Summary\nFixture"

        with patch.object(run, "execute", side_effect=execute), patch.object(run, "pickup_new_code"):
            run.rounds(self.lp)
        self.assert_restored()
        return calls

    def test_only_blocking_findings_and_the_loops_two_outputs_reach_the_fixer(self):
        command = "if test -f reviewer-only; then exit 7; fi; echo 'passing note proof'"
        calls = self.rounds([
            {"commands": [finding("legacy.py:1", "blocking regression", self.regression),
                          finding("api.py:2", "old follow-up", self.fails),
                          finding("api.py:1", "unproven note", command)],
             "edits": {"reviewer-only": "defect\n"}},
            {}])
        self.assertEqual([role for role, _ in calls], ["executor", "fixer"])
        fixer = calls[1][1]
        self.assertIn("blocking regression", fixer)
        self.assertIn("proof on branch", fixer)
        self.assertIn("proof on base", fixer)
        self.assertNotIn("old follow-up", fixer)
        self.assertNotIn("unproven note", fixer)
        self.assertEqual([r["finding_count"] for r in self.lp.state["round_summaries"]], [1, 0])

    def test_notes_do_not_start_a_fix_round(self):
        command = "if test -f reviewer-only; then exit 7; fi; echo 'passing note proof'"
        calls = self.rounds([{"commands": [finding("api.py:1", "note only", command)],
                              "edits": {"reviewer-only": "defect\n"}}])
        self.assertEqual([role for role, _ in calls], ["executor"])
        self.assertEqual(self.lp.state["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
