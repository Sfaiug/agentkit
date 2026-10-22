"""A conversation a harness never ends itself is ended its own way 30 days after its last write.

Offline: HOME, PATH's `codex` and /proc are the fixture's.  The fake `codex delete` records the
database it would use and its arguments, and removes the rollout from its home the way the real
one does, with what it indexed.  Muse's store is laid out as 1.4.11 lays it out: a folder per
session, views cached beside them, and a row per session in session-index.db.
"""

import contextlib
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import sqlite3

from fixtures.sandbox import Sandbox
from agentkit import gc, orch, retention

DAY = 86400
THREAD = "01a06837-7de8-7f32-a435-95eeece164e{}"


class GcConversations(Sandbox):
    def setUp(self):
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))
        self.stack.enter_context(patch.object(gc, "tmp_hidden_processes", return_value=None))
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir()
        self.calls = self.root / "codex-calls"
        self.codex = bin_dir / "codex"
        self.codex.write_text(f'#!/bin/sh\nhome=${{CODEX_HOME:-$HOME/.codex}}\n'
                              f'echo "${{CODEX_SQLITE_HOME:-$home}} $*" >> {self.calls}\n'
                              'find "$home/sessions" -name "rollout-*-$3.jsonl" -delete\n')
        self.codex.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}))
        os.environ.pop("XDG_DATA_HOME", None)
        self.muse = Path.home() / ".local/share/muse/sessions"
        self.muse.mkdir(parents=True)
        self.index = self.muse.parent / "session-index.db"
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            db.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, session_dir TEXT,"
                       " session_log_path TEXT UNIQUE)")

    def rollout(self, n, age):
        path = (Path.home() / ".codex/sessions/2026/09/03"
                / f"rollout-2026-09-03T19-01-0{n}-{THREAD.format(n)}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"session_meta"}\n')
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def session(self, n, age):
        folder = self.muse / "2026/09/03" / THREAD.format(n)
        view = self.muse / ".msp-view-v1" / folder.name
        for directory in (folder / "subagent", view):
            directory.mkdir(parents=True)
        for path in (folder / "session.jsonl", folder / "subagent/session.jsonl", view / "HEAD.json"):
            path.write_text("{}\n")
        for path in (folder / "subagent/session.jsonl", folder / "session.jsonl", view / "HEAD.json"):
            os.utime(path, (time.time() - age, time.time() - age))
        with contextlib.closing(sqlite3.connect(self.index)) as db, db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                       (folder.name, str(folder), str(folder / "session.jsonl")))
        return folder

    def indexed(self):
        with contextlib.closing(sqlite3.connect(self.index)) as db:
            return {row[0] for row in db.execute("SELECT session_id FROM sessions")}

    def holds(self, path):
        proc = self.proc / "1000"
        (proc / "fd").mkdir(parents=True)
        fields = ["S", "1", *(["0"] * 18)]
        (proc / "stat").write_text(f"{proc.name} (fixture) " + " ".join(fields))
        (proc / "status").write_text("Uid:\t" + "\t".join([str(os.getuid())] * 4) + "\n")
        (proc / "cmdline").write_bytes(b"fixture")
        (proc / "cwd").symlink_to(self.root)
        (proc / "fd" / "3").symlink_to(path)

    def planned(self):
        return {item["path"] for item in gc.gc_plan() if item["kind"] == "conversation"}

    def test_a_codex_thread_untouched_for_thirty_days_is_deleted_by_codex(self):
        old = self.rollout(1, 31 * DAY)
        recent = self.rollout(2, 29 * DAY)
        held = self.rollout(3, 40 * DAY)
        self.holds(held)
        self.assertEqual(self.planned(), {str(old)})
        # on the home it scanned, whichever one the caller's environment selects
        other = str(self.root / ".codex-other")
        with patch.dict(os.environ, {"CODEX_HOME": other, "CODEX_SQLITE_HOME": other}):
            gc.gc(lambda _: None)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists() and held.exists())
        self.assertEqual(self.calls.read_text(),
                         f"{Path.home() / '.codex'} delete --force {THREAD.format(1)}\n")

    def test_a_muse_session_untouched_for_thirty_days_goes_with_what_muse_indexed_of_it(self):
        old, recent, written, held = (self.session(n, age) for n, age in
                                      ((1, 31 * DAY), (2, 29 * DAY), (3, 31 * DAY), (4, 40 * DAY)))
        os.utime(written / "subagent/session.jsonl", (time.time() - DAY, time.time() - DAY))
        self.holds(held / "session.jsonl")
        self.assertEqual(self.planned(), {str(old)})
        gc.gc(lambda _: None)
        self.assertFalse(old.exists() or (self.muse / ".msp-view-v1" / old.name).exists())
        self.assertEqual(self.indexed(), {recent.name, written.name, held.name})
        self.assertTrue(recent.exists() and written.exists() and held.exists())

    def test_a_muse_index_that_cannot_be_opened_keeps_every_session(self):
        old = self.session(1, 31 * DAY)
        self.index.unlink()
        said = []
        gc.gc(said.append)
        self.assertTrue(old.exists() and (self.muse / ".msp-view-v1" / old.name).exists())
        self.assertFalse(self.index.exists())
        self.assertEqual(sum("session index" in line for line in said), 1)

    def test_a_muse_view_held_or_reached_through_a_link_keeps_its_session(self):
        held, linked = self.session(1, 31 * DAY), self.session(2, 31 * DAY)
        self.holds(self.muse / ".msp-view-v1" / held.name / "HEAD.json")
        elsewhere = Path.home() / "elsewhere"
        elsewhere.mkdir()
        (self.muse / ".msp-view-v1" / linked.name).rename(elsewhere / linked.name)
        (self.muse / ".msp-view-v2").symlink_to(elsewhere)
        gc.gc(lambda _: None)
        self.assertTrue(held.exists() and linked.exists()
                        and (elsewhere / linked.name / "HEAD.json").exists())
        self.assertTrue((self.muse / ".msp-view-v1" / held.name / "HEAD.json").exists())
        self.assertEqual(self.indexed(), {held.name, linked.name})

    def test_what_muse_writes_while_gc_waits_on_the_index_is_judged_with_the_session(self):
        old = self.session(1, 31 * DAY)
        view = self.muse / ".msp-view-v2" / old.name
        connect = sqlite3.connect

        def gc_while(write):
            class Muse(sqlite3.Connection):
                def execute(self, sql, *args):
                    if sql == "BEGIN IMMEDIATE":     # Muse writes while it holds the index
                        write()
                    return super().execute(sql, *args)

            with patch.object(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=Muse)):
                gc.gc(lambda _: None)

        gc_while(lambda: (old / "session.jsonl").write_text("{}\n{}\n"))
        self.assertTrue(old.exists() and (self.muse / ".msp-view-v1" / old.name).exists())
        self.assertEqual(self.indexed(), {old.name})
        os.utime(old / "session.jsonl", (time.time() - 31 * DAY, time.time() - 31 * DAY))
        gc_while(lambda: view.mkdir(parents=True))
        self.assertFalse(old.exists() or view.exists())
        self.assertEqual(self.indexed(), set())

    def test_a_process_whose_handles_cannot_be_read_keeps_every_one(self):
        old = self.rollout(1, 31 * DAY)
        (self.proc / "1001").mkdir()      # a process nothing of which can be read
        self.assertEqual(self.planned(), set())
        with patch.object(gc, "stale_conversations",
                          return_value=[{"action": "remove", "kind": "conversation",
                                         "path": str(old), "harness": "codex", "why": "old"}]):
            gc.gc(lambda _: None)
        self.assertTrue(old.exists())
        self.assertFalse(self.calls.exists())

    def test_a_harness_that_cannot_end_one_is_tried_once_a_pass(self):
        for n in (1, 2, 3):
            self.rollout(n, 31 * DAY)
        said = []
        with patch.object(gc, "end_conversation", side_effect=OSError("no codex")) as end:
            gc.gc(said.append)
        self.assertEqual(end.call_count, 1)
        self.assertEqual(sum("no codex" in line for line in said), 1)
        self.assertEqual(len(self.planned()), 3)
        self.codex.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\nexit 1\n')
        said.clear()
        gc.gc(said.append)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertEqual(sum(line.startswith("gc: kept") for line in said), 1)
        self.assertEqual(len(self.planned()), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
