"""Temporary files age from their last change and stay while a process holds them.

Offline: /tmp, /proc, HOME and privileged inspection are all fixture-owned.
Move the clock forward to age files; utime cannot backdate inode change times.
"""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, gc, orch, proc_snapshot, retention, run

DAY = 86400
HIDDEN_INSPECT = gc.tmp_hidden_processes


class GcTmp(Sandbox):
    def setUp(self):
        self.now = time.time() + 1
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(config, "JOBS", self.root / "jobs"))
        self.stack.enter_context(patch.object(retention, "unix_sockets", return_value=set()))
        self.tmp = self.root / "tmp-base"
        self.tmp.mkdir()
        self.stack.enter_context(patch.object(gc, "TMP_BASE", self.tmp))
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))
        self.hidden = self.stack.enter_context(
            patch.object(gc, "tmp_hidden_processes", return_value=None))

    def process(self, args=("fixture",), cwd=None, opened=(), uid=None, kernel=False, pid=None):
        proc = self.proc / str(pid or 1000 + len(list(self.proc.iterdir())))
        (proc / "fd").mkdir(parents=True)
        fields = ["S", "1", *(["0"] * 18)]
        fields[6], fields[19] = str(0x200000 if kernel else 0), "12345"
        (proc / "stat").write_text(f"{proc.name} (fixture) " + " ".join(fields))
        uid = os.getuid() if uid is None else uid
        (proc / "status").write_text("Uid:\t" + "\t".join([str(uid)] * 4) + "\n")
        (proc / "cmdline").write_bytes(b"\0".join(os.fsencode(arg) for arg in args))
        (proc / "cwd").symlink_to(cwd or self.root)
        for index, path in enumerate(opened):
            (proc / "fd" / str(index)).symlink_to(path)
        return proc

    def session_record(self, proc, session, account=".claude", **extra):
        directory = self.root / account / "sessions"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{proc.name}.json"
        path.write_text(json.dumps({"pid": int(proc.name), "procStart": "12345",
                                    "sessionId": session, **extra}))
        return path

    @contextmanager
    def unreadable(self, proc):
        scandir, readlink = os.scandir, os.readlink
        def directory(path):
            if path == proc / "fd":
                raise PermissionError("fixture hidden descriptors")
            return scandir(path)
        def link(path, *args, **kwargs):
            if path == proc / "cwd":
                raise PermissionError("fixture hidden cwd")
            return readlink(path, *args, **kwargs)
        with patch.object(os, "scandir", directory), patch.object(os, "readlink", link):
            yield

    def touch(self, path):
        os.utime(path, (self.now, self.now), follow_symlinks=False)
        return path

    def entry(self, name):
        path = self.tmp / name
        path.mkdir()
        (path / "inner").write_text("temp\n")
        self.touch(path / "inner")
        return self.touch(path)

    def scratch(self, name="sess-gone"):
        path = self.tmp / f"claude-{os.getuid()}" / "acme" / name
        path.mkdir(parents=True)
        (path / "scratch").write_text("temp\n")
        for item in (path / "scratch", path, path.parent, path.parents[1]):
            self.touch(item)
        return path

    def planned(self):
        return {item["path"]: item for item in gc.gc_plan()
                if item["kind"] in ("tmp-entry", "claude-session")}

    def gc_out(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(gc.cmd_gc(list(argv)), 0)
        return out.getvalue()

    def test_stale_unopened_entry_goes_and_is_logged_once(self):
        old_dir = self.entry("old-dir")
        old_file = self.tmp / "old-file"
        old_file.write_text("temp\n")
        self.touch(old_file)
        self.now += 3 * DAY
        self.assertEqual(set(self.planned()), {str(old_dir), str(old_file)})
        dry = self.gc_out("--dry-run")
        for path in (old_dir, old_file):
            self.assertIn(f"gc: would remove tmp-entry {path}: untouched for 3 days", dry)
            self.assertTrue(path.exists())
        removed = gc.gc(lambda _: None, automatic=True)
        logged = (config.STATE / "gc.log").read_text()
        for path in (old_dir, old_file):
            self.assertIn(str(path), removed)
            self.assertFalse(path.exists())
            self.assertEqual(logged.count(f"gc: remove tmp-entry {path}:"), 1)

    def test_open_files_and_working_directories_stay(self):
        held = self.entry("held")
        nested = self.entry("nested (deleted)")
        self.process(cwd=held, opened=[nested / "inner"])
        self.now += 3 * DAY
        self.assertEqual(self.planned(), {})
        gc.gc(lambda _: None)
        self.assertTrue(held.is_dir())
        self.assertTrue(nested.is_dir())

    def test_recent_entry_and_recent_nested_change_stay(self):
        mixed = self.entry("mixed")
        self.now += 3 * DAY
        fresh = self.entry("fresh")
        (mixed / "inner").write_text("just now\n")
        self.touch(mixed / "inner")
        self.assertEqual(self.planned(), {})
        gc.gc(lambda _: None)
        self.assertTrue(fresh.is_dir())
        self.assertTrue(mixed.is_dir())

    def test_restored_mtimes_do_not_backdate_changes(self):
        # Tar restores historical mtimes but these inodes were created just now.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            entry = tarfile.TarInfo("inner")
            entry.mtime, entry.size = self.now - 5 * DAY, 4
            archive.addfile(entry, io.BytesIO(b"temp"))
        tree = self.tmp / "restored"
        tree.mkdir()
        buffer.seek(0)
        with tarfile.open(fileobj=buffer) as archive:
            archive.extractall(tree)
        old = self.now - 5 * DAY
        os.utime(tree, (old, old))
        standalone = self.tmp / "restored-file"
        standalone.write_text("temp")
        os.utime(standalone, (old, old))
        link = tree / "link"
        link.symlink_to("inner")
        os.utime(link, (old, old), follow_symlinks=False)
        for path in (tree, tree / "inner", standalone, link):
            self.assertGreaterEqual(gc.tmp_tree_newest(tree if path == link else path),
                                    path.lstat().st_ctime)
        self.assertEqual(self.planned(), {})
        self.now += 3 * DAY
        self.assertEqual(set(self.planned()), {str(tree), str(standalone)})

    def test_running_sessions_stay_and_ended_sessions_go(self):
        running, gone = self.scratch("sess-running"), self.scratch()
        proc = self.process(args=["claude", "--resume", "before-clear"])
        self.session_record(proc, running.name, account=".claude-work")
        self.now += DAY + 3600
        plan = self.planned()
        self.assertEqual(set(plan), {str(gone)})
        self.assertEqual(plan[str(gone)]["kind"], "claude-session")
        self.assertIn(f"gc: would remove claude-session {gone}", self.gc_out("--dry-run"))
        gc.gc(lambda _: None)
        self.assertFalse(gone.exists())
        self.assertTrue(running.is_dir())

    def test_nested_metadata_changes_reset_the_age(self):
        tree = self.entry("old-tree")
        link = tree / "link"
        link.symlink_to("inner")
        self.now += 3 * DAY
        original = Path.lstat
        for changed in (tree / "inner", link):
            def metadata(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == changed:
                    fields = list(info)
                    fields[9] = self.now       # a change at the advanced fixture clock
                    return os.stat_result(fields)
                return info
            with self.subTest(changed=changed), patch.object(Path, "lstat", metadata):
                self.assertEqual(gc.tmp_tree_newest(tree), self.now)
                self.assertEqual(self.planned(), {})

    def test_live_record_protects_whole_tree_after_clear_and_hand_launch(self):
        running, gone = self.scratch("after-clear"), self.scratch()
        proc = self.process()
        self.session_record(proc, running.name)
        self.now += 3 * DAY
        for args in (["claude"], ["claude", "--session-id", "before-clear"],
                     ["node", "/opt/lib/@anthropic-ai/claude-code/cli.js"]):
            with self.subTest(args=args):
                (proc / "cmdline").write_bytes(b"\0".join(os.fsencode(a) for a in args))
                self.assertEqual(set(self.planned()), {str(gone)})
        gc.gc(lambda _: None)
        self.assertFalse(gone.exists())
        self.assertTrue(running.is_dir())
        shutil.rmtree(proc)
        self.now += 3 * DAY
        self.assertEqual(set(self.planned()), {str(running.parents[1])})

    def test_unidentified_client_keeps_all_scratch_only(self):
        scratch, ordinary = self.scratch(), self.entry("ordinary")
        proc = self.process(args=["claude"])
        self.now += 3 * DAY
        for extra in (None, {"pid": int(proc.name) + 1}, {"procStart": "old-start"},
                      {"sessionId": ""}):
            with self.subTest(extra=extra):
                if extra is not None:
                    self.session_record(proc, "sess-other", **extra)
                self.assertEqual(set(self.planned()), {str(ordinary)})
        # A missing client record does not make ordinary temporary files permanent.
        gc.gc(lambda _: None)
        self.assertFalse(ordinary.exists())
        self.assertTrue(scratch.is_dir())

    def test_kernel_hidden_foreign_and_exiting_processes_do_not_block_collection(self):
        old, held = self.entry("old"), self.entry("held")
        foreign = self.process(uid=os.getuid() + 1, cwd=held, pid=1)
        kernel = self.process(args=[], uid=0, kernel=True, pid=2)
        (kernel / "cwd").unlink()
        (kernel / "fd").rmdir()
        exited = self.process(pid=3)
        readable, _ = proc_snapshot.collect([foreign])
        self.assertNotEqual(readable[1]["uid"], os.getuid())
        self.hidden.return_value = readable
        original = Path.read_text
        def disappear(path, *args, **kwargs):
            if path == exited / "stat":
                shutil.rmtree(exited)
                raise FileNotFoundError("fixture process exited")
            return original(path, *args, **kwargs)
        self.now += 3 * DAY
        with self.unreadable(foreign), patch.object(Path, "read_text", disappear):
            self.assertEqual(set(self.planned()), {str(old)})
            gc.gc(lambda _: None)
        self.assertFalse(old.exists())
        self.assertTrue(held.is_dir())
        self.assertFalse(exited.exists())
        self.hidden.assert_called_with([1])

    def test_readable_foreign_process_keeps_our_open_file(self):
        held = self.entry("held")
        foreign = self.process(uid=os.getuid() + 1, opened=[held / "inner"])
        self.now += 3 * DAY
        paths, table = gc.tmp_processes()
        self.assertEqual(table[int(foreign.name)]["uid"], os.getuid() + 1)
        self.assertIn(str(held / "inner"), paths)
        self.assertEqual(self.planned(), {})
        self.hidden.assert_not_called()

    def test_closed_descriptor_does_not_cancel_the_inventory(self):
        old = self.entry("old")
        proc = self.process(opened=[self.root / "unrelated"])
        original = os.readlink
        def close(path, *args, **kwargs):
            if path == proc / "fd" / "0":
                path.unlink()
                raise FileNotFoundError("fixture descriptor closed")
            return original(path, *args, **kwargs)
        self.now += 3 * DAY
        with patch.object(os, "readlink", close):
            self.assertEqual(set(self.planned()), {str(old)})
        self.hidden.assert_not_called()

    def test_unresolved_processes_still_keep_files(self):
        old = self.entry("old")
        proc = self.process()
        self.now += 3 * DAY
        with self.unreadable(proc):
            self.assertEqual(self.planned(), {})
            gc.gc(lambda _: None)
        self.assertTrue(old.exists())
        self.hidden.assert_called_with([int(proc.name)])
        with patch.object(retention, "process_dirs", side_effect=PermissionError):
            self.assertEqual(self.planned(), {})

    def test_empty_userspace_argv_still_protects_handles_and_unidentified_scratch(self):
        old, held, scratch = self.entry("old"), self.entry("held"), self.scratch()
        self.process(args=[], opened=[held / "inner"])
        self.now += 3 * DAY
        self.assertEqual(set(self.planned()), {str(old)})
        gc.gc(lambda _: None)
        self.assertFalse(old.exists())
        self.assertTrue(held.is_dir())
        self.assertTrue(scratch.is_dir())
        self.hidden.assert_not_called()

    def test_privileged_helper_is_read_only_bounded_and_refusal_keeps_files(self):
        proc = self.process(uid=os.getuid() + 1)
        rows, _ = proc_snapshot.collect([proc])
        response = subprocess.CompletedProcess([], 0, json.dumps([rows, []]))
        with patch.object(run.subprocess, "run", return_value=response) as call:
            self.assertEqual(HIDDEN_INSPECT([int(proc.name)]), rows)
            argv, kwargs = call.call_args.args[0], call.call_args.kwargs
            self.assertEqual(argv[:6], ["sudo", "-n", "/usr/bin/python3", "-I", "-S", "-B"])
            self.assertEqual(argv[6:], [proc_snapshot.__file__, proc.name])
            self.assertEqual(kwargs["timeout"], 10)
            response.returncode = 1
            self.assertIsNone(HIDDEN_INSPECT([int(proc.name)]))

    def test_recheck_keeps_newly_held_files_and_sessions(self):
        held, scratch = self.entry("held"), self.scratch()
        self.now += 3 * DAY
        plan = list(self.planned().values())
        self.assertEqual(len(plan), 2)
        proc = self.process(args=["claude"], opened=[held / "inner"])
        self.session_record(proc, scratch.name)
        with patch.object(gc, "gc_candidates", return_value=iter(plan)):
            self.assertEqual(gc.gc(lambda _: None), [])
        self.assertTrue(held.is_dir())
        self.assertTrue(scratch.is_dir())

    def test_recheck_refuses_failed_inspection(self):
        old, scratch = self.entry("old"), self.scratch()
        self.now += 3 * DAY
        plan = list(self.planned().values())
        self.assertEqual(len(plan), 2)
        with patch.object(gc, "gc_candidates", return_value=iter(plan)), \
                patch.object(retention, "process_dirs", side_effect=PermissionError):
            self.assertEqual(gc.gc(lambda _: None), [])
        self.assertTrue(old.is_dir())
        self.assertTrue(scratch.is_dir())

    def test_process_inventory_cost_is_per_batch(self):
        paths = [self.entry(f"old-{index}") for index in range(5)]
        self.now += 3 * DAY
        with patch.object(gc, "tmp_processes", wraps=gc.tmp_processes) as inventory:
            removed = gc.gc(lambda _: None)
        self.assertEqual(set(removed), set(map(str, paths)))
        self.assertEqual(inventory.call_count, 2)   # plan, then recheck the batch

    def test_protected_names_stay(self):
        kept = [self.entry(name) for name in (".X11-unix", "tmux-1000", "systemd-private-abc")]
        self.now += 3 * DAY
        self.assertEqual(self.planned(), {})
        gc.gc(lambda _: None)
        self.assertTrue(all(path.is_dir() for path in kept))


if __name__ == "__main__":
    unittest.main(verbosity=2)
