"""The history board counts findings and answered disputes by their own dates, including
findings raised in an earlier round of the same run. Black-box: AK_BIN and a throwaway HOME.
"""

from contextlib import closing
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from test_key_history_db import DATABASE, ORIGINAL
from test_key_scoreboard import ROOMY, scoreboard


class FindingsRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.env["AK_HOST_READINGS"] = ROOMY
        now = time.time()
        with closing(sqlite3.connect(cls.home.path / DATABASE)) as db, db:
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
            db.execute("CREATE TABLE findings (run_id TEXT, review_id TEXT, round INTEGER, "
                       "path TEXT, line INTEGER, handed TEXT, kind TEXT, proof TEXT, "
                       "commit_exit INTEGER, base_exit INTEGER, replayed TEXT, reason TEXT, "
                       "outcome TEXT, at REAL)")
            # These runs are still going: the finding's date decides its week, not an ending.
            db.executemany("INSERT INTO runs (run_id, repo, final_state) VALUES (?, ?, ?)",
                           [(name, "acme", "running") for name in ("fix-api", "fix-cache", "older-api")]
                           + [("stopped", "acme", "stopped"), ("suite", "agentkit-smoke", "pass")])
            rows = [
                ("fix-api", 1, "retry.py", "finding", "retry proof", None, 3600),
                ("fix-api", 2, "retry.py", "finding", "retry proof", None, 3500),
                ("fix-api", 2, "cache.py", "finding", "cache proof", None, 3400),
                ("fix-cache", 1, "cache.py", "finding", "cache proof", None, 3300),
                ("fix-api", 2, "retry.py", "dispute", "first answer", "dropped", 3200),
                ("fix-api", 2, "cache.py", "dispute", "second answer", "conceded", 3100),
                ("fix-cache", 2, "cache.py", "dispute", "third answer", "upheld", 3000),
                ("fix-api", 3, "retry.py", "note", "retry proof", None, 2900),
                ("fix-api", 3, "cache.py", "dispute", "unanswered", None, 2800),
                ("older-api", 1, "old.py", "finding", "old proof", None, 15 * 86400),
                ("older-api", 2, "old.py", "finding", "old proof", None, 8 * 86400),
                ("fix-api", 3, "retry.py", "finding", "retry proof", None, -86400),
                ("stopped", 1, "retry.py", "finding", "retry proof", None, 3600),
                ("suite", 1, "retry.py", "finding", "retry proof", None, 3600),
            ]
            db.executemany("INSERT INTO findings (run_id, round, path, kind, proof, outcome, at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           [(*row[:-1], now - row[-1]) for row in rows])
        cls.done = cls.home.ak("run", "status", "--history")

    def test_this_week_counts_blocking_disputed_conceded_and_raised_again(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        rows = {label: (this, last) for label, this, last in scoreboard(self.done.out)}
        self.assertIn("findings", rows, self.done.out)
        self.assertEqual(rows["findings"][0],
                         "4 blocking; 3 disputed; 2 of 3 conceded; 1 of 4 raised again; "
                         "0 let go; 0 of 0 on a change that broke main or live after merge; "
                         "0 of 0 handed in after round 1 inside the fix")

    def test_previous_week_recognises_a_finding_raised_before_both_weeks(self):
        rows = {label: (this, last) for label, this, last in scoreboard(self.done.out)}
        self.assertIn("findings", rows, self.done.out)
        self.assertEqual(rows["findings"][1],
                         "1 blocking; 0 disputed; 0 of 0 conceded; 1 of 1 raised again; "
                         "0 let go; 0 of 0 on a change that broke main or live after merge; "
                         "0 of 0 handed in after round 1 inside the fix")


if __name__ == "__main__":
    unittest.main()
