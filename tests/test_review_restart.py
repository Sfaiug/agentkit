"""A parked pull request review is started again as that review, with the writer it captured.

The tick starts a run stopped waiting on an older change again once that change has landed
(`leases.restart`).  A pull request's review has no task to start again: the new run is
launched as `ak run --review-pr <url>` of its seat and carries the stopped run's `own_pr` and
`own_orchestrator`, so its launch check (`run.preflight`) keeps the writer that run captured
at its launch instead of asking the seat again, which may run another model by now, and reads
no GitHub login for it.  Offline: the lease stage (`fixtures.leases`), a fake launch.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import config, leases, run
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"
INFO = {"state": "OPEN", "title": "Change line 5", "author": "owner", "baseRefName": "main",
        "headRefOid": "c" * 40}


class ReviewRestart(LiveRuns):
    def parked_review(self):
        """A seat's own pull request's review, stopped waiting on the older run (`leases.park`)
        with the writer it captured at its launch; the older run has landed since."""
        self.run_on(OLDER, 900, state="pass")
        record.save_state(config.RUNS / OLDER, {**self.state(OLDER), "merged": True})
        self.run_on(YOUNGER, 1000, step=None, rounds=0, session="seat-b")
        record.save_state(config.RUNS / YOUNGER, {
            **self.state(YOUNGER), "state": "stopped", "review_pr": URL, "pr": URL,
            "own_pr": True, "own_orchestrator": "opus", "own_orchestrator_effort": "high",
            "launch_opts": {"--review-pr": URL, "--review": None, "--bg": True},
            "lease_wait": {"on": OLDER, "files": ["api.py"], "since": 2000}})

    def test_the_review_starts_again_as_that_review_with_the_writer_it_captured(self):
        self.parked_review()
        config.save_session(config.load(), "seat-b", "astra", ["opus", "astra"])   # switched since
        launched = []
        # the launch's size check reads the PR's checkout (`test_own_pr_size_before_slot`)
        with patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "origin_default", return_value="main"), \
                patch.object(run, "git", return_value=""), \
                patch.object(run, "own_pr_first_review", return_value=None), \
                patch.object(run, "pr_view", return_value=INFO), \
                patch.object(run, "viewer_login", return_value=None), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append((d, argv))):
            leases.restart(log=self.logs.append, now=3000)
        [(fresh, argv)] = launched
        self.assertEqual(argv, ["--review-pr", URL])
        self.assertFalse((fresh / "task.md").exists())
        state = record.read_state(fresh)
        self.assertEqual((state["state"], state["launched_session"], state["review_pr"]),
                         ("queued", "seat-b", URL))
        self.assertEqual((state["own_pr"], state["own_orchestrator"], state["own_orchestrator_effort"]),
                         (True, "opus", "high"))
        self.assertEqual(state["restarted"], {"run": YOUNGER, "why": f"{OLDER} has landed"})
        self.assertEqual(self.state(YOUNGER)["lease_restarted"], fresh.name)
        self.assertIn(f"started again for {YOUNGER}: {OLDER} has landed; the review of {URL} "
                      "starts again on the landed base", (fresh / "log.txt").read_text())
        self.assertIn(f"{YOUNGER} started again as {fresh.name}: {OLDER} has landed", self.logs[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
