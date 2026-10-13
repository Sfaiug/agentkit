"""A replacement pull request inherits the rounds its failed predecessor spent.

After a seat's own pull request fails its third round the budget says split or redesign, and
a new pull request on a new branch with the same lines got three fresh rounds.  Now a pull
request's first review is refused when more than half its added lines were added by a pull
request whose review failed at the budget within fourteen days and did not merge, unless it is
a real split, under half that one's size (`transitions.replacement_refusal`); a redesign adds
lines of its own and starts fresh.  Offline: run records in a throwaway HOME and a git
repository the test writes.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, transitions
from agentkit import record

FAILED = "https://github.com/acme/widget/pull/7"


class ReplacementRounds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-replacement-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.root))
        for name in ("RUNS", "TMP"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull,
                                                    "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
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

    def head(self, name, lines):
        """A branch off the base adding `lines` to feature.py; its head."""
        self.git("checkout", "-qb", name, self.base)
        (self.repo / "feature.py").write_text("".join(f"{line}\n" for line in lines))
        self.git("add", "."); self.git("commit", "-qm", name)
        sha = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        return sha

    def failed_review(self, run_id, head, finished=None, merged=False, rounds=3):
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        record.save_state(directory, {
            "run_id": run_id, "state": "fail", "verdict": "FAIL", "review_pr": FAILED, "pr": FAILED,
            "own_pr": True, "repo": str(self.repo), "base_sha": self.base, "head_sha": head,
            "merged": merged, "finished_at": time.time() - 86400 if finished is None else finished,
            "round_summaries": [{"round": n, "verdict": "FAIL"} for n in range(1, rounds + 1)]})
        return directory

    def refusal(self, head, number=9):
        counted = transitions.diff_lines(self.repo, self.base, head, added_only=True)
        return transitions.replacement_refusal(self.repo, self.base, head, number, counted)

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

    def test_only_a_recent_unmerged_budget_failure_of_the_repository_charges_it(self):
        theirs = [f"def f{n}(): return {n}" for n in range(40)]
        failed = self.head("failed", theirs)
        again = self.head("again", theirs[:30] + [f"def g{n}(): return {n}" for n in range(5)])
        self.failed_review("20260101-0900-merged", failed, merged=True)
        self.failed_review("20260101-0800-old", failed, finished=time.time() - 20 * 86400)
        self.failed_review("20260101-0700-two-rounds", failed, rounds=2)
        self.assertIsNone(self.refusal(again))
        self.failed_review("20260101-0600-elsewhere", failed)
        other = config.RUNS / "20260101-0600-elsewhere"
        record.save_state(other, {**record.read_state(other), "repo": str(self.root / "other")})
        self.assertIsNone(self.refusal(again))
        self.failed_review("20260101-0500-here", failed)
        self.assertIsNotNone(self.refusal(again))
        # the run under review counts for nothing against itself
        self.assertIsNone(transitions.replacement_refusal(
            self.repo, self.base, again, 9, 35, exclude=config.RUNS / "20260101-0500-here"))

    def test_a_failed_head_git_no_longer_holds_is_skipped(self):
        theirs = [f"def f{n}(): return {n}" for n in range(40)]
        again = self.head("again", theirs[:30])
        self.failed_review("20260101-0900-gone", "0" * 40)
        self.assertIsNone(self.refusal(again))


if __name__ == "__main__":
    unittest.main(verbosity=2)
