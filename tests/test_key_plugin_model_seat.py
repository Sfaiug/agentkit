"""A model ak has never heard of opens a seat once it is an adapter, its toml and a config.toml
entry: `ak orch NAME --model M --dry-run` says what it would start, the harness's own command
line, and starts and records nothing.

The owner's rule is that models are plugins they mark, never names in code, so a harness added
tomorrow must open a seat the way the shipped ones do.  The harness here is named for this test
alone: a copy of tests/fixtures/adapters/echo.sh and echo.toml whose `interactive` names the
model and effort it was given.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REPO, Home

ECHO = REPO / "tests/fixtures/adapters"
SHELL_LINE = """printf '%s\\n' "${SHELL:-/bin/sh}\""""
TUI_LINE = """printf 'acme-tui --model %s --effort %s\\n' "$2" "$3\""""


class PluginModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        adapters = cls.home.root / "plugins"
        adapters.mkdir()
        script = (ECHO / "echo.sh").read_text()
        assert SHELL_LINE in script, "echo.sh's `interactive` line moved"
        (adapters / "acme.sh").write_text(script.replace(SHELL_LINE, TUI_LINE))
        (adapters / "acme.sh").chmod(0o755)
        shutil.copy(ECHO / "echo.toml", adapters / "acme.toml")
        cls.home.env["AGENTKIT_ADAPTER_DIR"] = str(adapters)
        akconfig.write(cls.home, {"beta": {"harness": "acme", "model": "beta-1",
                                           "effort": "low", "provider": "acme"}})
        cls.done = cls.home.ak("orch", "beta-seat", "--model", "beta", "--dry-run", input="")

    def test_the_dry_run_names_the_model_and_the_new_seat(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        lines = self.done.out.splitlines()
        self.assertIn("orch: beta (--model)", lines)
        self.assertIn(f"session beta-seat in {self.home.path} (new)", lines)

    def test_the_last_line_is_the_harness_command_under_an_empty_account(self):
        command = shlex.split(self.done.out.splitlines()[-1])
        self.assertEqual(command[0], "env", command)
        settings = [word for word in command[1:] if "=" in word]
        self.assertIn("AGENTKIT_ACCOUNT=", settings)
        # what the adapter's `interactive` printed, told the model's id and effort
        self.assertEqual(command[-5:], ["acme-tui", "--model", "beta-1", "--effort", "low"])

    def test_a_dry_run_starts_and_records_no_seat(self):
        self.assertFalse((self.home.path / ".agentkit/state/session-beta-seat.json").exists())
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=beta-seat").code, 0)


if __name__ == "__main__":
    unittest.main()
