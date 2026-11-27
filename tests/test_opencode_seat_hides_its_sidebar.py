"""A seat's OpenCode is started with its sidebar hidden, so its screen stays one ak reads."""

import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class OpenCodeSeatHidesItsSidebar(unittest.TestCase):
    def test_the_seats_command_line_hands_opencode_a_hidden_sidebar(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir, rulebook = Path(temp) / "bin", Path(temp) / "rules.md"
            bin_dir.mkdir()
            rulebook.write_text("Follow the owner's task.\n")
            binary = bin_dir / "opencode"
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$OPENCODE_CLI_CONFIG_CONTENT"\n')
            binary.chmod(0o755)
            env = {"HOME": temp, "PATH": f"{bin_dir}:/usr/bin:/bin",
                   "AGENTKIT_RULEBOOK": str(rulebook), "LC_ALL": "C"}
            command = subprocess.run(
                [str(REPO / "adapters/opencode.sh"), "interactive", "acme/flash", "high"],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(command.returncode, 0, command.stderr)
            launched = subprocess.run(shlex.split(command.stdout), env=env,
                                      stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, timeout=10)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertEqual(json.loads(launched.stdout), {"session": {"sidebar": "hide"}})


if __name__ == "__main__":
    unittest.main()
