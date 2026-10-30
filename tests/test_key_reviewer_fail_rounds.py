"""A reviewer that files a blocking finding every round spends the round budget and the run FAILs.

Rounds are the repair: after a FAIL the executor goes again as a fixer, handed the finding, and
the reviewer looks again, until the work passes or the task's rounds (three, or fewer if its
front matter says so) are spent.  Then the run ends FAIL with exit 1, nothing pushed, the work
kept on its branch, and result.md telling a person what still blocks it, each finding with its
proof command, and, below the budget's cap, how to carry it on.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, a config
from akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# `false` fails on the change and on its base alike: a proof nothing the fixer does can pass.
FINDING = ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"]
REVIEW = {"final": "Found one.", "hand_in": [FINDING, ["done"]]}
LINE = "- retry.txt:1 - fake defect - it matters"


def failing_run(cls, front=None):
    """One --no-merge run whose reviewer files FINDING every round, in a Home of the class's."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets")
    akconfig.write(cls.home, ["opus", "astra"])
    # each fixer disputes it, as a fixer's done waits on every earlier finding's proof
    cls.fakes = fakeadapter.install(cls.home, claude=["work", "dispute"], codex=REVIEW)
    task = taskfile.write(cls.home, cls.rig.path, "Add retry file", front=front)
    cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text().splitlines()


class EveryRoundFails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        failing_run(cls)

    def test_all_three_rounds_are_spent_and_the_run_ends_fail(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertTrue(self.done.out.rstrip("\n").endswith(
            f"FAIL -> {self.run_dir / 'result.md'}"), self.done.out)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "rounds", "merged", "pr")}, {
            "state": "fail", "verdict": "FAIL", "rounds": 3, "merged": False, "pr": None})
        self.assertEqual([(summary["round"], summary["verdict"], summary["finding_count"])
                          for summary in self.state["round_summaries"]],
                         [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 1)])
        log = (self.run_dir / "log.txt").read_text()
        for rnd in (1, 2, 3):
            self.assertIn(f"round {rnd} verdict: FAIL", log)

    def test_one_executor_turn_then_a_fixer_turn_for_each_failed_review(self):
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer", "fixer"])
        reviews = self.fakes["codex"].runs()
        self.assertEqual([run["role"] for run in reviews], ["reviewer"] * 3)
        # Each review's finding was taken, so each FAIL is the reviewer's and not a refusal.
        for review in reviews:
            self.assertEqual([(hand_in["argv"][0], hand_in["code"])
                              for hand_in in review["hand_ins"]],
                             [("finding", 0), ("done", 0)], review["hand_ins"])

    def test_each_fixer_turn_is_handed_the_finding_it_must_fix(self):
        first = (self.run_dir / "round-1/executor/prompt.md").read_text()
        self.assertNotIn(LINE, first.splitlines())
        for rnd in (2, 3):
            with self.subTest(round=rnd):
                prompt = (self.run_dir / f"round-{rnd}/executor/prompt.md").read_text()
                self.assertIn(LINE, prompt.splitlines())
                self.assertIn("$ false", prompt)

    def test_result_md_says_fail_and_lists_the_blocking_finding_once_with_its_proof(self):
        self.assertEqual(self.result[4], "# FAIL — Add retry file")
        for line in ("VERDICT: FAIL", "rounds: 3 of 3", "pr: (none)", "merged: no"):
            self.assertIn(line, self.result)
        section = self.result[self.result.index("## Reviewer findings"):]
        # The findings that still block, not a log of every round's.
        self.assertEqual(section.count(LINE), 1, section)
        proof = section[section.index(LINE) + 1]
        self.assertEqual(proof.strip(), "$ false")
        # Three rounds is the cap: there are no more to ask for.
        self.assertFalse([line for line in self.result if line.startswith("continue:")],
                         self.result)

    def test_the_work_stays_on_its_branch_in_a_kept_worktree_and_nothing_is_pushed(self):
        worktree = Path(self.state["worktree"])
        self.assertTrue(worktree.is_dir())
        tree = self.home.run("git", "-C", str(worktree), "ls-tree", "--name-only", "HEAD")
        self.assertIn("retry.txt", tree.out.split())
        self.assertIn("ak/add-retry-file", self.rig.branches(remote=False))
        self.assertEqual(self.rig.branches(), ["main"])
        self.assertEqual(self.home.calls("gh"), [])


class TwoRoundBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        failing_run(cls, front={"rounds": 2})

    def test_a_task_of_two_rounds_ends_fail_after_two_reviews(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"], self.state["rounds"]),
                         ("fail", "FAIL", 2))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "FAIL"])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 2))
        self.assertIn("rounds: 2 of 2", self.result)
        self.assertIn(LINE, self.result)

    def test_the_result_says_how_to_carry_it_on_up_to_three_rounds(self):
        self.assertIn(f"continue: ak run resume {self.run_dir.name} --rounds 3", self.result)


if __name__ == "__main__":
    unittest.main()
