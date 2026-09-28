"""The collector clears /tmp entries and gone Claude sessions' scratch folders.

Offline. A temporary directory stands in for /tmp and both process tables are
faked; nothing here reads the real /tmp or the real /proc.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import orch, retention, run, watch

DAY = 86400


class GcTmp(Sandbox):
    def setUp(self):
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100"}))
        self.tmp = self.root / "tmp-base"
        self.tmp.mkdir()
        self.stack.enter_context(patch.object(run, "TMP_BASE", self.tmp))
        self.paths = set()
        self.stack.enter_context(patch.object(retention, "process_paths",
                                              lambda: set(self.paths)))
        self.table = {}
        self.stack.enter_context(patch.object(watch, "_proc_table",
                                              lambda: dict(self.table)))

    def age(self, path, seconds):
        stamp = time.time() - seconds
        path = Path(path)
        os.utime(path, (stamp, stamp), follow_symlinks=False)
        if path.is_dir() and not path.is_symlink():
            for root, dirs, files in os.walk(path, followlinks=False):
                for name in dirs + files:
                    try:
                        os.utime(Path(root) / name, (stamp, stamp), follow_symlinks=False)
                    except OSError:
                        pass
        return path

    def entry(self, name, age=3 * DAY):
        path = self.tmp / name
        path.mkdir()
        (path / "inner").write_text("temp\n")
        return self.age(path, age)

    def planned(self):
        return {item["path"]: item for item in run.gc_plan()
                if item["kind"] in ("tmp-entry", "claude-session")}

    def gc_out(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_gc(list(argv)), 0)
        return out.getvalue()

    def test_stale_unopened_entry_goes(self):
        old_dir = self.entry("old-dir")
        old_file = self.tmp / "old-file"
        old_file.write_text("temp\n")
        self.age(old_file, 3 * DAY)
        plan = self.planned()
        self.assertIn(str(old_dir), plan)
        self.assertIn(str(old_file), plan)
        dry = self.gc_out("--dry-run")
        self.assertIn(f"gc: would remove tmp-entry {old_dir}: untouched for 3 days", dry)
        self.assertIn(f"gc: would remove tmp-entry {old_file}: untouched for 3 days", dry)
        messages = []
        removed = run.gc(messages.append)
        self.assertIn(str(old_dir), removed)
        self.assertIn(str(old_file), removed)
        self.assertFalse(old_dir.exists())
        self.assertFalse(old_file.exists())
        self.assertTrue(any(f"gc: remove tmp-entry {old_dir}:" in line for line in messages))

    def test_opened_entry_stays(self):
        held = self.entry("held")
        nested = self.entry("nested")
        self.paths = {str(held), str(nested / "inner")}
        self.assertNotIn(str(held), self.planned())
        self.assertNotIn(str(nested), self.planned())
        self.assertEqual([item for item in run.gc(lambda _: None)
                          if item in (str(held), str(nested))], [])
        self.assertTrue(held.is_dir())
        self.assertTrue(nested.is_dir())

    def test_recent_entry_stays(self):
        fresh = self.entry("fresh", age=3600)
        mixed = self.entry("mixed")
        (mixed / "inner").write_text("just now\n")
        self.assertNotIn(str(fresh), self.planned())
        self.assertNotIn(str(mixed), self.planned())
        run.gc(lambda _: None)
        self.assertTrue(fresh.is_dir())
        self.assertTrue(mixed.is_dir())

    def test_running_session_stays_and_gone_session_goes(self):
        claude = self.tmp / f"claude-{os.getuid()}"
        running = claude / "acme" / "sess-running"
        gone = claude / "acme" / "sess-gone"
        for session in (running, gone):
            session.mkdir(parents=True)
            (session / "scratch").write_text("temp\n")
            self.age(session, 2 * DAY)
        self.table = {1234: (1, "S", ["claude", "--session-id", "sess-running"])}
        plan = self.planned()
        self.assertNotIn(str(running), plan)
        self.assertNotIn(str(claude), plan)
        self.assertIn(str(gone), plan)
        self.assertEqual(plan[str(gone)]["kind"], "claude-session")
        dry = self.gc_out("--dry-run")
        self.assertIn(f"gc: would remove claude-session {gone}: session sess-gone is gone", dry)
        self.assertNotIn(str(running), dry)
        messages = []
        removed = run.gc(messages.append)
        self.assertIn(str(gone), removed)
        self.assertFalse(gone.exists())
        self.assertTrue(running.is_dir())
        self.assertTrue(any(f"gc: remove claude-session {gone}:" in line for line in messages))

    def test_protected_names_stay(self):
        kept = []
        for name in (".X11-unix", "tmux-1000", "systemd-private-abc"):
            kept.append(self.entry(name))
        self.assertEqual(self.planned(), {})
        run.gc(lambda _: None)
        for path in kept:
            self.assertTrue(path.is_dir(), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
