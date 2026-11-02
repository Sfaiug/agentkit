"""A read of an open screen looks at every checkout: git is asked about a worktree once while its
`.git` leads where it led, and again once that changes or git said nothing."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch


class GitAsked(Sandbox):
    def worktree(self, *init):
        """acme and its worktree fix-api, `init` added to acme's `git init`."""
        acme, fix = config.CODE / "acme", config.CODE / "fix-api"
        for args in (["init", "-q", "-b", "main", *init, str(acme)],
                     ["-C", str(acme), "commit", "-q", "--allow-empty", "-m", "a"],
                     ["-C", str(acme), "worktree", "add", "-q", "-b", "fix-api", str(fix)]):
            subprocess.run(["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com",
                            *args], check=True)
        return acme, fix

    def elsewhere(self):
        """acme's git directory outside it, its worktree, and that worktree's git directory."""
        first = self.root / "first.git"
        _, fix = self.worktree("--separate-git-dir", str(first))
        return first, fix, Path((fix / ".git").read_text().removeprefix("gitdir: ").strip())

    def test_asked_once_until_git_says_something(self):
        acme, fix = self.worktree()
        said = (acme / ".git").resolve(), True
        with patch.object(orch, "git_in", wraps=orch.git_in) as asked:
            asked.side_effect = [(1, b"")]
            self.assertIsNone(orch.git_dirs(fix))
            asked.side_effect = None
            self.assertEqual([orch.git_dirs(fix) for _ in range(3)], [said] * 3)
            self.assertEqual(asked.call_count, 2)

    def test_a_link_led_elsewhere_is_asked_again(self):
        first, fix, private = self.elsewhere()
        second = self.root / "second.git"
        (fix / ".git").unlink()
        (fix / ".git").symlink_to(private, target_is_directory=True)
        self.assertEqual(orch.git_dirs(fix), (first.resolve(), True))
        first.rename(second)
        private.mkdir(parents=True)     # a directory at the old place vouches for nothing
        (fix / ".git").unlink()
        (fix / ".git").symlink_to(second / private.relative_to(first), target_is_directory=True)
        self.assertEqual(orch.git_dirs(fix), (second.resolve(), True))

    def named_link_led_elsewhere(self, name):
        """`git_dirs` follows a link to another repository once `name` has git read it."""
        first, fix, private = self.elsewhere()
        second, alias = self.root / "second.git", self.root / "named.git"
        alias.symlink_to(first, target_is_directory=True)
        name(fix, private, private.relative_to(first), alias)
        self.assertEqual(orch.git_dirs(fix), (first.resolve(), True))
        shutil.copytree(first, second, symlinks=True)
        alias.unlink()
        alias.symlink_to(second, target_is_directory=True)
        self.assertEqual(orch.git_dirs(fix), (second.resolve(), True))

    def test_a_link_the_gitfile_names_led_elsewhere_is_asked_again(self):
        self.named_link_led_elsewhere(lambda fix, _, under, alias: (
            (fix / ".git").write_text(f"gitdir: {alias / under}\n")))

    def test_a_link_commondir_names_led_elsewhere_is_asked_again(self):
        self.named_link_led_elsewhere(lambda _, private, __, alias: (
            (private / "commondir").write_text(f"{alias}\n")))

    def test_a_commondir_written_in_place_is_asked_again(self):
        first, fix, private = self.elsewhere()
        other = self.root / "other.git"
        subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
        self.assertEqual(orch.git_dirs(fix), (first.resolve(), True))
        (private / "commondir").write_text(f"{other}\n")
        self.assertEqual(orch.git_dirs(fix), (other.resolve(), True))

    def test_git_saying_nothing_of_a_directory_gone_is_heard(self):
        first, fix, _ = self.elsewhere()
        self.assertEqual(orch.git_dirs(fix), (first.resolve(), True))
        first.rename(self.root / "gone.git")    # nothing repaired: git finds no repository
        self.assertIsNone(orch.git_dirs(fix))

    def test_git_saying_nothing_of_a_head_gone_is_heard(self):
        first, fix, private = self.elsewhere()
        self.assertEqual(orch.git_dirs(fix), (first.resolve(), True))
        (private / "HEAD").unlink()
        self.assertIsNone(orch.git_dirs(fix))

    def test_a_gitfile_holding_a_nul_is_no_repository(self):
        _, fix = self.worktree()
        (fix / ".git").write_bytes(b"gitdir: /no\0where\n")
        self.assertIsNone(orch.git_dirs(fix))


if __name__ == "__main__":
    unittest.main()
