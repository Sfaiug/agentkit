"""A seat's own pull request whose third review left one blocking finding goes on, `extra_rounds` more.

At the end of its `review_rounds` (three), the review of a seat's own pull request whose last
round left one or two blocking findings hands them to the writer's model as the rounds before
did, and reviews what it pushes a fourth time; a PASS there lands the PR.  Each extra round
ending the same way earns the next, `extra_rounds` (two) of them at most.  With three findings
left after three, the run ends FAIL, as it always did.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, from the seat of akseat.py, against the bare origin of
gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RULES = "---\ntests: test -f contrib.txt\nusers: none\n---\n# widgets\n"


def finding(path):
    """A blocking finding on `path`'s first line, proven until the line reads `ready`."""
    return ["finding", f"{path}:1", "setting is wrong", "breaks callers", "--run",
            f"grep -qx ready {path}"]


ONE = {"final": "Found one.", "hand_in": [finding("contrib.txt"), ["done"]]}
THREE = {"final": "Found three.", "hand_in": [finding("contrib.txt"), finding("other.txt"),
                                             finding("third.txt"), ["done"]]}
# a fixer that fixes nothing: its done waits on the finding's proof, so it disputes the finding
DISPUTE = {"final": "Disputed.", "hand_in": [
    ["dispute", "contrib.txt:1", "not a defect", "--run", "true"], ["done"]]}
# ... and one that adds lines of its own, which the next review's further findings are on
DISPUTE_ADDING = {**DISPUTE, "write": {"other.txt": "wrong\n", "third.txt": "wrong\n"},
                  "commit": "add other.txt and third.txt"}
FIX = {"write": {"contrib.txt": "ready\n"}, "commit": "fix contrib.txt", "final": "Fixed.",
       "hand_in": [["done"]]}


def reviewed(cls, claude, codex):
    """The acme seat, whose orchestrator is opus, has its own PR adding contrib.txt reviewed,
    astra reviewing and opus fixing."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": RULES})
    cls.gh = GitHub(cls.home)
    akconfig.write(cls.home, ["opus", "astra"])
    cls.fakes = fakeadapter.install(cls.home, claude=claude, codex=codex)
    Seat(cls.home, "acme", cwd=cls.rig.path, alive=False,
         record={"workers": ["opus", "astra"]}, planned=True)
    cls.head = cls.rig.branch("contrib", {"contrib.txt": "c\n"})
    url = cls.gh.open_pr(cls.rig, "contrib", title="Add contrib")
    cls.done = cls.home.ak("run", "--review-pr", url, env={"AGENTKIT_SESSION": "acme"},
                           cwd=cls.rig.path, timeout=600)
    cls.state = json.loads((taskfile.only_run(cls.home) / "run.json").read_text())


def rounds(state):
    return [(summary["round"], summary["verdict"], summary["finding_count"])
            for summary in state["round_summaries"]]


class OneLeftAfterThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, [DISPUTE, DISPUTE, FIX], [ONE, ONE, ONE, "pass"])

    def test_what_its_seat_pushes_is_reviewed_a_fourth_time_and_merges(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 1),
                                              (4, "PASS", 0)])
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], ["fixer"] * 3)
        fix = self.gh.pr(1)["merge"]["head"]
        self.assertEqual([review["commit"]["oid"] for review in self.gh.pr(1)["reviews"]],
                         [self.head] * 3 + [fix])
        shown = self.home.run("git", "-C", str(self.rig.bare), "show", "main:contrib.txt")
        self.assertEqual(shown.out, "ready\n")


class OneLeftEveryTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, DISPUTE, ONE)

    def test_the_run_ends_fail_after_five(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(n, "FAIL", 1) for n in range(1, 6)])
        self.assertEqual((self.state["state"], self.state["merged"], self.state["rounds"]),
                         ("fail", False, 3))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (4, 5))
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["merge"]), ("OPEN", None))


class ThreeLeftAfterThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, [DISPUTE, DISPUTE_ADDING], [ONE, ONE, THREE, "pass"])

    def test_the_run_ends_fail_after_three(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 3)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 3))
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["merge"]), ("OPEN", None))


if __name__ == "__main__":
    unittest.main()
