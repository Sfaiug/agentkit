"""Inside a seat, `git stash` is refused in a repository with more than one checkout.

A repository keeps one stash list for all of its checkouts, and a seat's checkout is a worktree
of one, so the entry on top of a seat's `git stash pop`, `apply` or `drop` may be another
checkout's.  A seat's `git stash` that is neither `list` nor `show` is refused there with one line,
and git does not run: the list and the changed file are as they were.  `list` and `show` run as
typed, as does every `git stash` in a repository with one checkout, and a worker's or no seat's.
Black-box: the shims a seat's launch installs (tests/fixtures/shims.py), run as a seat's commands
with the real git behind them on a project (tests/fixtures/gitrig.py) with a second checkout under
~/.agentkit/wt, judged by the exit code, what was printed, the stash list and the files on disk;
this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.gitrig import Rig
from fixtures.shims import Shims

REFUSED = ("ak refused `git stash`: this repository's checkouts share one stash list, so an entry "
           "is any checkout's to take and the one on top may not be yours. Keep the change in a "
           "file (`git diff HEAD > FILE`, and `git apply FILE` brings it back) or on a commit of "
           "its own.\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SharedStash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)

    def project(self, name, other=True):
        """A project whose tracked notes.txt is changed in its checkout; with `other`, a second
        checkout under ~/.agentkit/wt that put the stash list's one entry there."""
        rig = Rig(self.home, name, files={"notes.txt": "committed\n"})
        if other:
            wt = self.home.path / ".agentkit" / "wt" / name
            rig.git("worktree", "add", "-q", "-b", "other", str(wt))
            (wt / "notes.txt").write_text("theirs\n")
            done = self.home.run("git", "-C", str(wt), "stash", "push", "-q", "-m", "theirs")
            assert done.code == 0, done.err
        (rig.path / "notes.txt").write_text("mine\n")
        return rig

    def git(self, rig, *args, cwd=None, seat="acme", env=None):
        return self.shims.run("git", *args, cwd=cwd or rig.path, seat=seat, env=env)

    def entries(self, rig):
        return rig.git("stash", "list", "--format=%H").split()

    def test_a_stash_that_writes_or_takes_from_the_shared_list_is_refused(self):
        rig = self.project("acme")
        held = self.entries(rig)
        self.assertEqual(len(held), 1)
        for cwd, args in ((None, ("stash",)), (None, ("stash", "-u")), (None, ("stash", "push")),
                          (None, ("stash", "pop")), (None, ("stash", "apply")),
                          (None, ("stash", "drop")), (None, ("stash", "clear")),
                          (self.home.path, ("-C", "code/acme", "stash"))):
            with self.subTest(args=args):
                done = self.git(rig, *args, cwd=cwd)
                self.assertEqual((done.code, done.out, done.err), (1, "", REFUSED))
                self.assertEqual(self.entries(rig), held)
                self.assertEqual((rig.path / "notes.txt").read_text(), "mine\n")

    def test_list_and_show_read_the_shared_list_as_typed(self):
        rig = self.project("beta")
        done = self.git(rig, "stash", "list")
        self.assertEqual((done.code, done.out, done.err), (0, "stash@{0}: On other: theirs\n", ""))
        done = self.git(rig, "stash", "show")
        self.assertEqual((done.code, done.err), (0, ""))

    def test_a_stash_in_a_project_of_one_checkout_stashes(self):
        rig = self.project("solo", other=False)
        done = self.git(rig, "stash")
        self.assertEqual((done.code, done.err), (0, ""))
        self.assertEqual(len(self.entries(rig)), 1)
        self.assertEqual((rig.path / "notes.txt").read_text(), "committed\n")

    def test_a_workers_stash_and_one_of_no_seat_run_as_typed(self):
        for name, seat, env in (("worker", "acme", {"AK_RUN_ROLE": "worker"}),
                                ("seatless", None, None)):
            with self.subTest(name):
                rig = self.project(name)
                held = self.entries(rig)
                done = self.git(rig, "stash", seat=seat, env=env)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertEqual(self.entries(rig)[1:], held)
                self.assertEqual(len(self.entries(rig)), 2)
                self.assertEqual((rig.path / "notes.txt").read_text(), "committed\n")


if __name__ == "__main__":
    unittest.main()
