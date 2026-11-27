"""A seat's agy is started trusting the folder the seat opens in, so it opens on its prompt."""

import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class AntigravitySeatTrustsItsFolder(unittest.TestCase):
    def test_the_seats_command_line_hands_agy_its_folder_as_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir, folder = Path(temp) / "bin", Path(temp).resolve() / "code" / "acme"
            rulebook = Path(temp) / "state" / "rules.md"
            for made in (bin_dir, folder, rulebook.parent):
                made.mkdir(parents=True)
            rulebook.write_text("Follow the owner's task.\n")
            binary = bin_dir / "agy"
            binary.write_text('#!/bin/sh\nwhile [ $# -gt 1 ]; do\n'
                              '  [ "$1" = --settings ] && printf "%s\\n" "$2"; shift\ndone\n')
            binary.chmod(0o755)
            env = {"HOME": temp, "PATH": f"{bin_dir}:/usr/bin:/bin",
                   "AGENTKIT_RULEBOOK": str(rulebook), "LC_ALL": "C"}
            command = subprocess.run(
                [str(REPO / "adapters/antigravity.sh"), "interactive", "acme-flash", "high"],
                cwd=folder, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(command.returncode, 0, command.stderr)
            launched = subprocess.run(shlex.split(command.stdout), cwd=folder, env=env,
                                      stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, timeout=10)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertEqual(json.loads(launched.stdout)["trustedWorkspaces"], [str(folder)])


if __name__ == "__main__":
    unittest.main()
