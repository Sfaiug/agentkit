"""The collector clears /tmp entries and gone Claude sessions' scratch folders.

Offline. Temporary directories stand in for /tmp and /proc; nothing here reads
the real temporary files or process table.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, orch, retention, run

DAY = 86400


class GcTmp(Sandbox):
    def setUp(self):
        real_time = time.time
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", real_time))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(config, "JOBS", self.root / "jobs"))
        self.stack.enter_context(patch.object(retention, "unix_sockets", return_value=set()))
        self.tmp = self.root / "tmp-base"
        self.tmp.mkdir()
        self.stack.enter_context(patch.object(run, "TMP_BASE", self.tmp))
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))

    def process(self, args=("fixture",), cwd=None, opened=()):
        proc = self.proc / str(1000 + len(list(self.proc.iterdir())))
        (proc / "fd").mkdir(parents=True)
        (proc / "stat").write_text(f"{proc.name} (fixture) S 1 0 0\n")
        (proc / "cmdline").write_bytes(b"\0".join(os.fsencode(arg) for arg in args))
        (proc / "cwd").symlink_to(cwd or self.root)
        for index, path in enumerate(opened):
            (proc / "fd" / str(index)).symlink_to(path)
        return proc

    def scratch(self, age=2 * DAY):
        path = self.tmp / f"claude-{os.getuid()}" / "acme" / "sess-gone"
        path.mkdir(parents=True)
        (path / "scratch").write_text("temp\n")
        return self.age(path, age)

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
        removed = run.gc(messages.append, automatic=True)
        self.assertIn(str(old_dir), removed)
        self.assertIn(str(old_file), removed)
        self.assertFalse(old_dir.exists())
        self.assertFalse(old_file.exists())
        self.assertTrue(any(f"gc: remove tmp-entry {old_dir}:" in line for line in messages))
        logged = (config.STATE / "gc.log").read_text()
        for path in (old_dir, old_file):
            self.assertEqual(logged.count(f"gc: remove tmp-entry {path}:"), 1)

    def test_opened_entry_stays(self):
        held = self.entry("held")
        nested = self.entry("nested")
        self.process(cwd=held, opened=[nested / "inner"])
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

    def test_gone_session_goes_after_a_day(self):
        gone = self.scratch(age=DAY + 3600)
        fresh = gone.with_name("sess-fresh")
        fresh.mkdir()
        plan = self.planned()
        self.assertNotIn(str(gone.parents[1]), plan)
        self.assertNotIn(str(fresh), plan)
        self.assertIn(str(gone), plan)
        self.assertEqual(plan[str(gone)]["kind"], "claude-session")
        dry = self.gc_out("--dry-run")
        self.assertIn(f"gc: would remove claude-session {gone}: session sess-gone is gone", dry)
        self.assertNotIn(str(fresh), dry)
        messages = []
        removed = run.gc(messages.append)
        self.assertIn(str(gone), removed)
        self.assertFalse(gone.exists())
        self.assertTrue(fresh.is_dir())
        self.assertTrue(any(f"gc: remove claude-session {gone}:" in line for line in messages))

    def test_running_client_protects_sessions_and_whole_tree(self):
        scratch = self.scratch()
        claude = scratch.parents[1]
        proc = self.process()
        for args in (["claude"], ["claude", "--session-id", "sess-gone"],
                     ["claude", "--resume", "before-clear"],
                     ["node", "/opt/lib/@anthropic-ai/claude-code/cli.js"]):
            for age in (DAY + 3600, 3 * DAY):
                with self.subTest(args=args, age=age):
                    self.age(claude, age)
                    (proc / "cmdline").write_bytes(b"\0".join(os.fsencode(a) for a in args))
                    self.assertEqual(self.planned(), {})
                    run.gc(lambda _: None)
                    self.assertTrue(scratch.is_dir())
        # A dead client cannot hold a session, even if its argv is unavailable.
        (proc / "stat").write_text(f"{proc.name} (fixture) Z 1 0 0\n")
        (proc / "cmdline").unlink()
        self.assertIn(str(claude), self.planned())
        run.gc(lambda _: None)
        self.assertFalse(claude.exists())

    def test_other_users_process_holds_our_entry(self):
        held = self.entry("held")
        proc = self.process(opened=[held / "inner"])
        original = Path.stat
        def foreign(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == proc:
                fields = list(info)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return info
        with patch.object(Path, "stat", foreign):
            self.assertEqual(self.planned(), {})
            run.gc(lambda _: None)
        self.assertTrue(held.is_dir())

    def test_incomplete_inventory_protects_entries_and_sessions(self):
        held = self.entry("old")
        scratch = self.scratch()
        proc = self.process(opened=[self.root / "elsewhere"])
        for method, target in (("read_text", proc / "stat"),
                               ("read_bytes", proc / "cmdline"),
                               ("scandir", proc / "fd"),
                               ("readlink", proc / "cwd"),
                               ("readlink", proc / "fd" / "0")):
            owner = os if method in ("readlink", "scandir") else Path
            original = getattr(owner, method)
            def unreadable(path, *args, **kwargs):
                if path == target:
                    raise PermissionError("fixture process is unreadable")
                return original(path, *args, **kwargs)
            with self.subTest(target=target), patch.object(owner, method, unreadable):
                self.assertEqual(run.tmp_processes(), (None, None))
                self.assertEqual(self.planned(), {})
                run.gc(lambda _: None)
                self.assertTrue(held.is_dir())
                self.assertTrue(scratch.is_dir())
        with patch.object(retention, "process_dirs", side_effect=PermissionError):
            self.assertEqual(self.planned(), {})
        (proc / "cmdline").write_bytes(b"")
        self.assertEqual(self.planned(), {})

    def test_recheck_protects_files_held_after_planning(self):
        held = self.entry("old")
        scratch = self.scratch()
        proc = self.process()
        for age in (DAY + 3600, 3 * DAY):
            with self.subTest(age=age):
                self.age(scratch.parents[1], age)
                plan = list(self.planned().values())
                self.assertEqual(len(plan), 2)
                (proc / "cmdline").write_bytes(b"claude\0")
                (proc / "fd" / "0").symlink_to(held / "inner")
                with patch.object(run, "gc_candidates", return_value=iter(plan)):
                    self.assertEqual(run.gc(lambda _: None), [])
                self.assertTrue(held.is_dir())
                self.assertTrue(scratch.is_dir())
                (proc / "cmdline").write_bytes(b"fixture\0")
                (proc / "fd" / "0").unlink()

    def test_recheck_refuses_incomplete_inventory(self):
        self.entry("old")
        scratch = self.scratch()
        for age in (DAY + 3600, 3 * DAY):
            with self.subTest(age=age):
                self.age(scratch.parents[1], age)
                plan = list(self.planned().values())
                self.assertEqual(len(plan), 2)
                with patch.object(run, "gc_candidates", return_value=iter(plan)), \
                        patch.object(retention, "process_dirs", side_effect=PermissionError):
                    self.assertEqual(run.gc(lambda _: None), [])
                self.assertTrue(all(Path(item["path"]).exists() for item in plan))

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
