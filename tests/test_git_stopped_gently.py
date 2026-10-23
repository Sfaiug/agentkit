"""A git ak times out gets SIGTERM, so it removes its own locks; one that ignores it is killed.

Offline: a fake `git` on PATH, started by tool_run itself, makes a lock file, removes it on
SIGTERM (or ignores SIGTERM) and otherwise sleeps.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall

GIT = """#!/bin/sh
echo $$ > "$FAKE_DIR/pid"
touch "$FAKE_DIR/index.lock"
trap '{on_term}' TERM
while :; do sleep 0.05; done
"""


class GitStoppedGently(unittest.TestCase):
    def call(self, on_term):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "git").write_text(GIT.format(on_term=on_term))
            (fake / "git").chmod(0o755)
            env = {"PATH": f"{fake}:{os.environ['PATH']}", "FAKE_DIR": str(fake)}
            with patch.object(gitcall, "TOOL_GRACE", 1):
                result = gitcall.tool_run(["git", "status"], timeout=2, env=env)
            pid = int((fake / "pid").read_text())
            return result, (fake / "index.lock").exists(), pid

    def assert_gone(self, pid):
        # tool_run reaped its child, so nothing answers on its pid any more
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a_timed_out_git_removes_its_lock(self):
        result, locked, pid = self.call('rm -f "$FAKE_DIR/index.lock"; exit 143')
        self.assertFalse(locked)
        self.assert_gone(pid)
        self.assertIsNone(result[0])
        self.assertIn("was killed after 2s", result[2])

    def test_a_git_ignoring_sigterm_is_killed_when_the_grace_ends(self):
        result, locked, pid = self.call("")
        self.assertTrue(locked)
        self.assert_gone(pid)
        self.assertEqual(result, (None, "", "`git status` was killed after 2s: "
                                            "the remote did not answer"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
