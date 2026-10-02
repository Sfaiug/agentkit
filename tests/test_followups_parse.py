"""A reviewer's `## Follow-ups` list: "none" is no follow-up, and evidence stays with its item.

Pure text: checks the fake adapter's Markdown parser directly.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import followups_in


class FollowupsParse(unittest.TestCase):
    def test_none_is_no_followup(self):
        for item in ("- None.", "- none", "* NONE", "1. None", "- n/a", "- N/A.", "None.", "n/a"):
            with self.subTest(item=item):
                self.assertEqual(followups_in(f"VERDICT: PASS\n## Follow-ups\n{item}\n"), [])

    def test_evidence_stays_under_any_marker(self):
        for marker in ("-", "*", "1.", "1)"):
            with self.subTest(marker=marker):
                text = (f"## Follow-ups\n{marker} a.py:1 - x - y\n  evidence: $ cmd -> 1\n"
                        f"{marker} b.py:2 - z\n")
                self.assertEqual(followups_in(text),
                                 ["a.py:1 - x - y\nevidence: $ cmd -> 1", "b.py:2 - z"])

    def test_unindented_line_is_not_evidence(self):
        self.assertEqual(followups_in("## Follow-ups\n1. a.py:1 - x\nnot evidence\n"),
                         ["a.py:1 - x"])


if __name__ == "__main__":
    unittest.main()
