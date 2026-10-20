"""A wait on an open pull request ends once no ak run of any seat is going on it.

A seat's own pull request never sent to `ak run --review-pr`, or one whose run ended failed or
stopped, stays open, and before, the seat's `ak wait <pull request>` held for good.  While the
pull request is open, the wait holds only while a run reviewing it (`review_pr`) or landing it
(`pr`) is going (`watch.wait_fact`); after that the seat is told it is open with nothing on it
and which command takes it, and `ak wait` on one already so refuses with the same words.
Offline: a faked `gh pr view`, fake run receipts and a throwaway HOME.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch, record, watch

SEAT = "acme-api"
PR = "https://github.com/acme/api/pull/26"
RUN = "20260101-0930-review-pr-api-26"
UNWATCHED = f"PR #26 is open with no ak run going on it: ak run --review-pr {PR} --bg takes it"


class WaitEndsWithItsRuns(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: SEAT}))
        self.stack.enter_context(patch.object(watch, "gh_json", side_effect=self.gh))
        # the seat is closed: the wait ends on its fact, with no screen to type into
        config.save_session(self.cfg, SEAT, "fable", ["opus"], {})
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))

    def gh(self, _cwd, *args, **_kw):
        self.assertEqual(args[:3], ("pr", "view", PR))
        return {"state": "OPEN", "number": 26, "mergeCommit": None}, ""

    def receipt(self, name=RUN, **state):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "title": "Review acme/api#26",
                                      "started_at": 1_800_000_000, **state})

    def wait(self):
        """`ak wait <PR>` in the seat: (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = watch.wait_main([PR])
        return code, out.getvalue(), err.getvalue()

    def test_an_open_pull_request_with_no_run_going_is_refused(self):
        # a run of another pull request, and a review of this one that is over, hold nothing
        self.receipt("20260101-0900-review-pr-api-27", state="running",
                     review_pr="https://github.com/acme/api/pull/27")
        self.receipt(state="error", verdict="FAIL", review_pr=PR, finished_at=1_800_000_600)
        code, out, err = self.wait()
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, f"ak wait: {UNWATCHED}; nothing is left to wait on\n")
        self.assertNotIn("wait", watch.seat_read(SEAT))

    def test_a_wait_ends_once_its_review_ends_without_merging(self):
        self.receipt(state="running", review_pr=PR + "/")
        self.assertEqual(self.wait(), (0, f"{SEAT}: waiting on PR #26\n", ""))
        watch.wait_over(self.cfg, lambda _line: None)
        self.assertEqual(watch.waiting_on(SEAT)["on"], PR)
        self.receipt(state="error", verdict="FAIL", review_pr=PR + "/", finished_at=1_800_000_600)
        watch.wait_over(self.cfg, lambda _line: None)
        self.assertIsNone(watch.waiting_on(SEAT))
        self.assertEqual(watch.seat_read(SEAT)["wait"]["over"], UNWATCHED)

    def test_a_run_landing_it_holds_the_wait(self):
        self.receipt("20260101-0900-fix-api", state="running", pr=PR)
        self.assertEqual(self.wait(), (0, f"{SEAT}: waiting on PR #26\n", ""))
        watch.wait_over(self.cfg, lambda _line: None)
        self.assertEqual(watch.waiting_on(SEAT)["on"], PR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
