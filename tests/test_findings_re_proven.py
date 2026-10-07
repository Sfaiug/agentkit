"""Earlier findings are re-proved on the current head and reported to the re-reviewer as prompt
context.  ak writes no record for a re-proof and changes no preface; the reviewer rules on each,
re-handing one to uphold it and leaving one out to drop it."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_proof_weighed as proof
from agentkit import hand_in, run


class FindingsReProven(unittest.TestCase):
    setUp = proof.ProofWeighed.setUp
    commit = proof.ProofWeighed.commit
    assert_restored = proof.ProofWeighed.assert_restored

    def review(self, *commands, record=True, preface=""):
        self.plan.write_text(json.dumps([{"commands": commands}]))
        if record:
            self.lp.rnd = len(self.lp.state["round_summaries"]) + 1
        self.lp.validation = run.commit_identity(self.wt)
        prompts = []
        call = run.call_retrying

        def capture(*args, **kwargs):
            prompts.append(args[2])
            return call(*args, **kwargs)

        with patch.object(run, "call_retrying", side_effect=capture):
            verdict = run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]",
                                 preface, record=record)
        self.prompt = prompts[-1]
        self.assert_restored()
        return verdict

    def change(self, name, content):
        (self.wt / name).write_text(content)
        self.commit("Fix the reported defect")
        self.head = run.git(self.wt, "rev-parse", "HEAD")

    def test_a_still_open_finding_is_reported_and_writes_no_record(self):
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", self.fails)), "FAIL")
        self.assertEqual(self.review(), "PASS")                 # the reviewer omits it: dropped
        self.assertIn("api.py:1 - wrong mode [still open]", self.prompt)
        # The re-proof is prompt context only: the reviewer handed nothing, so nothing blocks.
        self.assertEqual(hand_in.Review(self.lp.state["review_records"]).findings, [])

    def test_the_reviewer_upholds_a_still_open_finding_by_re_handing_it(self):
        finding = proof.finding("api.py:1", "wrong mode", self.fails)
        self.assertEqual(self.review(finding), "FAIL")
        self.assertEqual(self.review(finding), "FAIL")          # re-handed: it blocks
        # The record is the reviewer's hand-in alone; the re-proof adds none of its own.
        self.assertEqual(len(hand_in.Review(self.lp.state["review_records"]).findings), 1)

    def test_a_fixed_proof_is_reported_fixed(self):
        self.review(proof.finding("api.py:1", "wrong mode", self.regression))
        self.change("api.py", (self.wt / "api.py").read_text().replace('"branch"', '"base"'))
        self.assertEqual(self.review(), "PASS")
        self.assertIn("## ak re-proved each earlier finding", self.prompt)
        self.assertIn("api.py:1 - wrong mode [fixed]", self.prompt)

    def test_a_present_quote_is_still_open_and_a_gone_one_is_fixed(self):
        self.review(proof.finding("api.py:1", "quoted mode", quote='mode = "branch"'))
        self.assertEqual(self.review(), "PASS")
        self.assertIn("quoted mode [still open]", self.prompt)  # quote still in the file
        self.review(proof.finding("api.py:1", "quoted mode", quote='mode = "branch"'))
        self.change("api.py", (self.wt / "api.py").read_text().replace('"branch"', '"base"'))
        self.assertEqual(self.review(), "PASS")
        self.assertIn("quoted mode [fixed]", self.prompt)       # quote gone

    def test_a_quote_file_linked_out_of_the_checkout_reads_fixed_not_crash(self):
        # A fix turns the quoted file into a link to an unreadable file outside the checkout.
        # Re-proving locates the quote through quoted_sites, so it reads as gone -- never a crash
        # out of review() and never a read outside the checkout.
        self.review(proof.finding("api.py:1", "quoted mode", quote='mode = "branch"'))
        secret = self.root / "outside-secret"
        secret.write_text('mode = "branch"\n')
        secret.chmod(0)
        (self.wt / "api.py").unlink()
        (self.wt / "api.py").symlink_to(secret)
        self.commit("Link the config out of the checkout")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(self.review(), "PASS")
        self.assertIn("quoted mode [fixed]", self.prompt)

    def test_scratch_re_proves_without_a_base(self):
        self.lp.scratch = self.lp.state["scratch"] = True
        self.review(proof.finding("api.py:1", "scratch defect", self.fails))
        self.assertEqual(self.review(), "PASS")
        self.assertIn("api.py:1 - scratch defect [still open]", self.prompt)

    def test_a_parked_and_resumed_review_re_proves_the_same_earlier_findings(self):
        # A dead attempt overwrites review_records mid-review with its own (empty) records; the
        # resumed review still re-proves the last completed review's findings.json on disk.
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", self.fails)), "FAIL")
        self.lp.rnd = 2
        with patch.object(run, "call_retrying", return_value=(1, "", None, True)):
            with self.assertRaises(run.Exhausted):
                run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]")
        self.review()
        self.assertIn("api.py:1 - wrong mode [still open]", self.prompt)

    def test_earlier_findings_come_from_disk_not_a_cleared_review_records(self):
        # A dead attempt (this round's, or the base version's before an upgrade) clears
        # review_records; the earlier set still comes from the last completed review's findings.json.
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", self.fails)), "FAIL")
        self.lp.state["review_records"] = []
        self.review()
        self.assertIn("api.py:1 - wrong mode [still open]", self.prompt)

    def test_disputing_one_finding_does_not_hide_another_with_the_same_summary(self):
        # Two findings on one line with the SAME what but different why and quote; disputing one must
        # not hide the other -- the match is the whole captured finding, not a partial key.
        (self.wt / "api.py").write_text('mode = "branch"; enabled = False\n')
        self.commit("Two independent configuration defects")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        mode = proof.finding("api.py:1", "invalid configuration", quote='mode = "branch"')
        disabled = proof.finding("api.py:1", "invalid configuration", quote="enabled = False")
        mode[3] = "The deployment mode violates the contract"
        disabled[3] = "The requested feature is disabled"
        self.assertEqual(self.review(mode, disabled), "FAIL")
        previous = Path(self.lp.state["findings_file"]).with_name(hand_in.FINDINGS_FILE)
        fixer = self.root / "fixer"
        fixer.mkdir()
        file = Path(hand_in.start(fixer, self.wt, role="fixer", findings=previous))
        handed = hand_in.read(file).handed_findings
        dispute = hand_in.checked(
            ["dispute", "api.py:1", "The mode change is intentional", "--quote", 'mode = "branch"'],
            self.wt, role="fixer", findings=handed)
        self.assertEqual(dispute["finding"]["evidence"]["quote"], 'mode = "branch"')
        with file.open("a") as output:
            output.write(json.dumps(dispute) + "\n" + json.dumps({"kind": "done"}) + "\n")
        self.lp.state["dispute_files"] = [str(file)]
        self.assertEqual(self.review(), "PASS")
        # The undisputed feature-disabled finding is re-proved; the disputed mode finding is not,
        # though both share path, line and what.
        self.assertEqual(self.prompt.count("invalid configuration [still open]"), 1)

    def test_a_parked_landing_attempt_does_not_change_the_earlier_set(self):
        # A completed PASS, then a landing re-review (record=False) that writes a finding but dies
        # without done; the resume re-proves the PASS's empty set, not the unfinished attempt's.
        self.assertEqual(self.review(), "PASS")
        row = hand_in.checked(
            proof.finding("api.py:1", "unweighed candidate", quote='mode = "branch"'), self.wt)

        def dead(*args, **kwargs):
            out = Path(args[4])
            out.mkdir(parents=True)
            with Path(hand_in.start(out, self.wt)).open("a") as output:
                output.write(json.dumps(row) + "\n")
            (out / "final.md").write_text("Interrupted landing review")
            return 1, "Interrupted landing review", None, True

        with patch.object(run, "call_retrying", side_effect=dead):
            with self.assertRaises(run.Exhausted):
                run.review(self.lp, "Landing", True, "$ true\n[exit 0]", record=False)
        self.review(record=False, preface="Landing")
        self.assertNotIn("unweighed candidate [still open]", self.prompt)

    def test_a_quote_still_in_a_shorter_file_is_not_reported_fixed(self):
        # A fix deletes lines above the quote, so the file is now shorter than the finding's line
        # number, but the quoted line is still there: re-proving judges by the quote, not the line.
        self.assertEqual(self.review(proof.finding("api.py:4", "quoted border", quote="border = True")), "FAIL")
        self.change("api.py", 'mode = "branch"\nborder = True\ntail = True\n')
        self.assertEqual(self.review(), "PASS")
        self.assertIn("border = True", (self.wt / "api.py").read_text())
        self.assertIn("quoted border [still open]", self.prompt)

    def test_a_quote_file_turned_into_a_symlink_loop_does_not_crash_review(self):
        # A fix turns the quoted file into a symlink loop; Path.resolve raises RuntimeError on 3.11.
        # quoted_sites' full catch makes it read as gone, so the re-review never crashes.
        self.review(proof.finding("api.py:1", "quoted mode", quote='mode = "branch"'))
        (self.wt / "api.py").unlink()
        (self.wt / "api.py").symlink_to("api.py")
        self.commit("Loop the config")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(self.review(), "PASS")
        self.assertIn("quoted mode [fixed]", self.prompt)

    def test_a_landing_re_review_re_proves_nothing_the_passing_review_settled(self):
        # A landing re-review (record=False) runs in the same round as the PASS that dropped the
        # finding; the earlier set is that PASS's (empty), so nothing settled is re-proved stale.
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", self.fails)), "FAIL")
        self.assertEqual(self.review(), "PASS")          # round 2 drops it: the last recorded review
        self.review(record=False, preface="Re-review after the rebase of origin/main.")
        self.assertEqual(self.lp.rnd, 2)
        self.assertNotIn("wrong mode [still open]", self.prompt)

    def test_a_head_past_a_skipped_review_re_proves_nothing_its_pass_settled(self):
        # A text-only own-PR head records a PASS with no reviewer answer and clears review_records;
        # the next head's earlier set is that empty PASS, not a finding from two heads back.
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", self.fails)), "FAIL")
        self.lp.state.update(verdict="PASS", findings="")
        self.lp.state.pop("review_records", None)
        self.lp.state.pop("findings_file", None)
        self.lp.state["round_summaries"].append({"round": 2, "verdict": "PASS", "done_when": None,
                                                 "summary": "Text and translation files only; review skipped."})
        self.review()                                    # round 3, the next head
        self.assertEqual(self.lp.rnd, 3)
        self.assertNotIn("wrong mode [still open]", self.prompt)

    def test_a_proof_that_cannot_run_is_not_reported_still_open(self):
        # The proof's script is gone (exit 127): hand_in.proof_failed says it shows nothing, so ak
        # reports no result -- never "still open" over an unexecutable proof.
        script = self.wt / "check.sh"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(0o755)
        self.commit("Add the check")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", "./check.sh")), "FAIL")
        script.unlink()
        self.commit("Remove the check")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        self.assertEqual(self.review(), "PASS")
        self.assertNotIn("wrong mode [still open]", self.prompt)
        self.assertIn("wrong mode [no result]", self.prompt)


if __name__ == "__main__":
    unittest.main()
