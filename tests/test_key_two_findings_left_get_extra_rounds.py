"""A run that spent its review rounds with two blocking findings left goes on, `extra_rounds` more.

At the end of its `review_rounds` (three), a task's run whose last review left two blocking
findings goes on to a fixer round and a review as the rounds before did, and so does each extra
round that ends the same way, `extra_rounds` (two) of them at most, as with one left
(tests/test_key_one_finding_left_gets_extra_rounds.py).  With three left the run ends FAIL after
three, as it always did.  The owner, 20 Nov 2026: yes to two or fewer.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py
with the GitHub of fakegh.py, a config from akconfig.py, a task from taskfile.py and scripted
harnesses from fakeadapter.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_one_finding_left_gets_extra_rounds import finding, rounds, run

TWO = {"final": "Found two.", "hand_in": [finding("retry.txt"), finding("other.txt"), ["done"]]}
THREE = {"final": "Found three.", "hand_in": [finding("retry.txt"), finding("other.txt"),
                                             finding("third.txt"), ["done"]]}
WORK = {"write": {"retry.txt": "wrong\n", "other.txt": "wrong\n"}, "commit": "add two files",
        "final": "## Summary\nwrote retry.txt and other.txt", "hand_in": [["done"]]}
# a fixer that fixes nothing: its done waits on the findings' proofs, so it disputes both
DISPUTE = {"final": "Disputed.", "hand_in": [
    ["dispute", "retry.txt:1", "not a defect", "--run", "true"],
    ["dispute", "other.txt:1", "not a defect", "--run", "true"], ["done"]]}
# ... and one that adds a line of its own, which the next review's third finding is on
DISPUTE_ADDING = {**DISPUTE, "write": {"third.txt": "wrong\n"}, "commit": "add third.txt"}
FIX = {"write": {"retry.txt": "ready\n", "other.txt": "ready\n"}, "commit": "fix both",
       "final": "## Summary\nfixed both", "hand_in": [["done"]]}


class TwoLeftAfterThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE, DISPUTE, FIX], [TWO, TWO, TWO, "pass"])

    def test_a_fourth_round_fixes_them_and_the_change_merges(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 2), (2, "FAIL", 2), (3, "FAIL", 2),
                                              (4, "PASS", 0)])
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()],
                         ["executor", "fixer", "fixer", "fixer"])


class ThreeLeftAfterThree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE, DISPUTE_ADDING], [TWO, TWO, THREE, "pass"], None, "--no-merge")

    def test_the_run_ends_fail_after_three(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(1, "FAIL", 2), (2, "FAIL", 2), (3, "FAIL", 3)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 3))


class TwoLeftEveryTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run(cls, [WORK, DISPUTE], TWO, None, "--no-merge")

    def test_the_run_ends_fail_after_five(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(rounds(self.state), [(n, "FAIL", 2) for n in range(1, 6)])
        self.assertEqual((self.state["state"], self.fakes["codex"].n), ("fail", 5))


if __name__ == "__main__":
    unittest.main()
