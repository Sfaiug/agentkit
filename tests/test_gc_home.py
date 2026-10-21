"""Nothing in ak's home outlives its use.

At its top, anything not ak's own goes a week after its last change; a task file, and a file
fetched from the Mac, 30 days after theirs.  Offline: HOME, the Mac bridge's folder and /proc
are the fixture's.  The clock moves forward to age files, since utime cannot backdate an
inode's change time.
"""

import os
from pathlib import Path
import re
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gc, job as jobs, macbridge, orch, retention

DAY = 86400
REPO = Path(__file__).resolve().parent.parent


class GcHome(Sandbox):
    def setUp(self):
        self.now = time.time() + 1
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100",
                                                        "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(retention, "unix_sockets", return_value=set()))
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.stack.enter_context(patch.object(retention, "process_dirs", self.proc.iterdir))
        self.stack.enter_context(patch.object(gc, "tmp_hidden_processes", return_value=None))

    def made(self, path, text="kept\n"):
        """A file at `path`, changed at the clock's now."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        for each in (path, path.parent):
            os.utime(each, (self.now, self.now))
        return path

    def holds(self, path):
        """A process of this user with `path` open."""
        proc = self.proc / str(1000 + len(list(self.proc.iterdir())))
        (proc / "fd").mkdir(parents=True)
        fields = ["S", "1", *(["0"] * 18)]
        fields[19] = "12345"
        (proc / "stat").write_text(f"{proc.name} (fixture) " + " ".join(fields))
        (proc / "status").write_text("Uid:\t" + "\t".join([str(os.getuid())] * 4) + "\n")
        (proc / "cmdline").write_bytes(b"fixture")
        (proc / "cwd").symlink_to(self.root)
        (proc / "fd" / "3").symlink_to(path)

    def planned(self):
        return {item["path"] for item in gc.gc_plan() if item["kind"] == "home-entry"}

    def test_a_stray_at_the_top_goes_a_week_after_its_last_change(self):
        notes = self.made(config.HOME / "handover" / "seat.md")
        backup = self.made(config.HOME / "rules.md-20260929")
        own = [self.made(config.HOME / name / "x") if name in ("bin", "tasks") else
               self.made(config.HOME / name) for name in ("bin", "rules.md", "history.db",
                                                         "history.db-journal", "history.lock", "tasks")]
        self.now += 6 * DAY
        self.made(config.HOME / "handover" / "today.md")
        self.now += 2 * DAY
        # a folder still in use loses only what nothing changed for a week
        self.assertEqual(self.planned(), {str(notes), str(backup)})
        self.now += 6 * DAY
        self.assertEqual(self.planned(), {str(notes.parent), str(backup)})
        removed = gc.gc(lambda _: None)
        self.assertEqual(set(removed) & {str(notes.parent), str(backup)},
                         {str(notes.parent), str(backup)})
        self.assertFalse(notes.parent.exists())
        self.assertFalse(backup.exists())
        for path in own:
            self.assertTrue(path.exists(), path)

    def test_old_task_files_go_after_thirty_days_and_new_ones_beside_them_stay(self):
        tasks = config.HOME / "tasks"
        old = self.made(tasks / "acme" / "old-task.md")
        shots = self.made(tasks / "acme" / "ref" / "hero.png")
        loose = self.made(tasks / "fix-api.md")
        gone_project = self.made(tasks / "widget" / "task.md")
        queued = self.made(tasks / "acme" / "queued.md")
        jobs.save_job(self.made(config.JOBS / "job-1" / "log.txt").parent, {
            "tasks": [{"name": "queued", "state": "queued", "task_file": str(queued)}]})
        self.now += 20 * DAY
        new = self.made(tasks / "acme" / "new-task.md")
        self.assertEqual(self.planned(), set())
        self.now += 11 * DAY
        self.assertEqual(self.planned(), {str(old), str(shots.parent), str(loose),
                                          str(gone_project.parent)})
        self.assertTrue(new.exists() and queued.exists())

    def test_a_file_fetched_from_the_mac_goes_thirty_days_after_it_came(self):
        inbox = macbridge.home() / "inbox"
        fetched = self.made(inbox / "0123456789abcdef.png")
        receipt = self.made(inbox / ".0123456789abcdef.ready")
        self.now += 29 * DAY
        self.assertEqual(self.planned(), set())
        self.now += 2 * DAY
        self.assertEqual(self.planned(), {str(fetched), str(receipt)})
        gc.gc(lambda _: None)
        self.assertFalse(fetched.exists())
        self.assertTrue(inbox.is_dir())

    def test_what_a_process_holds_stays_and_its_untouched_neighbours_go(self):
        held = self.made(config.HOME / "scripts" / "watch.sh")
        idle = self.made(config.HOME / "scripts" / "old.sh")
        self.holds(held)
        self.now += 8 * DAY
        self.assertEqual(self.planned(), {str(idle)})
        gc.gc(lambda _: None)
        self.assertTrue(held.exists())
        self.assertFalse(idle.exists())

    def test_a_process_whose_handles_cannot_be_read_keeps_everything(self):
        notes = self.made(config.HOME / "handover.md")
        (self.proc / "1234").mkdir()
        self.now += 8 * DAY
        self.assertEqual(self.planned(), set())
        gc.gc(lambda _: None)
        self.assertTrue(notes.exists())

    def test_every_name_ak_keeps_at_the_top_of_its_home_is_its_own(self):
        # A new folder of ak's own the collector does not know would go a week after it is
        # left unchanged: anything the code names directly under HOME is in config.OWN.
        pattern = r'HOME / "([A-Za-z0-9_.-]+)"|\.agentkit/([A-Za-z0-9_.-]+)'
        found = subprocess.run(
            ["git", "-C", str(REPO), "grep", "-h", "-o", "-I", "-E", pattern, "--",
             "agentkit", "bin", "adapters", "hooks", "tools", "templates", "install.sh"],
            capture_output=True, text=True).stdout.splitlines()
        names = {(match[1] or match[2]).rstrip(".")
                 for match in map(lambda line: re.fullmatch(pattern, line), found) if match}
        self.assertGreater(len(names), 5, names)
        self.assertEqual({name for name in names if name not in config.OWN}, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
