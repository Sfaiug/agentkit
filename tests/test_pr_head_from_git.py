"""A PR's head is read from git, so GitHub's lag never ends a review.

GitHub here shows the head from before the run's own fix push on every read, `gh pr view` and
its REST answer alike, as it did for seconds on 19 Oct; the head branch git reads is where the
push put it.  A round after the fix reviews the pushed head, posts its PASS and merges pinned
to it, resumed after a cut or not, and through a merge GitHub first refuses for a head it has
not taken; a push by somebody else still ends the run.  Offline, on the `fixtures.own_pr`
stage, with the real `pr_view` over that GitHub.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from fixtures.own_pr import URL, OwnPr
from agentkit import gitcall, record, run, turns, worker

PR_VIEW = run.pr_view       # the fixture stands one in; these tests read the PR as ak does
HEAD_RACE = "GraphQL: Head branch was modified. Review and try the merge again. (mergePullRequest)"


class PrHeadFromGit(OwnPr):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(run, "pr_view", PR_VIEW))

    def gh_json(self, cwd, *args, **_kw):
        current, why = super().gh_json(cwd, *args)
        if args[:2] == ("pr", "view"):
            return {**current, "author": {"login": self.pr["author"]}, "headRefOid": self.heads[0]}, ""
        if "head" in current:           # the REST answer
            current["head"]["sha"] = self.heads[0]
            current["mergeable"] = True
        return current, why

    def landed(self, state):
        """Round two reviewed the pushed fix, posted its PASS on it and merged pinned to it."""
        self.assertTrue(state["merged"])
        self.assertTrue(state["review_posted"])
        self.assertEqual([s["head_sha"] for s in state["round_summaries"]], self.heads[:2])
        self.assertEqual(self.remote_head(), self.heads[1])
        self.assertIn(f"agentkit review of {self.heads[1][:12]}", (self.run_dir / "review.md").read_text())
        self.assertEqual([m[m.index("--match-head-commit") + 1] for m in self.merges], [self.heads[1]])

    def test_the_round_after_the_fix_reviews_posts_and_merges_the_pushed_head(self):
        self.landed(self.review(["FAIL", "PASS"]))

    def test_a_round_cut_off_after_its_checkout_resumes_on_the_pushed_head(self):
        reviewer, cut = self.reviewer, []

        def cut_off(cfg, name, body, *args, **kwargs):
            if len(self.prompts) == 1 and not cut:        # round two's reviewer, after its checkout
                cut.append(body)
                raise InterruptedError("the host cut the run off")
            return reviewer(cfg, name, body, *args, **kwargs)

        with patch.object(worker, "call", side_effect=submitting(cut_off)), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        self.assertEqual(run.git(saved["worktree"], "rev-parse", "HEAD"), self.heads[1])
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        self.landed(self.review(["FAIL", "PASS"]))

    def test_a_merge_refused_for_a_head_github_has_not_taken_is_tried_again(self):
        gh, refused = self.gh, []

        def head_race(cwd, *args, **kw):
            if args[:2] == ("pr", "merge") and not refused:
                refused.append(args[args.index("--match-head-commit") + 1])
                return 1, HEAD_RACE
            return gh(cwd, *args, **kw)

        with patch.object(gitcall, "gh", side_effect=head_race), \
                patch.object(turns, "transient_delay", return_value=0):
            self.landed(self.review(["FAIL", "PASS"]))
        self.assertEqual(refused, [self.heads[1]])

    def test_a_push_by_somebody_else_still_ends_the_run(self):
        fix = self.fix

        def raced(lp):
            fix(lp)                     # the fixer's commit ...
            self.hand_push(2)           # ... and the seat's push meanwhile

        self.fix = raced
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "fail")
        self.assertIn("the PR head moved while the fix was made", state["error"])
        self.assertEqual((len(self.prompts), self.merges, self.remote_head()), (1, [], self.heads[2]))

    def test_a_merge_another_read_shows_is_never_put_on_the_pushed_head(self):
        """`gh pr view` already shows the PR merged on its old head; the REST read, still open,
        names the branch git reads: state and head come from that one read."""
        self.hand_push(1)
        with patch.object(self, "view", return_value={**self.pr, "state": "MERGED"}):
            view = run.pr_view(URL)
        self.assertEqual((view["state"], view["headRefOid"]), ("OPEN", self.heads[1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
