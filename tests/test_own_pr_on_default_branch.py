"""A seat's own PR based on any branch but the repository's default is refused at launch.

ak lands a PR on its base: one stacked on an unmerged change would land in that change's
branch, under that change's own review, and never reach the default branch (19 Oct 2026: a
seat held its second change back for exactly this, and nothing would have stopped it).
Somebody else's PR is only reviewed, never landed by ak, so it launches on any base.
Offline, on the `fixtures.own_pr` stage.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import OwnPr, URL
from agentkit import config, gate, record, run


class OwnPrOnDefaultBranch(OwnPr):
    def launch(self):
        """(the refusal, how many background runs started, the new run's record)."""
        before = set(config.RUNS.iterdir())
        with patch.object(run, "spawn_bg", return_value=0) as spawned, \
                patch.object(gate, "wait_for_slot", side_effect=AssertionError("waited for a slot")):
            try:
                run.review_pr_main(self.cfg, {"--review-pr": URL, "--review": None},
                                   {"--bg": True}, ["--review-pr", URL, "--bg"], None)
                why = None
            except config.Error as refused:
                why = str(refused)
        launched = (set(config.RUNS.iterdir()) - before).pop()
        return why, spawned.call_count, record.read_state(launched)

    def stack_on_earlier(self):
        """The PR now stands on an unmerged branch of the seat's, `earlier`."""
        self.git("push", "-q", "origin", "main:refs/heads/earlier")
        self.pr.update(baseRefName="earlier")

    def test_a_pr_stacked_on_an_unmerged_branch_is_refused_at_launch(self):
        self.stack_on_earlier()
        why, spawned, state = self.launch()
        self.assertEqual(spawned, 0)
        self.assertIn("PR #7 is based on earlier, not main", why)
        self.assertIn("rebase this branch onto origin/main", why)
        self.assertEqual(state["state"], "error")
        self.assertIn("based on earlier", state["error"])

    def test_a_pr_on_the_default_branch_launches(self):
        self.assertEqual(self.launch()[:2], (None, 1))

    def test_somebody_elses_pr_launches_on_any_base(self):
        self.stack_on_earlier()
        self.pr.update(author="stranger")
        self.assertEqual(self.launch()[:2], (None, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
