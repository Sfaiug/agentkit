"""An OpenCode seat is started with its sidebar hidden, so its screen reads after a turn."""

from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config  # noqa: E402

NAME, HIDDEN = "OPENCODE_CLI_CONFIG_CONTENT", '{"session":{"sidebar":"hide"}}'


class OpenCodeSeatHidesItsSidebar(unittest.TestCase):
    def launch(self, held):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "opencode").symlink_to("/bin/true")
            env = {"HOME": temp, "PATH": f"{temp}:/usr/bin", "AGENTKIT_RULEBOOK": __file__, **held}
            return subprocess.run([REPO / "adapters/opencode.sh", "interactive", "acme/x", "high"],
                                  cwd=temp, env=env, capture_output=True, text=True, timeout=20)

    def test_the_command_line_hands_opencode_the_hidden_sidebar(self):
        for held in ({}, {NAME: ""}, {NAME: HIDDEN}):    # the last: asked for from inside a seat
            done = self.launch(held)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn(f"{NAME}={HIDDEN}", shlex.split(done.stdout))

    def test_another_document_is_refused_naming_the_owners_file(self):
        done = self.launch({NAME: '{"theme":{"name":"acme"}}'})
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertRegex(done.stderr, f"{NAME}.*~/.config/opencode/cli.json")

    def test_nothing_a_seat_starts_is_handed_it(self):
        self.assertIn(NAME, config.seat_env_names())


if __name__ == "__main__":
    unittest.main()
