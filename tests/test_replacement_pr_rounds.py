"""A replacement pull request inherits the rounds its failed predecessor spent.

After a seat's own pull request fails its third round the budget says split or redesign, and
a new pull request on a new branch with the same lines got three fresh rounds.  Now a pull
request's first review is refused when more than half the lines it adds that a reviewer reads
were added by a pull request whose review spent the budget across its runs within fourteen days
and never merged, unless it is a real split, under half that one's size, counted alike
(`transitions.replacement_refusal`); a redesign adds lines of its own and starts fresh.
Offline: run records in the sandbox HOME and a git repository the test writes.
"""

import os
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gitcall, record, transitions

FAILED = "https://github.com/acme/widget/pull/7"


class ReplacementRounds(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                                         "GIT_CONFIG_NOSYSTEM": "1"}))
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-qb", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "api.py").write_text("".join(f"line {n}\n" for n in range(1, 11)))
        self.git("add", "."); self.git("commit", "-qm", "Base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def head(self, name, lines, moved=(), into="feature.py"):
        """A branch off the base adding `lines` to `into`, and moving the base's api.py lines
        `moved` (indexes) to moved.py; its head."""
        self.git("checkout", "-qb", name, self.base)
        (self.repo / into).write_text("".join(f"{line}\n" for line in lines))
        if moved:
            kept = (self.repo / "api.py").read_text().splitlines(keepends=True)
            (self.repo / "moved.py").write_text("".join(kept[n] for n in moved))
            (self.repo / "api.py").write_text("".join(line for n, line in enumerate(kept) if n not in moved))
        self.git("add", "."); self.git("commit", "-qm", name)
        sha = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        return sha

    def failed_review(self, run_id, head, finished=None, merged=False, rounds=3, pr=FAILED):
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        record.save_state(directory, {
            "run_id": run_id, "state": "pass" if merged else "fail", "review_pr": pr, "pr": pr,
            "own_pr": True, "repo": str(self.repo), "base_sha": self.base, "head_sha": head,
            "merged": merged, "finished_at": time.time() - 86400 if finished is None else finished,
            "round_summaries": [{"round": n, "verdict": "FAIL"} for n in range(1, rounds + 1)]})
        return directory

    def refusal(self, head, number=9):
        return transitions.replacement_refusal(self.repo, self.base, head, number)

    def test_a_pull_request_mostly_made_of_a_failed_ones_lines_inherits_its_rounds(self):
        theirs = [f"def f{n}(): return {n}" for n in range(40)]
        failed = self.head("failed", theirs)
        self.failed_review("20260101-0900-review-pr-widget-7", failed)
        again = self.head("again", theirs[:30] + [f"def g{n}(): return {n}" for n in range(5)])
        self.assertEqual(self.refusal(again),
                         f"PR #9 re-adds 30 of its 35 lines from {FAILED}, whose review failed after 3 "
                         "rounds; a replacement inherits them: split it into parts under 21 lines, or "
                         "redesign it")
        split = self.head("split", theirs[:15])                      # under half its size: a real split
        self.assertIsNone(self.refusal(split))
        redesign = self.head("redesign", [f"def h{n}(): return {n}" for n in range(60)] + theirs[:10])
        self.assertIsNone(self.refusal(redesign))                     # mostly lines of its own
        # a name Git quotes in the patch is still read
        quoted = self.head("quoted", theirs, into='feature".py')
        self.assertIn("re-adds 40 of its 40 lines", self.refusal(quoted))

    def test_shares_and_sizes_count_the_lines_a_reviewer_reads(self):
        # blank lines count on every side, as the size ceiling counts them
        spaced = [part for n in range(40) for part in (f"def f{n}(): return {n}", "")]
        failed = self.head("failed", spaced)
        self.failed_review("20260101-0900-spaced", failed)
        self.assertIn("re-adds 80 of its 80 lines", self.refusal(self.head("again", spaced)))
        self.assertIsNone(self.refusal(self.head("split", spaced[:50:2])))   # 25 of its 80
        # lines moved unchanged count on no side: an unchanged replacement of a change that also
        # moved them inherits its rounds, and moving them charges an unrelated change nothing
        (self.repo / "api.py").write_text("".join(f"def legacy{n}(): return {n}\n" for n in range(60)))
        self.git("commit", "-qam", "Existing code")
        self.base = self.git("rev-parse", "HEAD")
        theirs = [f"def g{n}(): return {n}" for n in range(30)]
        moving = self.head("moving", theirs, moved=range(60))
        self.failed_review("20260101-0800-moving", moving)
        self.assertIn("re-adds 30 of its 30 lines", self.refusal(self.head("again-unmoved", theirs)))
        self.assertIsNone(self.refusal(self.head("unrelated", [f"def h{n}(): return {n}" for n in range(25)],
                                                 moved=range(60))))

    def test_only_a_recent_unmerged_budget_failure_of_the_repository_charges_it(self):
        theirs = [f"def f{n}(): return {n}" for n in range(40)]
        failed = self.head("failed", theirs)
        again = self.head("again", theirs[:30] + [f"def g{n}(): return {n}" for n in range(5)])
        self.failed_review("20260101-0800-old", failed, finished=time.time() - 20 * 86400,
                           pr="https://github.com/acme/widget/pull/5")
        self.failed_review("20260101-0700-two-rounds", failed, rounds=2)
        self.assertIsNone(self.refusal(again))
        self.failed_review("20260101-0600-elsewhere", failed, pr="https://github.com/acme/other/pull/7")
        other = config.RUNS / "20260101-0600-elsewhere"
        record.save_state(other, {**record.read_state(other), "repo": str(self.root / "other")})
        self.assertIsNone(self.refusal(again))
        # the budget is the pull request's, across its runs: two rounds in one, the last in another
        self.failed_review("20260101-0500-last-round", failed, rounds=1)
        self.assertIsNotNone(self.refusal(again))
        # the run under review counts for nothing against itself
        self.assertIsNone(transitions.replacement_refusal(
            self.repo, self.base, again, 9, exclude=config.RUNS / "20260101-0500-last-round"))
        # a pull request one of whose runs merged is no failure
        self.failed_review("20260101-0900-merged", failed, merged=True, rounds=0)
        self.assertIsNone(self.refusal(again))

    def test_a_failed_head_git_no_longer_holds_is_skipped_and_a_stopped_git_stops(self):
        theirs = [f"def f{n}(): return {n}" for n in range(40)]
        again = self.head("again", theirs[:30])
        self.failed_review("20260101-0900-gone", "0" * 40)
        self.assertIsNone(self.refusal(again))
        failed = self.head("failed", theirs)
        record.save_state(config.RUNS / "20260101-0900-gone",
                          {**record.read_state(config.RUNS / "20260101-0900-gone"), "head_sha": failed})
        git = gitcall.git

        def stalled(repo, *args, **kw):
            if f"{self.base}...{failed}" in args:
                raise gitcall.Stopped("git diff timed out")
            return git(repo, *args, **kw)

        with patch.object(gitcall, "git", side_effect=stalled), self.assertRaises(gitcall.Stopped):
            self.refusal(again)


if __name__ == "__main__":
    unittest.main(verbosity=2)
