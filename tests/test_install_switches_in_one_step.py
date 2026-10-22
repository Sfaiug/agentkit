"""~/agentkit moves between versions in one step: a move cut off anywhere leaves the old one running.

A git killed in a run's worktree left ~/agentkit's HEAD.lock; the tick's fast-forward moved the
files and failed on it, and nothing went live for nineteen hours.  Now each version is checked
out whole beside ~/agentkit and swapped in by one rename(2) (agentkit/versions.py): a cut before
it leaves the old version as it was, one after it leaves the new one whole and its install owed,
and a lock in the old version's git directory is in nobody's way.  The clone a fresh install
made is adopted at its first move, and the worktrees added from it go on working.
test_go_live_retries_install's offline clone, its origin one commit ahead.
"""

import errno
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as base
from agentkit import config, gc, gitcall, retention, update, versions

git = base.git


class InstallSwitchesInOneStep(unittest.TestCase):
    installs = base.GoLiveRetriesInstall.installs

    def setUp(self):
        base.GoLiveRetriesInstall.setUp(self)
        self.old, self.held = git(self.clone, "rev-parse", "HEAD"), set()
        self.wt = config.WT / "fix-api"      # a run's, added from the clone before it was adopted
        git(self.clone, "worktree", "add", "-q", "--detach", str(self.wt))

    def go_live(self):
        said = []
        with patch.object(gc, "tmp_processes", lambda: (self.held, {})):
            update.go_live(said.append)
        return said

    def live(self, commit):
        """~/agentkit whole at `commit`, and the run's worktree still a checkout."""
        self.assertEqual((git(self.clone, "rev-parse", "HEAD"),
                          git(self.clone, "status", "--porcelain")), (commit, ""))
        self.assertEqual(git(self.wt, "status", "--porcelain"), "")

    def push(self, name):
        seed = self.root / "seed"
        (seed / name).write_text(f"{name}\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", name)
        git(seed, "push", "-q", "origin", "main")
        return git(seed, "rev-parse", "HEAD")

    def swapped_out(self):
        return sorted(git(path, "rev-parse", "HEAD")
                      for path in (config.HOME / versions.VERSIONS).iterdir())

    def test_a_lock_a_killed_git_left_is_in_no_move_s_way(self):
        for name in ("HEAD.lock", "index.lock"):
            (self.clone / ".git" / name).write_text("")
        self.assertEqual(self.go_live(), [f"agentkit is live at {self.new[:12]}"])
        self.live(self.new)
        self.assertTrue(versions.owned(self.clone))
        self.assertEqual(self.installs(), 1)
        # a worktree added from the clone is still of agentkit's checkout, wherever its repository went
        self.assertEqual(gitcall.main_checkout(self.wt), self.clone)
        self.assertEqual(retention.common_directory(self.clone), versions.repository().resolve())
        # ak's own, never a session's leftover a week unchanged
        later = time.time() + gc.GC_AGE + 60
        self.assertEqual(list(gc.home_entries(config.HOME, gc.GC_AGE, later, set())), [])
        third = self.push("third")
        gitdir = Path(git(self.clone, "rev-parse", "--absolute-git-dir"))
        (gitdir / "HEAD.lock").write_text("")
        (gitdir / "index.lock").write_text("")
        self.assertEqual(self.go_live(), [f"agentkit is live at {third[:12]}"])
        self.live(third)
        # the clone adopted went once nothing used it; the version before this one waits
        self.assertEqual((self.installs(), self.swapped_out()), (2, [self.new]))

    def test_a_move_cut_off_before_the_swap_leaves_the_old_version_as_it_was(self):
        real = versions.git

        def no_checkout(where, *args):
            return (128, "fatal: killed") if "add" in args else real(where, *args)
        for name, cut in (("checkout", patch.object(versions, "git", no_checkout)),
                          ("swap", patch.object(versions, "exchange",
                                                side_effect=OSError(errno.EXDEV, "cut")))):
            with self.subTest(name), cut:
                self.go_live()
                self.live(self.old)
                self.assertEqual((self.installs(), self.swapped_out()), (0, []))
        self.assertEqual(self.go_live(), [f"agentkit is live at {self.new[:12]}"])
        self.live(self.new)

    def test_a_move_cut_off_after_the_swap_is_live_whole_and_installs_next(self):
        self.go_live()
        third, real, swapped = self.push("third"), versions.exchange, []
        real_repair = versions.repair

        def exchange(one, other):
            real(one, other)
            swapped.append(other)

        def repair(*paths):
            if swapped:
                raise KeyboardInterrupt     # the tick, killed the moment after its swap
            return real_repair(*paths)
        with patch.object(versions, "exchange", exchange), \
                patch.object(versions, "repair", repair), self.assertRaises(KeyboardInterrupt):
            self.go_live()
        self.live(third)
        self.assertEqual(self.installs(), 1)
        self.assertEqual(self.go_live(), [f"agentkit is live at {third[:12]}"])
        self.assertEqual(self.installs(), 2)
        # records git could not put right keep every version, the live one's among them
        with patch.object(versions, "repair", return_value=False), \
                patch.object(gc, "tmp_processes", lambda: (set(), {})):
            versions.tidy(self.clone)
        self.live(third)
        self.assertEqual(self.swapped_out(), [self.new])
        # the two swapped left each other's record of where they are; the next move puts them
        # right before it removes the one swapped out, and the live one is no worse for it
        fourth = self.push("fourth")
        self.assertEqual(self.go_live(), [f"agentkit is live at {fourth[:12]}"])
        self.live(fourth)
        self.assertEqual(self.swapped_out(), [third])

    def test_an_adoption_cut_off_between_its_renames_is_finished(self):
        (self.clone / ".git").rename(versions.repository())
        self.assertEqual(self.go_live(), [f"agentkit is live at {self.new[:12]}"])
        self.live(self.new)

    def test_a_version_in_use_or_with_changes_of_its_own_stays(self):
        self.go_live()
        (self.clone / "mine").write_text("somebody's\n")      # against the owner's rule
        third = self.push("third")
        self.go_live()
        fourth = self.push("fourth")
        self.go_live()
        used = next(path for path in (config.HOME / versions.VERSIONS).iterdir()
                    if git(path, "rev-parse", "HEAD") == third)
        self.held = {str(used.resolve() / "agentkit")}         # a process working in it
        fifth = self.push("fifth")
        self.go_live()
        self.live(fifth)
        self.assertEqual(self.swapped_out(), sorted([self.new, third, fourth]))
        kept = [path for path in (config.HOME / versions.VERSIONS).iterdir()
                if (path / "mine").exists()]
        self.assertEqual([(path / "mine").read_text() for path in kept], ["somebody's\n"])
        # nor one whose changes git could not read
        unread = next(path for path in (config.HOME / versions.VERSIONS).iterdir()
                      if git(path, "rev-parse", "HEAD") == fourth)
        Path(git(unread, "rev-parse", "--absolute-git-dir"), "index").write_bytes(b"cut")
        sixth = self.push("sixth")
        self.go_live()
        self.live(sixth)
        self.assertEqual(self.swapped_out(), sorted([self.new, third, fourth, fifth]))

if __name__ == "__main__":
    unittest.main(verbosity=2)
