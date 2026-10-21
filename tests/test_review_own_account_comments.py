"""A FAIL review of a pull request the account ak posts with opened is posted as a comment.

GitHub refuses a changes-requested review from the PR's author, and a review ak could not
tie to a seat (`own_pr` false) is no exception.  Offline: `gh` is a fake that knows who it
is logged in as, shows the PR open at the reviewed head and records the review it is asked
to post.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gitcall, run
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"
HEAD = "b" * 40
LOGIN = "acme-bot"


class OwnAccountReview(unittest.TestCase):
    def post(self, author):
        """The events `post_review` asks gh to post for a FAIL on `author`'s PR, and the
        record it leaves."""
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-own-account-")
        self.addCleanup(tmp.cleanup)
        run_dir = Path(tmp.name)
        events = []

        def gh(_cwd, *args, **_kw):
            if args[:2] == ("api", "user"):
                return 0, json.dumps({"login": LOGIN})
            if args[0] == "api" and args[1].endswith("/pulls/7/reviews"):
                events.extend(a for a in args if a.startswith("event="))
                return 0, "{}"
            raise AssertionError(f"unexpected gh call: {args}")

        state = {"run_id": run_dir.name, "round_summaries": [], "rounds": 1, "base": "origin/main",
                 "executor": None, "reviewer": "astra", "review_pr": URL, "head_sha": HEAD,
                 "author": author, "own_pr": False, "verdict": "FAIL"}
        lp = run.Loop({}, run_dir, state, {}, lambda *_: None, run_dir, "", [], "")
        lp.findings = "api.py:2 wrong answer"
        with patch.object(config, "RUNS", run_dir), patch.object(gitcall, "gh", side_effect=gh), \
                patch.object(run, "pr_view", return_value={"headRefOid": HEAD, "state": "OPEN"}):
            posted = run.post_review(lp, URL, "FAIL")
        return posted, events, record.read_state(run_dir)

    def test_fail_on_a_pr_the_account_opened_comments(self):
        posted, events, state = self.post(LOGIN.upper())
        self.assertEqual(events, ["event=COMMENT"])
        self.assertTrue(posted)
        self.assertTrue(state["review_posted"])
        self.assertNotIn("review_error", state)

    def test_fail_on_another_accounts_pr_requests_changes(self):
        posted, events, state = self.post("contributor")
        self.assertEqual(events, ["event=REQUEST_CHANGES"])
        self.assertTrue(posted)
        self.assertTrue(state["review_posted"])


if __name__ == "__main__":
    unittest.main()
