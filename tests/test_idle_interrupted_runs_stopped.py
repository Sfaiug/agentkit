"""The retention pass takes a run interrupted a month ago and never resumed as it takes an old
ended run: its directory whole, with its checkout and branch.  One interrupted two days ago stays,
and so does one resumed between the pass's look and its removal.

Offline: a throwaway HOME, the clock pinned, every loop gone by an injected `process_active`, the
checkouts tiny git repos under that HOME, and the seat that launched them never there.
"""

import os
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, gc, orch, record

DAY = 86400


class IdleInterruptedRunsStopped(Sandbox):
    def setUp(self):
        self.now = time.time()
        super().setUp()
        self.stack.enter_context(patch.object(time, "time", return_value=self.now))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_GC_DISK_PERCENT": "100"}))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(record, "process_active", return_value=False))
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.email=a@localhost", "-c", "user.name=acme",
                 "commit", "-q", "--allow-empty", "-m", "base")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              text=True, check=True).stdout.strip()

    def interrupted(self, name, days):
        directory, wt, branch = config.RUNS / name, config.WT / name, "ak/" + name
        directory.mkdir(parents=True)
        self.git("worktree", "add", "-q", str(wt), "-b", branch)
        (wt / "half-done.txt").write_text("work in progress\n")
        at = self.now - days * DAY
        record.save_state(directory, {
            "run_id": name, "title": name, "state": "interrupted", "interrupted_at": at,
            "started_at": at - 600, "repo": str(self.repo), "worktree": str(wt),
            "branch": branch, "launched_session": "acme-gone", "pid": 99999999,
            "process_identity": None})
        return directory, wt, branch

    def branches(self):
        return self.git("branch", "--format=%(refname:short)").split()

    def test_a_month_interrupted_run_goes_and_a_resumed_or_recent_one_stays(self):
        old, old_wt, old_branch = self.interrupted("fix-api-1", 31)
        recent, recent_wt, recent_branch = self.interrupted("fix-api-2", 2)
        resumed, resumed_wt, resumed_branch = self.interrupted("fix-api-3", 31)
        planned = gc.gc_plan()
        self.assertEqual(sorted(item["path"] for item in planned if item["kind"] == "old-run"),
                         [str(old), str(resumed)])
        # resumed after the look: its record says running again, under the same interruption
        record.save_state(resumed, {**record.read_state(resumed), "state": "running"})
        lines = []
        with patch.object(gc, "gc_candidates", return_value=iter(planned)):
            gc.gc(lines.append)
        self.assertIn(f"gc: remove old-run {old}", lines)
        self.assertFalse(old.exists())
        self.assertFalse(old_wt.exists())
        for directory, wt in ((recent, recent_wt), (resumed, resumed_wt)):
            self.assertTrue((directory / "run.json").is_file())
            self.assertTrue((wt / "half-done.txt").is_file())
        self.assertEqual(sorted(self.branches()), ["ak/fix-api-2", "ak/fix-api-3", "main"])


if __name__ == "__main__":
    unittest.main()
