"""A Claude seat's claude gets ak's pinned settings and no other, and a dry run prints that launch.

Every session ak starts runs with three settings whatever the login's own file says: permissions
bypassed, Claude Code's messages from other sessions refused, and a message its safeguards flag
switching the conversation to another model instead of stopping the seat on a dialog.  They come
on the command line, which outranks the login's settings file, so an accepted auto-mode offer or
a hand edit there cannot undo them, and no launch writes them there: a harness's settings are its
own.  ak adds no setting beyond them, and the seat runs the model and effort the config names.
A dry run, which a person or a model may ask for without a terminal, prints that same launch
with the switches that keep Claude's background daemon, its own instruction files and its
memory off.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and a
fake `claude` keeps what it was started with.  This test fails against `/bin/false`.
"""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home

PINS = {"permissions": {"defaultMode": "bypassPermissions"}, "crossSessionInbound": "refuse",
        "switchModelsOnFlag": True}
# What the owner's login says, each against a pin.
LOGIN = '{"permissions": {"defaultMode": "acceptEdits"}, "crossSessionInbound": "allow",\n' \
        ' "switchModelsOnFlag": false, "theme": "dark"}\n'
STARTED = """#!{python}
import json, os, sys, time
with open({part}, "w") as out:
    json.dump({{"argv": sys.argv[1:], "env": dict(os.environ)}}, out)
os.replace({part}, {saw})
time.sleep(600)
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClaudeSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        saw = home.root / "claude-started.json"
        home.fake("claude", STARTED.format(python=sys.executable, saw=repr(str(saw)),
                                           part=repr(f"{saw}.part")))
        akconfig.write(home, {"opus": {"harness": "claude", "model": "claude-acme-7",
                                       "effort": "low"}})
        cls.login = home.write(".claude/settings.json", LOGIN, ago=86400)
        cls.before = (cls.login.read_bytes(), cls.login.stat().st_mtime_ns)
        cls.cwd = home.path / "code" / "acme"
        cls.cwd.mkdir(parents=True)
        done = home.ak("orch", "fix-api", "--model", "opus", "--workers", "opus", tty=True,
                       cwd=cls.cwd)
        assert done.code == 0, done.err
        deadline = time.monotonic() + 60
        while not saw.exists():
            assert time.monotonic() < deadline, home.tmux("capture-pane", "-p", "-t",
                                                          "=fix-api:").out
            time.sleep(0.05)
        cls.argv = json.loads(saw.read_text())["argv"]

    def dry_run(self):
        """The words of the launch a dry run with no terminal prints last."""
        done = self.home.ak("orch", "cl-seat", "--model", "opus", "--dry-run", cwd=self.cwd)
        self.assertEqual(done.code, 0, done.err)
        return shlex.split(done.out.splitlines()[-1])

    def settings(self, words):
        """Every settings value given, as its own word or after `=`, each parsed: JSON on the
        command line, or a file's."""
        given = [words[at + 1] for at, word in enumerate(words[:-1]) if word == "--settings"]
        given += [word.split("=", 1)[1] for word in words if word.startswith("--settings=")]
        return [json.loads(value if value.lstrip().startswith("{") else Path(value).read_text())
                for value in given]

    def after(self, words, flag):
        self.assertIn(flag, words[:-1])
        return words[words.index(flag) + 1]

    def test_its_settings_are_ak_s_pins_given_once_and_nothing_more(self):
        self.assertEqual(self.settings(self.argv), [PINS])

    def test_the_login_s_own_settings_file_is_left_as_it_was(self):
        self.assertEqual((self.login.read_bytes(), self.login.stat().st_mtime_ns), self.before)

    def test_it_runs_the_configured_model_and_effort_with_permissions_bypassed(self):
        self.assertEqual(self.after(self.argv, "--model"), "claude-acme-7")
        self.assertEqual(self.after(self.argv, "--effort"), "low")
        self.assertIn("--dangerously-skip-permissions", self.argv)

    def test_a_dry_run_without_a_terminal_prints_that_launch(self):
        words = self.dry_run()
        self.assertEqual(self.settings(words), [PINS])
        self.assertEqual(self.after(words, "--model"), "claude-acme-7")
        self.assertEqual(self.after(words, "--effort"), "low")
        self.assertIn("--dangerously-skip-permissions", words)
        self.assertEqual(Path(self.after(words, "--append-system-prompt-file")).name,
                         "rulebook-cl-seat.md")

    def test_a_dry_run_s_launch_keeps_the_daemon_claude_s_own_rules_and_memory_off(self):
        words = self.dry_run()
        for switch in ("CLAUDE_CODE_DISABLE_AGENT_VIEW=1", "CLAUDE_CODE_DISABLE_CLAUDE_MDS=1",
                       "CLAUDE_CODE_DISABLE_AUTO_MEMORY=1"):
            with self.subTest(switch=switch):
                self.assertIn(switch, words)
        # the worker token and another login's folder are taken out of what the seat inherits
        pairs = set(zip(words, words[1:]))
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"):
            with self.subTest(unset=name):
                self.assertIn(("-u", name), pairs)


if __name__ == "__main__":
    unittest.main()
