"""An OpenCode seat starts with its sidebar hidden, without pinning OPENCODE_CLI_CONFIG_CONTENT."""

import json
import os
from pathlib import Path
import resource
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, plan  # noqa: E402

NAME = "OPENCODE_CLI_CONFIG_CONTENT"


def _make_home(root):
    home = Path(root) / "home"
    installed = home / ".opencode/bin"
    installed.mkdir(parents=True)
    binary = installed / "opencode"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    rulebook = Path(root) / "rules.md"
    rulebook.write_text("Follow the owner's task.\n")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin",
           "AGENTKIT_RULEBOOK": str(rulebook), "LC_ALL": "C"}
    return home, env


def _launch(env, *extra):
    return subprocess.run(
        [str(REPO / "adapters/opencode.sh"), "interactive", "acme/x", "high", *extra],
        env=env, capture_output=True, text=True, timeout=20)


class OpenCodeSeatHidesItsSidebar(unittest.TestCase):
    def test_fresh_home_writes_cli_json_without_setting_env_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            words = shlex.split(done.stdout)
            self.assertFalse(any(w.startswith(f"{NAME}=") for w in words), done.stdout)
            cli = home / ".config/opencode/cli.json"
            self.assertEqual(json.loads(cli.read_text()), {"session": {"sidebar": "hide"}})
            self.assertEqual(sorted(p.name for p in cli.parent.iterdir()), ["cli.json"])

    def test_existing_cli_json_keeps_other_settings_and_untouched_when_already_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            cli = home / ".config/opencode/cli.json"
            cli.parent.mkdir(parents=True)
            cli.write_text('{"highlights": false, "session": {"sidebar": "auto", "scrollbar": true}}\n')
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                json.loads(cli.read_text()),
                {"highlights": False, "session": {"sidebar": "hide", "scrollbar": True}},
            )
            # JSONC already hiding the sidebar is left byte-for-byte untouched (comments intact).
            commented = '// owner comment\n{\n  "highlights": false,\n  "session": {"sidebar": "hide",},\n}\n'
            cli.write_text(commented)
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(cli.read_text(), commented)

    def test_legacy_tui_or_kv_updates_kv_json_so_migration_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            cfg = home / ".config/opencode"
            state = home / ".local/state/opencode"
            cfg.mkdir(parents=True)
            state.mkdir(parents=True)
            (cfg / "tui.json").write_text('{"theme": "nord"}\n')
            kv = state / "kv.json"
            kv.write_text('{"thinking_visibility": false}\n')
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse((cfg / "cli.json").exists())
            self.assertEqual(
                json.loads(kv.read_text()),
                {"thinking_visibility": False, "sidebar": "hide"},
            )

    def test_inline_env_accepts_hidden_or_unrelated_settings_and_refuses_auto(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            cli = home / ".config/opencode/cli.json"
            for doc in (
                '{"session": {"sidebar": "hide"}}',
                '{"session": {"sidebar": "hide"}, "highlights": false}',
                '/* c */ {"session": {"sidebar": "hide",},}',
            ):
                done = _launch({**env, NAME: doc})
                self.assertEqual(done.returncode, 0, f"{doc}: {done.stderr}")
                self.assertTrue(done.stdout.strip())
                self.assertFalse(cli.exists())

            for bad in (
                '{"session": {"sidebar": "auto"}}',
                '// comment\n{"session": {"sidebar": "auto",}, "highlights": false,}',
            ):
                done = _launch({**env, NAME: bad})
                self.assertEqual((done.returncode, done.stdout), (2, ""), bad)
                self.assertRegex(done.stderr, f"{NAME}.*~/.config/opencode/cli.json")
                self.assertFalse(cli.exists())

            done = _launch({**env, NAME: '{"highlights": false}'})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(cli.read_text()), {"session": {"sidebar": "hide"}})

    def test_opencode_config_dir_and_xdg_config_home_are_honored(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            xdg = Path(temp) / "xdg cfg"
            done = _launch({**env, "XDG_CONFIG_HOME": str(xdg)})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads((xdg / "opencode/cli.json").read_text()),
                             {"session": {"sidebar": "hide"}})
            self.assertFalse((home / ".config/opencode/cli.json").exists())

            custom = Path(temp) / "custom cfg"
            done = _launch({**env, "XDG_CONFIG_HOME": str(xdg), "OPENCODE_CONFIG_DIR": str(custom)})
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads((custom / "cli.json").read_text()),
                             {"session": {"sidebar": "hide"}})

    def test_non_file_corrupt_unwritable_and_fsize_limit_never_fail_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            cfg = home / ".config/opencode"
            cfg.mkdir(parents=True)
            cli = cfg / "cli.json"

            cli.mkdir()
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(list(cli.iterdir()), [])
            cli.rmdir()

            cli.write_text("not json\n")
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(cli.read_text(), "not json\n")

            cli.write_text('{"highlights": false}\n')
            cfg.chmod(0o555)
            try:
                done = _launch(env)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stderr, "")
            finally:
                cfg.chmod(0o755)

            def forbid_writes():
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

            proc = subprocess.run(
                [str(REPO / "adapters/opencode.sh"), "interactive", "acme/x", "high"],
                env=env, capture_output=True, text=True, timeout=20,
                preexec_fn=forbid_writes,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(sorted(p.name for p in cfg.glob(".sidebar.*")), [])

    def test_lone_surrogates_in_cli_json_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            cli = home / ".config/opencode/cli.json"
            cli.parent.mkdir(parents=True)
            cli.write_text(json.dumps({"label": "\ud800", "highlights": False}))
            done = _launch(env)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                json.loads(cli.read_text()),
                {"label": "\ud800", "highlights": False, "session": {"sidebar": "hide"}},
            )

    def test_caller_cli_config_env_is_not_stripped_from_child_env_or_checks(self):
        self.assertNotIn(NAME, config.seat_env_names())
        original = dict(os.environ)
        try:
            value = '{"highlights":false}'
            os.environ.clear()
            os.environ.update({"PATH": os.defpath, "HOME": original["HOME"], NAME: value})
            check = f'test "${NAME}" = {shlex.quote(value)}'
            self.assertFalse(plan.fails(REPO, check, plan.git_env()))
        finally:
            os.environ.clear()
            os.environ.update(original)


if __name__ == "__main__":
    unittest.main()
