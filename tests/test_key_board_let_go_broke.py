"""Findings let go belong to their change's merge week, with its later break.

Black-box: AK_BIN reads runs and findings from a throwaway HOME's history.db.
"""

from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from test_key_history_db import DATABASE, ORIGINAL
from test_key_scoreboard import ROOMY, scoreboard

DAY = 86400


class LetGoBroke(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env["AK_HOST_READINGS"] = ROOMY
        self.now = time.time()
        self.db = sqlite3.connect(self.home.path / DATABASE)
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE runs (%s, "change" TEXT, changed_lines INTEGER, '
                        "broke_after_merge TEXT, landing_breaks INTEGER DEFAULT 0, kind TEXT DEFAULT 'task')" %
                        ", ".join(map(" ".join, ORIGINAL)))
        self.db.execute("CREATE TABLE findings (run_id TEXT, round INTEGER, path TEXT, "
                        "kind TEXT, proof TEXT, outcome TEXT, at REAL)")
        self.run_row("fix-api", change="acme/widgets#1", broke="tip")
        self.run_row("fix-cache")
        self.finding("fix-api", "dispute", "conceded")
        self.finding("fix-cache", "follow-up")

    def run_row(self, name, *, change=None, broke="", ago=3600, merged=True, repo="acme"):
        self.db.execute('INSERT INTO runs (run_id, repo, final_state, started_at, finished_at, '
                        '"change", changed_lines, broke_after_merge) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (name, repo, "pass" if merged else "exhausted", self.now - ago - 600,
                         self.now - ago, change, 1 if merged else None, broke))

    def finding(self, name, kind, outcome=None, *, ago=7200):
        self.db.execute("INSERT INTO findings VALUES (?, 1, 'other.py', ?, 'proof', ?, ?)",
                        (name, kind, outcome, self.now - ago))

    def cells(self):
        self.db.commit()
        done = self.home.ak("run", "status", "--history")
        self.assertEqual(done.code, 0, done.out + done.err)
        return next((this, last) for label, this, last in scoreboard(done.out) if label == "findings")

    def test_conceded_dispute_and_followup_count_with_the_changes_break(self):
        self.assertIn("2 let go; 1 of 2 on a change that broke main or live after merge", self.cells()[0])

    def test_other_outcomes_and_unmerged_changes_do_not_count(self):
        for kind, outcome in (("finding", None), ("note", None),
                              ("dispute", "upheld"), ("dispute", None)):
            self.finding("fix-api", kind, outcome)
        self.run_row("held", broke="tip", merged=False)
        self.finding("held", "follow-up")
        self.run_row("other-repo", change="acme/widgets#1", repo="other", merged=False)
        self.finding("other-repo", "dispute", "dropped")
        self.run_row("future-api", ago=-DAY, broke="tip")
        self.finding("future-api", "follow-up")
        self.finding("fix-api", "follow-up", ago=-DAY)
        self.assertIn("2 let go; 1 of 2 on a change that broke", self.cells()[0])

    def test_earlier_runs_findings_follow_the_change_across_both_date_windows(self):
        self.run_row("retry-api", change="acme/widgets#1", merged=False, ago=17 * DAY)
        self.finding("retry-api", "dispute", "dropped", ago=16 * DAY)
        this, last = self.cells()
        self.assertIn("3 let go; 2 of 3 on a change that broke", this)
        self.assertEqual(last, "not recorded")

    def test_a_later_health_break_updates_the_previous_merge_week(self):
        self.run_row("last-api", ago=8 * DAY)
        self.finding("last-api", "dispute", "dropped", ago=16 * DAY)
        self.assertIn("1 let go; 0 of 1 on a change that broke", self.cells()[1])
        self.db.execute("UPDATE runs SET broke_after_merge='health' WHERE run_id='last-api'")
        this, last = self.cells()
        self.assertIn("1 let go; 1 of 1 on a change that broke main or live after merge", last)
        self.assertIn("2 let go; 1 of 2 on a change that broke", this)


if __name__ == "__main__":
    unittest.main()
