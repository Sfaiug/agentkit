"""Only what a reviewer hands in is its verdict: its prose is never read, and it cannot block.

A reviewer is a model, and a model writes whatever it likes; ak judges a round only by the
reviewer's `ak hand-in` records, so a final message saying FAIL over a `done` with no blocking
finding is a PASS, and the round goes no further.  Ending the run is not the reviewer's to do:
`blocked` and `not-needed` are refused in a review turn, which `done` still closes, and the run
passes.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py, a task from
taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PROSE_FAIL = {"final": "VERDICT: FAIL\n\nThe work is not good enough.", "hand_in": [["done"]]}
TRIES_TO_BLOCK = {"final": "Tried to stop the run.", "hand_in": [
    ["blocked", "the owner should decide"], ["not-needed", "nothing worth reviewing"],
    ["done"]]}


def reviewed(cls, reviewer):
    """One --no-merge run whose executor does the work and whose reviewer does `reviewer`."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    rig = Rig(cls.home, "widgets")
    akconfig.write(cls.home, ["opus", "astra"])
    cls.fakes = fakeadapter.install(cls.home, claude="work", codex=reviewer)
    task = taskfile.write(cls.home, rig.path, "Add retry file")
    cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text().splitlines()


class ProseIsNotTheVerdict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, PROSE_FAIL)

    def test_a_reviewer_writing_fail_over_a_done_hand_in_passes_the_run(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        final = (self.run_dir / "round-1/reviewer/final.md").read_text()
        self.assertTrue(final.startswith("VERDICT: FAIL"), final)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])
        log = (self.run_dir / "log.txt").read_text()
        self.assertRegex(log, r"(?m)\bround 1 verdict: PASS$")

    def test_result_md_says_pass_and_never_the_reviewer_s_fail(self):
        self.assertIn("VERDICT: PASS", self.result)
        self.assertNotIn("VERDICT: FAIL", self.result)

    def test_the_prose_sends_no_work_back_to_the_executor(self):
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))
        self.assertEqual([summary["finding_count"]
                          for summary in self.state["round_summaries"]], [0])


class ReviewerCannotBlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, TRIES_TO_BLOCK)

    def test_blocked_and_not_needed_are_refused_in_a_review_turn_and_done_is_not(self):
        hand_ins = self.fakes["codex"].runs()[0]["hand_ins"]
        self.assertEqual([(row["argv"][0], row["code"]) for row in hand_ins],
                         [("blocked", 2), ("not-needed", 2), ("done", 0)])
        for row in hand_ins[:2]:
            with self.subTest(row["argv"][0]):
                self.assertTrue(row["err"].strip(), "a refusal says why")

    def test_the_turn_records_only_its_done(self):
        path = self.run_dir / "round-1/reviewer/hand-in.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([row["kind"] for row in rows], ["turn", "done"])

    def test_the_run_passes_instead_of_ending_blocked(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertFalse(self.state.get("blocked"))
        self.assertIn("VERDICT: PASS", self.result)
        self.assertTrue(self.result[0].startswith("# PASS"), self.result[0])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 1))


if __name__ == "__main__":
    unittest.main()
