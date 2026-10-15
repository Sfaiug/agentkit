"""Every Claude login reads one settings file, so a change made on any of them is every session's.

A named login's `settings.json` is a link to the usual login's `~/.claude/settings.json`: a seat's
`/config` on that login writes through it (Claude Code 2.1.292 does), and no launch copies the
usual settings back over it.  The first launch carries over what the login's own file held alone,
and a worker's turn on that login (`adapters/claude.sh run`) links it as a seat's launch does.
Offline: a temporary HOME, invented names, the real `account_config` and adapter, a fake `claude`.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit.harness import claude
from agentkit.harness.claude import account_config

# A worker's `claude -p`: keeps the settings its login reads where the test looks
FAKE = """#!/usr/bin/env python3
import os, shutil, sys
sys.stdin.read()
shutil.copy(os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "settings.json"), os.environ["ACME_READ"])
"""


class OneSettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-claude-one-settings-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)
        stack = patch.dict(os.environ, {"HOME": str(self.root)})
        stack.start()
        self.addCleanup(stack.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.usual = self.root / ".claude/settings.json"
        self.usual.parent.mkdir()

    def own(self, account):
        return self.root / f".claude-{account}/settings.json"

    def launch(self, account):
        with patch.dict(os.environ, {"AGENTKIT_ACCOUNT": account}):
            account_config()
            os.environ.pop("CLAUDE_CONFIG_DIR", None)

    def read(self, path):
        return json.loads(path.read_text())

    def test_a_change_made_on_one_login_is_every_login_s_and_survives_their_launches(self):
        self.usual.write_text(json.dumps({"autoCompactWindow": 1000000, "theme": "dark"}))
        self.launch("harbor")
        self.launch("quay")
        # /config on the harbor login writes its own path
        own = self.own("harbor")
        own.write_text(json.dumps({**self.read(own), "autoCompactWindow": 300000}))
        for account in ("harbor", "quay", ""):
            self.launch(account)
        for path in (self.usual, self.own("harbor"), self.own("quay")):
            self.assertEqual(self.read(path)["autoCompactWindow"], 300000)
            self.assertEqual(self.read(path)["permissions"]["defaultMode"], "bypassPermissions")
        self.assertTrue(self.own("harbor").is_symlink())
        self.assertEqual(self.own("quay").resolve(), self.usual.resolve())

    def test_what_a_login_s_own_file_held_alone_is_carried_over_once(self):
        held = {"theme": "light", "statusLine": {"command": "acme-status"},
                "hooks": {"Stop": ["past-checkout"]}}
        # a file of its own, or a link to one elsewhere: a dotfiles checkout's
        for account, elsewhere in (("harbor", None), ("quay", self.root / "dotfiles/claude.json")):
            with self.subTest(account=account):
                self.usual.write_text(json.dumps({"theme": "dark", "hooks": {"Stop": ["current"]}}))
                own = self.own(account)
                own.parent.mkdir()
                if elsewhere:
                    elsewhere.parent.mkdir()
                    elsewhere.write_text(json.dumps(held))
                    own.symlink_to(elsewhere)
                else:
                    own.write_text(json.dumps(held))
                self.launch(account)
                shared = self.read(self.usual)
                self.assertEqual(shared["theme"], "dark")             # the usual login's wins
                self.assertEqual(shared["statusLine"], {"command": "acme-status"})
                self.assertEqual(shared["hooks"], {"Stop": ["current"]})
                self.assertEqual(own.resolve(), self.usual.resolve())

    def test_a_launch_puts_nothing_it_read_back_over_a_change_made_while_it_ran(self):
        self.usual.write_text(json.dumps({"autoCompactWindow": 1000000}))
        write = claude._write
        for window, account in ((300000, "harbor"), (250000, "")):
            with self.subTest(account=account):
                self.launch(account)

                def configured(path, data):
                    # a running session's /config, while this launch writes its global config
                    if path.name == ".claude.json":
                        self.usual.write_text(json.dumps(
                            {**self.read(self.usual), "autoCompactWindow": window}))
                    write(path, data)
                with patch.object(claude, "_write", side_effect=configured):
                    self.launch(account)
                self.assertEqual(self.read(self.usual)["autoCompactWindow"], window)

    def test_a_worker_turn_on_a_named_login_reads_the_one_file(self):
        self.usual.write_text(json.dumps({"autoCompactWindow": 300000}))
        own = self.own("harbor")
        own.parent.mkdir()
        own.write_text(json.dumps({"autoCompactWindow": 1000000, "theme": "light"}))
        fake = self.root / "bin/claude"
        fake.parent.mkdir()
        fake.write_text(FAKE)
        fake.chmod(0o755)
        prompt, read = self.root / "prompt.md", self.root / "read.json"
        prompt.write_text("acme task\n")
        env = {**os.environ, "AGENTKIT_ACCOUNT": "harbor", "ACME_READ": str(read),
               "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}"}
        subprocess.run([str(REPO / "adapters/claude.sh"), "run", "opus", "high", str(self.root),
                        str(prompt), str(self.root / "out")], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, check=True, timeout=60)
        self.assertEqual(self.read(read)["autoCompactWindow"], 300000)
        self.assertEqual(self.read(read)["theme"], "light")
        self.assertEqual(own.resolve(), self.usual.resolve())

if __name__ == "__main__":
    unittest.main()
