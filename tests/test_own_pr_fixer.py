"""A FAIL on a seat's own pull request is fixed by ak, never handed to the seat.

With rounds left, the run takes a fixer turn on its own checkout of the reviewed head -- the
session's executor, else the seat's own orchestrator model -- commits what the turn left,
pushes it to the PR branch over the reviewed head and reviews it in the next round.  Nothing
is typed into the seat and no process waits for a push.  A head pushed by hand before the fix
is what the next round reviews; one pushed while the fix was made ends the run.  Offline, on
the `fixtures.own_pr` stage.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import OwnPr
from agentkit import run
from agentkit import record


class OwnPrFixer(OwnPr):
    def test_a_fail_is_fixed_on_the_prs_branch_and_reviewed_again(self):
        def leaves_a_fix(lp):           # the fixer edits and never commits: ak commits what it left
            (lp.wt / "fence.txt").write_text("mended\n")

        self.fix = leaves_a_fix
        clock = self.stack.enter_context(patch.object(run, "time", wraps=time))
        clock.sleep.side_effect = lambda _seconds: self.fail("the run slept instead of fixing")
        with patch.object(run, "ready_order", return_value=["astra"]):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
        self.assertEqual(state["executor"], "astra")        # the session's executor fixes
        [fix] = self.fixes
        self.assertIn("## Reviewer findings to fix", fix)
        self.assertIn("defect 1", fix)
        self.assertIn(f"Repo checkout: {state['worktree']}", fix)
        self.assertIn("# acme", fix)                        # the repository's rules ride along
        fixed = state["round_summaries"][1]["head_sha"]
        self.assertNotEqual(fixed, self.heads[0])
        self.assertEqual(self.remote_head(), fixed)         # pushed to the PR branch
        self.assertEqual(run.git(self.repo, "show", f"{fixed}:fence.txt"), "mended")
        self.assertEqual(self.notices, [])                  # nothing typed into the seat
        self.kill.assert_not_called()
        self.resume.assert_not_called()

    def test_with_no_executor_the_seats_own_model_fixes(self):
        def by_role(cfg, providers, workers=None, log=None, **kw):
            return ["astra"] if kw.get("role") == "reviewer" else []

        with patch.object(run, "ready_order", side_effect=by_role):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(state["executor"], "opus")

    def test_a_fixer_that_commits_nothing_has_the_same_head_reviewed_again(self):
        self.fix = lambda lp: None
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([s["head_sha"] for s in state["round_summaries"]], [self.heads[0]] * 2)
        self.assertEqual(len(self.fixes), 1)
        self.assertEqual(self.merges[0][-1], self.heads[0])

    def test_a_head_pushed_by_hand_before_the_fix_is_reviewed_instead(self):
        post = run.post_review

        def then_pushed_by_hand(lp, url, verdict, **_kw):
            posted = post(lp, url, verdict)
            if verdict == "FAIL":
                self.hand_push(1)
            return posted

        with patch.object(run, "post_review", side_effect=then_pushed_by_hand):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(self.fixes, [])
        self.assertEqual([s["head_sha"] for s in state["round_summaries"]], self.heads[:2])

    def test_a_head_pushed_by_hand_during_the_fix_ends_the_run(self):
        fix = self.fix

        def raced(lp):
            fix(lp)                     # the fixer's commit ...
            self.hand_push(2)           # ... and the seat's force-push meanwhile

        self.fix = raced
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertIn("moved while the fix was made", state["error"])
        self.assertEqual(self.remote_head(), self.heads[2])     # the hand push stands
        self.assertEqual((len(self.prompts), len(self.fixes)), (1, 1))
        self.assertNotIn("own_pr_wait", state)

    def test_a_fixer_turn_cut_off_after_its_commit_keeps_that_commit(self):
        fix = self.fix

        def cut_off(lp):
            if len(self.fixes) == 1:
                fix(lp)                 # the commit lands ...
                raise InterruptedError("... and the host cuts the turn off before ak records it")
            # resumed on the checkout as it was left: nothing reset it to the reviewed head
            self.assertEqual(run.git(lp.wt, "rev-parse", "HEAD"), self.heads[1])

        self.fix = cut_off
        with self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        self.assertEqual(run.git(saved["worktree"], "rev-parse", "HEAD"), self.heads[1])
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(self.remote_head(), self.heads[1])
        self.assertEqual((len(self.fixes), len(self.prompts)), (2, 2))    # the turn resumed, once

    def test_a_finished_fixer_turn_is_never_run_again(self):
        self.fix = lambda lp: None      # it handed in a dispute and committed nothing
        moves = []

        def moved(lp, **_kw):
            moves.append(lp.rnd)
            if len(moves) == 1:
                raise InterruptedError("the process moved onto new code right after the fix")
            return False

        with patch.object(run, "pickup_new_code", side_effect=moved), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual((len(self.fixes), len(self.prompts)), (1, 2))    # no second turn
        self.assertEqual([s["head_sha"] for s in state["round_summaries"]], [self.heads[0]] * 2)

    def test_a_crash_after_the_push_pushes_nothing_again_and_reviews(self):
        pushes = []
        git_out = run.git_out

        def dies_after_push(cwd, *args, **kw):
            result = git_out(cwd, *args, **kw)
            if args[0] == "push":
                pushes.append(args)
                raise InterruptedError("the run died after its push")
            return result

        with patch.object(run, "git_out", side_effect=dies_after_push), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        self.assertEqual(saved["delivery_sha"], self.heads[1])
        self.assertEqual(self.remote_head(), self.heads[1])
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        with patch.object(run, "git_out", side_effect=dies_after_push):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual((len(pushes), len(self.fixes), len(self.prompts)), (1, 1, 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
