"""Grok logins share user settings, carrying over only values the usual login lacks.

Offline: the adapter launches a fake Grok in a temporary HOME. Grok Build 1.0.46's
bundled Configuration guide names config.toml and pager.toml; checked both links
survive real TUI saves (/vim-mode and /settings' Respect manual folds toggle).
auth.json and the subscription's settings_cache.json are not user preferences.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/grokbuild.sh"
SETTINGS = ("config.toml", "pager.toml")
FAKE_GROK = """#!/usr/bin/env python3
import json, os
from pathlib import Path
home = Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")
for name in ("config.toml", "pager.toml"):
    if os.environ.get("SAVE_SETTINGS"):
        (home / name).write_text(os.environ["SAVE_SETTINGS"])
print(json.dumps({"type": "result", "result": "ok", "session_id": "fixture"}))
"""


class OneSettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-grok-settings-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.usual, self.named = self.home / ".grok", self.home / ".grok-second"
        self.bin = self.home / "bin"
        for path in (self.usual, self.named, self.bin):
            path.mkdir()
        fake = self.bin / "grok"
        fake.write_text(FAKE_GROK)
        fake.chmod(0o755)
        self.prompt = self.home / "prompt.md"
        self.prompt.write_text("Reply ok.")
        self.env = {**os.environ, "HOME": str(self.home), "GROK_HOME": "",
                    "AGENTKIT_ACCOUNT": "second", "SAVE_SETTINGS": "",
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}

    def adapter(self, *args, **env):
        return subprocess.run([str(ADAPTER), *map(str, args)], cwd=self.home,
                              env={**self.env, **env}, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=15)

    def launch(self, **env):
        proc = self.adapter("run", "grok-4.7", "xhigh", self.home, self.prompt,
                            self.home / "out", **env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def assert_shared(self, usual=None, named=None):
        for name in SETTINGS:
            source, link = (usual or self.usual) / name, (named or self.named) / name
            self.assertTrue(link.is_symlink(), str(link))
            self.assertEqual(link.resolve(), source.resolve())
            self.assertFalse(source.is_symlink())

    def test_first_launch_merges_missing_values_and_keeps_usual_values(self):
        for name in SETTINGS:
            (self.usual / name).write_text('[ui]\nvim_mode = false\n'
                                           'theme = "usual"\n')
            (self.named / name).write_text('[ui]\nvim_mode = true\n'
                                           'show_timestamps = true\n'
                                           '[custom]\nvalues = [1, 2]\n')
        private = ("auth.json", "settings_cache.json")
        for home, account in ((self.usual, "usual"), (self.named, "second")):
            for name in private:
                (home / name).write_text(json.dumps({"account": account}))
        self.launch()
        self.assert_shared()
        for name in SETTINGS:
            with (self.usual / name).open("rb") as handle:
                self.assertEqual(tomllib.load(handle), {
                    "ui": {"vim_mode": False, "theme": "usual", "show_timestamps": True},
                    "custom": {"values": [1, 2]}})
        for home, account in ((self.usual, "usual"), (self.named, "second")):
            for name in private:
                self.assertFalse((home / name).is_symlink())
                self.assertEqual(json.loads((home / name).read_text()), {"account": account})

    def test_a_change_from_either_login_reaches_every_login_and_worker(self):
        self.launch()
        self.launch(SAVE_SETTINGS='[ui]\nvim_mode = true\n')
        third = self.home / ".grok-third"
        self.launch(AGENTKIT_ACCOUNT="third")
        self.assert_shared(named=third)
        self.assertEqual((third / "config.toml").read_text(), '[ui]\nvim_mode = true\n')
        self.launch(AGENTKIT_ACCOUNT="", SAVE_SETTINGS='[ui]\nvim_mode = false\n')
        for name in SETTINGS:
            self.assertEqual((self.named / name).read_text(), (third / name).read_text())
            self.assertIn("false", (third / name).read_text())

    def test_only_named_settings_are_carried_over_without_reformatting(self):
        original = '# keep this comment\n[ui]\nvim_mode = true\n'
        for name in SETTINGS:
            (self.named / name).write_text(original)
        self.launch()
        self.assert_shared()
        for name in SETTINGS:
            self.assertEqual((self.usual / name).read_text(), original)

    def test_usual_files_without_missing_values_stay_byte_for_byte(self):
        original = '# keep this comment\n[ui]\nvim_mode = false\n'
        for name in SETTINGS:
            (self.usual / name).write_text(original)
            (self.named / name).write_text('[ui]\nvim_mode = true\n')
        self.launch()
        self.launch()
        self.assert_shared()
        for name in SETTINGS:
            self.assertEqual((self.usual / name).read_text(), original)

    def test_new_login_links_even_settings_that_do_not_exist_yet(self):
        self.launch()
        self.assert_shared()
        self.launch(SAVE_SETTINGS='[ui]\nvim_mode = true\n')
        self.assert_shared()
        for name in SETTINGS:
            self.assertIn("true", (self.usual / name).read_text())

    def test_interactive_launch_prepares_settings_too(self):
        rulebook = self.home / "rules.md"
        rulebook.write_text("Fixture rules.")
        proc = self.adapter("interactive", "grok-4.7", "xhigh",
                            AGENTKIT_RULEBOOK=str(rulebook))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_shared()

    def test_launches_use_the_installed_adapter_code_over_the_workspace(self):
        package = self.home / "agentkit"
        package.mkdir()
        (package / "__init__.py").write_text(
            'raise AssertionError("adapter imported the workspace package")\n')
        rulebook = self.home / "rules.md"
        rulebook.write_text("Fixture rules.")
        for args in (("run", "grok-4.7", "xhigh", self.home, self.prompt, self.home / "out"),
                     ("interactive", "grok-4.7", "xhigh")):
            with self.subTest(verb=args[0]):
                proc = self.adapter(*args, AGENTKIT_RULEBOOK=str(rulebook))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assert_shared()

    def test_custom_usual_home_and_inherited_named_home(self):
        custom = self.home / "custom"
        self.launch(GROK_HOME=str(custom))
        self.assert_shared(usual=custom)
        # A worker launched by a named seat still shares with the usual home.
        self.launch(AGENTKIT_ACCOUNT="third", GROK_HOME=str(self.named))
        self.assert_shared(named=self.home / ".grok-third")

    def test_usual_launch_leaves_its_files_and_named_settings_alone(self):
        for home in (self.usual, self.named):
            for name in SETTINGS:
                (home / name).write_text(f'# {home.name}\n[ui]\nvim_mode = true\n')
        before = {p: p.read_bytes() for home in (self.usual, self.named)
                  for p in home.iterdir()}
        self.launch(AGENTKIT_ACCOUNT="")
        for path, content in before.items():
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_bytes(), content)

    def test_usual_dotfile_links_are_kept_during_migration(self):
        for name in SETTINGS:
            dotfile = self.home / f"dotfile-{name}"
            dotfile.write_text('[ui]\nvim_mode = false\n')
            (self.usual / name).symlink_to(dotfile)
            (self.named / name).write_text('[ui]\nshow_timestamps = true\n')
        self.launch()
        for name in SETTINGS:
            source = self.usual / name
            self.assertTrue(source.is_symlink())
            self.assertEqual(source.readlink(), self.home / f"dotfile-{name}")
            self.assertEqual(tomllib.loads(source.read_text()), {
                "ui": {"vim_mode": False, "show_timestamps": True}})

    def test_invalid_settings_fail_without_discarding_either_file(self):
        for name in SETTINGS:
            (self.usual / name).write_text('[ui]\nvim_mode = false\n')
            (self.named / name).write_text('[invalid')
        proc = self.adapter("run", "grok-4.7", "xhigh", self.home, self.prompt,
                            self.home / "out")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual((self.named / "config.toml").read_text(), '[invalid')
        self.assertEqual((self.usual / "config.toml").read_text(),
                         '[ui]\nvim_mode = false\n')


if __name__ == "__main__":
    unittest.main()
