"""The history board counts suites and all check hours per merged change, across its runs.

Black-box: AK_BIN reads runs and checks written into a throwaway HOME's history.db, as an
older ak leaves them. Shards share one suite; rounds, kinds, trees and runs do not.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from test_key_history_db import DATABASE, ORIGINAL
from test_key_scoreboard import scoreboard

WEEK = 7 * 86400


class BoardChecks(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.now = time.time()
        self.path = self.home.path / DATABASE
        with closing(sqlite3.connect(self.path)) as db, db:
            columns = (*ORIGINAL, ("change", "TEXT"), ("changed_lines", "INTEGER"))
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, columns)))
            db.execute("CREATE TABLE checks (run_id TEXT, round INTEGER, kind TEXT, tree TEXT, "
                       "command TEXT, started_at REAL, finished_at REAL, requested_at REAL, "
                       "exit INTEGER, place TEXT, rerun INTEGER)")
        self.run_row("retry", change="acme/widgets#7", ago=WEEK + 3600, merged=False)
        self.run_row("first", change="acme/widgets#7")
        self.run_row("second")                  # no change name: grouped by its run id
        self.run_row("earlier", ago=WEEK + 3600)
        self.run_row("unmerged", merged=False)
        for round, kind in ((1, "rules"), (2, "rules"), (None, "landing")):
            for shard in range(2):
                self.piece("first", round=round, kind=kind, command=f"AK_SHARD={shard}/2 suite")
        for shard in range(2):
            self.piece("second", command=f"AK_SHARD={shard}/2 suite")
        self.piece("retry", command="verify-api", seconds=3600, ago=WEEK + 3600)
        self.piece("unmerged", seconds=36000)

    def run_row(self, name, *, change=None, ago=3600, merged=True):
        finish = self.now - ago
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO runs (run_id, repo, final_state, started_at, finished_at, "
                       "rounds_used, change, changed_lines) VALUES (?, 'acme', ?, ?, ?, 2, ?, ?)",
                       (name, "pass" if merged else "fail", finish - 7200, finish,
                        change, 1 if merged else None))

    def piece(self, run_id, *, round=1, kind="rules", tree="cedar", command="AK_SHARD=0/2 suite",
              seconds=900, ago=3600):
        finish = self.now - ago
        with closing(sqlite3.connect(self.path)) as db, db:
            # named: ak adds columns to the table as it opens it
            db.execute("INSERT INTO checks (run_id, round, kind, tree, command, started_at, "
                       "finished_at, requested_at, exit, place, rerun) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'helper', 1)",
                       (run_id, round, kind, tree, command, finish - (seconds or 900),
                        finish if seconds is not None else None, finish - 7200, 1))

    def checks(self):
        done = self.home.ak("run", "status", "--history")
        self.assertEqual(done.code, 0, done.out + done.err)
        return next((this, before) for label, this, before in scoreboard(done.out)
                    if label == "checks")

    def clear_checks(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM checks")

    def test_four_suites_and_all_check_hours_are_divided_by_two_merged_changes(self):
        # Eight overlapping shard rows cost two hours, the earlier failed run another hour.
        # Its change merged this week, so that hour belongs here, not in the previous week.
        self.assertEqual(self.checks(),
                         ("2.00 suite runs and 1.50 check hours per merged change", "not recorded"))

    def test_each_week_counts_its_own_merged_changes(self):
        self.piece("earlier", seconds=3600, ago=WEEK + 3600)
        self.assertEqual(self.checks(),
                         ("2.00 suite runs and 1.50 check hours per merged change",
                          "1.00 suite runs and 1.00 check hours per merged change"))

    def test_no_check_rows_is_unknown_but_recorded_checks_without_a_suite_is_zero(self):
        self.clear_checks()
        self.assertEqual(self.checks(), ("not recorded", "not recorded"))
        self.piece("first", command="verify-api", seconds=1800)
        self.assertEqual(self.checks()[0], "0.00 suite runs and 0.25 check hours per merged change")

    def test_suite_identity_is_run_round_kind_and_tree_even_when_a_command_repeats(self):
        self.clear_checks()
        for round, kind, tree in ((1, "rules", "cedar"), (2, "rules", "cedar"),
                                  (2, "rules", "birch"), (2, "done-when", "cedar")):
            self.piece("first", round=round, kind=kind, tree=tree, seconds=1800)
        self.piece("second", seconds=1800)       # same round, kind and tree, another run
        self.piece("first", seconds=1800)        # same identity again: hours, not another suite
        self.assertEqual(self.checks()[0], "2.50 suite runs and 1.50 check hours per merged change")

    def test_an_unfinished_check_counts_its_suite_without_inventing_hours(self):
        self.piece("first", round=3, seconds=None)
        self.assertEqual(self.checks()[0], "2.50 suite runs and 1.50 check hours per merged change")

    def test_checks_on_unmerged_work_give_no_measure(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE runs SET changed_lines=NULL, final_state='fail'")
        self.assertEqual(self.checks(), ("not recorded", "not recorded"))


if __name__ == "__main__":
    unittest.main()
