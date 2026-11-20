"""A run that spent its review rounds with one blocking finding left goes on, `extra_rounds` more.

At the end of its `review_rounds` (three), a task's run whose last review left exactly one
blocking finding goes on to a fixer round and a review as the rounds before did, and so does each
extra round that ends the same way, `extra_rounds` (two) of them at most.  With two findings left,
or `extra_rounds = 0`, the run ends FAIL after three, as it always did.  Other runs of the change
count the rounds it spent: a relaunch from the branch of a run that spent five is refused, and
so is its resume, naming the five.  A fourth round whose reviewer never answered is finished
by the run's resume.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py with the GitHub of fakegh.py, a config from
akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


def finding(path):
    """A blocking finding on `path`'s first line, proven until the line reads `ready`."""
    return ["finding", f"{path}:1", "setting is wrong", "breaks callers", "--run",
            f"grep -qx ready {path}"]


ONE = {"final": "Found one.", "hand_in": [finding("retry.txt"), ["done"]]}
TWO = {"final": "Found two.", "hand_in": [finding("retry.txt"), finding("other.txt"), ["done"]]}
# words but no verdict: the reviewer never answers, asked once more or not
SILENT = {"final": "Looks fine."}
WORK = {"write": {"retry.txt": "wrong\n"}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
# a fixer that fixes nothing: its done waits on the finding's proof, so it disputes the finding
DISPUTE = {"final": "Disputed.", "hand_in": [
    ["dispute", "retry.txt:1", "not a defect", "--run", "true"], ["done"]]}
# ... and one that adds a line of its own, which the next review's second finding is on
DISPUTE_ADDING = {**DISPUTE, "write": {"other.txt": "wrong\n"}, "commit": "add other.txt"}
FIX = {"write": {"retry.txt": "ready\n"}, "commit": "fix retry.txt",
       "final": "## Summary\nfixed retry.txt", "hand_in": [["done"]]}


def run(cls, claude, codex, settings=None, *args):
    """One run of `Add retry file` in a Home of the class's, the harnesses scripted: opus builds
    and fixes, astra alone reviews."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets")
    cls.gh = GitHub(cls.home)
    cls.gh.grant(cls.rig.slug, "WRITE")         # a run that passed could push and merge
    akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                   settings=settings)
    cls.fakes = fakeadapter.install(cls.home, claude=claude, codex=codex)
    task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
    cls.done = cls.home.ak("run", str(task), *args, timeout=600)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = state(cls.run_dir)


def state(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def rounds(state):
    return [(summary["round"], summary["verdict"], summary["finding_count"])
            for summary in state["round_summaries"]]


class OneLeftAfterThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE, DISPUTE, FIX], [ONE, ONE, ONE, "pass"])

    def test_a_fourth_round_fixes_it_and_the_change_merges(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 1),
                                              (4, "PASS", 0)])
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual(self.rig.files().count("retry.txt"), 1)
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()],
                         ["executor", "fixer", "fixer", "fixer"])


class TwoLeftAfterThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE, DISPUTE_ADDING], [ONE, ONE, TWO, "pass"], None, "--no-merge")

    def test_the_run_ends_fail_after_three(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 2)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 3))


class OneLeftEveryTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE], ONE, None, "--no-merge")
        # the same change again, from the branch the first run kept
        task = taskfile.write(cls.home, cls.rig.path, "Finish retry file",
                              front={"from": cls.state["branch"]})
        cls.again = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.resumed = cls.home.ak("run", "resume", cls.run_dir.name, timeout=300)

    def test_the_run_ends_fail_after_five(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(n, "FAIL", 1) for n in range(1, 6)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 5))

    def test_a_relaunch_from_its_branch_is_refused(self):
        self.assertEqual(self.again.code, 2, self.again.out + self.again.err)
        self.assertIn(f"5 review rounds spent on branch {self.state['branch']} across 1 run",
                      self.again.err)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (5, 5))

    def test_its_resume_is_refused_naming_the_five(self):
        self.assertEqual(self.resumed.code, 2, self.resumed.out + self.resumed.err)
        self.assertIn("5 review rounds spent on this change across 1 run", self.resumed.err)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (5, 5))


class ExtraRoundsOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE, DISPUTE, FIX], [ONE, ONE, ONE, "pass"], {"extra_rounds": 0},
            "--no-merge")

    def test_one_finding_left_after_three_ends_fail(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 1)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 3))


class FourthReviewNeverAnswered(unittest.TestCase):
    """Round 4's reviewer gives no verdict, asked once more too, and no other reviewer is left:
    the run parks with the review pending, and its resume finishes that review."""

    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE, DISPUTE, FIX], [ONE, ONE, ONE, SILENT, SILENT, "pass"], None,
            "--no-merge")
        cls.resumed = cls.home.ak("run", "resume", cls.run_dir.name, timeout=300)
        cls.after = state(cls.run_dir)

    def test_the_run_parks_with_its_fourth_review_pending(self):
        self.assertNotEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.state["state"], "exhausted")
        self.assertEqual(self.state["review_pending"]["round"], 4)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 1)])

    def test_its_resume_finishes_the_fourth_round_and_passes(self):
        self.assertEqual(self.resumed.code, 0, self.resumed.out + self.resumed.err)
        self.assertEqual(rounds(self.after), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 1),
                                              (4, "PASS", 0)])
        self.assertEqual(self.after["state"], "pass")
        # the review alone: no fixer turn spent again
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (4, 6))


if __name__ == "__main__":
    unittest.main()
