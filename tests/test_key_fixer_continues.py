"""A failed review is fixed by the executor's own session continued, and a later pass lands.

After a FAIL, ak does not start a stranger on the work: the next round's turn resumes the
session the executor's last turn handed back, in the run's worktree, handed the findings to
fix, while each review reads a checkout of its own round.  A finding that no longer stands in
the next round, because the reviewer drops a quoted one or ak's replay of a proven one passes
on the fixed commit, ends the run PASS after two rounds of three.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py,
a config from akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# The session a fix turn hands back, unlike the fake's own `sid-claude-<n>`, so the round
# after it shows which one ak resumed.
FIX_SESSION = "sid-claude-fix"
QUOTED = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--quote", "hello"],
    ["done"]]}
# Its proof fails until the fixer adds fixed.txt.
PROVEN = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fixture defect", "the fixture says so", "--run",
     "test -f fixed.txt"], ["done"]]}
FIX = {"write": {"fixed.txt": "ok\n"}, "commit": "add fixed.txt",
       "final": "## Summary\nadded fixed.txt", "hand_in": [["done"]]}


class Run:
    """One `ak run task.md --no-merge` in a Home of the class's own, the harnesses scripted
    as `steps` gives them."""

    steps = {}

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, **cls.steps)
        cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(cls.task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.result = (cls.run_dir / "result.md").read_text().splitlines()

    def assert_passed_in_the_second_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "PASS"])
        log = (self.run_dir / "log.txt").read_text()
        self.assertRegex(log, r"(?s)round 1 verdict: FAIL\n.*round 2 verdict: PASS\n")
        self.assertNotIn("round 3", log)
        self.assertEqual(self.result[0], "# PASS, not merged: --no-merge — Add retry file")
        for line in ("VERDICT: PASS", "rounds: 2 of 3", "merged: no"):
            self.assertIn(line, self.result)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 2))
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer"])


class FixerContinuesTheExecutorsSession(Run, unittest.TestCase):
    # A reviewer failing every round gives three executor turns, the last two fixes.  Each fix
    # disputes the finding, as a fixer's done waits on every earlier finding's proof.
    steps = {"claude": ["work", {"final": "## Summary\nlooked again",
                                 "hand_in": fakeadapter.DISPUTE["hand_in"],
                                 "session": FIX_SESSION}, "dispute"],
             "codex": "fail"}

    def test_the_run_fails_after_three_rounds_of_one_executor_and_two_fixes(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(self.state["state"], "fail")
        self.assertEqual([run["role"] for run in self.fakes["claude"].runs()],
                         ["executor", "fixer", "fixer"])
        self.assertEqual(self.fakes["codex"].n, 3)

    def test_each_fix_resumes_the_session_the_last_executor_turn_handed_back(self):
        # The adapter's sixth `run` argument is the session to resume; a new one has none.
        sessions = [run["argv"][5:] for run in self.fakes["claude"].runs()]
        self.assertEqual(sessions, [[], ["sid-claude-1"], [FIX_SESSION]])

    def test_each_fix_works_in_the_runs_worktree_on_its_own_rounds_prompt(self):
        for n, run in enumerate(self.fakes["claude"].runs(), 1):
            with self.subTest(round=n):
                turn = self.run_dir / f"round-{n}" / "executor"
                self.assertEqual(run["argv"][2], self.state["worktree"])
                self.assertEqual(run["argv"][3:5], [str(turn / "prompt.md"), str(turn)])
                self.assertTrue((turn / "prompt.md").is_file())

    def test_a_fix_is_handed_the_findings_of_the_review_before_it(self):
        for n in (2, 3):
            with self.subTest(round=n):
                turn = self.run_dir / f"round-{n}" / "executor"
                prompt = (turn / "prompt.md").read_text()
                self.assertIn("retry.txt:1", prompt)
                self.assertIn("fixture defect", prompt)
                first = json.loads((turn / "hand-in.jsonl").read_text().splitlines()[0])
                self.assertEqual((first["kind"], first["role"]), ("turn", "fixer"))
                self.assertEqual([(row["path"], row["line"]) for row in first["findings"]],
                                 [("retry.txt", 1)])

    def test_each_review_reads_a_checkout_of_its_own_round(self):
        places = [run["argv"][2] for run in self.fakes["codex"].runs()]
        self.assertEqual(places, [str(self.run_dir / f"round-{n}" / "review-checkout")
                                  for n in (1, 2, 3)])


class AQuotedFindingTheReviewerDropsPasses(Run, unittest.TestCase):
    # The fixer changes nothing: only the reviewer's second word decides.
    steps = {"claude": "work", "codex": [QUOTED, "pass"]}

    def test_the_run_passes_in_the_second_round_and_says_so(self):
        self.assert_passed_in_the_second_round()
        self.assertNotIn("## Reviewer findings", self.result)

    def test_the_second_review_judges_the_same_commit_again(self):
        heads = [summary["head_sha"] for summary in self.state["round_summaries"]]
        self.assertEqual(heads[0], heads[1])


class AProvenFindingTheFixMakesPassPasses(Run, unittest.TestCase):
    steps = {"claude": ["work", FIX], "codex": [PROVEN, "pass"]}

    def test_the_run_passes_in_the_second_round_with_the_fix_on_its_branch(self):
        self.assert_passed_in_the_second_round()
        tree = self.home.run("git", "-C", self.state["worktree"], "ls-tree", "--name-only",
                             "HEAD")
        self.assertEqual(sorted(tree.out.split()), [".keep", "fixed.txt", "retry.txt"])

    def test_the_fixed_finding_stays_in_the_result_as_a_note_not_a_finding(self):
        self.assertNotIn("## Reviewer findings", self.result)
        self.assertIn("## Notes", self.result)
        notes = self.result[self.result.index("## Notes"):]
        self.assertTrue([line for line in notes if re.match(r"- retry\.txt:1\b", line)],
                        self.result)


if __name__ == "__main__":
    unittest.main()
