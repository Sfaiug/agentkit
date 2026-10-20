"""`ak wait` refuses a pull request or run that is already over, saying which.

The tick ends a wait the moment what it names is merged, closed or ended (`watch.wait_over`),
so a wait on one already over would end the seat's turn only to wake it at once with "your
wait is over".  `ak wait` reads the same fact first (`watch.wait_fact`) and refuses, exit 1,
the fact on stderr and nothing written, so the seat goes on with its turn instead.  Offline:
a faked `gh`, fake run receipts and a throwaway HOME.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, record, watch

SEAT = "acme-api"
PR = "https://github.com/acme/api/pull/12"
RUN = "20260101-0900-schema"


class AlreadyOver(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: SEAT}))
        self.gh = {"state": "OPEN", "number": 12, "mergeCommit": None}
        self.stack.enter_context(patch.object(watch, "gh_json",
                                              side_effect=lambda *_a, **_k: (self.gh, "")))

    def wait(self, on):
        """`ak wait <on>` in the seat: (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = watch.wait_main([on])
        return code, out.getvalue(), err.getvalue()

    def receipt(self, **state):
        directory = config.RUNS / RUN
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": RUN, "title": "Task schema",
                                      "started_at": 1_800_000_000, **state})

    def refused(self, on, fact):
        code, out, err = self.wait(on)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, f"ak wait: {fact}; nothing is left to wait on\n")
        self.assertNotIn("wait", watch.seat_read(SEAT))

    def test_a_merged_or_closed_pull_request_is_refused(self):
        self.gh = {"state": "MERGED", "number": 12, "mergeCommit": {"oid": "abcdef1234567890"}}
        self.refused(PR, "PR #12 merged as abcdef123456")
        self.gh = {"state": "CLOSED", "number": 12, "mergeCommit": None}
        self.refused(PR, "PR #12 closed without merging")

    def test_an_ended_or_stalled_run_is_refused(self):
        self.receipt(state="pass", verdict="PASS", merged=True, finished_at=1_800_000_600)
        self.refused(RUN, f"run {RUN} ended PASS, merged")
        self.receipt(state="stalled")
        self.refused(RUN, f"run {RUN} stalled: resume it with ak run resume {RUN}")

    def test_an_open_pull_request_or_a_going_run_is_waited_on(self):
        self.receipt(state="running", review_pr=PR)
        self.assertEqual(self.wait(PR), (0, f"{SEAT}: waiting on PR #12\n", ""))
        self.assertEqual(watch.seat_read(SEAT)["wait"]["on"], PR)
        self.assertEqual(self.wait(RUN), (0, f"{SEAT}: waiting on run {RUN}\n", ""))
        self.assertEqual(watch.seat_read(SEAT)["wait"]["kind"], "run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
