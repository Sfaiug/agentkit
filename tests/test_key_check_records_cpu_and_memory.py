"""A check ak runs and reaps on this machine keeps in its `checks` row what it used:
`cpu_seconds`, the user plus system CPU of its command and of every descendant it waited for, and
`peak_mb`, the largest resident memory any one of them reached, both from the rusage `os.wait4`
returns.

Black-box: the program `AK_BIN` names runs a round whose done-when command burns a second of
CPU holding 200 MB, from outside through tests/fixtures/akbin.py, on a project from gitrig.py
with scripted harnesses from fakeadapter.py, and a tick probes a merged run with the same
command as its `health:`, as tests/test_key_landing_and_health_leave_rows.py does; the test
reads the Home's history.db.
"""

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from test_key_every_check_leaves_a_row import Rows
import test_key_health_pass as health
import test_key_landing_and_health_leave_rows as probed

# a second of its own CPU, all of it with 200 MB it wrote resident
BURN = ("python3 -c \"import time; held = b'x' * (200 << 20); "
        "any(time.process_time() >= 1 for _ in iter(int, 1))\"")


class Measured:
    def assert_used(self, db, run, kind):
        """`run`'s rows of `kind` in `db` each keep about what BURN used."""
        with contextlib.closing(sqlite3.connect(db)) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM checks WHERE run_id=? AND kind=? ORDER BY rowid", (run, kind))]
        self.assertTrue(rows)
        for row in rows:
            self.assertGreaterEqual(row.get("cpu_seconds") or 0, 0.5, row)
            self.assertGreaterEqual(row.get("peak_mb") or 0, 150, row)


class ARound(Rows, Measured, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start()
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.burned = cls.launch("Add retry file", (BURN,))

    def test_its_done_when_command_keeps_its_cpu_and_peak_memory(self):
        self.assert_used(self.db, self.burned["id"], "done-when")


class ALiveProbe(probed.Probed, Measured):
    record = {"health": {"command": BURN}}

    def test_it_keeps_its_cpu_and_peak_memory(self):
        self.assert_used(self.home.path / ".agentkit" / "history.db", health.RUN, "health")


if __name__ == "__main__":
    unittest.main()
