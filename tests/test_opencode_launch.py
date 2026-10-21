"""The printed seat command finds OpenCode outside the adapter's private PATH."""

from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class OpenCodeLaunch(unittest.TestCase):
    def test_a_seat_launches_the_installers_binary_or_the_paths_override(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home with spaces"
            installed = home / ".opencode/bin"
            override = home / "chosen bin"
            rulebook = Path(temp) / "rules.md"
            rulebook.write_text("Follow the owner's task.\n")
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin",
                   "AGENTKIT_RULEBOOK": str(rulebook)}
            for directory, label in ((installed, "installed"), (override, "override")):
                with self.subTest(label=label):
                    directory.mkdir(parents=True)
                    binary = directory / "opencode"
                    binary.write_text(f'#!/bin/sh\nprintf "%s\\n" {label} "$@"\n')
                    binary.chmod(0o755)
                    if directory == override:
                        env["PATH"] = f"{directory}:{env['PATH']}"
                    command = subprocess.run(
                        [str(REPO / "adapters/opencode.sh"), "interactive", "acme/flash", "high"],
                        env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(command.returncode, 0, command.stderr)
                    launched = subprocess.run(shlex.split(command.stdout), env=env,
                                              stdin=subprocess.DEVNULL, capture_output=True,
                                              text=True, timeout=10)
                    self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
                    self.assertEqual(launched.stdout.splitlines(), [label, "--standalone", "--auto"])


if __name__ == "__main__":
    unittest.main()
