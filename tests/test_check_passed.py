"""history.check_passed, chosen rows in test_audit, and gate.unnamed recording exit 1."""

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import gate, history, scoreboard, worker

SHA = "a" * 40


class CheckPassed(Sandbox):
    def insert(self, run_id, kind, tree, exit_code, finished_at=2.0, cmd="python3 suite.py"):
        with contextlib.closing(sqlite3.connect(history.path())) as db:
            db.execute(
                "INSERT INTO checks (run_id, round, kind, command, tree, place, exit, "
                "requested_at, started_at, finished_at, rerun) "
                "VALUES (?, 1, ?, ?, ?, 'host', ?, 1.0, 1.0, ?, 0)",
                (run_id, kind, cmd, tree, exit_code, finished_at))
            db.commit()

    def test_missing_unreadable_none_and_empty_answer_false_without_raising(self):
        self.assertFalse(history.check_passed("r1", "chosen", SHA))
        history.start_run("r1", repo="acme")
        self.insert("r1", "chosen", None, 0)
        for args in (("r1", "chosen", None), ("r1", "chosen", ""), (None, "chosen", SHA),
                     ("r1", None, SHA), ("r1", "chosen", 123)):
            self.assertFalse(history.check_passed(*args), args)
        history.path().unlink()
        history.path().mkdir()
        self.assertFalse(history.check_passed("r1", "chosen", SHA))
        history.path().rmdir()
        history.path().symlink_to(history.path().name)
        self.assertFalse(history.check_passed("r1", "chosen", SHA))

    def test_last_row_for_run_kind_tree_decides(self):
        history.start_run("r1", repo="acme")
        # Another kind on the same tree does not answer for chosen.
        self.insert("r1", "done-when", SHA, 0)
        self.assertFalse(history.check_passed("r1", "chosen", SHA))
        # Red, open, and exit-0 without finished_at all answer False.
        for exit_code, finished in ((1, 2.0), (None, None), (None, 2.0), (0, None)):
            self.insert("r1", "chosen", SHA, exit_code, finished)
            self.assertFalse(history.check_passed("r1", "chosen", SHA))
        # A passing retry (last row by rowid) answers True, for str or Path run_id.
        self.insert("r1", "chosen", SHA, 0, 3.0)
        self.assertTrue(history.check_passed("r1", "chosen", SHA))
        self.assertTrue(history.check_passed(self.root / "r1", "chosen", SHA))
        self.assertFalse(history.check_passed("r1", "chosen", "b" * 40))
        self.assertFalse(history.check_passed("r2", "chosen", SHA))
        # A later red or open row overrides an earlier green.
        self.insert("r1", "chosen", SHA, 1, 4.0)
        self.assertFalse(history.check_passed("r1", "chosen", SHA))
        self.insert("r1", "chosen", SHA, 0, 5.0)
        self.assertTrue(history.check_passed("r1", "chosen", SHA))
        self.insert("r1", "chosen", SHA, None, None)
        self.assertFalse(history.check_passed("r1", "chosen", SHA))

    def test_unnamed_exit_zero_records_red_and_answers_false(self):
        history.start_run("r1", repo="acme")
        repo = self.root / "acme"
        repo.mkdir()
        with patch.object(worker, "kill_marked"), patch.object(gate.gitcall, "dirty_paths", return_value=[]):
            ok, _ = gate.run_done_when(
                ["true"], repo, self.root / "dw.log", set(), 30, lambda _: None,
                silence=15, run_dir=self.root / "r1", shard="1/1", only=["tests/a.sh"],
                checked=(self.root / "r1", 1, "chosen", SHA), chosen=True)
        self.assertFalse(ok)
        self.assertFalse(history.check_passed("r1", "chosen", SHA))
        with contextlib.closing(sqlite3.connect(history.path())) as db:
            rows = db.execute("SELECT exit FROM checks WHERE run_id='r1' AND kind='chosen'").fetchall()
        self.assertEqual(rows, [(1,), (1,)])

    def test_audit_and_board_count_chosen_with_done_when(self):
        history.start_run("r1", repo="acme", started_at=10.0)
        history.finish_run("r1", final_state="pass", finished_at=20.0, changed_lines=1)
        history.test_reds((self.root / "r1", 1, "chosen", SHA), {"1/1": ["tests/a.py"]}, [])
        self.assertEqual(history.test_audit("acme")[0]["tests/a.py"]["catches"], 1)
        self.insert("r1", "done-when", SHA, 0, cmd="AK_SHARD=1/2 python3 other.py")
        self.insert("r1", "chosen", SHA, 0, cmd="AK_SHARD=1/1 python3 suite.py")
        self.assertEqual(scoreboard.compute(now=30.0)["checks"][0]["suites"], 1.0)


if __name__ == "__main__":
    unittest.main()
