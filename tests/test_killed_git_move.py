"""A fast-forward of ~/agentkit that a killed git cut off is finished by the next tick.

A git the host's memory killer took left HEAD.lock behind.  The tick's next fast-forward then
moved the files but not HEAD, and every tick after found the checkout `dirty`: nothing went live
for ten hours, and each harness upgrade's fresh-install gate refused the tree it was to test.
test_go_live_retries_install's offline clone, its origin one commit ahead.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as base

git = base.git
DAY = 86400     # any killed git's lock is long past `update.LOCK_STALE` by then


class KilledGitMove(unittest.TestCase):
    setUp, tick, installs = (base.GoLiveRetriesInstall.setUp, base.GoLiveRetriesInstall.tick,
                             base.GoLiveRetriesInstall.installs)

    def cut(self, age):
        """The tick's fast-forward, failing on a HEAD.lock a git left `age` seconds ago."""
        self.old, self.lock = git(self.clone, "rev-parse", "HEAD"), self.clone / ".git/HEAD.lock"
        self.lock.write_text("")
        os.utime(self.lock, (time.time() - age,) * 2)
        git(self.clone, "fetch", "-q", "origin", "main")
        merge = subprocess.run(["git", "-C", str(self.clone), "merge", "--ff-only", self.new],
                               capture_output=True, text=True, timeout=60)
        self.assertIn("cannot lock ref 'HEAD'", merge.stderr)
        self.assertEqual(((self.clone / "notes").read_text(), self.head()), ("second\n", self.old))

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def test_the_cut_move_is_finished_and_installed(self):
        self.cut(DAY)
        said, _ = self.tick()
        self.assertEqual(said, [f"agentkit is live at {self.new[:12]}"])
        self.assertEqual((self.head(), git(self.clone, "status", "--porcelain")), (self.new, ""))
        self.assertEqual((self.installs(), self.lock.exists()), (1, False))

    def test_a_git_still_at_work_or_changes_of_its_own_keep_it_as_it_is(self):
        self.cut(0)
        self.tick()
        self.assertEqual((self.head(), self.lock.exists(), self.installs()), (self.old, True, 0))
        os.utime(self.lock, (time.time() - DAY,) * 2)
        (self.clone / "notes").write_text("mine\n")
        self.tick()
        self.assertEqual((self.head(), (self.clone / "notes").read_text()), (self.old, "mine\n"))
        self.assertEqual((self.installs(), self.lock.exists()), (0, False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
