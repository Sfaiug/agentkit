"""A task's run whose review leaves `rescope_findings` blocking findings or more spends no further round.

With ak's six, a run whose first review leaves six ends FAIL after that round, as a run that
spent its rounds ends: its budget is the one round it recorded, its result says why in one
sentence -- the count, the number, and that the task is to be rescoped -- and its resume is
refused as at its round budget.  One left five goes on to its second round, as does one left six
under `rescope_findings = 0`; a project's front matter of four ends a run its review left four.
Under two, two left at the third round end the run there, with no extra round
(tests/test_key_one_finding_left_gets_extra_rounds.py) after it.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py
with the GitHub of fakegh.py, a config from akconfig.py, a task from taskfile.py and scripted
harnesses from fakeadapter.py.
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
import test_key_one_finding_left_gets_extra_rounds as extra

LINES = 6
WORK = {"write": {"retry.txt": "wrong\n" * LINES}, "commit": "add retry.txt",
        "final": "## Summary\nwrote retry.txt", "hand_in": [["done"]]}
FIX = {"write": {"retry.txt": "ready\n" * LINES}, "commit": "fix retry.txt",
       "final": "## Summary\nfixed retry.txt", "hand_in": [["done"]]}


def review(count):
    """A review leaving `count` blocking findings, one on each of retry.txt's first lines, each
    proven until its line reads `ready`."""
    return {"final": f"Found {count}.", "hand_in": [
        *(["finding", f"retry.txt:{n}", f"line {n} is wrong", "breaks callers", "--run",
           f"sed -n {n}p retry.txt | grep -qx ready"] for n in range(1, count + 1)), ["done"]]}


def run(cls, count, settings=None, files=None):
    """One run of `Add retry file` whose first review leaves `count` findings and whose second
    passes: opus builds and fixes, astra alone reviews."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets", files=files)
    if files:
        cls.rig.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    GitHub(cls.home).grant(cls.rig.slug, "WRITE")
    akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                   settings=settings)
    cls.fakes = fakeadapter.install(cls.home, claude=[WORK, FIX], codex=[review(count), "pass"])
    task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
    cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=600)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text()


def rounds(state):
    return [(row["round"], row["verdict"], row["finding_count"]) for row in state["round_summaries"]]


class Ends:
    """The run ends FAIL after its first round, and its result says why."""
    count = number = 0

    def test_the_run_ends_failed_after_its_first_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", self.count)])
        self.assertEqual((self.state["state"], self.state["merged"]), ("fail", False))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))
        self.assertIn("rounds: 1 of 1", self.result.splitlines())

    def test_its_result_says_why(self):
        lines = self.result.splitlines()
        at = lines.index("## Why this run stopped")
        self.assertEqual(lines[at + 2], f"The review left {self.count} blocking findings, at or past "
                                        f"rescope_findings = {self.number}: rescope the task.")


class GoesOn:
    """The run goes on to its second round, which passes."""
    count = 0

    def test_the_run_goes_on_to_its_second_round(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", self.count), (2, "PASS", 0)])
        self.assertEqual(self.state["state"], "pass")
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 2))


class SixLeft(Ends, unittest.TestCase):
    count = number = 6

    @classmethod
    def setUpClass(cls):
        run(cls, 6)

    def test_its_resume_is_refused_as_at_its_round_budget(self):
        resumed = self.home.ak("run", "resume", self.run_dir.name, timeout=300)
        self.assertEqual(resumed.code, 2, resumed.out + resumed.err)
        self.assertIn(f"{self.run_dir.name} FAILed at its round budget (1); give --rounds N above "
                      "it, at most 3, to continue", resumed.err)
        self.assertEqual(json.loads((self.run_dir / "run.json").read_text()), self.state)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))


class FiveLeft(GoesOn, unittest.TestCase):
    count = 5

    @classmethod
    def setUpClass(cls):
        run(cls, 5)


class SixLeftWithRescopeOff(GoesOn, unittest.TestCase):
    count = 6

    @classmethod
    def setUpClass(cls):
        run(cls, 6, settings={"rescope_findings": 0})


class FourLeftUnderAProjectsFour(Ends, unittest.TestCase):
    count = number = 4

    @classmethod
    def setUpClass(cls):
        run(cls, 4, files={"AGENTS.md": "---\ntests: none\nhealth: none\nusers: none\n"
                                        "rescope_findings: 4\n---\nA project.\n"})


class TwoLeftAtTheThirdRoundUnderTwo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        two = {"final": "Found two.", "hand_in": [extra.finding("retry.txt"),
                                                  extra.finding("other.txt"), ["done"]]}
        extra.run(cls, [extra.WORK, extra.DISPUTE, extra.DISPUTE_ADDING],
                  [extra.ONE, extra.ONE, two, "pass"], {"rescope_findings": 2}, "--no-merge")

    def test_the_run_ends_failed_after_three_with_no_extra_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 2)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 3))
        self.assertEqual(self.state["error"], "The review left 2 blocking findings, at or past "
                                              "rescope_findings = 2: rescope the task.")


if __name__ == "__main__":
    unittest.main()
