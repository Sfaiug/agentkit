"""The test audit reads existing timings and ledger rows, and only proposes changes.

Black-box: AK_BIN runs in a Rig with a temporary HOME; no test suite is executed.
"""

import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.gitrig import Rig

DAY, AT = 86400, 1800000000
TIMES = {"tests/test_slow.py": 224, "tests/test_shaky.py": 2, "tests/test_api.py": 8,
         "tests/test_equal.py": 80, "tests/test_unused.py": 50, "tests/test_both.py": 100,
         "tests/test_caught.py": 3}


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home)
        self.rig.git("config", "ak.repository", "0123456789ab")
        self.times = self.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
        self.db = self.home.path / ".agentkit/history.db"
        with sqlite3.connect(self.db) as connection:
            connection.executescript("""
                CREATE TABLE runs (run_id TEXT, repo TEXT);
                CREATE TABLE checks (run_id TEXT, command TEXT, started_at REAL, finished_at REAL);
                CREATE TABLE test_reds (run_id TEXT, round INTEGER, kind TEXT, tree TEXT,
                                        test TEXT, flaky INTEGER, at REAL);
            """)
            connection.executemany("INSERT INTO runs VALUES (?, ?)",
                                   [("fix-api", "widgets"), ("fix-web", "widgets"),
                                    ("fix-other", "widgets-linked")])
            connection.executemany("INSERT INTO checks VALUES (?, ?, ?, ?)",
                [("fix-api", f"AK_SHARD={i}/4 suite", AT, AT + seconds)
                 for i, seconds in enumerate((40, 60, 100, 120), 1)] +
                [("fix-other", "AK_SHARD=1/1 suite", 0, 1),
                 ("fix-api", "suite", AT, AT + 1),
                 ("fix-api", "AK_SHARD=1/1 suite", AT, None),
                 ("fix-api", "AK_SHARD=1/1 suite", AT, AT - 1)])
            reds = [("fix-api", kind, "api", 0) for kind in
                    ("landing", "landing", "done-when", "rules", "tip", "tip", "base-proof")]
            reds += [("fix-web", "landing", "api", 0),
                     ("fix-api", "landing", "shaky", 1), ("fix-api", "landing", "shaky", 1),
                     ("fix-api", "rules", "both", 1), ("fix-api", "rules", "caught", 1),
                     ("fix-web", "done-when", "caught", 0),
                     ("fix-web", "rules", "untimed", 0),
                     ("fix-api", "base-proof", "shaky", 0),
                     ("fix-api", "tip", "caught", 1)]
            connection.executemany("INSERT INTO test_reds VALUES (?, 1, ?, 'tree', ?, ?, ?)",
                [(run, kind, f"tests/test_{name}.py", flaky, AT + 4 * DAY)
                 for run, kind, name, flaky in reds] +
                [("fix-other", "landing", "tests/test_other.py", 1, 0)])

    def report(self, cwd=None, columns=120):
        done = self.home.ak("run", "status", "--tests", cwd=cwd or self.rig.path,
                            env={"COLUMNS": str(columns)})
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def rows(self):
        return {cells[0]: cells[1:] for line in self.report().splitlines()
                if (cells := line.split()) and cells[0].startswith("tests/")}

    def test_each_file_has_its_last_time_and_outcomes_and_proposals_come_first(self):
        before = self.db.read_bytes(), self.times.read_bytes(), self.rig.git("status", "--porcelain")
        rows = self.rows()
        self.assertEqual(list(rows), ["tests/test_slow.py", "tests/test_both.py",
            "tests/test_shaky.py", "tests/test_equal.py", "tests/test_unused.py",
            "tests/test_api.py", "tests/test_caught.py", "tests/test_untimed.py"])
        self.assertEqual(rows["tests/test_slow.py"], ["224.0s", "0", "0", "0", "split"])
        self.assertEqual(rows["tests/test_shaky.py"], ["2.0s", "2", "0", "0", "fix", "or", "delete"])
        self.assertEqual(rows["tests/test_both.py"],
                         ["100.0s", "1", "0", "0", "split;", "fix", "or", "delete"])
        self.assertEqual(rows["tests/test_api.py"], ["8.0s", "0", "2", "1"])
        self.assertEqual(rows["tests/test_caught.py"], ["3.0s", "2", "1", "0"])
        self.assertEqual(rows["tests/test_equal.py"], ["80.0s", "0", "0", "0"])
        self.assertEqual(rows["tests/test_untimed.py"], ["–", "0", "1", "0"])
        for name, seconds in TIMES.items():
            self.assertEqual(rows[name][0], f"{seconds:.1f}s")
        self.assertEqual((self.db.read_bytes(), self.times.read_bytes(),
                          self.rig.git("status", "--porcelain")), before)

    def test_first_line_names_repository_file_count_and_span_of_its_rows(self):
        first = self.report().splitlines()[0]
        for word in ("widgets", "8 files", "4.0 days"):
            self.assertIn(word, first)

    def test_a_subdirectory_uses_its_checkout_and_a_linked_checkout_keeps_its_own_name(self):
        nested = self.rig.path / "src"
        nested.mkdir()
        self.assertIn("widgets", self.report(nested).splitlines()[0])
        linked = self.home.path / "code/widgets-linked"
        self.rig.git("worktree", "add", "--detach", str(linked))
        out = self.report(linked)
        self.assertIn("widgets-linked", out.splitlines()[0])
        rows = {line.split()[0]: line.split()[1:] for line in out.splitlines()
                if line.startswith("tests/")}
        self.assertEqual(rows["tests/test_api.py"], ["8.0s", "0", "0", "0", "split"])
        self.assertEqual(rows["tests/test_other.py"], ["–", "1", "0", "0", "fix", "or", "delete"])

    def test_missing_ledger_and_a_ledger_from_before_test_reds_still_list_timings(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("DROP TABLE test_reds")
        self.assertEqual(self.rows()["tests/test_slow.py"][-1], "split")
        self.db.unlink()
        self.assertEqual(self.rows()["tests/test_slow.py"], ["224.0s", "0", "0", "0"])
        self.times.unlink()
        self.assertIn("0 files", self.report().splitlines()[0])

    def test_reds_still_appear_without_a_times_record(self):
        self.times.unlink()
        rows = self.rows()
        self.assertEqual(rows["tests/test_api.py"], ["–", "0", "2", "1"])
        self.assertEqual(rows["tests/test_shaky.py"], ["–", "2", "0", "0", "fix", "or", "delete"])

    def test_narrow_rows_fold_and_help_names_the_flag(self):
        out = self.report(columns=40)
        self.assertTrue(all(len(line) <= 40 and line == line.rstrip() for line in out.splitlines()), out)
        self.assertIn("tests/test_slow.py", out)
        self.assertIn("224.0s", out)
        self.assertIn("--tests", self.home.ak("run", "status", "--help").out)


if __name__ == "__main__":
    unittest.main()
