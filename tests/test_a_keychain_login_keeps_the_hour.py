"""A renewal in macOS's Keychain changes no file, so nothing follows it to a machine: a Keychain
login goes to one only with the hour left, whatever its harness's turns reread, and renews only once
lapsed, never revoking a copy that still works; a file's goes with any. The real `adapters/claude.sh`
and `machine_turn._lend`, a fake `security` and `claude`, a temporary HOME.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import machine_turn  # noqa: E402

ADAPTER = str(REPO / "adapters/claude.sh")
SECURITY = '#!/bin/sh\nexec cat "$HOME/keychain.json"\n'
CLAUDE = '#!/bin/sh\necho turn >>"$HOME/turns"\n'


class KeychainLogin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-keychain-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bin = self.root / "bin"
        bin.mkdir()
        for name, text in (("security", SECURITY), ("claude", CLAUDE)):
            (bin / name).write_text(text)
            (bin / name).chmod(0o755)
        self.env = {"HOME": str(self.root), "PATH": f"{bin}{os.pathsep}{os.environ['PATH']}"}
        (self.root / ".claude").mkdir()

    def login(self, name, left):
        ends = int(time.time()) + left
        (self.root / name).write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "fixture", "refreshToken": "r", "expiresAt": ends * 1000}}))
        return ends

    def lent(self):
        """Lent as a turn whose harness rereads its login is: to last no time at all."""
        with tempfile.TemporaryDirectory(dir=self.root) as home:
            return machine_turn._lend({"provider": "anthropic"}, ADAPTER, self.env, home, 0)

    def test_a_machine_takes_a_keychain_login_only_with_the_hour_left(self):
        self.login("keychain.json", 1800)
        self.assertEqual(self.lent(), {})
        self.login("keychain.json", 7200)
        self.assertTrue(self.lent())

    def test_a_machine_takes_a_file_s_login_with_any_time_left(self):
        self.login(".claude/.credentials.json", 1800)    # no keychain.json: `security` fails
        self.assertTrue(self.lent())

    def test_a_check_is_told_when_the_keychain_login_really_lapses(self):
        ends = self.login("keychain.json", 1800)
        with tempfile.TemporaryDirectory(dir=self.root) as home:
            done = subprocess.run(["bash", ADAPTER, "lend", home], env=self.env, text=True,
                                  capture_output=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout), (0, f"{ends}\n"))

    def test_a_keychain_login_near_its_end_is_left_until_it_lapses(self):
        for left, renewed in ((200, False), (-60, True)):
            with self.subTest(left=left):
                (self.root / "turns").unlink(missing_ok=True)
                self.login("keychain.json", left)
                subprocess.run(["bash", ADAPTER, "auth", "seat"], env=self.env, text=True,
                               capture_output=True, timeout=60)
                self.assertEqual((self.root / "turns").exists(), renewed)


if __name__ == "__main__":
    unittest.main()
