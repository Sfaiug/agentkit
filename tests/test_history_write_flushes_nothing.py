"""A history write flushes nothing under the one lock every run and the tick take: on 30 Oct 2026
each held it 1 to 4 s on a busy disk, a commit flushing the WAL, and every 1000 pages or the last
close checkpointing it into the database. The WAL goes in once the lock is released.
"""

import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, waiter  # noqa: E402

# A writer that dies at once after its write, as a killed run does, leaving history.db open nowhere.
WRITER = """import os, sys; sys.path.insert(0, sys.argv[1])
from pathlib import Path
from agentkit import config, history
config.HOME = Path(sys.argv[2]); history.start_run("first", repo="acme"); os._exit(0)"""


class WriteFlushesNothing(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", Path(home.name)))
        subprocess.run([sys.executable, "-c", WRITER, str(REPO), home.name], check=True,
                       timeout=120)
        writing = waiter.writing

        @contextlib.contextmanager
        def held(database, **kw):
            with writing(database, **kw):
                before = Path(database).read_bytes()
                yield
                self.assertTrue(Path(database).read_bytes() == before, "history.db changed")
        stack.enter_context(patch.object(waiter, "writing", held))

    def test_writes_past_sqlites_own_checkpoint_leave_the_database_to_after_the_lock(self):
        for write in range(100):    # 2500 pages, where sqlite checkpoints every 1000
            history.update_run("first", session=str(write % 10) * 100_000)
        self.assertEqual(history.get("first")["session"], "9" * 100_000)
        self.assertLess(Path(f"{history.path()}-wal").stat().st_size, 2 * waiter.CHECKPOINT_AT)
        self.assertEqual(waiter.connect(history.path()).execute("PRAGMA synchronous").fetchone(),
                         (1,))

    def test_a_waiter_alone_on_the_database_leaves_it_too(self):
        waiter.count(str(history.path()), "first", time.time(), time.monotonic() - 1)
        self.assertGreaterEqual(history.get("first")["slot_wait_seconds"], 1)

    def test_what_a_killed_writer_wrote_reaches_another_process(self):
        self.assertEqual(history.get("first")["repo"], "acme")


if __name__ == "__main__":
    unittest.main()
