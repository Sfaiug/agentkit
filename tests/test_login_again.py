"""A harness's `login again` signs in afresh over a login that still stands.

`login` alone stops at "already logged in", so a login about to end -- or one dead in a way
its files cannot show -- could not be renewed from ak.  `login again` runs the harness's own
sign-in all the same.  Each adapter runs for real on a temporary HOME holding a saved login,
with its harness a fake on PATH that writes down how it was called: no real login.
"""

import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

# harness -> (adapter, the fake program, where its saved login lives, what it holds, the sign-in)
HARNESSES = {
    "claude": ("claude.sh", "claude", ".claude/.credentials.json",
               {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r"}}, ["auth", "login"]),
    "codex": ("codex.sh", "codex", ".codex/auth.json",
              {"tokens": {"access_token": "a"}}, ["login", "--device-auth"]),
    "grok": ("grokbuild.sh", "grok", ".grok/auth.json", {"acme": {"key": "a"}}, ["login"]),
    "muse": ("muse.sh", "muse", ".config/muse/auth.json", {"token": "a"}, ["login"]),
    "antigravity": ("antigravity.sh", "agy", ".gemini/antigravity-cli/antigravity-oauth-token",
                    {"token": {"refresh_token": "r"}}, []),
}

FAKE = """#!/usr/bin/env bash
jq -nc '$ARGS.positional' --args -- "$@" >>"$FAKE_CALLS"
"""


class LoginAgain(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        bin_ = self.home / "fake-bin"
        bin_.mkdir()
        for _, program, *_ in HARNESSES.values():
            (bin_ / program).write_text(FAKE)
            (bin_ / program).chmod(0o755)
        (bin_ / "security").write_text("#!/bin/sh\nexit 1\n")   # no Keychain login to find
        (bin_ / "security").chmod(0o755)
        self.calls = self.home / "calls"
        self.env = {"HOME": str(self.home), "PATH": f"{bin_}:{os.environ['PATH']}",
                    "FAKE_CALLS": str(self.calls), "TERM": "dumb"}

    def login(self, harness, *args):
        """The adapter's `login` at a terminal, and each call of its harness's program."""
        adapter, _, saved, held, _ = HARNESSES[harness]
        (self.home / saved).parent.mkdir(parents=True, exist_ok=True)
        (self.home / saved).write_text(json.dumps(held))
        self.calls.unlink(missing_ok=True)
        primary, secondary = pty.openpty()
        try:
            proc = subprocess.run(["bash", str(REPO / "adapters" / adapter), "login", *args],
                                  stdin=secondary, capture_output=True, text=True,
                                  env=self.env, timeout=30)
        finally:
            os.close(primary)
            os.close(secondary)
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        return proc, [json.loads(call) for call in calls]

    def test_a_login_that_stands_is_left_as_it_is(self):
        for harness in HARNESSES:
            with self.subTest(harness):
                proc, calls = self.login(harness)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("already logged in", proc.stdout)
                self.assertEqual(calls, [])

    def test_b_again_runs_the_harness_sign_in_over_it(self):
        for harness, (*_, sign_in) in HARNESSES.items():
            with self.subTest(harness):
                proc, calls = self.login(harness, "again")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn("already logged in", proc.stdout)
                self.assertEqual(calls, [sign_in])


if __name__ == "__main__":
    unittest.main()
