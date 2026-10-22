"""A move of ~/agentkit cut off anywhere is finished by a later tick.

A killed git's HEAD.lock failed the tick's fast-forward after it had moved the files but not
HEAD; every tick after found the checkout `dirty`, somebody's work, and nothing went live for ten
hours.  A move ak cut off -- a git step failing half done, or one it killed at its cap -- is its
own: it goes to the commit that move was for.  Commits and edits of the checkout's own stay.
test_go_live_retries_install's offline clone, its origin one commit ahead.
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


class CutMoveFinished(unittest.TestCase):
    setUp, tick, installs = (base.GoLiveRetriesInstall.setUp, base.GoLiveRetriesInstall.tick,
                             base.GoLiveRetriesInstall.installs)

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def live(self):
        self.assertEqual(self.tick()[0], [f"agentkit is live at {self.new[:12]}"])
        self.assertEqual((self.head(), git(self.clone, "status", "--porcelain")), (self.new, ""))
        self.assertEqual(self.installs(), 1)

    def test_a_fast_forward_a_left_lock_failed_half_way_goes_live_once_it_is_gone(self):
        old, lock = self.head(), self.clone / ".git/HEAD.lock"
        lock.write_text("")
        said, _ = self.tick()
        self.assertIn("cannot lock ref 'HEAD'", "\n".join(said))
        self.assertEqual(((self.clone / "notes").read_text(), self.head()), ("second\n", old))
        lock.unlink()                               # the dead git lock pass
        self.live()

    def cut(self, moved=lambda clone, target: git(clone, "read-tree", "-m", "-u", "HEAD", target)):
        """The tick's move killed at its cap once it `moved` the checkout: by default its files
        and its index."""
        run = subprocess.run

        def killed(cmd, *args, **kwargs):
            if "merge" not in cmd:
                return run(cmd, *args, **kwargs)
            moved(self.clone, cmd[-1])
            raise subprocess.TimeoutExpired(cmd, update.STEP_CAP)
        with patch.object(update.subprocess, "run", side_effect=killed):
            update.go_live(lambda line: None)
        self.assertEqual(self.installs(), 0)

    def test_a_move_killed_mid_way_goes_live(self):
        self.cut()
        self.live()

    def test_a_move_killed_mid_file_goes_live(self):
        self.cut(lambda clone, target: (clone / "notes").write_text("sec"))
        self.live()

    def test_a_commit_of_its_own_after_a_cut_move_stays(self):
        self.cut()
        git(self.clone, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-q", "-m", "mine")
        mine = self.head()
        self.tick()
        self.assertEqual((self.head(), self.installs()), (mine, 0))

    def edited(self, staged=False):
        """The owner's edit, in the file or only staged, which no later tick may touch, and the
        HEAD it stays on."""
        mine, head = self.clone / "install.sh", self.head()
        kept = mine.read_text()
        mine.write_text(kept + "# mine\n")
        if staged:
            git(self.clone, "add", "install.sh")
            mine.write_text(kept)
        self.tick()
        edit = git(self.clone, "show", ":install.sh") if staged else mine.read_text()
        self.assertEqual((self.head(), edit.strip().endswith("# mine"), self.installs()),
                         (head, True, 0))

    def test_an_edit_after_a_move_that_never_began_stays(self):
        lock = self.clone / ".git/index.lock"
        lock.write_text("")
        self.tick()
        lock.unlink()
        self.edited()

    def test_an_edit_after_a_cut_move_stays(self):
        self.cut()
        self.edited()

    def test_a_staged_edit_after_a_cut_move_stays(self):
        self.cut()
        self.edited(staged=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
