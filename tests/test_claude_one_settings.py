"""Every Claude login reads one settings file, so a change made on any of them is every session's.

A named login's `settings.json` is a link to the usual login's `~/.claude/settings.json`: a seat's
`/config` on that login writes through it (Claude Code 2.1.292 does), and no launch copies the
usual settings back over it.  The first launch carries over what the login's own file held alone.
Offline: a temporary HOME, invented names, the real `account_config`.
"""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit.harness.claude import account_config


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
        self.usual.write_text(json.dumps({"theme": "dark", "hooks": {"Stop": ["current"]}}))
        own = self.own("harbor")
        own.parent.mkdir()
        own.write_text(json.dumps({"theme": "light", "statusLine": {"command": "acme-status"},
                                   "hooks": {"Stop": ["past-checkout"]}}))
        self.launch("harbor")
        shared = self.read(self.usual)
        self.assertEqual(shared["theme"], "dark")             # the usual login's wins
        self.assertEqual(shared["statusLine"], {"command": "acme-status"})
        self.assertEqual(shared["hooks"], {"Stop": ["current"]})
        self.assertTrue(own.is_symlink())
        self.assertEqual(self.read(own), shared)


if __name__ == "__main__":
    unittest.main()
