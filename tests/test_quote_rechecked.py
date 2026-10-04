"""Quoted findings must hold in the reviewed work, outside the reviewer's editable copy."""

import json
from pathlib import Path
import unittest

import test_proof_weighed as proof
from agentkit import hand_in, run


class QuoteRechecked(unittest.TestCase):
    setUp = proof.ProofWeighed.setUp
    commit = proof.ProofWeighed.commit
    review = proof.ProofWeighed.review
    rounds = proof.ProofWeighed.rounds
    assert_restored = proof.ProofWeighed.assert_restored

    def quote(self, path="api.py", line=1, quote='mode = "branch"', kind="finding"):
        row = {"kind": kind, "path": path, "line": line,
               "what": "quoted defect", "why": "breaks callers", "evidence": {"quote": quote}}
        if kind == "follow-up":
            row["before"] = "base already has this defect"
        return row

    def weigh(self, *rows, head=None):
        file = hand_in.start(self.directory, self.wt)
        with Path(file).open("a") as output:
            output.write("".join(json.dumps(row) + "\n" for row in [*rows, {"kind": "done"}]))
        return run.weigh_review(self.lp, hand_in.read(file), head or self.head)

    def test_a_line_added_by_the_reviewer_is_a_note_and_starts_no_fix_round(self):
        quote = "reviewer_only = True"
        content = (self.wt / "api.py").read_text()
        calls = self.rounds([{
            "commands": [proof.finding("api.py:1", "invented defect", quote=quote)],
            "edits": {"api.py": quote + "\n" + content}}])
        self.assertEqual(self.lp.state["verdict"], "PASS")
        self.assertEqual([role for role, _ in calls], ["executor"])
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 0)
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), 1)
        self.assertIn(quote, self.lp.state["notes"][0])
        self.assertEqual((self.wt / "api.py").read_text(), content)

    def test_a_quote_in_the_commit_still_blocks(self):
        self.assertEqual(self.review(proof.finding(
            "api.py:1", "committed defect", quote='mode = "branch"')), "FAIL")
        self.assertEqual(self.lp.state["round_summaries"][0]["finding_count"], 1)
        self.assertEqual(self.lp.state["notes"], [])

    def test_unchecked_records_with_bad_sites_or_quotes_are_notes(self):
        (self.wt / "loop.py").symlink_to("loop.py")
        self.commit("Record a broken file link")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        (self.wt / "untracked.py").write_text('mode = "branch"\n')
        for row in (self.quote(path="missing.py"), self.quote(path="tests"),
                    self.quote(path="untracked.py"), self.quote(path="loop.py"),
                    self.quote(path=".git/HEAD", quote=self.head),
                    self.quote(line=0), self.quote(line=6),
                    self.quote(line="two"), self.quote(quote="absent"), self.quote(quote=" ")):
            with self.subTest(row=row):
                weighed = self.weigh(row)
                self.assertEqual(weighed.verdict, "PASS")
                self.assertEqual(weighed.records[0]["kind"], "note")
                self.assertEqual(weighed.records[0]["evidence"], row["evidence"])

    def test_quotes_use_the_reviewed_head_even_when_the_checkout_has_moved(self):
        (self.wt / "api.py").write_text('mode = "later"\n')
        self.commit("Move the checkout after review")
        later = run.git(self.wt, "rev-parse", "HEAD")
        weighed = self.weigh(self.quote(), self.quote(quote='mode = "later"'))
        self.assertEqual([row["kind"] for row in weighed.records], ["finding", "note", "done"])
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), later)
        self.assertEqual((self.wt / "api.py").read_text(), 'mode = "later"\n')

    def test_internal_links_and_multiline_quotes_use_the_same_rules_as_hand_in(self):
        (self.wt / "alias.py").symlink_to("api.py")
        self.commit("Add a file alias")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        for quote in ('mode = "branch"\nold_bug = True\n', "old_bug = True\nstable = True"):
            with self.subTest(quote=quote):
                checked = hand_in.checked(proof.finding("alias.py:1", "quoted defect", quote=quote),
                                          self.wt)
                weighed = self.weigh(self.quote(path="alias.py", quote=quote))
                self.assertEqual(weighed.verdict, "FAIL")
                self.assertEqual(weighed.records[0], checked)

    def test_scratch_quotes_are_checked_in_the_workspace_and_followups_are_dropped(self):
        self.lp.scratch = True
        followup = self.quote(path="missing.py", kind="follow-up")
        weighed = self.weigh(self.quote(), self.quote(quote="absent"),
                            self.quote(path="missing.py"), self.quote(line=6), followup)
        self.assertEqual([row["kind"] for row in weighed.records],
                         ["finding", "note", "note", "note", "note", "done"])
        self.assertEqual(weighed.followups, [])
        self.assertIn("no base commit", weighed.records[-2]["dropped"])


if __name__ == "__main__":
    unittest.main()
