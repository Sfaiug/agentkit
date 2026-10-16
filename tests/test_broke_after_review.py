"""The scoreboard counts the merged changes that broke after review passed them.

A review miss counts only when something breaks (the owner's yes, 16 Oct 2026): the change's
tests went red at landing, or main's checks or its live health broke after its merge, as its
history row records it (`history.add_landing_break`, `watch.broke_after_merge`).  Code a later
change rewrites is no break: it may be the next feature.  A row from before breaks were
recorded is unknown, never unbroken.  Offline: a sandbox HOME's history.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, scoreboard

NOW = 1_800_000_000
DAY = 86400


class BrokeAfterReview(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-broke-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.root))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        for name in ("RUNS", "REPO", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.object(scoreboard.time, "time", return_value=NOW))
        stack.enter_context(patch.object(scoreboard, "_git", return_value=None))
        stack.enter_context(patch.object(config, "session_records", return_value={}))
        history._OPEN.clear()

    def merged(self, run_id, when, landing=0, after=None):
        """A merged run's row ended at `when`, its tests red `landing` times at landing and its
        merge breaking `after` ("checks", "health") or nothing."""
        history.start_run(run_id, repo="widget", started_at=when - 3600, change=run_id)
        for _ in range(landing):
            history.add_landing_break(run_id)
        if after:
            history.update_run(run_id, broke_after_merge=after)
        history.finish_run(run_id, final_state="pass", finished_at=when, changed_lines=10)

    def test_breaks_are_counted_per_merged_change_each_week(self):
        self.merged("clean", NOW - DAY)
        self.merged("red-at-landing", NOW - DAY, landing=2)
        self.merged("broke-live", NOW - 2 * DAY, after="health")
        self.merged("broke-main", NOW - 9 * DAY, landing=1, after="checks")
        self.merged("old", NOW - 10 * DAY)
        # a row from before breaks were recorded: unknown, never unbroken
        with sqlite3.connect(history.path()) as db:
            db.execute("UPDATE runs SET landing_breaks=NULL, broke_after_merge=NULL "
                       "WHERE run_id='old'")
        history.start_run("failed", repo="widget", started_at=NOW - 7200, change="failed")
        history.finish_run("failed", final_state="fail", finished_at=NOW - 3600)
        [this_week, before] = scoreboard.compute(NOW)["broke"]
        self.assertEqual(this_week, {"merged": 3, "unknown": 0, "landing": 1, "after_merge": 1})
        self.assertEqual(before, {"merged": 1, "unknown": 1, "landing": 1, "after_merge": 1})
        with patch.object(scoreboard.terminal, "content_width", return_value=400):
            board = "\n".join(scoreboard.render())
        self.assertIn("broke     1 of 3 merged changes broke main or live after merge; 1 went red "
                      "at landing", board)
        self.assertIn("1 of 1 merged changes broke main or live after merge; 1 went red at "
                      "landing; 1 merged before breaks were recorded", board)

    def test_a_week_with_no_merged_change_says_so(self):
        history.start_run("open", repo="widget", started_at=NOW - 3600, change="open")
        history.finish_run("open", final_state="fail", finished_at=NOW - 1800)
        self.assertEqual(scoreboard.compute(NOW)["broke"], [None, None])
        with patch.object(scoreboard.terminal, "content_width", return_value=400):
            self.assertIn("broke     no merged change", "\n".join(scoreboard.render()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
