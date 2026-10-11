"""A seat's own PR red at landing gets the run's fixer turn and a re-review that spends no round.

The line's check, a required check or a rebase the tip conflicts with: the fixer turn on the PR
branch as for review findings, then a re-review at the next round number that enters no round
history, however the round budget stands, up to three times for one landing.  A PR moved under
its delivery is reviewed as a round, as any new head is.  Offline: the own-PR line fixture's
local Git, fake GitHub, reviewers and seats.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_own_pr_line as line
from agentkit import land, record, run


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
            return True
        return patch.object(run, "fix_own_pr", side_effect=fixed)

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
        with patch.object(run, "checks", return_value=(False, "required checks failed: fence")), \
                self.fixer(url, rename=False):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 1)
        self.assertIn("required checks failed: fence", self.reviews[-1])
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
            return True

        with patch.object(run, "fix_own_pr", side_effect=rebased):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(len(state["round_summaries"]), 1)
        land.check_line(self.turn)
        state = self.review(directory, url)
        self.assertTrue(state["merged"])

    def test_a_fourth_red_landing_ends_fail(self):
        directory, url = self.red_landing()
        with record.record(directory) as state:
            state["landing_reds"] = run.CONFLICT_ROUNDS
        with patch.object(run, "fix_own_pr", side_effect=AssertionError("a fourth landing fixer")):
            state = self.review(directory, url)
        self.assertEqual(state["state"], "fail")
        self.assertIn("landing failed 4 times", state["merge_note"])
        self.assertNotIn("own_pr_wait", state)
        self.assertNotIn("landing_fix", state)
        self.assertEqual(self.merges, [])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
