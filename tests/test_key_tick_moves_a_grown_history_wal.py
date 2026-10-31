"""The tick moves history.db's WAL into the database once it has grown past 4 MiB, and leaves a
smaller one where it is, while other processes have the database open.

No write of history moves the WAL: each holds the writers' shared lock, and on a busy disk the
syncs of moving it there held a dozen processes in that lock (30 Oct 2026).  So the tick does it
on its own, and a WAL nobody moves would only grow.  Black-box: the program `AK_BIN` names ticks
from outside through tests/fixtures/akbin.py, while this test holds history.db open, having read,
as a running ak does, and reads the database file sqlite3 leaves.
"""

import contextlib
import sqlite3
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, boxable

DATABASE = ".agentkit/history.db"
GROWN = "x" * (5 * 1024 * 1024)     # a WAL past 4 MiB, written by one commit


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class TickMovesAGrownWal(unittest.TestCase):
    def test_a_wal_past_4_mib_is_moved_and_a_smaller_one_left(self):
        with Home() as home, contextlib.closing(sqlite3.connect(home.path / DATABASE)) as db:
            akconfig.write(home, ["opus"])      # no audit seat for the tick to open
            database = home.path / DATABASE
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA wal_autocheckpoint=0")     # this test's own writes move nothing
            db.execute("CREATE TABLE notes (body TEXT)")
            db.commit()
            made = database.read_bytes()
            done = home.tick()
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(database.read_bytes(), made)

            db.execute("INSERT INTO notes VALUES (?)", (GROWN,))
            db.commit()
            self.assertEqual(database.read_bytes(), made)
            done = home.tick()
            self.assertEqual(done.code, 0, done.err)
            self.assertGreater(database.stat().st_size, len(GROWN))
            self.assertEqual(db.execute("SELECT length(body) FROM notes").fetchone()[0],
                             len(GROWN))


if __name__ == "__main__":
    unittest.main()
