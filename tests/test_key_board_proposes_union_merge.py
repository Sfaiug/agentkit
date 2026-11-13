"""The board's conflicts row names, for each file whose conflicts only added lines, the
`.gitattributes` line that lets git take both sides; a path that line cannot name, as git or the
screen reads it, is listed without one.

Black-box: AK_BIN reads history.db in a temporary HOME, with no project checkout.

Owner, 12 Nov 2026: the board lists no change that rewrote lines another seat's change added in
the 7 days before (write-up risk 18, two seats with opposite intent).  Of 80 of that week's 688
merges 12 did, 38 pairs, 24 of them of one or two lines: churn, as the count dropped on 16 Oct
was.  The first change's own key, run at landing, is what stops a second from undoing it.
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


class ProposesUnionMerge(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env["AK_HOST_READINGS"] = ROOMY
        self.now = time.time()
        with closing(sqlite3.connect(self.home.path / DATABASE)) as db, db:
            columns = (*ORIGINAL, ("change", "TEXT"), ("changed_lines", "INTEGER"))
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, columns)))
            db.execute("CREATE TABLE conflicts (run_id TEXT, at REAL, how TEXT, target TEXT, "
                       "tip TEXT, path TEXT, added_only INTEGER, outcome TEXT)")
            db.execute("INSERT INTO runs (run_id, repo, final_state, started_at, finished_at, "
                       "rounds_used, changed_lines) VALUES ('fix-api', 'acme', 'pass', ?, ?, 1, 1)",
                       (self.now - 7200, self.now - 3600))
        self.conflicts(("docs/notes.md", 1), ("docs/notes.md", 1), ("app.py", 1), ("app.py", 0))

    def conflicts(self, *rows):
        """Conflicts of the week on the merged run, each a path and whether it only added lines."""
        with closing(sqlite3.connect(self.home.path / DATABASE)) as db, db:
            db.executemany("INSERT INTO conflicts (run_id, at, path, added_only) "
                           "VALUES ('fix-api', ?, ?, ?)", [(self.now - 4000, *row) for row in rows])

    def row(self):
        done = self.home.ak("run", "status", "--history")
        self.assertEqual(done.code, 0, done.out + done.err)
        return dict((label, this) for label, this, _ in scoreboard(done.out))["conflicts"]

    def test_only_the_file_whose_conflicts_all_added_lines_gets_the_line(self):
        self.assertEqual(self.row(), (
            "100% of merged changes met a conflict; acme/app.py: 2 conflicts; acme/docs/notes.md: "
            "2 conflicts (added lines only: `docs/notes.md merge=union` in acme's .gitattributes "
            "takes both sides)"))

    def test_a_path_the_line_cannot_name_gets_none(self):
        # a space and a glob .gitattributes reads as a pattern's syntax, a format and a control
        # character the screen drops, and a path whose line git ignores at 2048 bytes
        for path in ("to do.md", "notes[1].md", "no\u200btes.md", "no\x01tes.md", "a" * 2033 + ".md"):
            with self.subTest(path=path[:20]):
                self.conflicts(*[(path, 1)] * 3)
                row = self.row()
                self.assertIn(": 3 conflicts (added lines only); acme/app.py: 2 conflicts; ", row)
                self.assertEqual(row.count("merge=union"), 1, row)
                with closing(sqlite3.connect(self.home.path / DATABASE)) as db, db:
                    db.execute("DELETE FROM conflicts WHERE path = ?", (path,))


if __name__ == "__main__":
    unittest.main()
