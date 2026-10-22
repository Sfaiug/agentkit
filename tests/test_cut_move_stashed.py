"""A fast-forward of ~/agentkit cut off anywhere is done again whole, and nothing is lost.

Git moves HEAD last: a fast-forward killed, or failing half way, leaves the files anywhere
between the two commits, some half written, and every tick after found the checkout `dirty`
and left it, nothing going live for ten hours.  The move records its target first; a later
tick finding HEAD short of it keeps whatever the checkout holds -- the move's half, or anybody's
edits since, staged or not -- in a stash, and goes to that commit.  A commit of the checkout's
own after it still stays.  test_go_live_retries_install's offline clone, its origin one ahead.
"""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as base
from agentkit import update

git = base.git


class CutMoveStashed(unittest.TestCase):
    setUp, installs = base.GoLiveRetriesInstall.setUp, base.GoLiveRetriesInstall.installs

    def go_live(self):
        said = []
        update.go_live(said.append)
        return said

    def killed(self, cmd, *args, **kwargs):
        """The fast-forward, killed at its cap with the index moved and `notes` half written."""
        if "merge" not in cmd:
            return self.run(cmd, *args, **kwargs)
        git(self.clone, "read-tree", "-m", "-u", "HEAD", cmd[-1])
        (self.clone / "notes").write_text("sec")
        raise subprocess.TimeoutExpired(cmd, update.STEP_CAP)

    def cut(self):
        self.old, self.run = git(self.clone, "rev-parse", "HEAD"), subprocess.run
        with patch.object(update.subprocess, "run", side_effect=self.killed):
            self.go_live()
        self.assertEqual((git(self.clone, "rev-parse", "HEAD"), self.installs()), (self.old, 0))

    def test_a_move_killed_half_way_goes_live_and_what_was_there_is_kept(self):
        self.cut()
        # somebody's edit since, in the index only: its file as HEAD has it
        blob = subprocess.run(["git", "-C", str(self.clone), "hash-object", "-w", "--stdin"],
                              input="#!/bin/sh\necho mine\n", capture_output=True, text=True,
                              check=True, timeout=60).stdout.strip()
        git(self.clone, "update-index", "--cacheinfo", f"100755,{blob},install.sh")
        self.assertEqual(self.go_live(), [f"agentkit is live at {self.new[:12]}"])
        self.assertEqual((git(self.clone, "rev-parse", "HEAD"),
                          git(self.clone, "status", "--porcelain"), self.installs()),
                         (self.new, "", 1))
        self.assertEqual(git(self.clone, "stash", "list", "--format=%s"),
                         f"On main: ak: held when its move to {self.new[:12]} was cut off")
        self.assertEqual((git(self.clone, "show", "stash@{0}:notes"),
                          git(self.clone, "show", "stash@{0}^2:install.sh")),
                         ("sec", "#!/bin/sh\necho mine"))

    def test_a_repository_nested_where_the_move_goes_stays(self):
        # the stash skips a nested repository, and the reset would delete one at a tracked path
        self.cut()
        (self.clone / "notes").unlink()
        (self.clone / "notes").mkdir()
        git(self.clone / "notes", "init", "-q")
        (self.clone / "notes" / "mine").write_text("only copy")
        self.go_live()
        self.assertEqual(((self.clone / "notes" / "mine").read_text(), self.installs(),
                          git(self.clone, "rev-parse", "HEAD")), ("only copy", 0, self.old))

    def test_a_commit_of_its_own_after_a_cut_move_stays(self):
        self.cut()
        git(self.clone, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-q", "-am", "mine")
        mine = git(self.clone, "rev-parse", "HEAD")
        self.go_live()
        self.assertEqual((git(self.clone, "rev-parse", "HEAD"), self.installs(),
                          git(self.clone, "stash", "list")), (mine, 0, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
