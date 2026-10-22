"""A Codex seat's thread is ended 30 days after its last write: by `codex delete` on the seat's
own home while the seat is open, as a file once its home is gone, and its seat folder with its
last rollout or its home, whichever goes last.

Offline: HOME, PATH's `codex` and /proc are the fixture's.  The fake `codex delete` records the
home and database it runs on and its arguments, and removes the rollout under that home.
"""

import os
from pathlib import Path
import runpy
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import gc, orch, retention
from agentkit.harness import codex

DAY = 86400
THREAD = "01a06837-7de8-7f32-a435-95eeece164e{}"
CLOSED, OPEN = "a" * 32, "b" * 32


class GcCodexSeats(Sandbox):
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
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir()
        self.calls = self.root / "codex-calls"
        fake = bin_dir / "codex"
        fake.write_text(f'#!/bin/sh\necho "$CODEX_HOME ${{CODEX_SQLITE_HOME:-}} $*" >> {self.calls}\n'
                        'for id; do :; done\n'
                        'find -L "$CODEX_HOME/sessions" -name "rollout-*-$id.jsonl" -delete\n')
        fake.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}",
                                                        "CODEX_SQLITE_HOME": "/elsewhere"}))
        # the open seat's home links its sessions to its seat folder, as tools/codex-seat.py does
        self.open_home = codex.remote_home(OPEN)
        self.open_home.mkdir(parents=True)
        (codex.seat_conversations(OPEN) / "sessions").mkdir(parents=True)
        (self.open_home / "sessions").symlink_to(codex.seat_conversations(OPEN) / "sessions")

    def rollout(self, folder, n, age):
        path = folder / "2026/09/03" / f"rollout-2026-09-03T19-01-0{n}-{THREAD.format(n)}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"session_meta"}\n')
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_seat_threads_untouched_for_thirty_days_end(self):
        closed = codex.seat_conversations(CLOSED)
        (closed / "sessions").mkdir(parents=True)
        gone = self.rollout(closed / "archived_sessions", 1, 31 * DAY)
        opened = self.rollout(codex.seat_conversations(OPEN) / "sessions", 2, 31 * DAY)
        recent = self.rollout(codex.seat_conversations(OPEN) / "sessions", 3, 29 * DAY)
        own = self.rollout(Path.home() / ".codex/sessions", 4, 31 * DAY)
        gc.gc(lambda _: None)
        self.assertFalse(closed.exists())
        self.assertFalse(opened.exists() or own.exists())
        self.assertTrue(recent.exists())
        sqlite = f'-c sqlite_home="{self.open_home}"'
        self.assertEqual(sorted(self.calls.read_text().splitlines()), sorted([
            f"{Path.home() / '.codex'}  delete --force {THREAD.format(4)}",
            f"{self.open_home}  {sqlite} delete --force {THREAD.format(2)}"]))

    def test_a_closed_seat_folder_still_holding_a_thread_stays(self):
        closed = codex.seat_conversations(CLOSED)
        old = self.rollout(closed / "sessions", 1, 31 * DAY)
        kept = self.rollout(closed / "archived_sessions", 2, 29 * DAY)
        gc.gc(lambda _: None)
        self.assertFalse(old.exists())
        self.assertTrue(kept.exists())
        self.assertFalse(self.calls.exists())

    def test_a_seat_home_reached_through_a_link_keeps_its_threads(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        home = codex.remote_home(CLOSED)
        home.symlink_to(elsewhere, target_is_directory=True)
        old = self.rollout(codex.seat_conversations(CLOSED) / "sessions", 1, 31 * DAY)
        gc.gc(lambda _: None)
        self.assertTrue(old.exists())
        self.assertFalse(self.calls.exists())

    def test_a_seat_closing_after_its_last_thread_went_takes_its_folder(self):
        self.rollout(codex.seat_conversations(OPEN) / "sessions", 1, 31 * DAY)
        (codex.seat_conversations(OPEN) / "archived_sessions").mkdir()
        gc.gc(lambda _: None)
        self.assertTrue(codex.seat_conversations(OPEN).exists())
        seat = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/codex-seat.py"))
        seat["remove_home"](self.open_home)
        self.assertFalse(self.open_home.exists() or codex.seat_conversations(OPEN).exists())

    def test_a_seat_folder_reached_through_a_link_keeps_what_it_leads_to(self):
        kept = self.root / "elsewhere/empty"
        kept.mkdir(parents=True)
        codex.seat_conversations(CLOSED).symlink_to(kept.parent, target_is_directory=True)
        codex.drop_closed_seat(CLOSED)
        self.assertTrue(kept.is_dir())


if __name__ == "__main__":
    unittest.main()
