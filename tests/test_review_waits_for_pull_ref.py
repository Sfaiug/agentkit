"""A newly opened PR's missing pull ref is waited out at launch and at review.

Offline: injected git results and sleep, with both callers stopped after the fetch.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import call, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, deliver, gc, gitcall, run, turns
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"
MISSING = "fatal: couldn't find remote ref pull/7/head"


class Fetched(Exception):
    """The caller advanced to reading the fetched commits."""


class ReviewWaitsForPullRef(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.repo = self.root / "acme"
        self.directory = config.RUNS / "review"
        self.directory.mkdir()
        self.opts = {"--review-pr": URL, "--review": None}
        info = dict(state="OPEN", title="Mend the fence", author="owner",
                    baseRefName="main", headRefOid="a" * 40, body="Small fix")
        for name, value in (("pr_view", info), ("pr_writer", (True, "opus", "high")),
                            ("launch_session", "fix-api"), ("own_pr_budget", (3, None)),
                            ("checkout_for", self.repo), ("default_base", "origin/main")):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run, "git", side_effect=Fetched))
        self.stack.enter_context(patch.object(gitcall, "tool_run",
                                             side_effect=AssertionError("unexpected tool call")))

    def attempt(self, site, outcomes, error=None):
        record.save_state(self.directory, {})
        logs = []
        with patch.object(gitcall, "git_out", side_effect=outcomes) as git, \
                patch.object(run.time, "sleep") as sleep, \
                patch.object(turns, "transient_delay", wraps=turns.transient_delay) as delay:
            with self.assertRaises(type(error) if error else Fetched) as caught:
                if site == "launch":
                    run.preflight(self.directory, self.opts, logs.append)
                else:
                    run.review_pr_round(self.cfg, self.directory, URL, self.opts, logs.append)
            if error:
                self.assertEqual(str(caught.exception), str(error))
            self.assertEqual(git.call_args_list, [
                call(self.repo, "fetch", "origin", "pull/7/head", "main", env=None)
            ] * len(outcomes))
            waits = len(outcomes) - 1
            self.assertEqual(delay.call_args_list, [call(n) for n in range(1, waits + 1)])
            self.assertEqual(sleep.call_args_list,
                             [call(turns.transient_delay(n)) for n in range(1, waits + 1)])
        self.assertEqual(len(logs), waits)
        for n, line in enumerate(logs, 1):
            self.assertIn("pull/7/head", line)
            self.assertIn(f"{turns.transient_delay(n)}s", line)
            self.assertIn(f"({n}/{deliver.GITHUB_RETRIES})", line)

    def failure(self, message):
        return config.Error(f"git fetch origin pull/7/head main failed in {self.repo}: {message}")

    def test_a_published_ref_never_waits(self):
        for site in ("launch", "review"):
            with self.subTest(site=site):
                self.attempt(site, [(0, "")])

    def test_a_missing_ref_is_retried_until_published(self):
        for site in ("launch", "review"):
            for missing in range(1, deliver.GITHUB_RETRIES + 1):
                with self.subTest(site=site, missing=missing):
                    self.attempt(site, [(128, MISSING)] * missing + [(0, "")])

    def test_a_ref_still_missing_after_the_bound_fails_as_before(self):
        for site in ("launch", "review"):
            with self.subTest(site=site):
                self.attempt(site, [(128, MISSING)] * (deliver.GITHUB_RETRIES + 1),
                             self.failure(MISSING))

    def test_other_fetch_failures_do_not_wait(self):
        messages = ["fatal: couldn't find remote ref " + ref for ref in
                    ("main", "pull/8/head", "pull/7/head-extra", "refs/pull/7/head")]
        messages += ["fatal: Authentication failed", "fatal: Could not resolve host: github.com",
                     MISSING + "\nerror: another failure", "remote: " + MISSING]
        for site in ("launch", "review"):
            for message in messages:
                with self.subTest(site=site, message=message):
                    self.attempt(site, [(128, message)], self.failure(message))

    def test_a_different_failure_after_a_missing_ref_ends_the_retry(self):
        message = "fatal: couldn't find remote ref main"
        for site in ("launch", "review"):
            with self.subTest(site=site):
                self.attempt(site, [(128, MISSING), (128, message)], self.failure(message))

    def test_a_stopped_fetch_is_not_retried(self):
        error = gitcall.Stopped("the remote did not answer")
        for site in ("launch", "review"):
            with self.subTest(site=site):
                self.attempt(site, [error], error)


if __name__ == "__main__":
    unittest.main()
