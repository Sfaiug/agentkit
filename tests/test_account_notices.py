"""A seat on another subscription's login opens past the notices the usual login answered.

The usual `~/.claude.json` records each answered one-time notice as a top-level `true`
flag; the named login's own file keeps its account, ids, caches and projects. Offline:
a temporary HOME, invented names, the real `account_config`.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
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

    def test_seat_launch_pins_bypass_and_answers_auto_offer_on_either_login(self):
        usual_settings = self.root / ".claude/settings.json"
        named_settings = self.root / f".claude-{ACCOUNT}/settings.json"
        for offer in ({}, {"hasSeenAutoDefaultNudge": False}):
            with self.subTest(offer=offer):
                usual_settings.write_text(json.dumps({
                    "permissions": {"defaultMode": "auto", "allow": ["Read"]},
                    "keep": "usual-keep"}))
                self.usual.write_text(json.dumps({
                    "oauthAccount": {"accountUuid": "usual-uuid"}, "userID": "usual-user",
                    "projects": {"/invented/acme": {"hasTrustDialogAccepted": True}},
                    "keep": 3, **offer}))
                with patch.dict(os.environ, {"AGENTKIT_ACCOUNT": ""}):
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                    account_config()
                    self.assertNotIn("CLAUDE_CONFIG_DIR", os.environ)
                settings = json.loads(usual_settings.read_text())
                self.assertEqual(settings["permissions"]["defaultMode"], "bypassPermissions")
                self.assertEqual(settings["permissions"]["allow"], ["Read"])
                self.assertEqual(settings["keep"], "usual-keep")
                global_data = json.loads(self.usual.read_text())
                self.assertIs(global_data["hasSeenAutoDefaultNudge"], True)
                self.assertEqual(global_data["oauthAccount"], {"accountUuid": "usual-uuid"})
                self.assertEqual(global_data["userID"], "usual-user")
                self.assertEqual(global_data["projects"],
                                 {"/invented/acme": {"hasTrustDialogAccepted": True}})
                self.assertEqual(global_data["keep"], 3)
        for offer in ({}, {"hasSeenAutoDefaultNudge": False}):
            with self.subTest(offer=offer):
                usual_settings.write_text(json.dumps({
                    "permissions": {"defaultMode": "auto", "allow": ["Read"]},
                    "keep": "usual-keep"}))
                self.usual.write_text(json.dumps({"userID": "usual-user"}))
                named_settings.parent.mkdir(parents=True, exist_ok=True)
                named_settings.write_text(json.dumps({
                    "permissions": {"defaultMode": "auto"}, "custom": "named-keep"}))
                self.named.write_text(json.dumps({
                    "oauthAccount": {"accountUuid": "named-uuid"}, "userID": "named-user",
                    "projects": {"/invented/acme": {"hasTrustDialogAccepted": True}},
                    "someCounter": 7, **offer}))
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
                account_config()
                self.assertEqual(os.environ.pop("CLAUDE_CONFIG_DIR"), str(self.named.parent))
                settings = json.loads(named_settings.read_text())
                self.assertEqual(settings["permissions"]["defaultMode"], "bypassPermissions")
                self.assertEqual(settings["permissions"]["allow"], ["Read"])
                self.assertEqual(settings["keep"], "usual-keep")
                self.assertEqual(settings["custom"], "named-keep")
                global_data = json.loads(self.named.read_text())
                self.assertIs(global_data["hasSeenAutoDefaultNudge"], True)
                self.assertEqual(global_data["oauthAccount"], {"accountUuid": "named-uuid"})
                self.assertEqual(global_data["userID"], "named-user")
                self.assertEqual(global_data["projects"]["/invented/acme"],
                                 {"hasTrustDialogAccepted": True})
                self.assertEqual(global_data["someCounter"], 7)
        for account in ("", ACCOUNT):
            proc = subprocess.run(
                [str(REPO / "adapters/claude.sh"), "interactive", "opus", "medium"],
                capture_output=True, text=True, cwd=self.work,
                env={**os.environ, "AGENTKIT_ACCOUNT": account, "HOME": str(self.root)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("--dangerously-skip-permissions", proc.stdout)
            self.assertIn("harness/claude.py", proc.stdout)

    def test_launch_keeps_file_modes_and_survives_launches_side_by_side(self):
        usual_settings = self.root / ".claude/settings.json"
        usual_settings.write_text(json.dumps({"permissions": {"defaultMode": "auto"}}))
        self.usual.write_text(json.dumps({"userID": "usual-user"}))
        for path in (usual_settings, self.usual):
            os.chmod(path, 0o600)
        with patch.dict(os.environ, {"AGENTKIT_ACCOUNT": ""}):
            errors = []
            barrier = threading.Barrier(8)
            def launch():
                try:
                    barrier.wait(timeout=30)
                    account_config()
                except Exception as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=launch) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            self.assertEqual(errors, [])
            self.assertFalse([thread for thread in threads if thread.is_alive()])
        for path in (usual_settings, self.usual):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        settings = json.loads(usual_settings.read_text())
        self.assertEqual(settings["permissions"]["defaultMode"], "bypassPermissions")
        self.assertIs(json.loads(self.usual.read_text())["hasSeenAutoDefaultNudge"], True)
        named_settings = self.root / f".claude-{ACCOUNT}/settings.json"
        named_settings.parent.mkdir(parents=True, exist_ok=True)
        named_settings.write_text(json.dumps({"permissions": {"defaultMode": "auto"}}))
        self.named.write_text(json.dumps({"userID": "named-user"}))
        for path in (named_settings, self.named):
            os.chmod(path, 0o600)
        account_config()
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        for path in (named_settings, self.named):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
