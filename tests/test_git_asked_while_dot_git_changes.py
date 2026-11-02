"""A read of an open screen looks at every checkout: git is asked about a worktree once while its
`.git` and what that leads to read the same, and again once they change or git said nothing."""

import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch, parsed


class GitAsked(Sandbox):
    def test_asked_once_until_dot_git_changes_or_git_said_nothing(self):
        acme, fix = config.CODE / "acme", config.CODE / "fix-api"
        for args in (["init", "-q", "-b", "main", str(acme)],
                     ["-C", str(acme), "commit", "-q", "--allow-empty", "-m", "a"],
                     ["-C", str(acme), "worktree", "add", "-q", "-b", "fix-api", str(fix)]):
            subprocess.run(["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com",
                            *args], check=True)
        said = (acme / ".git").resolve(), True
        with patch.object(parsed, "FRESH", 0), \
                patch.object(orch, "git_in", wraps=orch.git_in) as asked:
            self.assertEqual([orch.git_dirs(fix) for _ in range(3)], [said] * 3)
            self.assertEqual(asked.call_count, 1)
            os.utime(fix / ".git")
            asked.side_effect = [(1, b"")]
            self.assertIsNone(orch.git_dirs(fix))
            asked.side_effect = None
            self.assertEqual(orch.git_dirs(fix), said)
            self.assertEqual(asked.call_count, 3)

    def linked(self, first):
        """A repository whose git directory is under `first`, and its worktree, `.git` a link."""
        acme, fix = config.CODE / "acme", config.CODE / "fix-api"
        for args in (["init", "-q", "-b", "main", "--separate-git-dir", str(first / "acme.git"),
                      str(acme)],
                     ["-C", str(acme), "commit", "-q", "--allow-empty", "-m", "a"],
                     ["-C", str(acme), "worktree", "add", "-q", "-b", "fix-api", str(fix)]):
            subprocess.run(["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com",
                            *args], check=True)
        private = Path((fix / ".git").read_text().removeprefix("gitdir: ").strip())
        (fix / ".git").unlink()
        (fix / ".git").symlink_to(private, target_is_directory=True)
        return acme, fix

    def test_a_link_led_elsewhere_is_asked_again(self):
        first, second = self.root / "first", self.root / "second"
        first.mkdir()
        acme, fix = self.linked(first)
        private = (fix / ".git").readlink()
        with patch.object(parsed, "FRESH", 0):
            self.assertEqual(orch.git_dirs(fix), ((first / "acme.git").resolve(), True))
            first.rename(second)
            private.mkdir(parents=True)     # a directory at the old place vouches for nothing
            (acme / ".git").write_text(f"gitdir: {second / 'acme.git'}\n")
            (fix / ".git").unlink()
            (fix / ".git").symlink_to(second / private.relative_to(first), target_is_directory=True)
            self.assertEqual(orch.git_dirs(fix), ((second / "acme.git").resolve(), True))

    def test_a_write_through_the_link_is_asked_again(self):
        first = self.root / "first"
        first.mkdir()
        _, fix = self.linked(first)
        other = self.root / "other.git"
        subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
        with patch.object(parsed, "FRESH", 0):
            self.assertEqual(orch.git_dirs(fix), ((first / "acme.git").resolve(), True))
            private = (fix / ".git").resolve()
            with open(private / "commondir", "w") as named:   # in place: its directory's stat stays
                named.write(f"{other}\n")
            self.assertEqual(orch.git_dirs(fix), (other.resolve(), True))

    def test_git_saying_nothing_of_a_directory_gone_is_heard(self):
        first, gone = self.root / "first", self.root / "gone"
        first.mkdir()
        _, fix = self.linked(first)
        private = (fix / ".git").resolve()
        (fix / ".git").unlink()
        (fix / ".git").write_text(f"gitdir: {private}\n")
        with patch.object(parsed, "FRESH", 0):
            self.assertEqual(orch.git_dirs(fix), ((first / "acme.git").resolve(), True))
            first.rename(gone)      # moved, nothing repaired: git no longer finds a repository
            self.assertIsNone(orch.git_dirs(fix))


if __name__ == "__main__":
    unittest.main()
