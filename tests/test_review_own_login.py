"""A review of a PR this host's GitHub login wrote never asks GitHub for changes, whoever launched it.

GitHub refuses a changes-requested review from the PR's own author.  A review launched where no
seat is known (a shell that lost its seat, or the owner by hand) is reviewed as anyone's PR, and
its FAIL still has to be posted, as a comment.  Offline, on the `fixtures.own_pr` stage.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import OwnPr
from agentkit import record


class ReviewOwnLogin(OwnPr):
    def seatless(self):
        with record.record(self.run_dir) as state:
            state["launched_session"] = None

    def test_a_seatless_review_of_this_logins_pr_comments_its_fail(self):
        self.seatless()
        state = self.review(["FAIL"])
        self.assertFalse(state["own_pr"])               # no seat: reviewed as anyone's PR
        self.assertEqual(self.events, ["event=COMMENT"])
        self.assertTrue(state["review_posted"])
        self.assertEqual(state["state"], "fail")

    def test_someone_elses_fail_still_requests_changes(self):
        self.seatless()
        self.pr["author"] = "contributor"
        state = self.review(["FAIL"])
        self.assertEqual(self.events, ["event=REQUEST_CHANGES"])
        self.assertEqual(state["state"], "fail")


if __name__ == "__main__":
    unittest.main()
