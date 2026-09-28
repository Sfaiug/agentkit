"""A repository TMPDIR directly under /var/tmp is collected like /tmp.

Offline: /tmp, /var/tmp, /proc and HOME are all fixture-owned. A TMPDIR that is
not a canonical path directly under /var/tmp is named once per pass and never
swept. Move the clock forward to age files; utime cannot backdate inode change
times.
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


class GcRepoTmp(Sandbox):
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
        self.stack.enter_context(patch.object(run, "TMP_BASE", self.tmp))
        # Canonical spelling, or realpath would refuse the fixture values below.
        self.var_tmp = Path(os.path.realpath(self.root)) / "var-tmp"
        self.var_tmp.mkdir()
        self.stack.enter_context(patch.object(run, "VAR_TMP_BASE", self.var_tmp))
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))
        self.stack.enter_context(
            patch.object(run, "tmp_hidden_processes", return_value=None))

    def process(self, args=("fixture",), cwd=None, opened=(), uid=None, pid=None):
        proc = self.proc / str(pid or 1000 + len(list(self.proc.iterdir())))
        (proc / "fd").mkdir(parents=True)
        fields = ["S", "1", *(["0"] * 18)]
        fields[6], fields[19] = "0", "12345"
        (proc / "stat").write_text(f"{proc.name} (fixture) " + " ".join(fields))
        uid = os.getuid() if uid is None else uid
        (proc / "status").write_text("Uid:\t" + "\t".join([str(uid)] * 4) + "\n")
        (proc / "cmdline").write_bytes(b"\0".join(os.fsencode(arg) for arg in args))
        (proc / "cwd").symlink_to(cwd or self.root)
        for index, path in enumerate(opened):
            (proc / "fd" / str(index)).symlink_to(path)
        return proc

    def touch(self, path):
        os.utime(path, (self.now, self.now), follow_symlinks=False)
        return path

    def repo(self, name, tmpdir):
        (config.ENV / f"{name}.env").write_text(f"TMPDIR={tmpdir}\n")

    def entry(self, base, name):
        path = base / name
        path.mkdir()
        (path / "inner").write_text("temp\n")
        self.touch(path / "inner")
        return self.touch(path)

    def planned(self):
        return {item["path"]: item for item in run.gc_plan()
                if item["kind"] in ("tmp-entry", "repo-tmp")}

    def gc_out(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_gc(list(argv)), 0)
        return out.getvalue()

    def test_stale_entry_goes_and_directory_itself_stays(self):
        base = self.var_tmp / "ak-acme"
        base.mkdir()
        self.repo("acme", base)
        old = self.entry(base, "old-dir")
        self.now += 3 * DAY
        plan = self.planned()
        self.assertEqual(set(plan), {str(old)})
        self.assertEqual(plan[str(old)]["kind"], "tmp-entry")
        dry = self.gc_out("--dry-run")
        self.assertIn(f"gc: would remove tmp-entry {old}: untouched for 3 days", dry)
        self.assertTrue(old.exists())
        removed = run.gc(lambda _: None, automatic=True)
        logged = (config.STATE / "gc.log").read_text()
        self.assertIn(str(old), removed)
        self.assertFalse(old.exists())
        self.assertTrue(base.is_dir())
        self.assertEqual(logged.count(f"gc: remove tmp-entry {old}:"), 1)

    def test_open_entry_stays(self):
        base = self.var_tmp / "ak-acme"
        base.mkdir()
        self.repo("acme", base)
        held = self.entry(base, "held")
        nested = self.entry(base, "nested")
        self.process(cwd=held, opened=[nested / "inner"])
        self.now += 3 * DAY
        self.assertEqual(self.planned(), {})
        run.gc(lambda _: None)
        self.assertTrue(held.is_dir())
        self.assertTrue(nested.is_dir())

    def test_recent_entry_stays(self):
        base = self.var_tmp / "ak-acme"
        base.mkdir()
        self.repo("acme", base)
        mixed = self.entry(base, "mixed")
        self.now += 3 * DAY
        fresh = self.entry(base, "fresh")
        (mixed / "inner").write_text("just now\n")
        self.touch(mixed / "inner")
        self.assertEqual(self.planned(), {})
        run.gc(lambda _: None)
        self.assertTrue(fresh.is_dir())
        self.assertTrue(mixed.is_dir())

    def assert_skipped_untouched(self, value, *paths):
        self.now += 3 * DAY
        plan = self.planned()
        self.assertEqual(set(plan), {value})
        item = plan[value]
        self.assertEqual((item["action"], item["kind"]), ("skip", "repo-tmp"))
        self.assertEqual(item["why"], f"not a canonical path directly under {self.var_tmp}")
        dry = self.gc_out("--dry-run")
        self.assertIn(f"gc: would skip repo-tmp {value}: {item['why']}", dry)
        self.assertNotIn("would remove tmp-entry", dry)
        removed = run.gc(lambda _: None, automatic=True)
        self.assertEqual(removed, [])
        logged = (config.STATE / "gc.log").read_text()
        self.assertEqual(logged.count(f"gc: skip repo-tmp {value}:"), 1)
        for path in paths:
            self.assertTrue(Path(path).exists(), path)

    def test_symlinked_tmpdir_is_skipped_untouched(self):
        target = self.var_tmp / "ak-real"
        target.mkdir()
        old = self.entry(target, "old-dir")
        link = self.var_tmp / "ak-link"
        link.symlink_to(target)
        self.repo("acme", link)
        self.assert_skipped_untouched(str(link), link, old, old / "inner")

    def test_dotdot_tmpdir_is_skipped_untouched(self):
        base = self.var_tmp / "ak-thing"
        base.mkdir()
        old = self.entry(base, "old-dir")
        self.repo("acme", self.var_tmp / "sub" / ".." / "ak-thing")
        self.assert_skipped_untouched(str(self.var_tmp / "sub" / ".." / "ak-thing"),
                                      base, old, old / "inner")

    def test_tmp_tmpdir_is_skipped_while_tmp_pass_still_sweeps(self):
        self.repo("acme", "/tmp")
        old = self.entry(self.tmp, "old-dir")
        self.now += 3 * DAY
        plan = self.planned()
        self.assertEqual(set(plan), {str(old), "/tmp"})
        self.assertEqual(plan[str(old)]["kind"], "tmp-entry")
        self.assertEqual((plan["/tmp"]["action"], plan["/tmp"]["kind"]), ("skip", "repo-tmp"))
        dry = self.gc_out("--dry-run")
        self.assertIn(f"gc: would remove tmp-entry {old}: untouched for 3 days", dry)
        self.assertIn("gc: would skip repo-tmp /tmp:", dry)
        removed = run.gc(lambda _: None, automatic=True)
        self.assertEqual(removed, [str(old)])
        self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
