"""A history row left running after its run ended is brought up to date by the tick itself.

A row's own ending can be lost (a write that failed, a process killed before it), and until it
is written the row counts as running and its run's times count in no week.  One tick gives a
row whose run record has ended that record's ending, and closes a row whose run directory is
gone with its outcome unknown: no longer running, and neither a pass nor a fail, so the median
rounds `ak run status --history` shows leave it out.  A run still queued, running or waiting
keeps its row, and a second tick writes nothing.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
audit off (tests/fixtures/akconfig.py), on a history.db with the first `runs` columns ak kept
(tests/test_key_history_db.py), which ak brings up to its own.
"""

import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from test_key_history_db import ORIGINAL

# The tick asks the public boards: a proxy nobody answers keeps it off the network, as offline.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
NOW = time.time()
STARTED, FINISHED = NOW - 3 * 86400, NOW - 2 * 86400
ROUNDS = 4     # every row's rounds before the tick: what a record that keeps none leaves it
# Each run's record: three ended, with their state, verdict and rounds (None: it keeps none),
# and three still going (held from being resumed or reaped by a backoff that has not run out,
# or, waiting, by no seat to take it up).
ENDED = {"built": ("pass", "PASS", 2), "broke": ("fail", "FAIL", 1),
         "halted": ("stopped", None, None)}
GOING = {"queued": {"state": "queued", "resume_after": NOW + 86400},
         "running": {"state": "running", "resume_after": NOW + 86400},
         "waiting": {"state": "waiting"}}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class HistoryRowsAgreeWithRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, {"alpha": "claude", "beta": "claude"})
        cls.db = cls.home.path / ".agentkit" / "history.db"
        cls.repo = str(cls.home.path / "acme")
        for run_id, (state, verdict, rounds) in ENDED.items():
            kept = {} if rounds is None else {
                "round_summaries": [{"round": n + 1} for n in range(rounds)]}
            cls.record(run_id, state=state, verdict=verdict, finished_at=FINISHED, **kept)
        for run_id, fields in GOING.items():
            cls.record(run_id, **fields)
        with sqlite3.connect(cls.db) as db:
            db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
            db.executemany(
                "INSERT INTO runs (run_id, repo, rounds_used, final_state, started_at, "
                "executor_seconds, done_when_seconds, reviewer_seconds, merge_seconds) "
                "VALUES (?, 'acme', ?, 'running', ?, 0, 0, 0, 0)",
                [(run_id, ROUNDS, STARTED) for run_id in (*ENDED, *GOING, "gone")])
        db.close()
        cls.going = cls.rows(*GOING)
        cls.first = cls.home.ak("watch", env=OFFLINE)
        cls.after_first = cls.rows()
        cls.second = cls.home.ak("watch", env=OFFLINE)
        cls.after_second = cls.rows()
        cls.status = cls.home.ak("run", "status", "--history")

    @classmethod
    def record(cls, run_id, **fields):
        cls.home.write(f".agentkit/runs/{run_id}/run.json",
                       {"run_id": run_id, "repo": cls.repo, "started_at": STARTED, **fields})

    @classmethod
    def rows(cls, *run_ids):
        with sqlite3.connect(cls.db) as db:
            db.row_factory = sqlite3.Row
            found = {row["run_id"]: dict(row) for row in db.execute("SELECT * FROM runs")}
        db.close()
        return {run_id: found[run_id] for run_id in run_ids or found}

    def test_the_ticks_pass(self):
        for done in (self.first, self.second, self.status):
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_an_ended_record_gives_its_row_its_ending(self):
        for run_id, (state, verdict, rounds) in ENDED.items():
            with self.subTest(run_id):
                row = self.after_first[run_id]
                self.assertEqual((row["final_state"], row["verdict"], row["rounds_used"]),
                                 (state, verdict, ROUNDS if rounds is None else rounds))
                self.assertEqual(row["finished_at"], FINISHED)
                self.assertEqual(row["total_seconds"], FINISHED - STARTED)

    def test_a_gone_run_stops_running_as_neither_pass_nor_fail(self):
        row = self.after_first["gone"]
        self.assertIsNotNone(row["finished_at"])
        self.assertNotIn(row["final_state"], ("running", "pass", "fail"))
        # acme's ended tasks took 2 and 1 rounds (the stopped one never counts); the gone run's
        # 4 would bring the median to 2
        self.assertIn("acme: last 20 tasks: median 1.5 rounds", self.status.out)

    def test_a_run_still_going_keeps_its_row(self):
        for run_id, before in self.going.items():
            with self.subTest(run_id):
                after = self.after_second[run_id]
                self.assertEqual({name: after[name] for name in before}, before)
                self.assertEqual((after["final_state"], after["finished_at"]), ("running", None))

    def test_a_second_tick_writes_nothing(self):
        self.assertEqual(self.after_second, self.after_first)


if __name__ == "__main__":
    unittest.main()
