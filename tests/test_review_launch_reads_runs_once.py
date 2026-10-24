"""A review launch reads each run record once and diffs each failed pull request once.

`ak run --review-pr` asks whether the pull request replaces one whose review failed at the
budget (`transitions.replacement_refusal`).  That once read every record on disk again for each
failed review run and diffed a pull request once per failed run of it: 172 s on a host holding
4,700 records.  Now one pass over the records finds the failed reviews and counts each pull
request's rounds, and each failed pull request is diffed once.
Offline: run records in the sandbox HOME and a git repository the test writes.
"""

from collections import Counter
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))     # its fixtures, when loaded by path
from fixtures.sandbox import Sandbox
from agentkit import config, record, transitions

URL = "https://github.com/acme/widget/pull/{}"


class ReviewLaunchReadsRunsOnce(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                                         "GIT_CONFIG_NOSYSTEM": "1"}))
        self.repo = self.root / "widget"
        self.repo.mkdir()
        self.git("init", "-qb", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "api.py").write_text("base\n")
        self.git("add", "."); self.git("commit", "-qm", "Base")
        self.base = self.git("rev-parse", "HEAD")
        self.records = 0

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def head(self, name):
        """A branch off the base adding forty lines of its own; its head."""
        self.git("checkout", "-qb", name, self.base)
        (self.repo / "feature.py").write_text("".join(f"def f{n}(): return {n}\n" for n in range(40)))
        self.git("add", "."); self.git("commit", "-qm", name)
        sha = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        return sha

    def run_record(self, rounds=0, **fields):
        self.records += 1
        directory = config.RUNS / f"20261023-{self.records:04d}-run"
        directory.mkdir(parents=True)
        record.save_state(directory, {
            "run_id": directory.name, "state": "fail", "repo": str(self.repo),
            "round_summaries": [{"round": n, "verdict": "FAIL"} for n in range(1, rounds + 1)],
            **fields})
        return directory

    def test_one_pass_over_the_records_and_one_diff_per_failed_pull_request(self):
        heads = {number: self.head(f"pr-{number}") for number in range(1, 9)}
        # five failed review runs on each of eight pull requests: 1-3 spent the budget among
        # their runs, 4 and 5 did not, 6 and 7 did but merged, and 8 did through a task run
        rounds = {1: [1, 1, 1, 0, 0], 2: [3, 0, 0, 0, 0], 3: [1, 1, 1, 1, 1], 4: [1, 1, 0, 0, 0],
                  5: [0, 0, 0, 0, 0], 6: [3, 0, 0, 0, 0], 7: [1, 1, 1, 0, 0], 8: [0, 0, 0, 0, 0]}
        for number, spent in rounds.items():
            for n in spent:
                self.run_record(n, review_pr=URL.format(number), base_sha=self.base,
                                head_sha=heads[number], finished_at=time.time() - 3600)
        for number in (6, 7):
            self.run_record(state="pass", merged=True, review_pr=URL.format(number))
        self.run_record(3, pr="https://github.com/ACME/Widget/pull/8/")
        # the run being launched counts for nothing, though it holds three rounds of 4
        launching = self.run_record(3, review_pr=URL.format(4), base_sha=self.base,
                                    head_sha=heads[4], finished_at=time.time() - 60)
        while self.records < 60:
            self.run_record(2, pr=URL.format(100 + self.records), state="pass")

        reads = Counter()
        read_state = record.read_state
        def counting_read(run_dir):
            reads[run_dir.name] += 1
            return read_state(run_dir)
        with patch.object(transitions.run_record, "read_state", counting_read):
            failed = transitions.budget_failed_reviews(self.repo, exclude=launching)
        self.assertEqual(sorted(failed), sorted((URL.format(number), self.base, heads[number])
                                                for number in (1, 2, 3, 8)))
        self.assertEqual(len(reads), 59)
        self.assertEqual(max(reads.values()), 1)

        diffs = Counter()
        reviewed_lines = transitions.reviewed_lines
        def counting_diff(repo, base, head="HEAD"):
            diffs[base, head] += 1
            return reviewed_lines(repo, base, head)
        mine = self.head("replacement")
        with patch.object(transitions, "reviewed_lines", counting_diff):
            refusal = transitions.replacement_refusal(self.repo, self.base, mine, 9, 40,
                                                      exclude=launching)
        self.assertIn("PR #9 re-adds 40 of its 40 lines", refusal)
        self.assertEqual(diffs, Counter({(self.base, head): 1
                                         for head in (mine, *(heads[n] for n in (1, 2, 3, 8)))}))


if __name__ == "__main__":
    unittest.main()
