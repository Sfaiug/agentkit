"""A FAIL on a seat's own pull request is fixed by ak, never handed to the seat.

With rounds left, the run takes a fixer turn on its own checkout of the reviewed head -- the
seat's own orchestrator model, headless -- commits what the turn left,
pushes it to the PR branch over the reviewed head and reviews it in the next round.  Nothing
is typed into the seat and no process waits for a push.  A head pushed by hand before the fix
is what the next round reviews; one pushed while the fix was made ends the run.  Offline, on
the `fixtures.own_pr` stage.
"""

import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from fixtures.own_pr import OwnPr
from agentkit import config, hand_in, run, worker
from agentkit import record


class OwnPrFixer(OwnPr):
    def test_a_fail_is_fixed_on_the_prs_branch_and_reviewed_again(self):
        def leaves_a_fix(lp):           # the fixer edits and never commits: ak commits what it left
            (lp.wt / "fence.txt").write_text("mended\n")

        self.fix = leaves_a_fix
        clock = self.stack.enter_context(patch.object(run, "time", wraps=time))
        clock.sleep.side_effect = lambda _seconds: self.fail("the run slept instead of fixing")
        with patch.object(run, "ready_order", return_value=["astra", "opus"]):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
        # the seat's own model fixes its PR, and the reviewer is picked against it both rounds
        self.assertEqual((state["executor"], self.reviewers), ("opus", ["astra", "astra"]))
        [fix] = self.fixes
        self.assertIn("## Reviewer findings to fix", fix)
        self.assertIn("defect 1", fix)
        self.assertIn(f"Repo checkout: {state['worktree']}", fix)
        self.assertIn("# acme", fix)                        # the repository's rules ride along
        # ... told to fix, with what the PR says and its checks, never the reviewer's goal
        self.assertIn("# Fix PR #7: Mend the fence\n\n## Goal\nThe pull request passes its review", fix)
        self.assertIn("## The PR says\nFix the fence", fix)
        self.assertIn("## Done when", fix)
        self.assertNotIn("Judge https://", fix)
        self.assertNotIn("is a finding", fix)
        fixed = state["round_summaries"][1]["head_sha"]
        self.assertNotEqual(fixed, self.heads[0])
        self.assertEqual(self.remote_head(), fixed)         # pushed to the PR branch
        self.assertEqual(run.git(self.repo, "show", f"{fixed}:fence.txt"), "mended")
        self.assertEqual(self.notices, [])                  # nothing typed into the seat
        self.kill.assert_not_called()
        self.resume.assert_not_called()

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

    def test_a_turn_handed_to_another_model_is_resumed_by_it_and_reviewed_against_it(self):
        fix = self.fix

        def handed_over(lp):
            if len(self.fixes) == 1:
                # execute handed the turn to astra, which the host then cut off mid-way
                out = run.free_dir(lp, "executor-astra")
                out.mkdir(parents=True)
                (out / hand_in.FILE).write_text(json.dumps(
                    {"kind": "turn", "workspace": str(lp.wt), "role": "fixer", "findings": []}) + "\n")
                lp.executor = lp.state["executor"] = "astra"
                lp.state.setdefault("executor_history", []).append(
                    {"at": 1.0, "from": "opus", "to": "astra", "reason": "dry"})
                lp.save()
                raise InterruptedError("the host cut astra's turn off")
            if len(self.fixes) == 2:
                self.assertEqual((self.fix_names[-1], lp.executor), ("executor-astra", "astra"))
            fix(lp)

        self.fix = handed_over
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra", "grok"])
        with patch.object(run, "ready_order", return_value=["opus", "astra", "grok"]), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        with patch.object(run, "ready_order", return_value=["opus", "astra", "grok"]):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(state["executor"], "opus")            # round three's fix was the orchestrator's own
        # from round two on, the reviewer wrote none of the head: neither the PR's orchestrator
        # nor a model any fix was handed to comes first while another is ready, however many
        # fixes later
        self.assertEqual(self.reviewers, ["astra", "grok", "grok"])

    def test_what_the_fixer_said_reaches_the_next_reviewer(self):
        self.fix = lambda lp: None
        self.fix_summary = "## Summary\nWHY-MARKER: the flag is read by nobody; nothing to fix."
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertIn("## What the fixer said\n## Summary\nWHY-MARKER", self.prompts[1])
        self.assertNotIn("fix_summary", state)

    def test_what_the_fixer_said_reaches_a_reviewer_resumed_after_a_cut(self):
        self.fix = lambda lp: None
        self.fix_summary = "## Summary\nWHY-MARKER: the flag is read by nobody; nothing to fix."
        reviewer, cut = self.reviewer, []

        def cut_off(cfg, name, body, *args, **kwargs):
            if len(self.prompts) == 1 and not cut:        # round two's first reviewer call
                cut.append(body)
                raise InterruptedError("the host cut the reviewer off")
            return reviewer(cfg, name, body, *args, **kwargs)

        with patch.object(worker, "call", side_effect=submitting(cut_off)), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertIn("## What the fixer said\n## Summary\nWHY-MARKER", self.prompts[1])

    def test_a_push_while_the_cut_off_fix_was_made_ends_the_run_fail(self):
        fix = self.fix

        def pushed_over(lp):
            fix(lp)                     # the fix committed ...
            self.hand_push(2)           # ... the seat pushed meanwhile ...
            raise InterruptedError("the host cut the fixer off before its push")

        self.fix = pushed_over
        with self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "fail")
        self.assertIn("the PR head moved while the fix was made", state["error"])
        self.assertEqual((len(self.prompts), self.merges, self.remote_head()), (1, [], self.heads[2]))

    def test_a_push_right_after_the_fix_was_pushed_is_what_the_next_round_reviews(self):
        push = run.push_pr_branch

        def then_the_seat(lp, remote, reviewed):
            push(lp, remote, reviewed)
            self.hand_push(2)
            self.assertEqual(run.git(lp.wt, "rev-parse", "HEAD"), self.heads[1])   # the fix, not the seat's head

        with patch.object(run, "push_pr_branch", side_effect=then_the_seat):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(self.merges[0][-1], self.heads[2])

    def test_a_pr_closed_or_pushed_while_a_fix_without_a_commit_was_made_ends_the_run(self):
        self.fix = lambda lp: self.pr.update(state="CLOSED")       # closed during the fix, which committed nothing
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "fail")
        self.assertIn("not open", state["error"])
        self.assertEqual((len(self.prompts), self.merges), (1, []))
        self.setUp()
        self.fix = lambda lp: self.hand_push(2)                     # the seat pushed during the fix
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "fail")
        self.assertIn("the PR head moved while the fix was made", state["error"])
        self.assertEqual((len(self.prompts), self.merges, self.remote_head()), (1, [], self.heads[2]))

    def test_the_fixer_is_given_the_whole_pr_description(self):
        self.pr["body"] = "## Summary\nFix the fence\n\n## Test plan\nrun it"
        self.review(["FAIL", "PASS"])
        [fix] = self.fixes
        self.assertIn("## The PR says\n## Summary\nFix the fence\n\n## Test plan\nrun it", fix)

    def test_a_turn_handed_to_another_model_mid_way_is_read_where_it_finished(self):
        fix = self.fix

        def handed_over(lp):
            fix(lp)                                     # the fix lands under the second model ...
            out = run.free_dir(lp, "executor-astra")     # ... whose turn closed under its own name
            out.mkdir(parents=True)
            (out / hand_in.FILE).write_text("".join(json.dumps(row) + "\n" for row in (
                {"kind": "turn", "workspace": str(lp.wt), "role": "fixer", "findings": []},
                {"kind": "done"})))
            (out / "final.md").write_text("## Summary\nFixed.")
            raise InterruptedError("the run died before recording the fix; the first dir stays open")

        self.fix = handed_over
        with self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(self.remote_head(), self.heads[1])
        self.assertEqual((len(self.fixes), len(self.prompts)), (1, 2))    # no turn run again

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
