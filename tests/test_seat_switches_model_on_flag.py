"""A Claude seat switches model by itself on a safeguards flag, never pausing for the owner.

Claude Code keeps that answer in the login's user settings (`switchModelsOnFlag`), and
an account login's settings start as a copy of the usual login's: an answer on one must
not undo the other's. Offline: a temporary HOME, the real `account_config` each seat
launch runs, on either login.
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


class SeatSwitchesModelOnFlag(unittest.TestCase):
    def test_every_seat_launch_switches_model_on_a_flag_on_either_login(self):
        for account in ("", "quay"):
            for usual, own in (({}, None), ({"switchModelsOnFlag": False}, None),
                               ({"switchModelsOnFlag": False}, {"switchModelsOnFlag": True})):
                with self.subTest(account=account or "usual", usual=usual, own=own), \
                        tempfile.TemporaryDirectory(prefix="ak-seat-switches-model-") as tmp:
                    home = Path(tmp)
                    (home / ".claude").mkdir()
                    (home / ".claude/settings.json").write_text(json.dumps(usual))
                    login = home / (f".claude-{account}" if account else ".claude")
                    if account and own is not None:
                        login.mkdir()
                        (login / "settings.json").write_text(json.dumps(own))
                    cwd = os.getcwd()
                    try:
                        os.chdir(tmp)
                        with patch.dict(os.environ, {"HOME": tmp, "AGENTKIT_ACCOUNT": account}):
                            os.environ.pop("CLAUDE_CONFIG_DIR", None)
                            account_config()
                    finally:
                        os.chdir(cwd)
                    settings = json.loads((login / "settings.json").read_text())
                    self.assertIs(settings["switchModelsOnFlag"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
