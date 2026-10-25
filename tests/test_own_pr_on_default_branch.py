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
from fixtures.own_pr import OwnPr
from agentkit import gitcall, run


class OwnPrOnDefaultBranch(OwnPr):
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

    def test_the_default_is_origin_s_though_no_tracking_ref_names_it(self):
        # the checkout is on fix-api, which a fallback to the current branch would take
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.git("push", "-q", "origin", f"{self.heads[0]}:refs/pull/7/head")
        with patch.object(run, "fetch", side_effect=gitcall.fetch):
            self.assertEqual(self.launch()[:2], (None, 1))

    def test_the_default_is_origin_s_after_origin_renames_it(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("push", "-q", "origin", "main:refs/heads/trunk")
        self.git(f"--git-dir={self.remote}", "symbolic-ref", "HEAD", "refs/heads/trunk")
        self.pr.update(baseRefName="trunk")
        self.assertEqual(self.launch()[:2], (None, 1))

    def test_a_local_branch_named_like_the_tracking_ref_changes_nothing(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("branch", "origin/main", "main")
        self.assertEqual(self.launch()[:2], (None, 1))

    def test_somebody_elses_pr_launches_on_any_base(self):
        self.stack_on_earlier()
        self.pr.update(author="stranger")
        self.assertEqual(self.launch()[:2], (None, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
