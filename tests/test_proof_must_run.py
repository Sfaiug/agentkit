"""A proof that could not start establishes no defect on either commit."""

import shlex
import sys
import unittest
from unittest.mock import patch

import test_proof_weighed as proof
from agentkit import hand_in, run, worker


class ProofMustRun(unittest.TestCase):
    setUp = proof.ProofWeighed.setUp
    commit = proof.ProofWeighed.commit
    review = proof.ProofWeighed.review
    rounds = proof.ProofWeighed.rounds
    assert_restored = proof.ProofWeighed.assert_restored

    def test_missing_command_is_a_note_even_on_a_changed_line(self):
        self.assertEqual(self.review(proof.finding("api.py:1", "cannot start", "./absent")), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("[exit 127]", self.lp.state["notes"][0])

    def test_unexecutable_file_is_a_note(self):
        self.assertEqual(self.review(proof.finding("api.py:1", "cannot execute", "./keep.txt")), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("[exit 126]", self.lp.state["notes"][0])

    def test_launch_exit_codes_are_notes_even_without_diagnostics(self):
        self.assertEqual(self.review(*(proof.finding("api.py:1", "reserved exit", f"exit {code}")
                                       for code in (126, 127))), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), 2)

    def test_a_missing_script_blocks_when_the_interpreter_exits_two(self):
        self.assertEqual(self.review(proof.finding(
            "api.py:1", "missing script", "python3 absent.py")), "FAIL")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(self.lp.state["notes"], [])
        self.assertIn("[exit 2]", self.lp.findings)
        self.assertIn("can't open file", self.lp.findings)

    def test_missing_file_diagnostics_still_fail_on_commit_base_and_followups(self):
        diagnostics = (
            ("sh", 2, "sh: 0: cannot open probe.sh: No such file"),
            ("perl", 2, 'Can\'t open perl script "probe.pl": No such file or directory'),
            ("head", 1, "head: cannot open 'absent' for reading: No such file or directory"))
        for name, code, diagnostic in diagnostics:
            with self.subTest(program=name):
                # Each diagnostic represents an independent first review.
                self.lp.state["review_records"] = []
                self.lp.state["round_summaries"] = []
                # Keep diagnostic text independent of installed interpreters and locale.
                program = self.root / name
                program.write_text(f"#!{sys.executable}\nimport sys\n"
                                   f"print({diagnostic!r}, file=sys.stderr)\nsys.exit({code})\n")
                program.chmod(0o755)
                command = shlex.quote(str(program)) + " probe"
                base_only = "if grep -q branch api.py; then exit 7; fi; " + command
                self.assertEqual(self.review(
                    proof.finding("api.py:1", "missing changed-line proof", command),
                    proof.finding("legacy.py:1", "missing base proof", base_only),
                    proof.finding("api.py:2", "missing follow-up proof", command,
                                  kind="follow-up", before=self.base)), "FAIL")
                self.assertEqual(self.lp.state["followups"], [])
                self.assertEqual(self.lp.state["notes"], [])
                rows = self.lp.state["review_records"]
                self.assertEqual([row["kind"] for row in rows], ["finding", "follow-up", "follow-up", "done"])
                self.assertEqual(rows[0]["evidence"]["returncode"], code)
                self.assertEqual(rows[1]["evidence"]["base"]["returncode"], code)
                for row in rows[:-1]:
                    self.assertIn(diagnostic, hand_in.item_text(row))

    def test_a_missing_sourced_script_blocks_when_bash_exits_one(self):
        self.assertEqual(self.review(proof.finding("api.py:1", "missing source", "source absent.sh")), "FAIL")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(self.lp.state["notes"], [])
        self.assertIn("[exit 1]", self.lp.findings)

    def test_a_missing_or_unexecutable_shell_is_a_note_and_restores_the_checkout(self):
        limited = worker.limited
        for error in (FileNotFoundError("missing shell"), PermissionError("unexecutable shell")):
            with self.subTest(error=error):
                def cannot_start(command, *args, **kwargs):
                    if command == ["bash", "-c", self.fails]:
                        raise error
                    return limited(command, *args, **kwargs)
                with patch.object(worker, "limited", side_effect=cannot_start):
                    self.assertEqual(self.review(proof.finding("api.py:1", "no shell", self.fails)), "PASS")
                self.assertEqual(self.lp.state["followups"], [])
                self.assertIn(str(error), self.lp.state["notes"][0])

    def test_a_missing_script_reporting_exit_two_reaches_the_fixer(self):
        calls = self.rounds([{
            "commands": [proof.finding("api.py:1", "reviewer script", "python3 probe.py")],
            "edits": {"probe.py": "raise AssertionError('fixture defect')\n"}}, {}],
            fix=lambda: (self.wt / "probe.py").write_text("pass\n"))
        self.assertEqual([role for role, _ in calls], ["executor", "fixer"])
        self.assertIn("[exit 2]", calls[1][1])
        self.assertEqual(self.lp.state["verdict"], "PASS")
        self.assertEqual(self.lp.state["followups"], [])

    def test_a_proof_that_cannot_start_on_base_does_not_prove_an_old_defect(self):
        for command, code in (("./keep.txt", 126), ("./absent", 127)):
            with self.subTest(code=code):
                command = "if grep -q branch api.py; then exit 7; fi; " + command
                self.assertEqual(self.review(proof.finding("legacy.py:1", "no base proof", command)), "PASS")
                self.assertEqual(self.lp.state["followups"], [])
                self.assertIn(f"[exit {code}]", self.lp.state["notes"][0])

    def test_a_running_proof_of_a_missing_application_file_still_blocks(self):
        command = "python3 -c " + shlex.quote("from pathlib import Path; Path('absent').read_text()")
        self.assertEqual(self.review(proof.finding("api.py:1", "missing application file", command)), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertIn("FileNotFoundError", self.lp.findings)

    def test_completed_unittest_failures_can_report_child_launch_errors_on_commit_and_base(self):
        (self.wt / "tests/test_app.py").write_text(
            "import subprocess, unittest\n"
            "class App(unittest.TestCase):\n"
            "    def test_checks_pass(self):\n"
            "        for command in (['bash', '-c', './check.sh'],\n"
            "                        ['bash', '-c', './keep.txt'], ['python3', 'absent.py']):\n"
            "            with self.subTest(command=command):\n"
            "                p = subprocess.run(command, capture_output=True, text=True)\n"
            "                self.assertEqual(p.returncode, 0, '\\n' + p.stderr)\n"
            "unittest.main()\n")
        self.commit("Check that application commands succeed")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.validation = run.commit_identity(self.wt)
        command = "python3 tests/test_app.py"
        self.assertEqual(self.review(
            proof.finding("api.py:1", "failing application check", command),
            proof.finding("api.py:2", "old application failure", command),
            proof.finding("api.py:2", "submitted old failure", command,
                          kind="follow-up", before=self.base)), "FAIL")
        rows = self.lp.state["review_records"]
        self.assertEqual([row["kind"] for row in rows], ["finding", "follow-up", "follow-up", "done"])
        self.assertEqual(self.lp.state["notes"], [])
        for row in rows[:-1]:
            evidence = row["evidence"]
            self.assertIn("Ran 1 test", evidence["output"])
            self.assertIn("No such file or directory", evidence["output"])
            self.assertIn("Permission denied", evidence["output"])
            self.assertEqual(evidence["returncode"], 1)
            self.assertTrue(hand_in.proof_failed(evidence))

    def test_a_completed_proof_can_quote_a_launch_error_and_exit_with_its_own_failure(self):
        command = "echo 'bash: line 1: ./check.sh: No such file or directory'; exit 7"
        self.assertEqual(self.review(proof.finding("api.py:1", "application failure", command)), "FAIL")
        self.assertEqual(self.lp.state["notes"], [])


if __name__ == "__main__":
    unittest.main()
