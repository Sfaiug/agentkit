"""A seat's OpenCode is started with its sidebar hidden, so its screen stays one ak reads."""

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
from agentkit import config

NAME = "OPENCODE_CLI_CONFIG_CONTENT"
HIDDEN = {"session": {"sidebar": "hide"}}


class OpenCodeSeatHidesItsSidebar(unittest.TestCase):
    def handed(self, own=None):
        """What the seat's command line hands a fake `opencode` in that variable, where the
        launch was started with `own` in it."""
        with tempfile.TemporaryDirectory() as temp:
            bin_dir, rulebook = Path(temp) / "bin", Path(temp) / "rules.md"
            bin_dir.mkdir()
            rulebook.write_text("Follow the owner's task.\n")
            binary = bin_dir / "opencode"
            binary.write_text(f'#!/bin/sh\nprintf "%s\\n" "${NAME}"\n')
            binary.chmod(0o755)
            env = {"HOME": temp, "PATH": f"{bin_dir}:/usr/bin:/bin",
                   "AGENTKIT_RULEBOOK": str(rulebook), "LC_ALL": "C",
                   **({} if own is None else {NAME: own})}
            command = subprocess.run(
                [str(REPO / "adapters/opencode.sh"), "interactive", "acme/flash", "high"],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(command.returncode, 0, command.stderr)
            launched = subprocess.run(shlex.split(command.stdout), env=env,
                                      stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, timeout=10)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            return json.loads(launched.stdout)

    def test_the_seats_command_line_hands_opencode_a_hidden_sidebar(self):
        self.assertEqual(self.handed(), HIDDEN)

    def test_the_settings_the_launch_was_started_with_stand_beside_it(self):
        # key by key, as OpenCode lays the variable over cli.json; what a shell, JSON or
        # shlex would each read as more than text arrives as it was
        theme = {"name": 'it\'s "dusk" \\ $HOME `id` é 漢'}
        own = {"tabs": {"mode": "off"}, "theme": theme,
               "session": {"sidebar": "auto", "scrollbar": True}}
        self.assertEqual(self.handed(json.dumps(own, ensure_ascii=False)),
                         {"tabs": {"mode": "off"}, "theme": theme,
                          "session": {"sidebar": "hide", "scrollbar": True}})

    def test_a_value_that_is_no_json_object_gives_way_to_it(self):
        for own in ("", "[]", "null", '{"tabs": {"mode": "off"},}', "{} {}"):
            with self.subTest(own=own):
                self.assertEqual(self.handed(own), HIDDEN)

    def test_nothing_the_seat_starts_is_handed_it(self):
        with patch.dict(os.environ, {NAME: json.dumps(HIDDEN)}):
            self.assertNotIn(NAME, config.child_env())


if __name__ == "__main__":
    unittest.main()
