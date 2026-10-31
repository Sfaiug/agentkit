"""Every finding a review hands in leaves one row in history.db's `findings` table, with how ak
weighed it and how it ended.

A row names the run, its review and round, the record's site, the kind the reviewer handed in
and the kind ak weighed it to, its proof (the command, else the quoted lines) with the proof's
exit on the reviewed commit and on base, ak's word on a finding it re-proved, and how a dispute
ended.  A finding's end is read from its rows alone, the same run, path and proof across rounds:
fixed where its last row is ak's replay passing, at the budget where it is still a finding in
the run's last round.  A run with no `runs` row leaves none.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, with
scripted harnesses from fakeadapter.py, and the test reads the Home's history.db.
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

# Each fails while its line of words.txt is lower case, and passes on base, which has no file:
# no done-when names it, so its proof on base runs without the change's copy.
FIRST = "! grep -qx first words.txt"
SECOND = "! grep -qx second words.txt"
# fails on base and on the change alike: a defect from before the task
LEGACY = "! grep -qx legacy legacy.txt"
WORK = {"write": {"retry.txt": "hello\n", "words.txt": "first\nsecond\n"},
        "commit": "add retry.txt and words.txt", "final": "## Summary\nwrote both",
        "hand_in": [["done"]]}
REVIEW = {"final": "Found four.", "hand_in": [
    ["finding", "words.txt:1", "the first line is lower case", "it opens the file", "--run", FIRST],
    ["finding", "words.txt:2", "the second line is lower case", "it reads as one", "--run", SECOND],
    ["finding", "words.txt:2", "the second line is short", "it says little", "--quote", "second"],
    ["follow-up", "legacy.txt:1", "legacy is lower case", "it predates the task", "--run", LEGACY,
     "--before", "legacy"],
    ["done"]]}
# fixes the first finding and disputes the second
FIX = {"write": {"words.txt": "First\nsecond\n"}, "commit": "capitalise the first line",
       "final": "## Summary\ncapitalised the first line", "hand_in": [
           ["dispute", "words.txt:2", "lower case is the house style", "--run", "true"], ["done"]]}
# The Home's notify sink marks every run a test suite's, which ak never records: the owner's runs
# go without it, and with no webhook configured nothing is posted anywhere.
OWNERS = {"AK_NOTIFY_SINK": None}


class EveryFindingLeavesARow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"legacy.txt": "legacy\n"})
        cls.db = cls.home.path / ".agentkit" / "history.db"
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude=[WORK, FIX], codex=[REVIEW, "pass"])
        cls.two = cls.launch("Add retry file", OWNERS)
        # a fix that puts base back, disputing the second finding: the next round reviews base
        cls.fakes["claude"].behave(WORK, {"sh": f"git reset -q --hard {cls.rig.head()}",
                                          "final": "## Summary\nput base back",
                                          "hand_in": FIX["hand_in"]})
        cls.fakes["codex"].behave(REVIEW, "pass")
        cls.reset = cls.launch("Put base back", OWNERS, done_when=("true",))
        cls.fakes["claude"].behave("work")
        cls.fakes["codex"].behave("fail")
        cls.budget = cls.launch("Add spent file", OWNERS, {"rounds": 1})
        cls.suite = cls.launch("Add suite file", front={"rounds": 1})

    @classmethod
    def launch(cls, title, env=None, front=None, **task):
        task = taskfile.write(cls.home, cls.rig.path, title, front=front, **task)
        cls.home.ak("run", str(task), "--no-merge", env=env, timeout=300)
        run_dir, = (path for path in taskfile.runs(cls.home)
                    if path.name.endswith(taskfile.slug(title)))
        return {**json.loads((run_dir / "run.json").read_text()), "id": run_dir.name}

    def query(self, sql, *args):
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, args)]

    def rows(self, run, round=None):
        return self.query("SELECT * FROM findings WHERE run_id=? AND round IS COALESCE(?, round) "
                          "ORDER BY round, rowid", run["id"], round)

    def ends(self, run):
        """Each finding's last row, by its path and proof."""
        return {(row["path"], row["proof"]): row for row in self.rows(run)}

    def test_the_run_took_two_rounds(self):
        self.assertEqual([summary["verdict"] for summary in self.two["round_summaries"]],
                         ["FAIL", "PASS"])

    def test_round_one_has_a_row_for_each_record_handed_in_as_ak_weighed_it(self):
        self.assertEqual([(row["path"], row["line"], row["handed"], row["kind"], row["proof"])
                          for row in self.rows(self.two, 1)],
                         [("words.txt", 1, "finding", "finding", FIRST),
                          ("words.txt", 2, "finding", "finding", SECOND),
                          ("words.txt", 2, "finding", "note", "second"),
                          ("legacy.txt", 1, "follow-up", "follow-up", LEGACY)])

    def test_a_proof_s_exits_are_its_own_on_the_commit_and_on_base(self):
        first, second, quote, follow_up = self.rows(self.two, 1)
        self.assertEqual([(row["commit_exit"] != 0, row["base_exit"]) for row in (first, second)],
                         [(True, 0), (True, 0)])
        self.assertEqual((quote["commit_exit"], quote["base_exit"]), (None, None))
        # proven on base alone, where it fails
        self.assertEqual((follow_up["commit_exit"], follow_up["base_exit"] != 0), (None, True))

    def test_round_two_has_the_fixed_finding_s_replay_and_the_dropped_dispute(self):
        replay, dispute = self.rows(self.two, 2)
        self.assertEqual((replay["path"], replay["line"], replay["handed"], replay["kind"],
                          replay["proof"], replay["replayed"]),
                         ("words.txt", 1, "finding", "note", FIRST, "fixed; its proof passes now"))
        self.assertEqual((dispute["path"], dispute["line"], dispute["handed"], dispute["kind"],
                          dispute["proof"], dispute["commit_exit"], dispute["outcome"]),
                         ("words.txt", 2, "dispute", "dispute", "true", 0, "dropped"))

    def test_a_proof_on_reviewed_work_that_is_base_s_own_is_its_exit_there_alone(self):
        self.assertEqual(self.reset["round_summaries"][-1]["head_sha"], self.rig.head())
        self.assertEqual([(row["kind"], row["commit_exit"], row["base_exit"])
                          for row in self.rows(self.reset, 2)],
                         [("note", 0, None), ("dispute", 0, None)])

    def test_each_row_names_its_round_s_review(self):
        reviews = {row["round"]: row["review_id"] for row in self.query(
            "SELECT round, review_id FROM reviews WHERE run_id=?", self.two["id"])}
        self.assertEqual({(row["round"], row["review_id"]) for row in self.rows(self.two)},
                         set(reviews.items()))

    def test_a_finding_s_last_row_says_it_ended_fixed(self):
        self.assertEqual(self.ends(self.two)[("words.txt", FIRST)]["replayed"],
                         "fixed; its proof passes now")

    def test_a_finding_still_a_finding_in_the_last_round_ended_at_the_budget(self):
        last, = self.query("SELECT rounds_used FROM runs WHERE run_id=?", self.budget["id"])
        end, = self.ends(self.budget).values()
        self.assertEqual((end["kind"], end["round"]), ("finding", last["rounds_used"]))

    def test_a_run_with_no_runs_row_leaves_no_findings_rows(self):
        self.assertEqual(self.query("SELECT 1 FROM runs WHERE run_id=?", self.suite["id"]), [])
        self.assertEqual(self.rows(self.suite), [])
        # its reviewer did hand one in
        self.assertEqual(len(self.suite["round_summaries"]), 1)
        self.assertEqual(self.suite["round_summaries"][0]["finding_count"], 1)


if __name__ == "__main__":
    unittest.main()
