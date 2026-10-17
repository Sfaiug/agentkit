"""Every Claude login reads one settings file, so a change made on any of them is every session's.

A named login's `settings.json` is a link to the usual login's `~/.claude/settings.json`, made
by the first seat or worker turn on it: a seat's `/config` on that login writes through it
(Claude Code 2.1.292 does), every session there reads it, and no launch writes the usual file.
Offline: a temporary HOME, invented names, the real adapter with a fake `claude` first on PATH
that writes down the settings it was started with, and the real `account_config`.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit.harness.claude import account_config

FAKE = """#!/bin/sh
cat "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json" >"$AK_TEST_STARTED"
"""
# An `ln` that, once it has made a settings link, waits until both launches have made theirs
LN = """#!{python}
import os, pathlib, subprocess, sys, time
done = subprocess.run([{ln!r}, *sys.argv[1:]])
marks = pathlib.Path(os.environ["AK_TEST_MARKS"])
if done.returncode == 0 and os.path.basename(sys.argv[-1]).startswith("settings.json"):
    (marks / os.environ["AK_TEST_SIDE"]).touch()
    deadline = time.monotonic() + 30
    while len(list(marks.iterdir())) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
sys.exit(done.returncode)
"""


class OneSettings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-claude-one-settings-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.usual = self.root / ".claude/settings.json"
        self.usual.parent.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "claude").write_text(FAKE)
        (bin_dir / "claude").chmod(0o755)
        rulebook = self.root / "rulebook.md"
        rulebook.write_text("rules\n")
        self.workspace, self.prompt = self.root / "ws", self.root / "prompt.md"
        self.workspace.mkdir()
        self.prompt.write_text("hi\n")
        self.started = self.root / "started"
        self.env = {**os.environ, "HOME": str(self.root), "AK_TEST_STARTED": str(self.started),
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "AGENTKIT_RULEBOOK": str(rulebook), "AGENTKIT_CLAUDE_CHECKED": "1"}
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)

    def own(self, account):
        return self.root / f".claude-{account}/settings.json"

    def adapter(self, account, verb):
        args = (["m-1", "high"] if verb == "interactive" else
                ["m-1", "high", str(self.workspace), str(self.prompt), str(self.root / "out")])
        done = subprocess.run([str(REPO / "adapters/claude.sh"), verb, *args], capture_output=True,
                              text=True, timeout=60, cwd=self.root,
                              env={**self.env, "AGENTKIT_ACCOUNT": account})
        self.assertEqual(done.returncode, 0, done.stderr)

    def seat(self, account):
        """A seat's launch: the adapter prints its command, which prepares the login."""
        self.adapter(account, "interactive")
        with patch.dict(os.environ, {"HOME": str(self.root), "AGENTKIT_ACCOUNT": account}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            account_config()

    def turn(self, account):
        """The settings a worker turn on that login was started with."""
        self.adapter(account, "run")
        return json.loads(self.started.read_text())

    def read(self, path):
        return json.loads(path.read_text())

    def test_a_change_made_on_one_login_is_every_login_s_and_survives_their_launches(self):
        self.usual.write_text(json.dumps({"autoCompactWindow": 1000000, "theme": "dark"}))
        self.seat("harbor")
        self.turn("quay")     # a login only worker turns run on
        # /config on the harbor login writes its own path
        own = self.own("harbor")
        own.write_text(json.dumps({**self.read(own), "autoCompactWindow": 300000}))
        for account in ("harbor", "quay", ""):
            self.seat(account)
            self.assertEqual(self.turn(account)["autoCompactWindow"], 300000)
        for path in (self.usual, self.own("harbor"), self.own("quay")):
            self.assertEqual(self.read(path), {"autoCompactWindow": 300000, "theme": "dark"})
        for account in ("harbor", "quay"):
            self.assertEqual(os.readlink(self.own(account)), str(self.usual))

    def test_no_launch_writes_the_usual_file_and_a_login_s_own_file_is_replaced(self):
        self.usual.write_text(json.dumps({"theme": "dark", "hooks": {"Stop": ["current"]}}))
        before = (self.usual.read_bytes(), self.usual.stat().st_mtime_ns)
        own = self.own("harbor")
        own.parent.mkdir()
        own.write_text(json.dumps({"theme": "light", "statusLine": {"command": "acme-status"}}))
        for account in ("harbor", "", "harbor"):
            self.seat(account)
            self.assertEqual(self.turn(account), {"theme": "dark", "hooks": {"Stop": ["current"]}})
        self.assertEqual(os.readlink(own), str(self.usual))
        self.assertEqual((self.usual.read_bytes(), self.usual.stat().st_mtime_ns), before)

    def test_a_login_already_reaching_the_usual_file_through_other_links_is_left_alone(self):
        dotfiles = self.root / "dotfiles/claude.json"
        dotfiles.parent.mkdir()
        dotfiles.write_text(json.dumps({"autoCompactWindow": 300000}))
        own = self.own("harbor")
        own.parent.mkdir()
        # both logins linked to one dotfiles file, or the usual one linked through the named one
        for usual_to, own_to in ((dotfiles, dotfiles), (own, dotfiles)):
            with self.subTest(usual=usual_to.name, own=own_to.name):
                for path, target in ((self.usual, usual_to), (own, own_to)):
                    path.unlink(missing_ok=True)
                    path.symlink_to(target)
                self.seat("harbor")
                self.assertEqual(self.turn("harbor"), {"autoCompactWindow": 300000})
                self.assertEqual((os.readlink(self.usual), os.readlink(own)),
                                 (str(usual_to), str(own_to)))

    def test_a_usual_file_linked_to_a_login_s_file_not_there_yet_stays_linked_to_it(self):
        own = self.own("harbor")
        own.parent.mkdir()
        self.usual.symlink_to(own)
        self.seat("harbor")
        self.assertFalse(own.is_symlink())
        own.write_text(json.dumps({"theme": "dark"}))     # /config on either login
        for account in ("harbor", ""):
            self.assertEqual(self.turn(account), {"theme": "dark"})

    def test_two_first_turns_on_one_login_each_in_its_own_pid_namespace_both_start(self):
        # agentkit/box.py starts every worker in a PID namespace of its own, so both adapters
        # have the same $$
        self.usual.write_text("{}")
        own = self.own("harbor")
        own.parent.mkdir()
        own.write_text("{}")
        (self.root / "bin/ln").write_text(LN.format(python=sys.executable, ln=shutil.which("ln")))
        (self.root / "bin/ln").chmod(0o755)
        marks = self.root / "marks"
        marks.mkdir()
        launches = [subprocess.Popen(
            ["bwrap", "--unshare-user", "--unshare-pid", "--die-with-parent", "--ro-bind", "/", "/",
             "--bind", str(self.root), str(self.root), "--dev", "/dev", "--proc", "/proc", "--",
             str(REPO / "adapters/claude.sh"), "run", "m-1", "high", str(self.workspace),
             str(self.prompt), str(self.root / f"out-{side}")],
            env={**self.env, "AGENTKIT_ACCOUNT": "harbor", "AK_TEST_SIDE": side,
                 "AK_TEST_MARKS": str(marks), "AK_TEST_STARTED": str(self.root / f"started-{side}")},
            stderr=subprocess.PIPE, text=True) for side in ("a", "b")]
        for launch in launches:
            _, stderr = launch.communicate(timeout=60)
            self.assertEqual(launch.returncode, 0, stderr)
        self.assertEqual(os.readlink(own), str(self.usual))
        self.assertEqual(sorted(path.name for path in own.parent.glob("settings.json*")),
                         ["settings.json"])


if __name__ == "__main__":
    unittest.main()
