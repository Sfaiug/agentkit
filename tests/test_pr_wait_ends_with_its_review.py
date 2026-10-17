"""A wait on an open pull request ends when the newest run reviewing it ends without merging it.

A review that FAILs leaves its pull request open, and a run launched outside a seat records
none, so its ending reaches nobody: before, the seat's `ak wait <pull request>` held for good.
While the pull request is open, the newest run whose `review_pr` names it decides the wait as a
wait on that run would (`watch.wait_fact`), its line the one told; a pull request no run has
reviewed waits on its merge or close.  Offline: a faked `gh pr view`, fake run receipts and a
throwaway HOME.
"""

import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, record, watch

PR = "https://github.com/acme/api/pull/26"
OLDER, NEWER = "20260101-0900-review-pr-api-26", "20260101-0930-review-pr-api-26"


class PrWaitEndsWithItsReview(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(watch, "gh_json", side_effect=self.gh))

    def gh(self, _cwd, *args, **_kw):
        self.assertEqual(args[:3], ("pr", "view", PR))
        return {"state": "OPEN", "number": 26, "mergeCommit": None}, ""

    def receipt(self, name, **state):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "title": "Review acme/api#26",
                                      "started_at": 1_800_000_000, **state})

    def fact(self):
        return watch.wait_fact({"kind": "pr", "on": PR})

    def test_a_review_that_failed_with_no_seat_ends_the_wait(self):
        self.receipt(NEWER, review_pr=PR, state="error", verdict="FAIL", finished_at=1_800_000_600)
        self.assertEqual(self.fact(), (True, f"run {NEWER} ended FAIL"))

    def test_a_review_still_going_holds_it(self):
        self.receipt(NEWER, review_pr=PR, state="running")
        self.assertEqual(self.fact(), (False, ""))

    def test_the_newest_review_decides(self):
        self.receipt(OLDER, review_pr=PR, state="error", verdict="FAIL", finished_at=1_800_000_600)
        self.receipt(NEWER, review_pr=PR + "/", state="running")
        self.assertEqual(self.fact(), (False, ""))

    def test_newest_is_by_start_not_by_name(self):
        # the tenth review launched in one minute is named `-10`, which sorts before `-9`
        self.receipt(f"{OLDER}-9", review_pr=PR, state="error", verdict="FAIL",
                     started_at=1_800_000_009, finished_at=1_800_000_600)
        self.receipt(f"{OLDER}-10", review_pr=PR, state="running", started_at=1_800_000_010)
        self.assertEqual(self.fact(), (False, ""))

    def test_a_pull_request_no_run_reviewed_waits_on_its_merge_or_close(self):
        self.receipt(NEWER, review_pr="https://github.com/acme/api/pull/27", state="error",
                     verdict="FAIL", finished_at=1_800_000_600)
        self.receipt(OLDER, state="error", verdict="FAIL", finished_at=1_800_000_600)
        self.assertEqual(self.fact(), (False, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
