"""Inside a seat, `git worktree add` into ~/code is refused; one under ~/.agentkit/wt runs.

~/code holds only the owner's checkouts (owner rules); a seat makes its own under
~/.agentkit/wt.  A seat's git refuses a new worktree whose path lands in ~/code, read as git
reads it (from the working directory and each `-C`, past `worktree add`'s options, through a
link), says where to make it instead, and git makes nothing: no checkout, no branch.  A worktree
elsewhere, every other git call, and a worker's or no seat's checkout in ~/code run git as
typed.  Black-box: the shims a seat's launch installs (tests/fixtures/shims.py), run as a seat's
commands with the real git behind them on a project under ~/code (tests/fixtures/gitrig.py),
judged by the exit code, what was printed and the checkouts on disk; this test fails against
`/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.gitrig import Rig
from fixtures.shims import Shims

REFUSED = ("ak refused `git worktree add {}`: ~/code holds only the owner's checkouts. Make a "
           "seat's checkout under ~/.agentkit/wt/ instead: `git worktree add ~/.agentkit/wt/<name> "
           "...`.\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WorktreeInCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        cls.rig = Rig(cls.home, "acme")
        cls.code = cls.home.path / "code"
        cls.wt = cls.home.path / ".agentkit" / "wt"
        (cls.home.path / "link").symlink_to(cls.code)

    def git(self, *args, cwd=None, seat="acme", env=None):
        return self.shims.run("git", *args, cwd=cwd or self.rig.path, seat=seat, env=env)

    def checkouts(self):
        listed = self.rig.git("worktree", "list", "--porcelain").splitlines()
        return [line.removeprefix("worktree ") for line in listed if line.startswith("worktree ")]

    def test_each_way_of_naming_a_checkout_in_code_is_refused_and_git_makes_nothing(self):
        absolute, linked = str(self.code / "acme-fix"), str(self.home.path / "link/acme-fix")
        home = self.home.path
        for cwd, args, shown in (
                (None, ("worktree", "add", "../acme-fix", "-b", "fix"), "../acme-fix"),
                (home, ("-C", "code/acme", "worktree", "add", "-b", "fix", "../acme-fix"),
                 "../acme-fix"),
                (home, ("-C", "code", "-C", "acme", "worktree", "add", "-b", "fix",
                        "../acme-fix"), "../acme-fix"),
                (None, ("worktree", "add", "-q", "-fb", "fix", absolute), absolute),
                (None, ("worktree", "add", "-b", "fix", "--lock", "--reason", "mine", "--",
                        "../acme-fix"), "../acme-fix"),
                (None, ("worktree", "add", "-b", "fix", linked), linked)):
            with self.subTest(args=args):
                done = self.git(*args, cwd=cwd)
                self.assertEqual((done.code, done.out, done.err), (1, "", REFUSED.format(shown)))
                self.assertFalse((self.code / "acme-fix").exists())
                self.assertEqual(self.rig.git("branch", "--list", "fix"), "")
                self.assertNotIn(str(self.code / "acme-fix"), self.checkouts())

    def test_a_checkout_outside_code_is_made(self):
        for name, path in (("plain", str(self.wt / "plain")),
                           ("relative", "../../.agentkit/wt/relative"),
                           # a folder whose name only starts as ~/code's does is not in it
                           ("beside", str(self.home.path / "code-old" / "beside"))):
            with self.subTest(name):
                done = self.git("worktree", "add", "-q", "-b", name, path)
                self.assertEqual((done.code, done.err), (0, ""))
                made = (self.rig.path / path).resolve()
                self.assertIn(str(made), self.checkouts())
                self.assertEqual(self.rig.git("-C", str(made), "branch", "--show-current"), name)

    def test_every_other_git_call_of_a_seat_runs_git_as_typed(self):
        done = self.git("rev-parse", "--show-toplevel")
        self.assertEqual((done.code, done.out, done.err), (0, f"{self.rig.path}\n", ""))
        done = self.git("worktree", "list")
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue(done.out.startswith(f"{self.rig.path} "), done.out)

    def test_a_worker_and_a_command_of_no_seat_may_make_a_checkout_in_code(self):
        for name, seat, env in (("worker", "acme", {"AK_RUN_ROLE": "worker"}),
                                ("seatless", None, None)):
            with self.subTest(name):
                done = self.git("worktree", "add", "-q", "-b", name, f"../acme-{name}",
                                seat=seat, env=env)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertIn(str(self.code / f"acme-{name}"), self.checkouts())


if __name__ == "__main__":
    unittest.main()
