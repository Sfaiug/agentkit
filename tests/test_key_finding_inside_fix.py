"""A finding records whether it sits inside the fixer's last change, and the board counts them.

From round 2 on, each `findings` row's `inside_fix` is 1 where its path and line fall inside the
new side of the diff from the commit the last review judged to the one this review judged, and 0
where they do not; in round 1 it is NULL.  The history board's findings row says how many of the
week's findings reviewers handed in after round 1 sat inside the fix: new ground is the rest.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, with scripted harnesses from fakeadapter.py, and the test reads the
Home's history.db and `ak run status --history`.
"""

import contextlib
import json
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_scoreboard import OWNERS, ROOMY, scoreboard

# Each fails while its line is in words.txt and passes on base, which has no file.
BETA, CAPITAL, DELTA = ("! grep -qx beta words.txt", "! grep -qx Beta words.txt",
                        "! grep -qx delta words.txt")
WORK = {"write": {"words.txt": "alpha\nbeta\ngamma\ndelta\n"}, "commit": "add words.txt",
        "final": "## Summary\nwrote it", "hand_in": [["done"]]}
FIRST = {"final": "Found one.", "hand_in": [
    ["finding", "words.txt:2", "beta is lower case", "it opens a sentence", "--run", BETA],
    ["done"]]}
# the fix changes line 2 alone
FIX = {"write": {"words.txt": "alpha\nBeta\ngamma\ndelta\n"}, "commit": "capitalise beta",
       "final": "## Summary\ncapitalised beta", "hand_in": [["done"]]}
SECOND = {"final": "Found two.", "hand_in": [
    ["finding", "words.txt:2", "Beta should be shouted", "it is a heading", "--run", CAPITAL],
    ["finding", "words.txt:4", "delta is lower case", "it opens a sentence", "--run", DELTA],
    ["done"]]}


class AFindingRecordsWhetherItSitsInsideTheFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude=[WORK, FIX], codex=[FIRST, SECOND])
        task = taskfile.write(cls.home, rig.path, "Add words file", front={"rounds": 2},
                              done_when=("test -f words.txt",))
        cls.home.ak("run", str(task), "--no-merge", env=OWNERS, timeout=300)
        run_dir = taskfile.only_run(cls.home)
        cls.record = json.loads((run_dir / "run.json").read_text())
        with contextlib.closing(sqlite3.connect(cls.home.path / ".agentkit" / "history.db")) as db:
            cls.rows = db.execute("SELECT round, line, proof, replayed, inside_fix FROM findings "
                                  "WHERE run_id=? ORDER BY round, rowid", (run_dir.name,)).fetchall()
        cls.board = cls.home.ak("run", "status", "--history", env={"AK_HOST_READINGS": ROOMY})

    def test_the_run_took_two_rounds(self):
        self.assertEqual([summary["verdict"] for summary in self.record["round_summaries"]],
                         ["FAIL", "FAIL"])

    def test_round_one_says_nothing_of_a_fix(self):
        self.assertEqual([(line, proof, inside) for round, line, proof, _, inside in self.rows
                          if round == 1], [(2, BETA, None)])

    def test_round_two_marks_each_finding_inside_or_outside_the_fix(self):
        handed = {proof: inside for round, _, proof, replayed, inside in self.rows
                  if round == 2 and replayed is None}
        self.assertEqual(handed, {CAPITAL: 1, DELTA: 0})

    def test_the_board_counts_those_inside_the_fix(self):
        self.assertEqual(self.board.code, 0, self.board.out + self.board.err)
        rows = {label: cells for label, *cells in scoreboard(self.board.out)}
        self.assertIn("findings", rows, self.board.out)
        self.assertIn("1 of 2 handed in after round 1 inside the fix", rows["findings"][0])


if __name__ == "__main__":
    unittest.main()
