"""Each `ak orch check SEAT` that reaches a result is a row of the history's `done_checks`: the
seat, its orchestrator and that one's effort as the seat's record names them, when the check
ended, and how many things the owner asked it found not in the work, 0 for none.  A check that
could not be made (exit 2) leaves no row.

The owner compares orchestrators by how often and how much their seats' checks find missing, and
a seat is checked many times before a done, which `dones` keeps once.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a Claude seat of
tests/fixtures/akseat.py whose transcript the test writes, the checker a fake harness of
fakeadapter.py handing in what the test gives it, and the database is read with sqlite3.
"""

import json
import re
import shlex
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

CONVERSATION = "5c1e8a42-7d3b-4f9a-b2e6-0a9d4c7f1e35"
ASKED = ("Add a retry button to the upload page.", "Also email me a receipt after every upload.")


class ADoneChecksResultIsKept(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        self.checker = fakeadapter.install(home, codex="pass")["codex"]
        # its orchestrator at an effort of the seat's own, not its model entry's
        seat = Seat(home, "acme", alive=False, record={
            "conversation": CONVERSATION, "reviewers": ["astra"], "efforts": {"opus": {"effort": "low"}}})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/{CONVERSATION}.jsonl", "".join(
            json.dumps({"type": "user", "timestamp": f"2026-11-24T10:0{n}:00Z",
                        "message": {"role": "user", "content": text}}) + "\n"
            for n, text in enumerate(ASKED)))
        home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button · check: `true` · "
                                                   "acme · written 2026-11-24 10:05 · done 2026-11-24 11:00\n")

    def check(self, *missing):
        """`ak orch check acme`, its checker handing in each of `missing` as a gap quoting it."""
        self.checker.behave({"sh": "; ".join(
            f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- {shlex.quote(quote)} owner | head -n 1):1\" "
            f"'not in the work' 'the owner asked for it' --quote {shlex.quote(quote)}" for quote in missing),
            "final": "Checked.", "hand_in": [["done"]]})
        before = time.time()
        done = self.home.ak("orch", "check", "acme")
        return done, before, time.time()

    def rows(self):
        """The `done_checks` rows, none where ak made no such table."""
        connection = sqlite3.connect(self.home.path / ".agentkit/history.db")
        connection.row_factory = sqlite3.Row
        try:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'done_checks'").fetchone():
                return []
            return [dict(row) for row in connection.execute("SELECT * FROM done_checks")]
        finally:
            connection.close()

    def assert_kept(self, gaps, code):
        done, before, after = self.check(*ASKED[:gaps])
        self.assertEqual(done.code, code, done.out + done.err)
        rows = self.rows()
        self.assertEqual([{key: row[key] for key in ("session", "model", "effort", "gaps")} for row in rows],
                         [{"session": "acme", "model": "opus", "effort": "low", "gaps": gaps}])
        self.assertTrue(before <= rows[0]["at"] <= after, rows)

    def test_two_things_missing_leave_a_row_of_two_gaps(self):
        self.assert_kept(2, 1)

    def test_nothing_missing_leaves_a_row_of_no_gap(self):
        self.assert_kept(0, 0)

    def test_a_check_that_cannot_be_made_leaves_no_row(self):
        self.checker.behave("silent")
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(self.checker.n, 1)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
