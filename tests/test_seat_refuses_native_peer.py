"""A Claude seat refuses Claude Code's own messages from other sessions; seats never message one another.

The launch writes it into the login's user settings, which Claude Code reads again when
they change, so a seat opened before the launch refuses them too. Offline: a temporary
HOME, the real `account_config` each seat launch runs, on either login.
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


class SeatRefusesNativePeer(unittest.TestCase):
    def test_every_seat_launch_refuses_cross_session_messages_in_its_logins_settings(self):
        for account in ("", "quay"):
            for start in ({}, {"crossSessionInbound": "accept", "theme": "dark"}):
                with self.subTest(account=account or "usual", start=start), \
                        tempfile.TemporaryDirectory(prefix="ak-seat-refuses-peer-") as tmp:
                    home = Path(tmp)
                    (home / ".claude").mkdir()
                    (home / ".claude/settings.json").write_text(json.dumps(start))
                    cwd = os.getcwd()
                    try:
                        os.chdir(tmp)
                        with patch.dict(os.environ, {"HOME": tmp, "AGENTKIT_ACCOUNT": account}):
                            os.environ.pop("CLAUDE_CONFIG_DIR", None)
                            account_config()
                    finally:
                        os.chdir(cwd)
                    login = home / (f".claude-{account}" if account else ".claude")
                    settings = json.loads((login / "settings.json").read_text())
                    self.assertEqual(settings["crossSessionInbound"], "refuse")
                    self.assertEqual(settings.get("theme"), start.get("theme"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
