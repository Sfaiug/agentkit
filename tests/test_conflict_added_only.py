"""The index's conflicting hunks decide added_only, without touching the worktree."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall, roundloop


class AddedOnly(unittest.TestCase):
    def test_all_hunks_need_an_empty_base_and_missing_stages_are_not_additions(self):
        middle = b"".join(f"line {n}\n".encode() for n in range(10))
        cases = (
            (b"base\n", b"base\nleft\n", b"base\nright\n", 1),
            (b"base\n", b"left\n", b"right\n", 0),
            (None, b"left\n", b"right\n", 0),
            (b"base\n", None, b"right\n", 0),
            (b"base\n", b"left\n", None, 0),
            (b"=======\n", b"left\n", b"right\n", 0),
            (b"\0base", b"\0left", b"\0right", 0),
            (middle, b"left\n" + middle + b"left\n",
             b"right\n" + middle + b"right\n", 1),
            (b"base\n" + middle, b"left\n" + middle + b"left\n",
             b"right\n" + middle + b"right\n", 0),
            (b"base\n" + middle, b"edit\n" + middle + b"left\n",
             b"base\n" + middle + b"right\n", 1),
        )
        with tempfile.TemporaryDirectory(prefix=".ak-test-added-only-", dir=REPO) as root:
            env = {"PATH": os.defpath, "HOME": root, "GIT_CONFIG_NOSYSTEM": "1"}

            def git(*args, input=None):
                return subprocess.run(["git", *args], cwd=root, env=env, input=input,
                                      capture_output=True, check=True).stdout

            git("init", "-q")
            worktree = Path(root) / "file name.txt"
            worktree.write_bytes(b"the fixer's unfinished work\n")
            with patch.object(gitcall, "tool_env", return_value=env):
                for base, left, right, expected in cases:
                    with self.subTest(base=base, left=left, right=right):
                        git("read-tree", "--empty")
                        entries = []
                        for n, text in enumerate((base, left, right), 1):
                            if text is not None:
                                blob = git("hash-object", "-w", "--stdin", input=text).strip()
                                entries.append(b"100644 " + blob + f" {n}\tfile name.txt\n".encode())
                        git("update-index", "--index-info", input=b"".join(entries))
                        before = git("ls-files", "--stage")
                        self.assertEqual(roundloop.conflict_added_only(root, worktree.name), expected)
                        self.assertEqual(git("ls-files", "--stage"), before)
                        self.assertEqual(worktree.read_bytes(), b"the fixer's unfinished work\n")


if __name__ == "__main__":
    unittest.main()
