"""The board names repeat conflict files and classifies only unanimous added-only collisions.

Black-box: AK_BIN reads history.db in a temporary HOME, with no project checkout.
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
from test_key_scoreboard import ROOMY, scoreboard

WEEK = 7 * 86400
NOTES = " (added lines only: `notes.md merge=union` in acme's .gitattributes takes both sides)"


class CollidingFiles(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env["AK_HOST_READINGS"] = ROOMY
        self.now = time.time()
        self.path = self.home.path / DATABASE
        with closing(sqlite3.connect(self.path)) as db, db:
            columns = (*ORIGINAL, ("change", "TEXT"), ("changed_lines", "INTEGER"))
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, columns)))
            db.execute("CREATE TABLE conflicts (run_id TEXT, at REAL, how TEXT, target TEXT, "
                       "tip TEXT, path TEXT, added_only INTEGER, outcome TEXT)")
        for name in ("first", "second", "third", "clean"):
            self.run_row(name)
        for name in ("first", "second", "third"):
            self.conflict(name, "notes.md")
        self.conflict("first", "app.py")
        self.conflict("second", "app.py", added=False)
        self.conflict("first", "once.py")

    def run_row(self, name, *, repo="acme", ago=3600, change=None, merged=True, state="pass"):
        finish = self.now - ago
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO runs (run_id, repo, final_state, started_at, finished_at, "
                       "rounds_used, change, changed_lines) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                       (name, repo, state, finish - 7200, finish, change, 1 if merged else None))

    def conflict(self, name, path, *, added=True, ago=4000):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO conflicts (run_id, at, path, added_only) VALUES (?, ?, ?, ?)",
                       (name, self.now - ago, path, added))

    def row(self):
        done = self.home.ak("run", "status", "--history")
        self.assertEqual(done.code, 0, done.out + done.err)
        rows = {label: (this, before) for label, this, before in scoreboard(done.out)}
        self.assertIn("conflicts", rows, done.out)
        return rows["conflicts"]

    def test_repeat_files_have_counts_and_only_unanimous_added_only_files_say_so(self):
        for ago in (3 * WEEK, -86400):
            self.conflict("first", "notes.md", added=False, ago=ago)
        self.assertEqual(self.row(), (
            "75% of merged changes met a conflict; acme/notes.md: 3 conflicts" + NOTES
            + "; acme/app.py: 2 conflicts", "no merged change"))

    def test_merged_work_without_conflicts_shows_zero(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM conflicts")
        self.assertEqual(self.row(), ("0% of merged changes met a conflict", "no merged change"))

    def test_top_three_keep_repositories_separate_and_count_each_weeks_conflicts(self):
        self.run_row("other", repo="widgets")
        self.run_row("previous", ago=WEEK + 3600)
        for path, count in (("notes.md", 4), ("z.py", 2), ("single.py", 1)):
            for _ in range(count):
                self.conflict("other", path, added=None)
        for _ in range(2):
            self.conflict("previous", "old.md", ago=WEEK + 4000)
        self.assertEqual(self.row(), (
            "80% of merged changes met a conflict; widgets/notes.md: 4 conflicts; "
            "acme/notes.md: 3 conflicts" + NOTES + "; acme/app.py: 2 conflicts",
            "100% of merged changes met a conflict; acme/old.md: 2 conflicts (added lines only: "
            "`old.md merge=union` in acme's .gitattributes takes both sides)"))

    def test_change_share_counts_retries_once_and_ignores_unmerged_stopped_and_suite_work(self):
        self.run_row("retry", change="acme/widgets#7", ago=3 * WEEK, merged=False)
        self.run_row("delivered", change="acme/widgets#7")
        self.run_row("duplicate", change="acme/widgets#7")
        self.conflict("retry", "older.md", ago=3 * WEEK + 1)
        for name, repo, state in (("unmerged", "acme", "fail"), ("stopped", "acme", "stopped"),
                                  ("suite", "agentkit-smoke", "pass")):
            self.run_row(name, repo=repo, state=state, merged=False)
            self.conflict(name, "ignored.py")
        self.assertEqual(self.row()[0],
                         "80% of merged changes met a conflict; acme/notes.md: 3 conflicts"
                         + NOTES + "; acme/app.py: 2 conflicts")


if __name__ == "__main__":
    unittest.main()
