"""A setting changed in any Claude session, on any login, is every session's and survives launches.

Every login reads the usual login's user settings: the adapter links a named one's
`settings.json` to `~/.claude/settings.json` for a seat's launch and a worker's turn alike, and
nothing a launch runs writes it or replaces the link (Claude Code 2.1.292 writes its user
settings through the link and keeps it: checked with `claude plugin install --scope user`).
The first link carries over what only the named login's own file held; the usual login's values
win.  Offline: a temporary HOME, the real adapter, a seat's real launch line up to its TUI, and a
fake Claude Code that reads its login's settings and saves a change through the same path.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from threading import Thread
import unittest

REPO = Path(__file__).resolve().parents[1]
ADAPTER = REPO / "adapters/claude.sh"
FAKE = """#!/usr/bin/env python3
import json, os
from pathlib import Path
path = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
read = json.loads(path.read_text()) if path.exists() else {}
if os.environ.get("AK_TEST_SAVE"):
    path.write_text(json.dumps({**read, **json.loads(os.environ["AK_TEST_SAVE"])}))
print(json.dumps({"type": "result", "result": json.dumps(read), "session_id": "fixture"}))
"""


class OneSettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-claude-one-settings-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.usual = self.root / ".claude/settings.json"
        self.usual.parent.mkdir()
        self.own = self.root / ".claude-quay/settings.json"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.fake = bin_dir / "claude"
        self.fake.write_text(FAKE)
        self.fake.chmod(0o755)
        rulebook = self.root / "rulebook.md"
        rulebook.write_text("rules\n")
        self.prompt = self.root / "prompt.md"
        self.prompt.write_text("hi\n")
        self.env = {**os.environ, "HOME": str(self.root), "AGENTKIT_RULEBOOK": str(rulebook),
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        for name in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "AGENTKIT_CLAUDE_CHECKED"):
            self.env.pop(name, None)

    def adapter(self, account, *args, save=None):
        env = {**self.env, "AGENTKIT_ACCOUNT": account, "AK_TEST_SAVE": json.dumps(save) if save else ""}
        return subprocess.run([str(ADAPTER), *map(str, args)], capture_output=True, text=True,
                              timeout=60, cwd=self.root, env=env), env

    def seat(self, account, save=None):
        """What a seat opened on that login read: its own launch line, a fake in its TUI's place."""
        line, env = self.adapter(account, "interactive", "m-1", "high", save=save)
        self.assertEqual(line.returncode, 0, line.stderr)
        cmd = shlex.split(line.stdout)
        at = cmd.index(str(REPO / "tools/idle-compact.py")) - 1
        done = subprocess.run(cmd[:at] + [str(self.fake)], capture_output=True, text=True,
                              timeout=60, cwd=self.root, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(json.loads(done.stdout)["result"])

    def worker(self, account, save=None, out="out"):
        """What a worker turn on that login read."""
        done, _ = self.adapter(account, "run", "m-1", "high", self.root, self.prompt,
                               self.root / out, save=save)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads((self.root / out / "final.md").read_text())

    def assert_linked(self, *accounts):
        for account in accounts:
            link = self.root / f".claude-{account}/settings.json"
            self.assertTrue(link.is_symlink(), link)
            self.assertEqual(link.resolve(), self.usual.resolve())
        self.assertFalse(self.usual.is_symlink())

    def test_a_change_on_any_login_reaches_every_login_and_survives_their_launches(self):
        self.usual.write_text(json.dumps({"autoCompactWindow": 500000}))
        self.seat("quay", save={"autoCompactWindow": 200000})
        self.assertEqual(json.loads(self.usual.read_text()), {"autoCompactWindow": 200000})
        for opened in (self.seat, self.worker):
            for account in ("quay", "harbor", ""):
                with self.subTest(opened=opened.__name__, account=account or "usual"):
                    self.assertEqual(opened(account), {"autoCompactWindow": 200000})
        self.worker("harbor", save={"autoCompactWindow": 300000})
        self.seat("", save={"theme": "light"})
        for opened in (self.seat, self.worker):
            for account in ("quay", "harbor", ""):
                with self.subTest(opened=opened.__name__, account=account or "usual"):
                    self.assertEqual(opened(account),
                                     {"autoCompactWindow": 300000, "theme": "light"})
        self.assert_linked("quay", "harbor")

    def test_the_first_link_carries_over_only_what_the_usual_login_lacks(self):
        self.usual.write_text(json.dumps({"model": "usual", "env": {"ACME": "1"}}))
        self.own.parent.mkdir()
        self.own.write_text(json.dumps({"model": "quay", "env": {"FIX_API": "2"},
                                        "autoCompactWindow": 200000}))
        merged = {"model": "usual", "env": {"ACME": "1"}, "autoCompactWindow": 200000}
        self.assertEqual(self.worker("quay"), merged)
        self.assertEqual(json.loads(self.usual.read_text()), merged)
        self.assert_linked("quay")

    def test_a_usual_file_with_nothing_to_carry_over_is_left_byte_for_byte(self):
        before = '{\n  "model": "usual"\n}\n'
        self.usual.write_text(before)
        self.own.parent.mkdir()
        self.own.write_text(json.dumps({"model": "quay"}))
        self.seat("quay")
        self.worker("quay")
        self.seat("")
        self.assertEqual(self.usual.read_text(), before)
        self.assert_linked("quay")

    def test_a_new_login_links_before_the_usual_file_exists(self):
        self.assertEqual(self.worker("quay", save={"theme": "light"}), {})
        self.assertEqual(json.loads(self.usual.read_text()), {"theme": "light"})
        self.assert_linked("quay")

    def test_first_launches_side_by_side_each_keep_what_was_carried_over(self):
        self.usual.write_text(json.dumps({"model": "usual"}))
        self.own.parent.mkdir()
        self.own.write_text(json.dumps({"theme": "light"}))
        read = []
        turns = [Thread(target=lambda n=n: read.append(self.worker("quay", out=f"out-{n}")))
                 for n in range(6)]
        for turn in turns:
            turn.start()
        for turn in turns:
            turn.join()
        self.assertEqual(read, [{"model": "usual", "theme": "light"}] * 6)
        self.assertEqual(json.loads(self.usual.read_text()), {"model": "usual", "theme": "light"})
        self.assert_linked("quay")

    def test_settings_that_are_not_a_json_object_refuse_the_launch_and_keep_both_files(self):
        self.usual.write_text('{"model": "usual"}')
        self.own.parent.mkdir()
        for bad in ("{not json", "[]"):
            self.own.write_text(bad)
            for verb in (("interactive", "m-1", "high"),
                         ("run", "m-1", "high", self.root, self.prompt, self.root / "out")):
                with self.subTest(bad=bad, verb=verb[0]):
                    done, _ = self.adapter("quay", *verb)
                    self.assertEqual(done.returncode, 2, done.stdout)
                    self.assertFalse(self.own.is_symlink())
                    self.assertEqual(self.own.read_text(), bad)
                    self.assertEqual(self.usual.read_text(), '{"model": "usual"}')


if __name__ == "__main__":
    unittest.main()
