"""A launch reads Claude's settings in its own process, and the adapter starts no Python.

Claude Code is not started on settings that are not JSON objects, and the launch finds that out
before the pane it would replace is touched.  The adapter started a Python for it on every new
seat, reopen and model switch; now the launch reads them (the plugin's `checked`) and tells the
adapter, which reads them itself only when run on its own.  A temporary HOME, the real adapter,
and a `python3` first on PATH that refuses to run.
"""

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, orch

REFUSING = '#!/bin/sh\necho "a python was started: $*" >&2\nexit 97\n'
ASKED = '#!/bin/sh\n: >"$AK_TEST_ASKED"\necho fake-tui\n'


class CheckedByTheLaunch(Sandbox):
    def setUp(self):
        super().setUp()
        # the usual login: a seat this runs from may be on another
        self.stack.enter_context(patch.dict(os.environ))
        os.environ.pop(config.ACCOUNT_ENV, None)

    def refusing(self):
        """A PATH whose `python3` refuses to run."""
        refusing = self.root / "bin"
        refusing.mkdir()
        (refusing / "python3").write_text(REFUSING)
        (refusing / "python3").chmod(0o755)
        return os.pathsep.join([str(refusing), os.environ["PATH"]])

    def fake_adapter(self):
        """An adapter that writes down that it was asked; the file it writes."""
        adapters, asked = self.root / "adapters", self.root / "asked"
        adapters.mkdir()
        (adapters / "claude.sh").write_text(ASKED)
        (adapters / "claude.sh").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            config.ADAPTER_DIR_ENV: str(adapters), "AK_TEST_ASKED": str(asked)}))
        return asked

    def test_a_claude_seat_s_command_is_built_without_a_second_python(self):
        with patch.dict(os.environ, {"PATH": self.refusing()}):
            cmd, conversation = orch.fresh_command(self.cfg, "opus", seat="acme")
        self.assertTrue(conversation)
        self.assertIn("claude", cmd)

    def test_settings_that_are_not_json_refuse_the_launch_before_its_adapter_is_asked(self):
        asked = self.fake_adapter()
        settings = Path.home() / ".claude/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{not json")
        with self.assertRaises(config.Error) as refused:
            orch.fresh_command(self.cfg, "opus", seat="acme")
        self.assertIn(str(settings), str(refused.exception))
        self.assertFalse(asked.exists())
        # mended, the same launch goes through
        settings.write_text("{}")
        orch.fresh_command(self.cfg, "opus", seat="acme")
        self.assertTrue(asked.exists())

    def test_a_named_login_s_own_config_is_read_for_its_launch_alone(self):
        asked = self.fake_adapter()
        own = Path.home() / ".claude-second/.claude.json"
        own.parent.mkdir(parents=True)
        own.write_text("[]")
        with self.assertRaises(config.Error) as refused:
            orch.fresh_command(self.cfg, "opus", seat="acme", account="second")
        self.assertIn(str(own), str(refused.exception))
        self.assertFalse(asked.exists())
        orch.fresh_command(self.cfg, "opus", seat="acme")
        self.assertTrue(asked.exists())

    def test_the_adapter_run_on_its_own_still_reads_them(self):
        settings = Path.home() / ".claude/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{not json")
        handed = self.root / "handed.md"
        handed.write_text("rules\n")
        line = subprocess.run([str(REPO / "adapters/claude.sh"), "interactive", "opus", "high"],
                              env={**os.environ, config.SESSION_ENV: "acme",
                                   config.RULEBOOK_ENV: str(handed)},
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(line.returncode, 2, line.stdout)
        self.assertIn(str(settings), line.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
