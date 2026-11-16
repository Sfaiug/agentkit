"""Importing agentkit inside a seat starts no git.

`agentkit.browser` once rendered its usage as it was imported, and a seat's help reads its
project's numbers from git (`config.policy`): git calls in every hook and `ak` a seat ran.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class ASeatsImportRunsNoGit(unittest.TestCase):
    def test_importing_what_a_seat_s_hook_imports_calls_no_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, calls = Path(tmp) / "home", Path(tmp) / "calls"
            state, tools = home / ".agentkit" / "state", Path(tmp) / "bin"
            state.mkdir(parents=True)
            tools.mkdir()
            (state / "session-acme.json").write_text(json.dumps(
                {"name": "acme", "cwd": tmp, "repo": tmp, "orchestrator": "opus"}))
            git = tools / "git"
            git.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexit 1\n')
            git.chmod(0o755)
            env = {**os.environ, "HOME": str(home), "AGENTKIT_SESSION": "acme",
                   "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}
            def started(code):
                done = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                said = calls.read_text() if calls.exists() else ""
                calls.unlink(missing_ok=True)
                return said

            self.assertEqual(started("from agentkit import browser, watch"), "")
            # the usage it no longer renders there does read git: the line above would catch it
            self.assertTrue(started(
                "from agentkit import command_help; command_help.render('browser')"))


if __name__ == "__main__":
    unittest.main()
