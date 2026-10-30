"""A history write holds the shared lock through no checkpoint and no close.

Every `ak run` and the tick write history.db one at a time behind history.lock, and on a busy
disk the syncs made under it held a dozen processes there and the tick 96% of its time
(30 Oct 2026).  Here, read from ak's own files, as what a process does with its connection is not
visible from outside it: a write commits at `synchronous=NORMAL`, moves no WAL into the database
past SQLite's 1000 pages, and its close leaves the WAL where it is, in a waiter process that
imports no history as in ak; only the tick's own pass, past 4 MiB and holding no lock of ak's,
moves the WAL into the database.
"""

import contextlib
import gc
import json
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
from agentkit import config, history, waiter, watch  # noqa: E402

CHECKPOINT = "history's WAL was not checkpointed"
BIG = "x" * waiter.WAL_MAX       # one commit of over 1000 pages, and a WAL past 4 MiB

# The waiter as `run.pickup_while_queued` runs it, with no agentkit on its path: it counts a
# wait in history, then says whether the database file is as it was and the WAL still there.
LONE_WAITER = """
import importlib.util, json, os, sys, time
spec = importlib.util.spec_from_file_location("waiter", sys.argv[1])
waiter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(waiter)
database = sys.argv[2]
before = open(database, "rb").read()
waiter.count(database, "fix-api", 0.0, time.monotonic() - 5)
print(json.dumps([open(database, "rb").read() == before, os.path.exists(database + "-wal")]))
"""


class HistoryWriteHoldsNoCheckpoint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agentkit-history-checkpoint-")
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        for name in ("HOME", "RUNS"):
            patcher = patch.object(config, name, home / name.lower())
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(waiter._kept.cache_clear)      # this test's database closed before it goes
        history.start_run("first", repo="acme")       # the database, made by a first write
        self.made = history.path().read_bytes()

    def wal(self):
        return os.path.getsize(f"{history.path()}-wal")

    def test_a_write_commits_at_normal_and_leaves_the_wal_where_it_is(self):
        real, seen = waiter.connect, []

        def spy(database):
            connection = real(database)
            try:
                with waiter.writing(database, wait=False):
                    held = False
            except BlockingIOError:
                held = True
            seen.append((held, *(connection.execute(f"PRAGMA {name}").fetchone()[0]
                                 for name in ("synchronous", "wal_autocheckpoint"))))
            return connection

        with patch.object(waiter, "connect", spy):
            history.start_run("fix-api", repo="acme", task_files=BIG)
        self.assertEqual(set(seen), {(True, 1, 0)})     # under the lock, NORMAL, no autocheckpoint
        self.assertEqual(history.path().read_bytes(), self.made)
        self.assertGreater(self.wal(), waiter.WAL_MAX)

    def test_the_waiter_process_writes_the_same_way(self):
        history.start_run("fix-api", repo="acme")
        waiter._kept.cache_clear()      # this process's last connection, closed: the WAL moved
        gc.collect()                    # ... once collected, a connection being in a cycle
        self.assertFalse(os.path.exists(f"{history.path()}-wal"))
        out = subprocess.run([sys.executable, "-I", "-S", "-c", LONE_WAITER,
                              str(REPO / "agentkit" / "waiter.py"), str(history.path())],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [True, True])
        with contextlib.closing(sqlite3.connect(history.path())) as db:
            counted = db.execute("SELECT slot_wait_seconds FROM runs WHERE run_id='fix-api'")
            self.assertGreaterEqual(counted.fetchone()[0], 5)

    def test_the_tick_alone_moves_the_wal_past_4_mib_holding_no_lock_of_aks(self):
        step = {what: step for what, step, _ in watch.local_passes({}, False, print)}[CHECKPOINT]
        step()
        self.assertEqual(history.path().read_bytes(), self.made)      # under 4 MiB, left
        history.start_run("fix-api", repo="acme", task_files=BIG)
        self.assertGreater(self.wal(), waiter.WAL_MAX)

        with history._LOCK, waiter.writing(history.path()):
            tick = threading.Thread(target=step, daemon=True)
            tick.start()
            tick.join(30)
            self.assertFalse(tick.is_alive(), "the tick's checkpoint waited on a lock of ak's")
        self.assertGreater(history.path().stat().st_size, waiter.WAL_MAX)
        with contextlib.closing(sqlite3.connect(f"{history.path().as_uri()}?mode=ro",
                                                uri=True)) as db:
            moved = db.execute("SELECT length(task_files) FROM runs WHERE run_id='fix-api'")
            self.assertEqual(moved.fetchone()[0], len(BIG))

        # the next commit begins the WAL anew and cuts its file back, so the next tick has none
        history.start_run("next", repo="acme")
        self.assertEqual(self.wal(), waiter.WAL_MAX)


if __name__ == "__main__":
    unittest.main()
