"""A history write made while another process reads history.db lands without waiting for it.

Writers share a lock, but readers (the status screen, the scoreboard) take none, and a read
held past sqlite's wait made a write give up: 2,868 `database is locked` lines in history.log
and runs whose rows never left `running`.  Here a second process holds a read open until told
to let go, and this process's sqlite wait is cut to nothing, so the write lands only if a
reader never blocks it.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history  # noqa: E402

# The reader: opens history.db read-only as the screens do, reads inside one transaction,
# says so, and holds the read until its stdin closes.
READER = """
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
db.execute("BEGIN")
db.execute("SELECT count(*) FROM runs").fetchone()
print("reading", flush=True)
sys.stdin.read()
"""


class WriteDuringRead(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agentkit-history-reader-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit").mkdir()
        self.addCleanup(patch.stopall)
        patch.object(config, "HOME", self.home / ".agentkit").start()
        history.start_run("first", repo="acme")
        connect = sqlite3.connect
        patch.object(history.sqlite3, "connect",
                     lambda *args, **kw: connect(*args, **{**kw, "timeout": 0})).start()

    def test_a_write_while_another_process_reads_lands_at_once(self):
        reader = subprocess.Popen([sys.executable, "-c", READER, str(history.path())], text=True,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  env={**os.environ, "HOME": str(self.home)})
        self.addCleanup(reader.stdout.close)
        self.addCleanup(reader.kill)
        self.assertEqual(reader.stdout.readline(), "reading\n")

        writer = threading.Thread(target=history.start_run, args=("mine",), kwargs={"repo": "acme"})
        writer.start()
        writer.join(10)
        self.assertFalse(writer.is_alive(), "the write waited on the reader")
        with sqlite3.connect(f"file:{history.path()}?mode=ro", uri=True) as db:
            rows = sorted(row[0] for row in db.execute("SELECT run_id FROM runs"))
        reader.stdin.close()
        self.assertEqual(reader.wait(), 0)

        self.assertEqual(rows, ["first", "mine"])
        self.assertFalse((config.HOME / "history.log").exists())


if __name__ == "__main__":
    unittest.main()
