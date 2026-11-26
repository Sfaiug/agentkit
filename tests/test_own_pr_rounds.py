"""Own PRs carry findings across rounds, while other PRs get one review.

Offline, on the `fixtures.own_pr` stage: a real PR branch and remote; GitHub, the reviewer,
the fixer, seats and processes are fakes.  A push by hand between rounds is the next head
reviewed; a crash anywhere resumes without repeating a round.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from fixtures.own_pr import BRANCH, OwnPr, URL
from agentkit import config, deliver, gitcall, history, round_tests, roundloop, run, worker, worktrees
from agentkit import record


class OwnPrRounds(OwnPr):
    def test_fail_fix_pass_in_round_two_merges(self):
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(state["state"], "pass")
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
        self.assertEqual(len(self.fixes), 1)
        self.assertIn("defect 1", self.prompts[1])
        self.assertIn("re-proven by ak", self.prompts[1])
        self.assertEqual(self.sessions, [None, None])      # a new round resumes no reviewer's conversation
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.merges[0][-1], self.heads[1])

    def test_three_fails_end_with_the_last_findings(self):
        # with no extra round for the one finding the third left
        record.save_state(self.run_dir, {**record.read_state(self.run_dir),
                                         "policy": {**config.policy(), "extra_rounds": 0}})
        state = self.review(["FAIL", "FAIL", "FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual(len(self.fixes), 2)
        self.assertIn("defect 2", self.prompts[2])
        self.assertFalse(state["merged"])
        self.assertEqual(self.merges, [])
        result = (self.run_dir / "result.md").read_text()
        self.assertIn("defect 3", result)
        self.assertNotIn("defect 1", result)
        self.assertEqual(self.notices, [])          # no round was handed back
        run.announce(state, self.run_dir, lambda _: None, self.cfg)
        self.assertIn("defect 3", self.notices[-1])
        self.assertIn("Next: split the task.", self.notices[-1])

    def test_a_resume_of_a_review_that_ended_fail_spends_no_extra_round(self):
        # ended after three with one finding left, as a review did before it could go on
        self.test_three_fails_end_with_the_last_findings()
        saved = record.read_state(self.run_dir)
        saved.update(state="queued", pid=999999991, recovery_pending=True,
                     policy={**saved["policy"], "extra_rounds": 2})
        record.save_state(self.run_dir, saved)
        with self.assertRaisesRegex(config.Error, "3 review rounds spent on PR #7 across 1 run"):
            self.review(["FAIL", "FAIL", "FAIL", "PASS"])
        self.assertEqual((len(self.prompts), len(self.fixes)), (3, 2))

    def test_an_extra_round_cut_off_before_its_review_is_reviewed_on_its_resume(self):
        def dies_in_round_four(*_args, **_kw):
            if record.read_state(self.run_dir).get("own_pr_round_pending") == 4:
                raise InterruptedError("the process died before the fourth review")
            return {}

        with patch.object(run, "collect_usage", side_effect=dies_in_round_four), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "FAIL", "FAIL", "PASS"])
        self.assertNotIn("own_pr_wait", record.read_state(self.run_dir))
        state = self.review(["FAIL", "FAIL", "FAIL", "PASS"])
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL"] * 3 + ["PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(self.merges[0][-1], self.heads[3])

    def test_a_pr_closed_during_the_fix_ends_the_run(self):
        fix = self.fix

        def closing(lp):
            fix(lp)
            self.pr["state"] = "CLOSED"

        self.fix = closing
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual((len(self.fixes), len(self.prompts)), (1, 1))
        self.assertIsNotNone(state["finished_at"])
        self.assertIn("closed", state["error"].lower())
        self.assertIn("defect 1", (self.run_dir / "result.md").read_text())
        self.assertEqual(self.merges, [])
        self.assertEqual(self.remote_head(), self.heads[0])      # nothing is pushed to a closed PR

    def test_other_pr_fail_keeps_its_single_review(self):
        self.pr["author"] = "contributor"
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.fixes, [])
        self.assertEqual(self.events, ["event=REQUEST_CHANGES"])

    def test_a_crash_in_the_fixer_turn_resumes_it_without_repeating_the_review(self):
        fix = self.fix

        def dies_first(lp):
            if len(self.fixes) == 1:
                raise InterruptedError("fixture: the loop died mid-turn")
            fix(lp)

        self.fix = dies_first
        with self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = record.read_state(self.run_dir)
        self.assertEqual(saved["own_pr_wait"], self.heads[0])
        self.assertEqual(len(saved["round_summaries"]), 1)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual((len(self.prompts), len(self.fixes)), (2, 2))
        self.assertEqual(self.notices, [])

    def test_a_github_read_that_fails_before_the_fix_is_retried_from_the_fix(self):
        gh_json = self.gh_json

        def unavailable(cwd, *args, **kw):
            if args[:2] == ("api", "repos/acme/widget/pulls/7"):
                return None, "fixture: GitHub unavailable"
            return gh_json(cwd, *args, **kw)

        with patch.object(deliver, "gh_json", side_effect=unavailable), self.assertRaises(config.Error):
            self.review(["FAIL", "PASS"])
        self.assertEqual(self.fixes, [])
        self.assertEqual(record.read_state(self.run_dir)["own_pr_wait"], self.heads[0])
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual((len(self.prompts), len(self.fixes)), (2, 1))

    def assert_resumed_post_finishes_round_one(self):
        saved = record.read_state(self.run_dir)
        self.assertEqual(len(saved["round_summaries"]), 1)
        saved.update(state="queued", pid=999999991)
        record.save_state(self.run_dir, saved)
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([(s["round"], s["head_sha"]) for s in state["round_summaries"]],
                         [(1, self.heads[0]), (2, self.heads[1])])
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(self.notices, [])
        self.assertEqual(len(self.fixes), 1)
        self.assertEqual(self.merges[0][-1], self.heads[1])

    def test_killed_while_posting_resumes_the_recorded_round(self):
        def killed(cwd, *args, **_kw):
            if args[0] == "api":
                raise InterruptedError("fixture: loop died while posting")
            return self.gh(cwd, *args)

        with patch.object(gitcall, "gh", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        self.assert_resumed_post_finishes_round_one()
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])

    def test_killed_after_posting_resumes_before_the_fix(self):
        post = run.post_review

        def killed(lp, url, verdict, **_kw):
            post(lp, url, verdict)
            raise InterruptedError("fixture: loop died after posting")

        with patch.object(run, "post_review", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        self.assert_resumed_post_finishes_round_one()
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])

    def test_failed_post_retries_without_spending_another_round(self):
        with patch.object(gitcall, "gh", return_value=(1, "HTTP 502: fixture")):
            state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "error")
        self.assertTrue(worktrees.resume_holds_tree(state, self.run_dir))
        self.assert_resumed_post_finishes_round_one()

    def test_round_three_pass_with_a_failed_post_can_still_merge(self):
        def failed(cwd, *args, **_kw):
            if args[0] == "api" and len(self.prompts) == 3:
                return 1, "HTTP 502: fixture"
            return self.gh(cwd, *args)

        with patch.object(gitcall, "gh", side_effect=failed):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertEqual(state["state"], "error")
        state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "FAIL", "PASS"])
        self.assertEqual(len(self.prompts), 3)
        self.assertEqual(self.merges[0][-1], self.heads[2])

    def assert_moved_round_merges(self, state):
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertNotIn("own_pr_round_pending", state)
        self.assertEqual([(s["round"], s["head_sha"]) for s in state["round_summaries"]],
                         list(enumerate(self.heads[:3], 1)))
        self.assertEqual(len(self.prompts), 3)
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.merges[0][-1], self.heads[2])
        self.assertEqual(len(self.fixes), 1)           # round two's fix; the hand push needed none
        self.assertEqual(self.notices, [])

    def test_a_push_by_hand_during_the_review_is_what_the_next_round_judges(self):
        def moved(*args, **kw):
            answer = self.reviewer(*args, **kw)
            if len(self.prompts) == 2:
                self.hand_push(2)
            return answer

        with patch.object(worker, "call", side_effect=submitting(moved)):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assert_moved_round_merges(state)
        self.assertIn("defect 2", self.prompts[2])          # round two's finding, re-proven on the pushed head
        self.assertIn("re-proven by ak", self.prompts[2])

    def test_a_push_by_hand_during_a_pass_is_reviewed_before_merging(self):
        def moved(*args, **kw):
            answer = self.reviewer(*args, **kw)
            if len(self.prompts) == 2:
                self.hand_push(2)
            return answer

        with patch.object(worker, "call", side_effect=submitting(moved)):
            state = self.review(["FAIL", "PASS", "PASS"])
        self.assert_moved_round_merges(state)

    def test_pending_round_resumes_after_a_push_by_hand_during_the_review(self):
        def killed(lp, url, verdict, **_kw):
            if len(self.prompts) == 2:
                self.hand_push(2)
                raise InterruptedError("fixture: loop died before posting the moved head")
            return post(lp, url, verdict)

        post = run.post_review
        with patch.object(run, "post_review", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "FAIL", "PASS"])
        self.assertEqual(record.read_state(self.run_dir)["own_pr_round_pending"], 2)
        self.assert_moved_round_merges(self.review(["FAIL", "FAIL", "PASS"]))
        self.assertIn("defect 2", self.prompts[2])

    def test_failed_post_resumes_on_a_new_head(self):
        def failed(cwd, *args, **_kw):
            if args[0] == "api" and len(self.prompts) == 2:
                return 1, "HTTP 502: fixture"
            return self.gh(cwd, *args)

        with patch.object(gitcall, "gh", side_effect=failed):
            state = self.review(["FAIL", "PASS", "PASS"])
        self.assertEqual(state["state"], "error")
        self.hand_push(2)
        self.assert_moved_round_merges(self.review(["FAIL", "PASS", "PASS"]))

    def test_closed_pr_settles_a_pending_round(self):
        with patch.object(gitcall, "gh", return_value=(1, "HTTP 502: fixture")):
            self.assertEqual(self.review(["FAIL"])["state"], "error")
        self.pr["state"] = "CLOSED"
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertIsNotNone(state["finished_at"])
        self.assertNotIn("own_pr_round_pending", state)
        self.assertIn("closed", state["error"].lower())
        self.assertIn("defect 1", (self.run_dir / "result.md").read_text())
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.fixes, [])
        self.assertEqual(self.events, [])
        self.assertEqual(self.merges, [])

    def test_a_push_by_hand_during_round_three_ends_without_a_fourth_review(self):
        def moved(*args, **kw):
            answer = self.reviewer(*args, **kw)
            if len(self.prompts) == 3:
                self.hand_push(3)
            return answer

        with patch.object(worker, "call", side_effect=submitting(moved)):
            state = self.review(["FAIL", "FAIL", "PASS"])
        self.assertEqual(state["state"], "fail")
        self.assertIsNotNone(state["finished_at"])
        self.assertNotIn("own_pr_round_pending", state)
        self.assertIn("head changed", state["error"])
        self.assertEqual(len(self.prompts), 3)
        self.assertEqual(self.merges, [])

    def test_killed_after_merge_settles_without_another_merge(self):
        merge = run.merge_own_pr

        def killed(lp, url, **_kw):
            merge(lp, url)
            self.pr["state"] = "MERGED"
            raise InterruptedError("fixture: loop died after merging")

        with patch.object(run, "merge_own_pr", side_effect=killed), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertFalse(state.get("merge_failed"))
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(len(self.merges), 1)

    def test_a_crash_before_the_new_heads_review_leaves_it_to_be_reviewed(self):
        def dies_once_checked_out(*_args, **_kw):
            if record.read_state(self.run_dir).get("head_sha") == self.heads[1]:
                raise InterruptedError("the process died before the new head's review")
            return {}

        with patch.object(run, "collect_usage", side_effect=dies_once_checked_out), self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        state = record.read_state(self.run_dir)
        self.assertEqual(run.git(state["worktree"], "rev-parse", "HEAD"), self.heads[1])
        self.assertNotIn("review", state)      # the old head's review went with its round
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual((len(self.prompts), len(self.fixes)), (2, 1))

    def test_a_crash_right_after_checking_out_the_new_head_is_resumed(self):
        git = run.git

        def dies_after_reset(cwd, *args, **kw):
            result = git(cwd, *args, **kw)
            # the review checkout's reset onto the pushed fix, not the fixer's own
            if args == ("reset", "--hard", self.heads[1]) and self.remote_head() == self.heads[1]:
                raise InterruptedError("the process died after the reset, before recording it")
            return result

        with patch.object(run, "git", side_effect=dies_after_reset), \
                self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        state = self.review(["FAIL", "PASS"])
        self.assertEqual(state["head_sha"], self.heads[1])
        self.assertTrue(state["merged"])

    def test_an_own_prs_first_review_is_refused_past_the_ceiling(self):
        self.hand_push(1)                               # 5000 added lines of fence.txt
        with patch.object(run, "ready_order", return_value=[]):     # decided from git alone: no reviewer is picked first
            state = self.review([])
        self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
        self.assertIn("PR #7 adds 5000 lines", state["error"])
        self.assertIn("Write it as a task", state["blocked"])
        self.assertEqual((self.prompts, self.merges), ([], []))

    def test_a_checks_only_own_pr_is_still_held_to_the_seat_size_cap(self):
        for label, extra in (("review_rounds_zero", {"policy": {"review_rounds": 0}}),
                             ("no_reviewers", {"reviewers": []})):
            with self.subTest(mode=label):
                self.hand_push(1)                       # 5000 added lines of fence.txt
                run_dir = config.RUNS / f"checks-only-over-{label}"
                run_dir.mkdir()
                (run_dir / "log.txt").touch()
                run.capture_launch(run_dir, {"--review-pr": URL})
                with record.record(run_dir) as saved:
                    saved.update(extra)
                with patch.object(run, "verify_work", side_effect=AssertionError("verified")):
                    state = run.review_pr(self.cfg, run_dir, URL,
                                          {"--review": None, "--review-pr": URL}, lambda _: None)
                self.assertEqual((state["state"], state["verdict"]), ("blocked", "BLOCKED"))
                self.assertIn("PR #7 adds 5000 lines", state["error"])
                self.assertEqual((self.prompts, self.merges), ([], []))
        # within the seat cap a checks-only run lands without recording a first-review size
        self.hand_push(0)
        with record.record(self.run_dir) as saved:
            saved["policy"] = {"review_rounds": 0}
        state = self.review([])
        self.assertEqual((state["state"], state["merged"]), ("pass", True))
        self.assertIsNone(history.get(self.run_dir.name)["first_review_lines"])

    def test_a_later_review_of_the_pr_in_a_new_run_reviews_what_the_fix_left(self):
        earlier = config.RUNS / "own-pr-earlier"        # an earlier run spent round 1 on this PR
        earlier.mkdir()
        record.save_state(earlier, {"run_id": earlier.name, "state": "blocked", "review_pr": URL, "pr": URL,
                                    "launched_session": "fix-api", "own_pr": True,
                                    "round_summaries": [{"round": 1, "verdict": "FAIL", "summary": ""}]})
        self.hand_push(1)                               # the fix left 5000 added lines
        self.assertEqual(self.review(["PASS"])["verdict"], "PASS")

    def test_a_round_under_way_elsewhere_is_no_review_of_the_pr(self):
        earlier = config.RUNS / "own-pr-earlier"        # holds round 1, with no verdict yet
        earlier.mkdir()
        record.save_state(earlier, {"run_id": earlier.name, "state": "running", "review_pr": URL, "pr": URL,
                                    "step": "executor", "step_round": 1, "round_summaries": []})
        self.hand_push(1)                               # 5000 added lines of fence.txt
        state = self.review(["PASS"])
        self.assertEqual((state["state"], self.prompts), ("blocked", []))

    def test_a_seat_renamed_mid_review_keeps_its_name_through_a_blocked_ending(self):
        def blocked(lp, *_a, **_kw):
            with record.record(lp.run_dir) as current:      # the seat is renamed during the review
                current["launched_session"] = "fix-api-renamed"
            raise run.Blocked("no reviewer can run", "## Blocked\n\nno reviewer can run")
        with patch.object(run, "review", side_effect=blocked):
            self.review([])
        state = record.read_state(self.run_dir)
        self.assertEqual((state["state"], state["launched_session"]), ("blocked", "fix-api-renamed"))

    def test_a_head_change_before_posting_a_rescoped_round_keeps_the_rescope_reason(self):
        with record.record(self.run_dir) as saved:
            saved["policy"] = {**config.policy(), "rescope_findings": 1}
        post = run.post_review

        def moved(lp, url, verdict):
            if lp.rnd == 1:
                self.hand_push(1)
            return post(lp, url, verdict)

        with patch.object(run, "post_review", moved):
            state = self.review(["FAIL", "PASS"])
        why = "The review left 1 blocking finding, at or past rescope_findings = 1: rescope the task."
        self.assertEqual((state["state"], state["rounds"], state["error"]), ("fail", 1, why))
        self.assertEqual((len(self.prompts), self.fixes), (1, []))
        self.assertIn(why, (self.run_dir / "result.md").read_text())

    def test_somebody_elses_pr_is_reviewed_whatever_its_size(self):
        self.pr.update(author="stranger")
        self.hand_push(1)
        state = self.review(["PASS"])
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(len(self.prompts), 1)

    def test_chosen_tests_changing_tracked_files_are_saved_and_restored(self):
        def dirty(lp, named, head):
            (lp.wt / "fence.txt").write_text("dirty from tests\n")
            return True, "$ suite\n[exit 0]"

        with patch.object(round_tests, "chosen", return_value=("true", ["tests/often.sh"])), \
                patch.object(roundloop, "chosen_tests", side_effect=dirty):
            state = self.review(["PASS"])
        self.assertEqual((state["state"], state["verdict"], state["merged"]), ("pass", "PASS", True))
        self.assertIn("dirty from tests", (self.run_dir / "tests-changes.patch").read_text())
        self.assertEqual(run.git(state["worktree"], "status", "--porcelain"), "")

    def test_chosen_tests_moving_head_end_the_run_with_restore_error(self):
        def move_head(lp, named, head):
            run.git(lp.wt, "commit", "--allow-empty", "-qm", "moved")
            return True, "$ suite\n[exit 0]"

        with patch.object(round_tests, "chosen", return_value=("true", ["tests/often.sh"])), \
                patch.object(roundloop, "chosen_tests", side_effect=move_head):
            with self.assertRaisesRegex(config.Error, "review checkout HEAD changed during tests"):
                self.review(["PASS"])
        self.assertEqual(self.merges, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
