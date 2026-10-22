"""A review that stopped before its first round names the relaunch that reviews its pull request
again, `ak run --review-pr URL`: its task file, launched alone, builds a change of its own titled
after the review instead (seen 22 Oct 2026, a review stopped by GitHub's 503).  Offline: a run
record in the sandbox HOME.
"""

import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, handback

PR = "https://github.com/acme/widget/pull/7"


class ReviewRelaunch(Sandbox):
    def stopped(self, **state):
        run_dir = config.RUNS / "20260101-0900-review-pr-widget-7"
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text("# Review PR #7: widget\n")
        handback.record_result(run_dir, dict(state, run_id=run_dir.name, title="Review PR #7: widget",
                                             error="cannot read the PR: Service Unavailable"))
        return run_dir, (run_dir / "result.md").read_text()

    def test_a_review_relaunches_as_a_review_of_its_pull_request(self):
        _, result = self.stopped(review_pr=PR)
        self.assertIn(f"relaunch: ak run --review-pr {PR}\n", result)

    def test_a_task_relaunches_as_its_task_file(self):
        run_dir, result = self.stopped()
        self.assertIn(f"relaunch: ak run {run_dir / 'task.md'}\n", result)


if __name__ == "__main__":
    unittest.main()
