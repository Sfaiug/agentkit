"""A run's result says where each round's blocking findings sat.

Each recorded round's summary keeps the file of every blocking finding it counted (`files`),
and the result has one `## Where the findings sat` section: a line per round that left one,
the round, then each file with its count, most first.  A run that fails three rounds -- two
findings at retry.txt and one at other.txt, then one at retry.txt twice -- has those three
lines; a run whose only review passes has no such section; a review of a seat's own PR that
stops with its fixer run dry, its result the short one, has its round's line too.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a project from
gitrig.py with the GitHub of fakegh.py, a config from akconfig.py, a task from taskfile.py and
scripted harnesses from fakeadapter.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_key_one_finding_left_gets_extra_rounds as extra
import test_key_own_pr_fix_and_land as own_pr

HEADING = "## Where the findings sat"


def finding(path, line):
    """A blocking finding on `path`'s `line`, proven until that line reads `ready`."""
    return ["finding", f"{path}:{line}", "setting is wrong", "breaks callers", "--run",
            f"sed -n {line}p {path} | grep -qx ready"]


WORK = {"write": {"retry.txt": "wrong\nwrong\n", "other.txt": "wrong\n"},
        "commit": "add retry.txt and other.txt", "final": "## Summary\nwrote both",
        "hand_in": [["done"]]}
THREE = {"final": "Found three.", "hand_in": [finding("retry.txt", 1), finding("other.txt", 1),
                                             finding("retry.txt", 2), ["done"]]}
ONE = {"final": "Found one.", "hand_in": [finding("retry.txt", 1), ["done"]]}
# fixes all but retry.txt's first line, which it disputes: its done waits on that proof
FIX_ALL_BUT_ONE = {**extra.DISPUTE, "write": {"retry.txt": "wrong\nready\n", "other.txt": "ready\n"},
                   "commit": "fix retry.txt's second line and other.txt"}


class FailsThreeRounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        extra.run(cls, [WORK, FIX_ALL_BUT_ONE, extra.DISPUTE], [THREE, ONE, ONE],
                  {"extra_rounds": 0}, "--no-merge")
        cls.result = (cls.run_dir / "result.md").read_text()

    def test_its_result_has_a_line_for_each_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(extra.rounds(self.state), [(1, "FAIL", 3), (2, "FAIL", 1), (3, "FAIL", 1)])
        lines = self.result.splitlines()
        self.assertEqual(lines.count(HEADING), 1, self.result)
        at = lines.index(HEADING)
        self.assertEqual(lines[at + 1:at + 6], ["", "- round 1: retry.txt 2, other.txt 1",
                                                "- round 2: retry.txt 1", "- round 3: retry.txt 1",
                                                ""])


class PassesItsOnlyReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        extra.run(cls, [WORK], ["pass"], None, "--no-merge")
        cls.result = (cls.run_dir / "result.md").read_text()

    def test_its_result_has_no_such_section(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(extra.rounds(self.state), [(1, "PASS", 0)])
        self.assertNotIn(HEADING, self.result.splitlines())


class StopsWithTheShortResult(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        own_pr.reviewed(cls, "dead", [own_pr.FIND, "dead"])
        cls.result = (cls.run_dir / "result.md").read_text()

    def test_its_result_has_its_round_s_line(self):
        self.assertEqual(self.state["state"], "exhausted", self.done.out + self.done.err)
        lines = self.result.splitlines()
        at = lines.index(HEADING)
        self.assertEqual(lines[at + 1:at + 4], ["", "- round 1: contrib.txt 1", ""])
        self.assertEqual(lines[at + 4], "## Why this run stopped")


if __name__ == "__main__":
    unittest.main()
