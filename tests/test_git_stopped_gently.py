"""A git ak times out or is interrupted in gets SIGTERM, so it removes its own locks; one that
ignores it is killed.

Offline: a fake `git` on PATH, started by tool_run itself, makes a lock file, removes it on
SIGTERM (or ignores SIGTERM) and otherwise sleeps.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gitcall

GIT = """#!/bin/sh
trap '{on_term}' TERM
echo $$ > "$FAKE_DIR/pid"
touch "$FAKE_DIR/index.lock"
while :; do sleep 0.05; done
"""


class GitStoppedGently(unittest.TestCase):
    def call(self, on_term, interrupt=False):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "git").write_text(GIT.format(on_term=on_term))
            (fake / "git").chmod(0o755)
            env = {"PATH": f"{fake}:{os.environ['PATH']}", "FAKE_DIR": str(fake)}

            def interrupted(proc, timeout=None):
                # Ctrl-C reaches ak once the fake holds its lock
                while not (fake / "index.lock").exists():
                    time.sleep(.01)
                raise KeyboardInterrupt

            with patch.object(gitcall, "TOOL_GRACE", 1), patch.object(
                    subprocess.Popen, "communicate",
                    interrupted if interrupt else subprocess.Popen.communicate):
                try:
                    result = gitcall.tool_run(["git", "status"], timeout=2, env=env)
                except KeyboardInterrupt:
                    result = "interrupted"
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

    def test_an_interrupted_git_removes_its_lock_too(self):
        result, locked, pid = self.call('rm -f "$FAKE_DIR/index.lock"; exit 143', interrupt=True)
        self.assertEqual(result, "interrupted")
        self.assertFalse(locked)
        self.assert_gone(pid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
