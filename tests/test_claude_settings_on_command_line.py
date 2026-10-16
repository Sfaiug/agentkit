"""What every Claude session ak starts runs with rides its command line; the settings file stays the owner's.

Bypass permissions, Claude Code's own messages between sessions refused (seats never message
one another) and a model switch on a safeguards flag instead of a dialog come in `--settings`,
which outranks the login's settings file, on a seat and on a worker turn, on either login.  So
an accepted auto-mode offer or a hand edit in that file cannot undo them, and a seat's launch
leaves the file as it found it.  Offline: a temporary HOME, the real adapter with a fake
`claude` first on PATH that writes down how it was started, the real `account_config`.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit.harness.claude import account_config

PINS = {"permissions": {"defaultMode": "bypassPermissions"}, "crossSessionInbound": "refuse",
        "switchModelsOnFlag": True}
# what an accepted auto-mode offer, a safeguards dialog answer and a hand edit leave behind
UNDONE = {"permissions": {"defaultMode": "auto", "allow": ["Read"]},
          "crossSessionInbound": "accept", "switchModelsOnFlag": False, "theme": "dark"}
FAKE = """#!/bin/sh
python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >"$AK_TEST_STARTED"
"""


def told(argv):
    """The settings a command line hands Claude Code."""
    return json.loads(argv[argv.index("--settings") + 1])


class SettingsOnCommandLine(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-claude-settings-flag-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.settings = self.root / ".claude/settings.json"
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps(UNDONE))
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "claude").write_text(FAKE)
        (bin_dir / "claude").chmod(0o755)
        rulebook = self.root / "rulebook.md"
        rulebook.write_text("rules\n")
        self.started = self.root / "started"
        self.env = {**os.environ, "HOME": str(self.root), "AK_TEST_STARTED": str(self.started),
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "AGENTKIT_RULEBOOK": str(rulebook), "AGENTKIT_CLAUDE_CHECKED": "1"}
        self.env.pop("CLAUDE_CONFIG_DIR", None)

    def adapter(self, account, *args):
        done = subprocess.run([str(REPO / "adapters/claude.sh"), *args], capture_output=True,
                              text=True, timeout=60, cwd=self.root,
                              env={**self.env, "AGENTKIT_ACCOUNT": account})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_seats_and_worker_turns_are_told_on_either_login(self):
        workspace, prompt, out = self.root / "ws", self.root / "prompt.md", self.root / "out"
        workspace.mkdir()
        prompt.write_text("hi\n")
        for account in ("", "quay"):
            with self.subTest(account=account or "usual"):
                seat = shlex.split(self.adapter(account, "interactive", "m-1", "high"))
                self.assertEqual(told(seat), PINS)
                self.adapter(account, "run", "m-1", "high", str(workspace), str(prompt), str(out))
                self.assertEqual(told(json.loads(self.started.read_text())), PINS)

    def test_a_seat_launch_leaves_the_settings_file_as_it_found_it(self):
        before = self.settings.read_bytes()
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.root)
        with patch.dict(os.environ, {"HOME": str(self.root), "AGENTKIT_ACCOUNT": ""}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            account_config()
        self.assertEqual(self.settings.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
