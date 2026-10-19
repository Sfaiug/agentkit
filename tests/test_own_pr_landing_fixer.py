"""A seat's own PR red at landing gets the run's fixer turn and a re-review that spends no round.

The line's check, a required check or a rebase the tip conflicts with: the fixer turn on the PR
branch as for review findings, then a re-review in the round whose PASS it repairs that enters
no round history, however the round budget stands, up to three times for one landing.  A PR
moved past its review, in the line or under its delivery, is reviewed as a round, as any new
head is.  Offline: the own-PR line fixture's local Git, fake GitHub, reviewers and seats.
"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_own_pr_line as line
from agentkit import deliver, hand_in, history, land, record, roundloop, run, turns, worker
from fixtures.hand_in import submitting


class OwnPrLandingFixer(line.OwnPrLineFixture, unittest.TestCase):
    def red_landing(self, name="second"):
        directory, url = self.own_pr(name, 1)
        self.review(directory, url)
        self.advance(**{"first.txt": "first\n"})     # the target's move makes the PR's tree red
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        return directory, url

    def fixer(self, url, rename=True):
        def fixed(cfg, directory, url_, state, opts, log):
            self.assertTrue(state["landing_fix"])
            self.assertIn("## Landing failed", state["findings"])
            self.push_fix(url, rename=rename)
            state["delivery_sha"] = self.prs[url]["head"]     # as fix_own_pr records its push
            record.save_state(directory, state)
            return True
        return patch.object(run, "fix_own_pr", side_effect=fixed)

    def fixer_turns(self, *edits):
        """`run.fix_own_pr` itself, its model faked: turn n stages `edits[n]` on the checkout,
        commits it and hands in done; the PR's head follows what the run pushes."""
        self.turns = []

        def execute(lp, role, _text, name):
            self.turns.append(name)
            out = turns.free_dir(lp, name)
            out.mkdir(parents=True)
            edits[len(self.turns) - 1](lp.wt)
            run.git(lp.wt, "-c", "user.name=f", "-c", "user.email=f@localhost", "commit", "-qm", name)
            rows = [{"kind": "turn", "workspace": str(lp.wt), "role": role, "findings": []}, {"kind": "done"}]
            (out / hand_in.FILE).write_text("".join(json.dumps(row) + "\n" for row in rows))
            (out / "final.md").write_text("## Summary\nFixed.")
            return "## Summary\nFixed."

        def view(url):
            pr = self.prs[url]
            pr["head"] = run.git(self.remote, "rev-parse", pr["branch"])
            return self.view(url)

        self.stack.enter_context(patch.object(run, "execute", side_effect=execute))
        self.stack.enter_context(patch.object(run, "pr_view", side_effect=view))

    @staticmethod
    def rename(wt):
        run.git(wt, "mv", "second.txt", "repaired.txt")

    def push(self, url):
        """The seat pushes a commit of its own onto the PR branch as origin holds it now."""
        pr = self.prs[url]
        run.git(self.repo, "fetch", "origin", pr["branch"])
        run.git(self.repo, "checkout", "-B", pr["branch"], "FETCH_HEAD")
        (self.repo / "fix.txt").write_text("seat\n")
        self.commit("the seat push")
        run.git(self.repo, "push", "origin", pr["branch"])
        pr["head"] = run.git(self.repo, "rev-parse", "HEAD")

    def seat_push_after_the_landing_fix(self, spent):
        """A landing red, its fixer turn, and the seat's own push landing between the fixer's
        push and the re-review's read of the PR: (the run's state, the reviews made, the seat's
        head)."""
        directory, url = self.red_landing()
        with record.record(directory) as state:
            first = state["round_summaries"][0]
            state["round_summaries"] = [{**first, "round": n} for n in range(1, spent + 1)]
        self.fixer_turns(self.rename)
        seen = len(self.reviews)
        with patch.object(run, "pickup_new_code", side_effect=lambda *a, **k: self.push(url)):
            state = self.review(directory, url)
        return state, self.reviews[seen:], self.prs[url]["head"]

    def test_a_seat_push_right_after_the_landing_fix_push_spends_a_round(self):
        state, reviews, seat = self.seat_push_after_the_landing_fix(1)
        self.assertEqual(state["head_sha"], seat)
        self.assertEqual(len(state["round_summaries"]), 2)
        self.assertNotIn("landing_fix", state)
        self.assertFalse(any("Re-review after the landing fix" in body for body in reviews))

    def test_past_the_budget_a_seat_push_right_after_the_landing_fix_push_is_not_reviewed(self):
        state, reviews, seat = self.seat_push_after_the_landing_fix(3)
        self.assertEqual(state["head_sha"], seat)
        self.assertEqual(reviews, [])
        self.assertEqual(state["state"], "fail")
        self.assertIn("3 review rounds spent on PR #1", state["error"])

    def test_the_fix_is_re_reviewed_without_a_round_and_lands(self):
        directory, url = self.red_landing()
        checks = len(self.checks)
        with self.fixer(url):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertNotIn("landing_fix", state)
        self.assertIn("Re-review after the landing fix", self.reviews[-1])
        self.assertIn("Landing failed", self.reviews[-1])
        self.assertEqual(len(self.checks), checks, "the re-review ran a suite")
        # its suite went red after review passed it: one break at landing, on its row
        self.assertEqual(history.get(directory.name)["landing_breaks"], 1)
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"])
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertEqual(len(self.reviews), 2)

    def test_past_the_round_budget_the_landing_red_still_gets_its_fixer(self):
        directory, url = self.own_pr("second", 1)
        self.review(directory, url)
        with record.record(directory) as state:
            first = state["round_summaries"][0]
            state["round_summaries"] = [{**first, "round": n} for n in (1, 2, 3)]
        self.advance(**{"first.txt": "first\n"})
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        with self.fixer(url):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2, 3])
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.reviews), 2)

    def test_a_red_required_check_gets_the_fixer_without_a_round(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        land.check_line(self.turn)
        self.assertIn("land", self.wait(directory))
        with patch.object(deliver, "checks", return_value=(False, "required checks failed: fence")):
            self.review(directory, url)
        # Parked on the fix: its fixer waits for a fix's admission, on the lander's wake.
        self.assertIn("fix", self.wait(directory))
        land.check_line(self.turn)
        with self.fixer(url, rename=False):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertIn("required checks failed: fence", self.reviews[-1])
        self.assertEqual(history.get(directory.name)["landing_breaks"], 1)
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"])

    def test_a_rebase_the_tip_conflicts_with_is_a_landing_red_of_the_fixers(self):
        directory, url = self.own_pr("second", 1)
        self.review(directory, url)
        self.on_main(lambda: (self.repo / "second.txt").write_text("the target's second\n"),
                     "the target takes the PR's file")
        land.check_line(self.turn)
        self.assertIn("rebase of origin/main failed", self.wait(directory)["fix"]["line"])
        pr = self.prs[url]

        def rebased(cfg, directory_, url_, state, opts, log):
            self.assertTrue(state["landing_fix"])
            self.assertIn("rebase of origin/main failed", state["findings"])
            run.git(self.repo, "checkout", pr["branch"])
            run.git(self.repo, "fetch", "origin", "main")
            self.assertNotEqual(run.git_out(self.repo, "rebase", "origin/main")[0], 0)
            run.git(self.repo, "checkout", "--theirs", "second.txt")
            run.git(self.repo, "add", "second.txt")
            run.git(self.repo, "-c", "core.editor=true", "rebase", "--continue")
            run.git(self.repo, "push", "--force", "origin", pr["branch"])
            pr["head"] = run.git(self.repo, "rev-parse", "HEAD")
            state["delivery_sha"] = pr["head"]     # as fix_own_pr records its push
            record.save_state(directory_, state)
            return True

        with patch.object(run, "fix_own_pr", side_effect=rebased):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 1)
        # a rebase the target conflicts with says nothing about what review let through
        self.assertFalse(history.get(directory.name)["landing_breaks"])
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"])

    def test_a_second_red_landing_gets_a_fixer_turn_of_its_own(self):
        def note(wt):       # a fix that leaves the tree red
            (wt / "note.txt").write_text("note\n")
            run.git(wt, "add", "note.txt")

        self.fixer_turns(note, self.rename)
        directory, url = self.red_landing()
        self.review(directory, url)
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        state = self.review(directory, url)
        self.assertEqual(self.turns, ["landing-1-fixer", "landing-2-fixer"])
        self.assertEqual(len(state["round_summaries"]), 1)
        land.check_line(self.turn)
        self.assertTrue(self.review(directory, url)["merged"])

    def test_a_failed_landing_re_review_gets_a_fixer_round(self):
        def mend(wt):
            (wt / "repaired.txt").write_text("mended\n")
            run.git(wt, "add", "repaired.txt")

        def reviewer(_cfg, _name, body, _wt, out, *_args, **_kw):
            self.reviews.append(body)
            verdict = verdicts.pop(0)
            text = ("## Findings\n- repaired.txt:1 - defect - wrong\n" if verdict == "FAIL"
                    else "## Findings\n- none\n") + f"VERDICT: {verdict}\n"
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text(text)
            return 0, text, "fixture-review", False

        self.fixer_turns(self.rename, mend)
        directory, url = self.red_landing()
        verdicts = ["FAIL", "PASS"]
        with patch.object(worker, "call", side_effect=submitting(reviewer)):
            state = self.review(directory, url)
        self.assertEqual(self.turns, ["landing-1-fixer", "executor"])
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2])
        self.assertEqual(state["state"], "waiting")

    def test_a_landing_re_review_whose_post_failed_is_posted_not_reviewed_again(self):
        directory, url = self.red_landing()
        with self.fixer(url), patch.object(run, "post_review", return_value=False):
            state = self.review(directory, url)
        self.assertEqual((state["state"], len(self.reviews)), ("error", 2))
        state = self.review(directory, url)
        self.assertEqual((state["state"], len(self.reviews)), ("waiting", 2))

    def test_a_fourth_red_landing_ends_fail(self):
        directory, url = self.red_landing()
        with record.record(directory) as state:
            state["landing_reds"] = roundloop.CONFLICT_ROUNDS
        with patch.object(run, "fix_own_pr", side_effect=AssertionError("a fourth landing fixer")):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "fail")
        self.assertIn("landing failed 4 times", state["merge_note"])
        self.assertNotIn("own_pr_wait", state)
        self.assertNotIn("landing_fix", state)
        self.assertEqual(self.merges, [])

    def test_a_head_the_seat_pushed_after_a_landing_red_spends_a_round(self):
        directory, url = self.red_landing()
        self.push_fix(url)
        with patch.object(run, "execute", side_effect=AssertionError("a fixer turn over the seat push")):
            state = self.review(directory, url)
        self.assertEqual(len(state["round_summaries"]), 2)
        self.assertNotIn("landing_fix", state)
        self.assertEqual(state["state"], "waiting")

    def test_past_the_budget_a_head_the_seat_pushed_after_a_landing_red_is_not_reviewed(self):
        directory, url = self.own_pr("second", 1)
        self.review(directory, url)
        with record.record(directory) as state:
            first = state["round_summaries"][0]
            state["round_summaries"] = [{**first, "round": n} for n in (1, 2, 3)]
        self.advance(**{"first.txt": "first\n"})
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        self.push_fix(url)
        with patch.object(run, "execute", side_effect=AssertionError("a fixer turn over the seat push")):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "fail")
        self.assertIn("3 review rounds spent on PR #1", state["error"])
        self.assertEqual(len(self.reviews), 1)
        self.assertNotIn("landing_fix", state)

    def test_a_run_a_fourth_red_landing_ended_counts_its_reds_again_when_resumed(self):
        directory, url = self.red_landing()
        with record.record(directory) as state:
            state["landing_reds"] = roundloop.CONFLICT_ROUNDS
        with patch.object(run, "fix_own_pr", return_value=False):
            state = self.review(directory, url)
        self.assertIn("landing failed 4 times", state["merge_note"])
        self.assertNotIn("landing_reds", state)
        state = self.review(directory, url)          # resumed: a review round, then the line again
        self.assertEqual(state["state"], "waiting", state.get("error"))
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        with patch.object(run, "fix_own_pr", return_value=False) as fixer:
            state = self.review(directory, url)
        self.assertTrue(fixer.called, state.get("merge_note"))
        self.assertEqual(state["landing_reds"], 1)

    def test_a_head_moved_under_delivery_is_reviewed_as_a_round(self):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        land.check_line(self.turn)
        self.assertIn("land", self.wait(directory))
        self.push_fix(url)
        state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 2)
        self.assertNotIn("landing_fix", state)
        self.assertNotIn("landing_reds", state)

    def pushed_while_waiting(self, spent):
        directory, url = self.own_pr("first", 1)
        self.review(directory, url)
        with record.record(directory) as state:
            first = state["round_summaries"][0]
            state["round_summaries"] = [{**first, "round": n} for n in range(1, spent + 1)]
        self.advance()
        self.push_fix(url)
        land.check_line(self.turn)
        self.assertIn("moved", self.wait(directory)["fix"]["line"])
        state = self.review(directory, url)
        self.assertNotIn("landing_reds", state)
        return state

    def test_a_head_the_seat_pushed_while_waiting_in_the_line_is_reviewed_as_a_round(self):
        state = self.pushed_while_waiting(1)
        self.assertEqual(len(state["round_summaries"]), 2)

    def test_past_the_budget_a_head_the_seat_pushed_while_waiting_is_not_reviewed(self):
        state = self.pushed_while_waiting(3)
        self.assertEqual((state["state"], len(self.reviews)), ("fail", 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
