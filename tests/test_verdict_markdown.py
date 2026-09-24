"""Reviewer verdict parsing without a live review loop."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run


class VerdictMarkdown(unittest.TestCase):
    def test_plain_line(self):
        self.assertEqual(run.review_verdicts("VERDICT: PASS"), ["PASS"])

    def test_bold_with_period(self):
        self.assertEqual(run.review_verdicts("**VERDICT: PASS.**"), ["PASS"])

    def test_heading(self):
        self.assertEqual(run.review_verdicts("## VERDICT: FAIL"), ["FAIL"])

    def test_blockquote_case_insensitive(self):
        self.assertEqual(run.review_verdicts("> **Verdict: pass**"), ["pass"])

    def test_last_matching_line_wins(self):
        text = "VERDICT: FAIL\nInitial findings.\n**VERDICT: pass.**\nFinal review."
        verdicts = run.review_verdicts(text)
        self.assertEqual(verdicts, ["FAIL", "pass"])
        self.assertEqual(verdicts[-1].upper(), "PASS")

    def test_no_verdict(self):
        for text in ("", "All checks passed.\nNo issues found."):
            with self.subTest(text=text):
                self.assertEqual(run.review_verdicts(text), [])

    def test_mid_sentence_mention_does_not_match(self):
        text = "The review says:\nthe VERDICT: PASS bar was not met"
        self.assertEqual(run.review_verdicts(text), [])

    def test_leading_whitespace_and_nested_markers(self):
        self.assertEqual(run.review_verdicts(" \t> > ## **VERDICT:\tFAIL!**"), ["FAIL"])

    def test_emphasis_and_code_markers_with_trailing_punctuation(self):
        for marker in ("*", "**", "_", "__", "`"):
            for suffix in (marker, "." + marker, ";" + marker):
                with self.subTest(marker=marker, suffix=suffix):
                    self.assertEqual(run.review_verdicts(f"{marker}VERDICT: PASS{suffix}"),
                                     ["PASS"])

    def test_verdict_must_start_with_a_complete_verdict_word(self):
        for text in ("VERDICT: probably PASS", "VERDICT: **PASS**",
                     "VERDICT: PASSING", "VERDICT: FAILURE", "VERDICT: PASS1"):
            with self.subTest(text=text):
                self.assertEqual(run.review_verdicts(text), [])


if __name__ == "__main__":
    unittest.main()
