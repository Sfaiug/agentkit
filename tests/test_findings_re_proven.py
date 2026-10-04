"""Earlier proofs decide fixes; late findings on unchanged lines spend no fix round."""

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

    def review(self, *commands, record=True):
        self.plan.write_text(json.dumps([{"commands": commands}]))
        self.lp.rnd = len(self.lp.state["round_summaries"]) + 1
        self.lp.validation = run.commit_identity(self.wt)
        prompts = []
        call = run.call_retrying

        def capture(*args, **kwargs):
            prompts.append(args[2])
            return call(*args, **kwargs)

        with patch.object(run, "call_retrying", side_effect=capture):
            verdict = run.review(self.lp, "## Summary\nFixture", True, "$ true\n[exit 0]",
                                 record=record)
        self.prompt = prompts[-1]
        self.assert_restored()
        return verdict

    def change(self, name, content):
        (self.wt / name).write_text(content)
        self.commit("Fix the reported defect")
        self.head = run.git(self.wt, "rev-parse", "HEAD")

    def test_an_omitted_finding_stays_blocking_until_its_proof_passes(self):
        self.assertEqual(self.review(proof.finding("api.py:1", "wrong mode", self.regression)), "FAIL")
        self.assertEqual(self.review(), "FAIL")
        self.assertIn("## Still-open earlier findings", self.prompt)
        self.assertIn("proof on branch", self.prompt)
        self.assertIn(self.head, self.prompt)
        self.assertEqual(self.review(), "FAIL")
        self.assertEqual([r["finding_count"] for r in self.lp.state["round_summaries"]], [1, 1, 1])

    def test_ak_reports_fixed_proofs_before_the_reviewer_and_keeps_the_result(self):
        self.review(proof.finding("api.py:1", "wrong mode", self.regression))
        self.change("api.py", (self.wt / "api.py").read_text().replace('"branch"', '"base"'))
        self.assertEqual(self.review(), "PASS")
        self.assertIn("## Fixed findings", self.prompt)
        self.assertIn("proof on base", self.prompt)
        self.assertIn("[exit 0]", self.prompt)
        self.assertIn("wrong mode", self.lp.findings)
        self.assertIn("## Fixed findings", Path(self.lp.state["findings_file"]).read_text())
        self.assertNotIn("wrong mode", run.without_followups(self.lp.findings))
        run.write_result(self.directory, self.lp.state, ["true"], cfg=self.cfg)
        self.assertIn("## Fixed findings", (self.directory / "result.md").read_text())

    def test_unchanged_quotes_still_block_and_missing_quotes_are_fixed(self):
        finding = proof.finding("api.py:1", "quoted mode", quote='mode = "branch"')
        self.review(finding)
        self.assertEqual(self.review(), "FAIL")
        self.change("api.py", (self.wt / "api.py").read_text().replace('"branch"', '"base"'))
        self.assertEqual(self.review(), "PASS")
        self.assertIn("## Fixed findings", self.prompt)

    def test_a_moved_quote_is_reproved_even_when_its_old_line_is_gone(self):
        self.review(proof.finding("api.py:4", "bad border", quote="border = True"))
        self.change("api.py", "border = True\n")
        self.assertEqual(self.review(), "FAIL")
        self.assertIn("api.py:1 - bad border", self.lp.findings)

    def test_rehanding_an_open_finding_does_not_duplicate_it(self):
        finding = proof.finding("api.py:1", "wrong mode", self.regression)
        self.review(finding)
        self.assertEqual(self.review(finding), "FAIL")
        self.assertEqual(len(hand_in.Review(self.lp.state["review_records"]).findings), 1)

    def test_a_new_finding_at_an_old_site_does_not_replace_its_proof(self):
        self.review(proof.finding("api.py:1", "wrong mode", self.regression))
        self.assertEqual(self.review(proof.finding("api.py:1", "another defect", self.fails)), "FAIL")
        rows = hand_in.Review(self.lp.state["review_records"])
        self.assertEqual([row["what"] for row in rows.findings], ["wrong mode"])
        self.assertEqual(len(rows.followups), 1)

    def test_late_proofs_on_unchanged_lines_are_followups_even_if_base_passes(self):
        self.review()
        self.assertEqual(self.review(proof.finding("api.py:1", "late regression", self.regression)), "PASS")
        self.assertEqual(len(self.lp.state["followups"]), 1)
        self.assertIn("late regression", self.lp.state["followups"][0])
        self.assertEqual(self.lp.state["round_summaries"][-1]["finding_count"], 0)

    def test_late_quotes_on_unchanged_lines_are_followups(self):
        self.review()
        self.assertEqual(self.review(proof.finding("api.py:1", "late quote", quote='mode = "branch"')), "PASS")
        self.assertEqual(len(self.lp.state["followups"]), 1)
        self.assertEqual(self.lp.state["notes"], [])

    def test_line_number_shifts_do_not_make_an_unchanged_line_new(self):
        self.review()
        self.change("api.py", "inserted = True\n" + (self.wt / "api.py").read_text())
        self.assertEqual(self.review(proof.finding("api.py:2", "shifted late defect", self.fails)), "PASS")
        self.assertEqual(len(self.lp.state["followups"]), 1)

    def test_each_original_proof_is_kept_when_other_findings_are_fixed(self):
        self.review(proof.finding("api.py:1", "wrong mode", self.regression),
                    proof.finding("same.py:1", "wrong value", quote='value = "head"'))
        self.change("same.py", 'value = "fixed"\n')
        self.assertEqual(self.review(), "FAIL")
        rows = hand_in.Review(self.lp.state["review_records"])
        self.assertEqual([row["what"] for row in rows.findings], ["wrong mode"])
        self.assertIn("wrong value", self.prompt.split("## Fixed findings", 1)[1])

    def test_scratch_reproves_earlier_findings_without_a_base(self):
        self.lp.scratch = self.lp.state["scratch"] = True
        self.review(proof.finding("api.py:1", "scratch defect", self.fails))
        self.assertEqual(self.review(), "FAIL")
        self.assertIn("## Still-open earlier findings", self.prompt)
        self.assertNotIn("Base ", self.lp.findings)

    def test_newly_changed_lines_still_block_and_other_lines_in_the_file_do_not(self):
        self.review()
        self.change("api.py", 'mode = "later"\nold_bug = True\nstable = True\nborder = True\ntail = True\n')
        self.assertEqual(self.review(
            proof.finding("api.py:1", "new changed defect", self.fails),
            proof.finding("api.py:2", "late unchanged defect", self.fails)), "FAIL")
        rows = hand_in.Review(self.lp.state["review_records"])
        self.assertEqual([row["what"] for row in rows.findings], ["new changed defect"])
        self.assertEqual(len(rows.followups), 1)

    def test_landing_reviews_compare_with_the_latest_review_not_the_task_round(self):
        self.review()
        self.change("api.py", (self.wt / "api.py").read_text().replace('"branch"', '"later"'))
        self.review(record=False)
        self.assertEqual(len(self.lp.state["round_summaries"]), 1)
        self.assertEqual(self.review(proof.finding("api.py:1", "late landing defect", self.fails)), "PASS")
        self.assertEqual(len(self.lp.state["followups"]), 1)

    def test_an_interrupted_review_keeps_the_prior_findings_even_after_a_dead_attempt(self):
        self.review(proof.finding("api.py:1", "wrong mode", self.regression))

        def interrupt(*args, **_kwargs):
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text("Provider failed.")
            run.record_findings(self.lp, out, "Provider failed.")
            self.lp.save()
            raise run.Stopped("fixture stop")

        with patch.object(run, "call_retrying", side_effect=interrupt):
            with self.assertRaisesRegex(run.Stopped, "fixture stop"):
                self.review()
        state = json.loads((self.directory / "run.json").read_text())
        self.lp = run.Loop(self.cfg, self.directory, state, {}, self.logs.append, self.wt,
                           "# Fixture", ["true"], "context", [])
        self.assertEqual(self.review(), "FAIL")
        self.assertIn("wrong mode", self.lp.findings)


if __name__ == "__main__":
    unittest.main()
