"""A proof that could not start establishes no defect on either commit."""

import shlex
import unittest
from unittest.mock import patch

import test_proof_weighed as proof
from agentkit import worker


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

    def test_missing_script_is_a_note_even_when_the_interpreter_exits_two(self):
        self.assertEqual(self.review(proof.finding(
            "api.py:1", "missing script", "python3 absent.py")), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("can't open file", self.lp.state["notes"][0])

    def test_a_missing_sourced_script_is_a_note_even_when_bash_exits_one(self):
        self.assertEqual(self.review(proof.finding("api.py:1", "missing source", "source absent.sh")), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("[exit 1]", self.lp.state["notes"][0])

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

    def test_a_script_only_in_the_reviewers_copy_cannot_start_a_fixer(self):
        calls = self.rounds([{
            "commands": [proof.finding("api.py:1", "reviewer script", "python3 probe.py")],
            "edits": {"probe.py": "raise AssertionError('fixture defect')\n"}}])
        self.assertEqual([role for role, _ in calls], ["executor"])
        self.assertEqual(self.lp.state["verdict"], "PASS")
        self.assertEqual(self.lp.state["followups"], [])

    def test_a_proof_that_cannot_start_on_base_does_not_prove_an_old_defect(self):
        command = "if grep -q branch api.py; then exit 7; fi; python3 absent.py"
        self.assertEqual(self.review(proof.finding("legacy.py:1", "no base proof", command)), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("can't open file", self.lp.state["notes"][0])

    def test_a_running_proof_of_a_missing_application_file_still_blocks(self):
        command = "python3 -c " + shlex.quote("from pathlib import Path; Path('absent').read_text()")
        self.assertEqual(self.review(proof.finding("api.py:1", "missing application file", command)), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertIn("FileNotFoundError", self.lp.findings)


if __name__ == "__main__":
    unittest.main()
