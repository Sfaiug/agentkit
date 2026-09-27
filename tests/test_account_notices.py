"""A seat on another subscription's login opens past the notices the usual login answered.

The usual `~/.claude.json` records each answered one-time notice as a top-level `true`
flag; the named login's own file keeps its account, ids, caches and projects. Offline:
a temporary HOME, invented names, the real `account_config`.
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

ACCOUNT = "harbor"


class AccountNotices(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-account-notices-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.work)
        self.stack = patch.dict(os.environ, {"HOME": str(self.root),
                                             "AGENTKIT_ACCOUNT": ACCOUNT})
        self.stack.start()
        self.addCleanup(self.stack.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        (self.root / ".claude").mkdir()
        (self.root / ".claude/settings.json").write_text("{}")
        self.usual = self.root / ".claude.json"
        self.named = self.root / f".claude-{ACCOUNT}" / ".claude.json"

    def arrange(self, usual, named):
        self.usual.write_text(json.dumps(usual))
        self.named.parent.mkdir(parents=True, exist_ok=True)
        self.named.write_text(json.dumps(named))
        account_config()
        return json.loads(self.named.read_text())

    def test_true_flags_carry_over_when_missing_or_false(self):
        usual = {"hasSeenAutoDefaultNudge": True, "hasSeenHarborNotice": True}
        for start in ({}, {"hasSeenAutoDefaultNudge": False, "hasSeenHarborNotice": False}):
            with self.subTest(start=start):
                after = self.arrange(usual, dict(start))
                self.assertIs(after["hasSeenAutoDefaultNudge"], True)
                self.assertIs(after["hasSeenHarborNotice"], True)

    def test_named_login_keeps_itself_and_ignores_what_is_not_a_true_flag(self):
        usual = {"hasSeenAutoDefaultNudge": True, "hasSeenHarborNotice": True,
                 "oauthAccount": {"accountUuid": "usual-uuid"}, "userID": "usual-user",
                 "projects": {"/usual/acme": {"hasTrustDialogAccepted": True}},
                 "someCounter": 3, "someName": "usual", "someFlag": False,
                 "nested": {"inner": True}, "nothing": None, "one": 1, "emptyList": []}
        named = {"oauthAccount": {"accountUuid": "named-uuid"}, "userID": "named-user",
                 "projects": {"/invented/acme": {"hasTrustDialogAccepted": True}},
                 "someCounter": 7}
        after = self.arrange(usual, named)
        self.assertIs(after["hasSeenAutoDefaultNudge"], True)
        self.assertIs(after["hasSeenHarborNotice"], True)
        self.assertEqual(after["oauthAccount"], {"accountUuid": "named-uuid"})
        self.assertEqual(after["userID"], "named-user")
        self.assertEqual(after["projects"]["/invented/acme"], {"hasTrustDialogAccepted": True})
        self.assertNotIn("/usual/acme", after["projects"])
        self.assertTrue(after["projects"][str(self.work.resolve())]["hasTrustDialogAccepted"])
        self.assertEqual(after["someCounter"], 7)
        for key in ("someName", "someFlag", "nested", "nothing", "one", "emptyList"):
            self.assertNotIn(key, after)


if __name__ == "__main__":
    unittest.main()
