"""A seat's OpenCode is started with its sidebar hidden, so its screen stays one ak reads --
where its pane holds no inline settings of the owner's, which stand as they are."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
NAME = "OPENCODE_CLI_CONFIG_CONTENT"
# stands in for OpenCode: that variable as it was handed it, and as what it starts through
# ak would be handed it in turn, each as bytes whatever the locale reads them as
FAKE = f"""#!{sys.executable}
import json, os, sys
sys.path.insert(0, {str(REPO)!r})
from agentkit import config
print(json.dumps([os.fsencode(env.get({NAME!r}, "")).hex()
                  for env in (os.environ, config.child_env())]))
"""
# what OpenCode reads there that ak cannot: comments and a trailing comma, a setting OpenCode
# refuses, what a shell would read as more than text, and 50 KB, which escaped to ASCII would
# be more than one variable or argument may hold
OWN = ('// tabs off\n{"tabs": {"mode": "off"},}',
       '{"session":{"scrollbar":"yes"}}',
       '{"theme": {"name": "it\'s \\"dusk\\" \\\\ $HOME `id` é 漢"}}',
       json.dumps({"plugins": [{"package": "acme-terminal", "options": {"text": "é" * 25_000}}]},
                  ensure_ascii=False))


class OpenCodeSeatHidesItsSidebar(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        bin_dir, rulebook = Path(temp.name) / "bin", Path(temp.name) / "rules.md"
        bin_dir.mkdir()
        rulebook.write_text("Follow the owner's task.\n")
        (bin_dir / "opencode").write_text(FAKE)
        (bin_dir / "opencode").chmod(0o755)
        self.env = {"HOME": temp.name, "PATH": f"{bin_dir}:/usr/bin:/bin",
                    "AGENTKIT_RULEBOOK": str(rulebook), "LC_ALL": "C"}

    def line(self, **env):
        """The seat's command line, as the adapter prints it with `env` in its environment."""
        command = subprocess.run(
            [str(REPO / "adapters/opencode.sh"), "interactive", "acme/flash", "high"],
            env={**self.env, **env}, capture_output=True, text=True, timeout=10)
        self.assertEqual(command.returncode, 0, command.stderr)
        return command.stdout

    def seat(self, **env):
        """(that variable as the seat's OpenCode is handed it, as what it starts is), in a pane
        whose environment holds `env`."""
        launched = subprocess.run(shlex.split(self.line()), env={**self.env, **env},
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=30)
        self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
        return tuple(bytes.fromhex(value).decode() for value in json.loads(launched.stdout))

    def test_a_pane_holding_none_starts_opencode_with_its_sidebar_hidden(self):
        for env in ({}, {NAME: ""}):
            with self.subTest(env=env):
                handed, passed_on = self.seat(**env)
                self.assertEqual(json.loads(handed), {"session": {"sidebar": "hide"}})
                self.assertEqual(passed_on, "")     # the launch's own goes no further

    def test_a_value_the_pane_holds_stands_as_it_is_and_goes_on(self):
        for own in OWN:
            with self.subTest(own=own[:60]):
                self.assertEqual(self.seat(**{NAME: own}), (own, own))

    def test_the_command_line_holds_nothing_of_the_owners_value(self):
        # neither read nor copied: no process's arguments show it, and none grows by it
        for own in OWN:
            with self.subTest(own=own[:60]):
                self.assertEqual(self.line(**{NAME: own}), self.line())


if __name__ == "__main__":
    unittest.main()
