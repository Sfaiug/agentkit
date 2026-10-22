"""A lock a killed git left goes from every repository ak works in, once no process uses it.

A git the host's memory killer took held ~/agentkit's HEAD.lock: every git after it that needed
that file failed, and ak's own update stayed half moved for ten hours.  A git at work in the
checkout or any worktree of it, or any process holding a file in its git directory, keeps every
lock; so do a process table that cannot be read whole and a lock replaced since it was found.
Offline: throwaway repositories and a fake process table, no real process read.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gc

DAY = 86400


def git(where, *args):
    subprocess.run(["git", "-C", str(where), "-c", "user.name=fixture",
                    "-c", "user.email=fixture@example.invalid", *args],
                   check=True, capture_output=True, timeout=60)


class DeadGitLocks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-git-locks-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo, self.other, self.wt = self.root / "agentkit", self.root / "acme", self.root / "wt"
        # acme keeps its git directory apart, its `.git` a file naming it
        for repo, apart in ((self.repo, ()), (self.other, ("--separate-git-dir", self.root / "acme.git"))):
            subprocess.run(["git", "init", "-q", *apart, str(repo)], check=True, timeout=60)
            git(repo, "commit", "-q", "--allow-empty", "-m", "first")
        git(self.repo, "worktree", "add", "-q", "--detach", str(self.wt))
        self.now, self.table = 10 * DAY, {}
        patch.object(config, "REPO", self.repo).start()
        patch.object(config, "session_records",
                     lambda: {"fix-api": {"repo": str(self.other)}}).start()
        patch.object(gc, "tmp_processes", lambda: (set(), self.table)).start()
        self.addCleanup(patch.stopall)
        self.lock = self.plant(self.repo / ".git", "HEAD.lock", DAY)

    def plant(self, gitdir, name, age):
        path = gitdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        os.utime(path, (self.now - age,) * 2)
        return path

    def process(self, args, cwd, *held):
        self.table[len(self.table) + 1] = {"args": args, "cwd": str(cwd),
                                           "paths": [str(cwd), *map(str, held)]}

    def clear(self):
        said = []
        gc.clear_git_locks(said.append, now=self.now)
        return said

    def test_locks_no_living_git_holds_go_from_every_repository_and_young_ones_stay(self):
        young = self.plant(self.repo / ".git", "index.lock", 10)
        theirs = self.plant(self.repo / ".git", "hooks/Gemfile.lock", DAY)    # a hook's, not git's
        dead = [self.lock, self.plant(self.repo / ".git", "refs/heads/topic.lock", DAY),
                self.plant(self.repo / ".git", f"worktrees/{self.wt.name}/index.lock", DAY),
                self.plant(self.root / "acme.git", "refs/remotes/origin/main.lock", DAY)]
        self.process(["/usr/bin/git", "status"], self.root / "elsewhere")
        self.process(["bash"], self.wt)             # a shell in a checkout is no git at work
        said = self.clear()
        self.assertEqual([lock.exists() for lock in dead], [False] * 4)
        self.assertTrue(young.exists() and theirs.exists())
        self.assertEqual(len(said), 4)
        self.assertIn(f"removed {self.lock}, left 1d ago by a git that has ended", said)

    def test_a_git_at_work_or_a_held_file_keeps_every_lock(self):
        for args, cwd, held in ((["git", "commit"], self.repo, ()),
                                (["/usr/lib/git-core/git", "gc"], self.wt / "src", ()),
                                (["python3"], self.root, (self.repo / ".git/objects/pack/a.pack",))):
            with self.subTest(args[0]):
                self.table.clear()
                self.process(args, cwd, *held)
                self.assertEqual((self.clear(), self.lock.exists()), ([], True))

    def test_a_file_held_through_a_linked_git_directory_keeps_its_lock(self):
        # /proc names the file a process holds by its real path, never the link's
        (self.repo / ".git").rename(self.root / "meta")
        (self.repo / ".git").symlink_to(self.root / "meta", target_is_directory=True)
        self.process(["python3"], self.root, self.root / "meta/HEAD.lock")
        self.assertEqual((self.clear(), self.lock.exists()), ([], True))

    def test_no_whole_process_table_or_a_lock_replaced_since_keeps_it(self):
        with patch.object(gc, "tmp_processes", return_value=(None, None)):
            self.assertEqual((self.clear(), self.lock.exists()), ([], True))

        def replaced():
            # a git took the name the moment the old lock went: a new file, with its own time
            self.lock.unlink()
            self.lock.write_text("")
            return set(), {}
        with patch.object(gc, "tmp_processes", side_effect=replaced):
            self.assertEqual((self.clear(), self.lock.exists()), ([], True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
