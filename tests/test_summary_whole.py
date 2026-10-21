"""A round keeps the executor's whole summary, a landing re-review's pending record included.

The round record kept only a summary's last 4000 characters, with no word that the rest was
gone: what the executor said first (often what it changed and why) was lost from result.md.
Now the record holds the summary whole.  No reviewer reads it (`roundloop.review`).

Offline: the fake harness and temporary HOME of test_reviewer_judges_the_diff.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_reviewer_judges_the_diff as fixture
from agentkit import roundloop

LONG = "## Summary\nFIRST changed the widget.\n" + "Checked one more acme case.\n" * 400 + "LAST"


class SummaryWhole(unittest.TestCase):
    setUp = fixture.ReviewerJudgesTheDiff.setUp
    script = fixture.ReviewerJudgesTheDiff.script
    reviews = fixture.ReviewerJudgesTheDiff.reviews
    calls = fixture.ReviewerJudgesTheDiff.calls
    log = fixture.ReviewerJudgesTheDiff.log
    launch_scratch = fixture.ReviewerJudgesTheDiff.launch_scratch

    def test_the_record_keeps_the_whole_summary_for_a_landing_re_review(self):
        adapter = fixture.ADAPTER.replace('"## Summary\\nFixture work."', json.dumps(LONG))
        self.assertNotEqual(adapter, fixture.ADAPTER)
        for path in (self.root / "adapters").glob("*.sh"):
            self.script(path, adapter)
        code, directory, state = self.launch_scratch(fixture.PASS)
        self.assertEqual(code, 0, self.log(directory))
        self.assertNotIn("FIRST changed the widget.", self.calls("reviewer")[0]["prompt"])
        self.assertEqual(state["round_summaries"][-1]["summary"], LONG)

        class Run:
            rnd = 2

            def save(self):
                pass
        lp = Run()
        lp.state = state
        roundloop.pending_review(lp, "The target moved; review the integrated commit.")
        self.assertEqual(lp.state["review_pending"]["summary"], LONG)


if __name__ == "__main__":
    unittest.main()
