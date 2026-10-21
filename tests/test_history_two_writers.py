"""A history write made while another process is writing history.db waits for it and lands.

Runs, the tick and the menu are separate processes; a write that met another's longer than
sqlite's own wait used to be dropped.  Here a second process holds a write open until told to
let go, and this process's sqlite wait is cut to nothing, so only the writers' shared lock can
keep its write.
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

# The other writer: inserts its own row, says so, and holds the write until its stdin closes.
HOLDER = """
import sys
sys.path.insert(0, sys.argv[1])
from agentkit import history

def hold(connection):
    connection.execute("INSERT INTO runs (run_id, repo) VALUES ('other', 'acme')")
    print("held", flush=True)
    sys.stdin.read()

history._write(hold)
"""


class TwoWriters(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agentkit-history-writers-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit").mkdir()
        self.addCleanup(patch.stopall)
        patch.object(config, "HOME", self.home / ".agentkit").start()
        connect = sqlite3.connect
        patch.object(history.sqlite3, "connect",
                     lambda *args, **kw: connect(*args, **{**kw, "timeout": 0})).start()

    def test_a_write_while_another_process_writes_lands_after_it(self):
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(REPO)], text=True,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  env={**os.environ, "HOME": str(self.home)})
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline(), "held\n")

        writer = threading.Thread(target=history.start_run, args=("mine",), kwargs={"repo": "acme"})
        writer.start()
        writer.join(1)      # without the lock it meets the held database here and drops its row
        holder.stdin.close()
        self.assertEqual(holder.wait(), 0)
        writer.join()

        with sqlite3.connect(history.path()) as db:
            rows = sorted(row[0] for row in db.execute("SELECT run_id FROM runs"))
        self.assertEqual(rows, ["mine", "other"])
        self.assertFalse((config.HOME / "history.log").exists())


if __name__ == "__main__":
    unittest.main()
