"""A seat's Codex is started with its startup update question off, so it opens on its prompt."""

from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class CodexSeatAsksNoUpdate(unittest.TestCase):
    def test_the_seats_command_line_turns_the_startup_update_check_off(self):
        with tempfile.TemporaryDirectory() as temp:
            rulebook = Path(temp) / "rules.md"
            rulebook.write_text("Follow the owner's task.\n")
            env = {"HOME": temp, "PATH": "/usr/bin:/bin", "AGENTKIT_RULEBOOK": str(rulebook),
                   "LC_ALL": "C"}
            command = subprocess.run(
                [str(REPO / "adapters/codex.sh"), "interactive", "acme-model", "high"],
                cwd=temp, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(command.returncode, 0, command.stderr)
            words = shlex.split(command.stdout)
            codex = words[words.index("codex"):]
            options = list(zip(codex, codex[1:]))
            self.assertIn(("-c", "check_for_update_on_startup=false"), options, command.stdout)


if __name__ == "__main__":
    unittest.main()
