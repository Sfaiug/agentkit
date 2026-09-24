"""The leftover sweep never commits a test sandbox. Entirely offline."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run


class NoSandboxCommit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".no-sandbox-commit-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                      "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run.git(self.repo, "init", "-b", "main")
        run.git(self.repo, "config", "user.name", "fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        (self.repo / "app.py").write_text("value = 1\n")
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-m", "baseline")
        self.logs = []

    def head(self):
        return run.git(self.repo, "rev-parse", "HEAD")

    def committed(self):
        out = run.git(self.repo, "show", "--name-only", "--pretty=format:", "HEAD")
        return [line for line in out.splitlines() if line.strip()]

    def write_sandbox(self, dirname, *files):
        for name in files:
            path = self.repo / dirname / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("sandbox\n")

    def sandbox_lines(self):
        return [line for line in self.logs if "untracked sandbox files uncommitted" in line]

    def test_sandbox_directory_is_not_committed(self):
        before = self.head()
        self.write_sandbox(".acceptance-xyz", "stub/git", "stub/ssh")
        self.write_sandbox(".phone-abc", "adapters/echo.sh")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.head(), before)
        self.assertTrue((self.repo / ".acceptance-xyz" / "stub" / "git").exists())

    def test_ignored_file_is_not_committed(self):
        (self.repo / ".gitignore").write_text("*.log\n")
        run.git(self.repo, "add", ".gitignore")
        run.git(self.repo, "commit", "-m", "ignore logs")
        (self.repo / "debug.log").write_text("noise\n")
        (self.repo / "app.py").write_text("value = 2\n")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.committed(), ["app.py"])
        self.assertTrue((self.repo / "debug.log").exists())

    def test_real_untracked_source_file_is_committed(self):
        (self.repo / "feature.py").write_text("new = True\n")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.committed(), ["feature.py"])
        self.assertEqual(self.sandbox_lines(), [])
        self.assertTrue(any("committed uncommitted executor changes" in line
                            for line in self.logs))

    def test_log_line_names_the_count(self):
        self.write_sandbox(".acceptance-one", "a", "b")
        self.write_sandbox(".acceptance-two", "c")
        self.write_sandbox(".phone-three", "d")
        self.write_sandbox(".smoke-four", "e")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(len(self.sandbox_lines()), 1)
        line = self.sandbox_lines()[0]
        self.assertIn("left 5 untracked sandbox files uncommitted", line)
        for name in (".acceptance-one/a", ".acceptance-one/b", ".acceptance-two/c"):
            self.assertIn(name, line)
        self.assertNotIn(".phone-three/d", line)

    def test_check_ignore_skips_a_listed_but_ignored_path(self):
        (self.repo / ".gitignore").write_text("*.log\n")
        run.git(self.repo, "add", ".gitignore")
        run.git(self.repo, "commit", "-m", "ignore logs")
        (self.repo / "debug.log").write_text("noise\n")
        (self.repo / "feature.py").write_text("new = True\n")
        with patch.object(run, "dirty_paths", return_value=["debug.log", "feature.py"]):
            run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.committed(), ["feature.py"])

    def test_sweep_removes_a_killed_tests_sandbox(self):
        self.write_sandbox(".smoke-xyz", "stub/git")
        (self.repo / "feature.py").write_text("new = True\n")
        run.sweep_sandboxes(self.repo, self.logs.append)
        self.assertFalse((self.repo / ".smoke-xyz").exists())
        self.assertTrue((self.repo / "feature.py").exists())
        self.assertTrue(any("removed test sandboxes" in line for line in self.logs))

    def test_ignored_sandbox_is_counted_in_the_log_line(self):
        (self.repo / ".gitignore").write_text(".phone-*\n")
        run.git(self.repo, "add", ".gitignore")
        run.git(self.repo, "commit", "-m", "ignore phone sandboxes")
        before = self.head()
        self.write_sandbox(".phone-xyz", "stub/git", "stub/ssh")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.head(), before)
        self.assertEqual(len(self.sandbox_lines()), 1)
        line = self.sandbox_lines()[0]
        self.assertIn("left 2 untracked sandbox files uncommitted", line)
        self.assertIn(".phone-xyz/stub/git", line)
        self.assertIn(".phone-xyz/stub/ssh", line)

    def test_ignored_sandbox_beside_real_work_commits_and_logs(self):
        (self.repo / ".gitignore").write_text(".smoke-*\n")
        run.git(self.repo, "add", ".gitignore")
        run.git(self.repo, "commit", "-m", "ignore smoke sandboxes")
        self.write_sandbox(".smoke-xyz", "stub/git")
        (self.repo / "feature.py").write_text("new = True\n")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.committed(), ["feature.py"])
        self.assertEqual(len(self.sandbox_lines()), 1)
        self.assertIn("left 1 untracked sandbox files uncommitted", self.sandbox_lines()[0])

    def test_nested_sandbox_shaped_name_still_commits(self):
        path = self.repo / "src" / ".phone-keep" / "note.txt"
        path.parent.mkdir(parents=True)
        path.write_text("real work\n")
        run.commit_leftovers(self.repo, self.logs.append, set())
        self.assertEqual(self.committed(), ["src/.phone-keep/note.txt"])
        self.assertEqual(self.sandbox_lines(), [])


if __name__ == "__main__":
    unittest.main()
