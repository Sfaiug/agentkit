"""An OpenCode seat sets dontShow in each existing channel's go-upsell.json before launch."""

import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


def _make_home(root, name="home"):
    home = Path(root) / name
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


def _launch(env):
    return subprocess.run(
        [str(REPO / "adapters/opencode.sh"), "interactive", "acme/flash", "high"],
        env=env, capture_output=True, text=True, timeout=10)


class OpenCodeFreeLimitDialog(unittest.TestCase):
    def test_no_state_folder_prints_command_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            proc = _launch(env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(proc.stdout.strip())
            self.assertFalse((home / ".local").exists())

    def test_existing_channels_set_dont_show_and_keep_other_fields_and_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp, name="home with spaces")
            baseline = _launch(env)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)

            state = home / ".local/state/opencode"
            latest_tui = state / "latest/tui"
            latest_tui.mkdir(parents=True)
            latest_note = latest_tui / "go-upsell.json"
            latest_note.write_text('{"lastSeenAt": 1795717297316}\n')
            sibling = latest_tui / "other.json"
            sibling.write_text('{"keep": 1}\n')

            empty_tui = state / "beta/tui"
            empty_tui.mkdir(parents=True)

            corrupt_tui = state / "canary/tui"
            corrupt_tui.mkdir(parents=True)
            (corrupt_tui / "go-upsell.json").write_text("not json\n")

            array_tui = state / "dev/tui"
            array_tui.mkdir(parents=True)
            (array_tui / "go-upsell.json").write_text("[1, 2]\n")

            proc = _launch(env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, baseline.stdout)
            self.assertEqual(
                json.loads(latest_note.read_text()),
                {"lastSeenAt": 1795717297316, "dontShow": True},
            )
            self.assertEqual(sibling.read_text(), '{"keep": 1}\n')
            self.assertEqual(
                sorted(p.name for p in latest_tui.iterdir()),
                ["go-upsell.json", "other.json"],
            )
            self.assertEqual(
                json.loads((empty_tui / "go-upsell.json").read_text()),
                {"dontShow": True},
            )
            self.assertEqual(
                json.loads((corrupt_tui / "go-upsell.json").read_text()),
                {"dontShow": True},
            )
            self.assertEqual(
                json.loads((array_tui / "go-upsell.json").read_text()),
                {"dontShow": True},
            )

    def test_xdg_state_home_overrides_default_state_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            default_tui = home / ".local/state/opencode/latest/tui"
            default_tui.mkdir(parents=True)
            default_note = default_tui / "go-upsell.json"
            default_note.write_text('{"lastSeenAt": 111}\n')

            xdg = Path(temp) / "custom state"
            xdg_tui = xdg / "opencode/latest/tui"
            xdg_tui.mkdir(parents=True)
            xdg_note = xdg_tui / "go-upsell.json"
            xdg_note.write_text('{"lastSeenAt": 222}\n')

            proc = _launch({**env, "XDG_STATE_HOME": str(xdg)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(
                json.loads(xdg_note.read_text()),
                {"lastSeenAt": 222, "dontShow": True},
            )
            self.assertEqual(default_note.read_text(), '{"lastSeenAt": 111}\n')

    def test_unwritable_state_folder_does_not_fail_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            baseline = _launch(env)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)

            tui = home / ".local/state/opencode/latest/tui"
            tui.mkdir(parents=True)
            note = tui / "go-upsell.json"
            note.write_text('{"lastSeenAt": 1795717297316}\n')
            tui.chmod(0o555)
            try:
                proc = _launch(env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, baseline.stdout)
                self.assertEqual(proc.stderr, "")
                if os.geteuid() != 0:
                    self.assertEqual(note.read_text(), '{"lastSeenAt": 1795717297316}\n')
            finally:
                tui.chmod(0o755)

    def test_directory_or_symlink_to_directory_at_note_receives_no_temp_file(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            state = home / ".local/state/opencode"
            outside = Path(temp) / "elsewhere"
            outside.mkdir()
            (outside / "keep").write_text("keep")

            latest_tui = state / "latest/tui"
            latest_tui.mkdir(parents=True)
            (latest_tui / "go-upsell.json").symlink_to(outside, target_is_directory=True)

            beta_tui = state / "beta/tui"
            beta_tui.mkdir(parents=True)
            nested = beta_tui / "go-upsell.json"
            nested.mkdir()

            proc = _launch(env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(sorted(p.name for p in outside.iterdir()), ["keep"])
            self.assertEqual(sorted(p.name for p in nested.iterdir()), [])
            self.assertEqual(sorted(p.name for p in latest_tui.iterdir()), ["go-upsell.json"])
            self.assertEqual(sorted(p.name for p in beta_tui.iterdir()), ["go-upsell.json"])

    def test_non_rfc_json_is_replaced_and_lone_surrogates_keep_existing_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            state = home / ".local/state/opencode"

            invalid_notes = [
                ("leading_zero_true", '{"lastSeenAt":001795717297316,"dontShow":true}'),
                ("leading_zero", '{"lastSeenAt":001795717297316}'),
                ("invalid_utf8", b'{"lastSeenAt":1795717297316,"label":"\xff","dontShow":true}'),
                ("above_unicode", b'{"lastSeenAt":1795717297316,"label":"\xf4\x90\x80\x80","dontShow":true}'),
                ("five_byte_utf8", b'{"lastSeenAt":1795717297316,"label":"\xf8\x88\x80\x80\x80"}'),
                ("utf8_surrogate", b'{"lastSeenAt":1795717297316,"label":"\xed\xa0\x80","dontShow":true}'),
                ("raw_nul", b'{"lastSeenAt":1795717297316,"label":"\x00"}'),
            ]
            for channel, raw in invalid_notes:
                tui = state / channel / "tui"
                tui.mkdir(parents=True)
                note = tui / "go-upsell.json"
                if isinstance(raw, bytes):
                    note.write_bytes(raw)
                else:
                    note.write_text(raw)

            surrogate_notes = [
                ("lone_high", {"lastSeenAt": 1795717297316, "label": "\ud800"}),
                ("lone_low", {"lastSeenAt": 1795717297316, "label": "\udc00"}),
            ]
            for channel, content in surrogate_notes:
                tui = state / channel / "tui"
                tui.mkdir(parents=True)
                (tui / "go-upsell.json").write_text(json.dumps(content))

            escaped_backslash_notes = [
                ("u005c_val", br'{"lastSeenAt":1795717297316,"label":"\u005cu0001d800"}',
                 {"lastSeenAt": 1795717297316, "label": r"\u0001d800", "dontShow": True}),
                ("u005c_and_surr",
                 br'{"lastSeenAt":1795717297316,"label":"\u005cu0001d800","surrogate":"\udc00"}',
                 {"lastSeenAt": 1795717297316, "label": r"\u0001d800", "surrogate": "\udc00",
                  "dontShow": True}),
                ("u005c_keys",
                 br'{"lastSeenAt":1795717297316,"\u005cu0001d800":"kept","\u005cud800":"separate"}',
                 {"lastSeenAt": 1795717297316, r"\u0001d800": "kept", r"\ud800": "separate",
                  "dontShow": True}),
            ]
            for channel, raw, _ in escaped_backslash_notes:
                tui = state / channel / "tui"
                tui.mkdir(parents=True)
                (tui / "go-upsell.json").write_bytes(raw)

            minimal = Path(temp) / "minimal-bin"
            minimal.mkdir()
            for name in ("bash", "dirname", "jq", "mktemp", "mv", "rm"):
                (minimal / name).symlink_to(shutil.which(name))

            proc = _launch({**env, "PATH": str(minimal)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for channel, _ in invalid_notes:
                self.assertEqual(
                    json.loads((state / channel / "tui/go-upsell.json").read_text()),
                    {"dontShow": True},
                    channel,
                )
            for channel, content in surrogate_notes:
                self.assertEqual(
                    json.loads((state / channel / "tui/go-upsell.json").read_text()),
                    {**content, "dontShow": True},
                    channel,
                )
            for channel, _, expected in escaped_backslash_notes:
                self.assertEqual(
                    json.loads((state / channel / "tui/go-upsell.json").read_text()),
                    expected,
                    channel,
                )

    def test_file_size_limit_does_not_kill_launch_or_leave_temp_file(self):
        with tempfile.TemporaryDirectory() as temp:
            home, env = _make_home(temp)
            baseline = _launch(env)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)

            tui = home / ".local/state/opencode/latest/tui"
            tui.mkdir(parents=True)
            note = tui / "go-upsell.json"
            note.write_text('{"lastSeenAt":1795717297316}\n')

            def forbid_file_writes():
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

            proc = subprocess.run(
                [str(REPO / "adapters/opencode.sh"), "interactive", "acme/flash", "high"],
                env=env, capture_output=True, text=True, timeout=10,
                preexec_fn=forbid_file_writes,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, baseline.stdout)
            self.assertEqual(proc.stderr, "")
            self.assertEqual(sorted(p.name for p in tui.glob(".go-upsell.*")), [])


if __name__ == "__main__":
    unittest.main()
