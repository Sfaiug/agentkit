"""An Antigravity conversation nobody wrote to for 30 days goes with what every home keeps of it.

Offline: HOME and /proc are the fixture's.  The store is laid out as agy 1.4.4 lays it out: the
default home's conversations/<id>.db and brain/<id>/, a login's home linking both, and in each
home its annotations, implicit and presence files and a conversation_summaries.db row.
"""

import contextlib
import os
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import gc, orch, retention

DAY = 86400
FILES = (("annotations", ".pbtxt"), ("implicit", ".pb"), ("presence", ".lock"))


class GcAntigravity(Sandbox):
    def setUp(self):
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        proc = self.root / "proc"
        proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", proc.iterdir))
        self.stack.enter_context(patch.object(gc, "tmp_hidden_processes", return_value=None))
        default = Path.home() / ".gemini/antigravity-cli"
        self.homes = [default, default.with_name("antigravity-cli-acme")]
        for store in ("conversations", "brain"):
            (default / store).mkdir(parents=True)
            (self.homes[1] / store).parent.mkdir(exist_ok=True)
            (self.homes[1] / store).symlink_to(f"../antigravity-cli/{store}")
        for home in self.homes:
            with contextlib.closing(sqlite3.connect(home / "conversation_summaries.db")) as db, db:
                db.execute("CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY,"
                           " summary BLOB)")

    def conversation(self, name, age):
        default = self.homes[0]
        db, brain = default / f"conversations/{name}.db", default / f"brain/{name}"
        brain.mkdir()
        (brain / "task.md").write_text("plan\n")
        db.write_bytes(b"steps")
        for path in (brain / "task.md", db):
            os.utime(path, (time.time() - age, time.time() - age))
        for home in self.homes:
            for folder, suffix in FILES:
                (home / folder).mkdir(exist_ok=True)
                (home / folder / f"{name}{suffix}").write_bytes(b"")
            with contextlib.closing(sqlite3.connect(home / "conversation_summaries.db")) as summaries, summaries:
                summaries.execute("INSERT INTO conversation_summaries VALUES (?, ?)", (name, b""))
        return db

    def kept(self, name):
        """Every part of it still there, and every home's row."""
        default = self.homes[0]
        parts = [default / f"conversations/{name}.db", default / f"brain/{name}/task.md",
                 *(home / folder / f"{name}{suffix}" for home in self.homes for folder, suffix in FILES)]
        rows = []
        for home in self.homes:
            with contextlib.closing(sqlite3.connect(home / "conversation_summaries.db")) as db:
                rows += db.execute("SELECT 1 FROM conversation_summaries WHERE conversation_id = ?",
                                   (name,)).fetchall()
        return [part.exists() for part in parts] + [len(rows) == len(self.homes)]

    def test_a_conversation_untouched_for_thirty_days_goes_with_all_it_left(self):
        old, recent = self.conversation("fix-api", 31 * DAY), self.conversation("acme-docs", 29 * DAY)
        self.assertEqual({item["path"] for item in gc.gc_plan() if item["kind"] == "conversation"},
                         {str(old)})
        gc.gc(lambda _: None)
        self.assertFalse(any(self.kept("fix-api")), self.kept("fix-api"))
        self.assertFalse((self.homes[0] / "brain/fix-api").exists())
        self.assertTrue(all(self.kept("acme-docs")), self.kept("acme-docs"))
        self.assertTrue(recent.exists() and (self.homes[1] / "conversations").is_symlink())

    def test_a_home_whose_summaries_cannot_be_read_keeps_all_of_it(self):
        self.conversation("fix-api", 31 * DAY)
        broken = self.homes[1] / "conversation_summaries.db"
        intact, elsewhere = broken.read_bytes(), Path.home() / "acme-summaries.db"

        def garbled():
            broken.write_bytes(b"not a database" * 100)

        def linked():
            broken.rename(elsewhere)
            broken.symlink_to(elsewhere)

        def unsearchable():
            self.homes[1].chmod(0)

        for breaks in (garbled, linked, unsearchable):
            with self.subTest(breaks.__name__):
                breaks()
                said = []
                gc.gc(said.append)
                self.homes[1].chmod(0o700)
                broken.unlink()
                elsewhere.unlink(missing_ok=True)
                broken.write_bytes(intact)
                self.assertTrue(all(self.kept("fix-api")), self.kept("fix-api"))
                self.assertEqual(sum(line.startswith("gc: kept") for line in said), 1, said)

if __name__ == "__main__":
    unittest.main(verbosity=2)
