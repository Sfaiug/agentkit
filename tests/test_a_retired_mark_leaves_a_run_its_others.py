"""A mark the config no longer has leaves a run the others its saved lists allowed.

A run keeps the role lists it launched with while the config moves on: a reviewer removed
since is still in them.  The shared pick (`usage.pick_order`) passes over it, so a resume
waiting for review goes on with another reviewer the run allowed instead of failing on
`unknown model`; a run left with none waits for review as any other does.

Offline: the sandbox's config in a throwaway HOME, a model taken out in memory, no meters.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, staffing, turns


class RetiredMark(Sandbox):
    def resume(self, reviewers):
        state = {"executor": "opus", "reviewer": "astra", "workers": ["opus"],
                 "reviewers": reviewers, "review_pending": {"round": 2}}
        config.remove_model(self.cfg, "astra")
        return staffing.resume_models(self.cfg, {}, state)

    def test_a_resume_reviews_with_the_mark_still_allowed(self):
        self.assertEqual(self.resume(["astra", "fable"]), ("opus", "fable"))

    def test_a_run_left_no_reviewer_waits_for_review(self):
        with self.assertRaisesRegex(turns.QuotaDry, "no eligible reviewer"):
            self.resume(["astra"])


if __name__ == "__main__":
    unittest.main()
