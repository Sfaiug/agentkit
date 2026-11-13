"""A finding records whether it sits inside the fixer's last change, and the board counts them.

From round 2 on, each `findings` row's `inside_fix` is 1 where its path and line fall inside the
new side of the diff from the commit the last review judged to the one this review judged, renames
followed from whatever bytes the old name holds, and 0 where they do not; in round 1 it is NULL.
The history board's findings row says how many of the week's findings reviewers handed in after
round 1 sat inside the fix: new ground is the rest.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, with scripted harnesses from fakeadapter.py, and the test reads the
Home's history.db and `ak run status --history`.
"""

import contextlib
import json
import os
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_scoreboard import OWNERS, ROOMY, scoreboard

# Each fails while its line is in its file and passes on base, with no words.txt or notes.txt.
BETA, DELTA, THREE = ("! grep -qx beta words.txt", "! grep -qx delta words.txt",
                      "! grep -qx THREE notes.txt")
# base holds notes under a name that is not UTF-8
NOTES = {os.fsdecode(b"notes-\xff.txt"): "one\ntwo\nthree\nfour\n"}
WORK = {"write": {"words.txt": "alpha\nbeta\ngamma\ndelta\n"}, "commit": "add words.txt",
        "final": "## Summary\nwrote it", "hand_in": [["done"]]}
FIRST = {"final": "Found one.", "hand_in": [
    ["finding", "words.txt:2", "beta is lower case", "it opens a sentence", "--run", BETA],
    ["done"]]}
# the fix changes words.txt's line 2, and renames the notes to notes.txt changing line 3
FIX = {"write": {"words.txt": "alpha\nBeta\ngamma\ndelta\n"},
       "sh": "git mv \"$(printf 'notes-\\377.txt')\" notes.txt && "
             "printf 'one\\ntwo\\nTHREE\\nfour\\n' > notes.txt",
       "commit": "capitalise beta and three", "final": "## Summary\ncapitalised them",
       "hand_in": [["done"]]}
SECOND = {"final": "Found two.", "hand_in": [
    ["finding", "notes.txt:3", "THREE should be a numeral", "it counts", "--run", THREE],
    ["finding", "words.txt:4", "delta is lower case", "it opens a sentence", "--run", DELTA],
    ["done"]]}


class AFindingRecordsWhetherItSitsInsideTheFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        rig = Rig(cls.home, "widgets", files=NOTES)
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
        self.assertEqual(handed, {THREE: 1, DELTA: 0})

    def test_the_board_counts_those_inside_the_fix(self):
        self.assertEqual(self.board.code, 0, self.board.out + self.board.err)
        rows = {label: cells for label, *cells in scoreboard(self.board.out)}
        self.assertIn("findings", rows, self.board.out)
        self.assertIn("1 of 2 handed in after round 1 inside the fix", rows["findings"][0])


if __name__ == "__main__":
    unittest.main()
