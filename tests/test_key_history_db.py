"""The history database: an older ak's is brought up to today's tables in place, keeping its rows,
and a run that ends in error still leaves its row, in a database it creates.

`~/.agentkit/history.db` is the record of past work that outlives run cleanup: the scoreboard,
the size lines and the reviewers' counts read it, and a host upgraded from an older ak keeps
the database that ak wrote.  So one holding only the first `runs` columns gains every table and
column today's ak reads, with its rows as they were, and says seats' dones were kept only from
then on; and a run refused before its first round is still a row, ended in error.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and the database
is read with sqlite3, as any other program reads it.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home

DATABASE = ".agentkit/history.db"
TABLES = {"runs", "phases", "reviews", "owner", "dones", "kept", "done_runs"}
# The `runs` table as the first ak to keep a history made it, and nothing else.
ORIGINAL = (("run_id", "TEXT PRIMARY KEY"), ("repo", "TEXT"), ("executor", "TEXT"),
            ("reviewer", "TEXT"), ("rounds_used", "INTEGER"), ("final_state", "TEXT"),
            ("verdict", "TEXT"), ("started_at", "REAL"), ("finished_at", "REAL"),
            ("executor_seconds", "REAL"), ("done_when_seconds", "REAL"),
            ("reviewer_seconds", "REAL"), ("merge_seconds", "REAL"), ("total_seconds", "REAL"),
            ("executor_tokens", "INTEGER"), ("reviewer_tokens", "INTEGER"),
            ("peak_rss_mb", "REAL"), ("session", "TEXT"))
GAINED = {"runs": {"task_words", "orchestrator", "change", "merge_sha", "landing_breaks",
                   "broke_after_merge", "executor_effort", "own_orchestrator_effort"},
          "reviews": {"round", "verdict", "effort"}, "dones": {"work"}}
# The Home's notify sink marks every run a test suite's, which ak never records: these runs go
# without it, as the owner's, and with no webhook configured nothing is posted anywhere.
OWNERS = {"AK_NOTIFY_SINK": None}


def read(home, query):
    connection = sqlite3.connect(home.path / DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(query)]
    finally:
        connection.close()


def tables(home):
    return {row["name"] for row in read(home, "SELECT name FROM sqlite_master WHERE type='table'")}


def columns(home, table):
    return {row["name"] for row in read(home, f"PRAGMA table_info({table})")}


class AnOlderDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        now = time.time()
        cls.old = {"run_id": "20261001-1200-fix-api", "repo": "acme", "executor": "opus",
                   "reviewer": "astra", "rounds_used": 2, "final_state": "pass", "verdict": "PASS",
                   "started_at": now - 7200, "finished_at": now - 3600, "executor_seconds": 900.0,
                   "done_when_seconds": 60.0, "reviewer_seconds": 600.0, "merge_seconds": 30.0,
                   "total_seconds": 3600.0, "executor_tokens": 12000, "reviewer_tokens": 3000,
                   "peak_rss_mb": 210.5, "session": "acme-seat"}
        connection = sqlite3.connect(cls.home.path / DATABASE)
        connection.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
        connection.execute("INSERT INTO runs VALUES (%s)" % ",".join("?" * len(ORIGINAL)),
                           [cls.old[name] for name, _ in ORIGINAL])
        connection.commit()
        connection.close()
        cls.before = time.time()
        cls.done = cls.home.ak("run", "status", "--history")

    def test_it_gains_every_table_and_column_today_s_ak_reads(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(tables(self.home), TABLES)
        for table, gained in GAINED.items():
            with self.subTest(table):
                self.assertLessEqual(gained, columns(self.home, table))

    def test_its_rows_keep_their_values_and_still_count(self):
        rows = read(self.home, "SELECT * FROM runs")
        self.assertEqual([{name: row[name] for name, _ in ORIGINAL} for row in rows], [self.old])
        # its repository's size line reads the two rounds the old row took
        sized = [line for line in self.done.out.splitlines() if line.startswith("acme:")]
        self.assertEqual(len(sized), 1, self.done.out)
        self.assertIn("median 2 rounds", sized[0])

    def test_it_says_dones_were_kept_only_from_the_moment_it_was_brought_up(self):
        kept = read(self.home, "SELECT since FROM kept")
        self.assertEqual(len(kept), 1, kept)
        self.assertGreaterEqual(kept[0]["since"], self.before)


class AFailedRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        # four checks: more than a task may hold, so the run ends before its first round
        task = taskfile.write(cls.home, "none", "Tidy the notes", done_when=(
            "test -d .", "true", "test -n x", "echo ok"))
        cls.done = cls.home.ak("run", str(task), env=OWNERS, timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def test_it_ends_in_error_before_any_turn(self):
        self.assertEqual(self.done.code, 2, self.done.out + self.done.err)
        self.assertEqual(self.state["state"], "error")
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))

    def test_it_creates_the_database_with_dones_kept_from_its_start(self):
        self.assertEqual(tables(self.home), TABLES)
        self.assertEqual(read(self.home, "SELECT since FROM kept"), [{"since": 0.0}])

    def test_its_row_says_it_ended_in_error(self):
        rows = read(self.home, "SELECT * FROM runs")
        self.assertEqual(len(rows), 1, rows)
        row, run_id = rows[0], self.run_dir.name
        self.assertEqual({key: row[key] for key in (
            "run_id", "repo", "final_state", "change", "landing_breaks", "broke_after_merge")}, {
            "run_id": run_id, "repo": None, "final_state": "error", "change": run_id,
            "landing_breaks": 0, "broke_after_merge": ""})
        for key in ("task_words", "task_points", "task_checks"):
            with self.subTest(key):
                self.assertEqual(row[key], self.state.get(key))


if __name__ == "__main__":
    unittest.main()
