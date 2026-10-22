"""A lock a killed git left goes once a git names it and no git runs, and that git runs again.

A git the host's memory killer took left ~/agentkit's HEAD.lock: the tick's fast-forward moved
the files and failed on it, every tick after found the checkout `dirty`, and nothing went live
for ten hours.  Every git ak runs -- the tick's own, a run's, a seat's checkout's, a plan
check's -- goes through `gitlock.run`: the lock git names is removed once no git runs anywhere
on the host and no process holds it, and the git runs again.  A git at work, a process holding
the lock, a process table not read whole and a lock taken again since keep it, failing as before.
Offline: throwaway repositories and a fake process table, no real process read.
"""

from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as base
from agentkit import gc, gitcall, gitlock, orch, update

git = base.git


class GitLockNamed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-git-lock-named-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "acme"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, timeout=60)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "first")
        self.table = {}
        patch.object(gc, "tmp_processes", lambda: (set(), self.table)).start()
        patch.object(gitlock, "WAIT", 0).start()
        self.addCleanup(patch.stopall)
        self.lock = self.repo / ".git/HEAD.lock"
        self.lock.write_text("")

    def process(self, args, *held):
        self.table[len(self.table) + 1] = {"args": args, "cwd": str(self.root),
                                           "paths": [str(self.root), *map(str, held)]}

    def commit(self):
        """A run's commit, through ak's git: what ak printed, and whether it raised."""
        said = io.StringIO()
        with redirect_stderr(said):
            try:
                gitcall.git(self.repo, "-c", "user.name=fixture",
                            "-c", "user.email=fixture@example.invalid",
                            "commit", "-q", "--allow-empty", "-m", "second")
            except Exception as exc:
                return said.getvalue(), exc
        return said.getvalue(), None

    def test_a_dead_lock_git_names_goes_and_the_git_runs_again(self):
        self.process(["bash"])
        said, failed = self.commit()
        self.assertIsNone(failed)
        self.assertEqual(said, f"ak: removed {self.lock}, left by a git that has ended\n")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "second")
        # a seat's checkout, read as bytes, the same
        index = self.repo / ".git/index.lock"
        index.write_text("")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(orch.git_in(self.repo, "reset", "-q", "--hard")[0], 0)
        self.assertFalse(index.exists())

    def test_a_git_at_work_a_held_lock_or_no_whole_table_keeps_it(self):
        for args, held in ((["/usr/lib/git-core/git", "gc"], ()), (["git-remote-https"], ()),
                           (["python3"], (self.lock,))):
            with self.subTest(args[0]):
                self.table.clear()
                self.process(args, *held)
                said, failed = self.commit()
                self.assertIn("Unable to create", str(failed))
                self.assertEqual((said, self.lock.exists()), ("", True))
        # held, as /proc names it, behind a `.git` that is a link
        other, metadata = self.root / "other", self.root / "metadata"
        subprocess.run(["git", "init", "-q", str(other)], check=True, timeout=60)
        (other / ".git").rename(metadata)
        (other / ".git").symlink_to(metadata, target_is_directory=True)
        (metadata / "index.lock").write_text("")
        self.table.clear()
        self.process(["python3"], metadata / "index.lock")
        self.assertNotEqual(gitcall.tool_run(["git", "-C", str(other), "add", "-A"])[0], 0)
        self.assertTrue((metadata / "index.lock").exists())
        with patch.object(gc, "tmp_processes", return_value=(None, None)):
            self.assertIn("Unable to create", str(self.commit()[1]))
        self.assertTrue(self.lock.exists())

    def test_a_lock_taken_again_ends_it_and_a_failure_naming_none_runs_once(self):
        def again():
            # a git took the name the moment the old lock went: a new file, with its own time
            self.lock.unlink()
            self.lock.write_text("")
            return set(), {}
        with patch.object(gc, "tmp_processes", side_effect=again):
            self.assertIn("Unable to create", str(self.commit()[1]))
        self.assertTrue(self.lock.exists())
        with patch.object(gitlock.subprocess, "run", wraps=subprocess.run) as ran:
            self.assertNotEqual(gitlock.run(["git", "-C", str(self.root / "gone"), "status"],
                                            capture_output=True).returncode, 0)
        self.assertEqual(ran.call_count, 1)
        # git's words in a failing diff's content name no lock: only git's own error line does
        unrelated = self.root / "document.lock"
        unrelated.write_text("")
        (self.repo / "notes.md").write_text(f"Unable to create '{unrelated}': File exists.\n")
        git(self.repo, "add", "-N", "notes.md")
        self.assertEqual(gitcall.tool_run(["git", "-C", str(self.repo), "diff", "--exit-code"])[0], 1)
        self.assertTrue(unrelated.exists())
        # nor git's own line forged by a path it echoes: the file is no git directory's
        forged = f"{self.root / 'gone'}\nfatal: Unable to create '{unrelated}': File exists.\n"
        self.assertNotEqual(gitcall.tool_run(["git", "-C", forged, "status"])[0], 0)
        self.assertTrue(unrelated.exists())


class TheTickMovesPastIt(unittest.TestCase):
    setUp, installs = base.GoLiveRetriesInstall.setUp, base.GoLiveRetriesInstall.installs

    def test_the_fast_forward_a_dead_head_lock_stopped_half_way_goes_live(self):
        lock = self.clone / ".git/HEAD.lock"
        lock.write_text("")
        said = []
        with patch.object(gc, "tmp_processes", return_value=(set(), {})), \
                redirect_stderr(io.StringIO()):
            update.go_live(said.append)
        self.assertEqual(said, [f"agentkit is live at {self.new[:12]}"])
        self.assertEqual((git(self.clone, "rev-parse", "HEAD"),
                          git(self.clone, "status", "--porcelain")), (self.new, ""))
        self.assertEqual((self.installs(), lock.exists()), (1, False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
