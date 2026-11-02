"""A read of an open screen looks at every checkout: git is asked about a worktree once while its
`.git` reads the same, and again once that changes or git said nothing."""

import os
import subprocess
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


if __name__ == "__main__":
    unittest.main()
