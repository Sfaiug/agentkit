"""Seats on two Claude logins read the one usual settings file, and no launch writes it.

A harness's settings are its own, changed in any of its sessions: its settings screen, or its
model asked to.  So every login of Claude reads one settings file, and a change made on one
reaches every session on every login.  A named login's `settings.json` is a link to the usual
login's `~/.claude/settings.json`, made when a seat opens on it and kept by every launch after;
a file of its own there gives way to the link.  The usual file is never written by a launch: it
holds the owner's settings, and an edit made on one login was once reverted by the next launch.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
config whose Claude subscription lists named logins with seat credentials that hold, and a fake
`claude` keeps the login folder it was started on and the settings it found there.  A seat's
pane asks its own tmux server by the socket path tmux gives it; the Home refuses every socket
path, so here its own goes through.  This test fails against `/bin/false`.
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

USUAL = '{"theme": "dark", "autoCompactWindow": 1000000}\n'
OWN_SOCKET = """#!/bin/sh
case $1:$2 in
  -S:*..*) ;;
  -S:{dir}/*) exec {real} "$@" ;;
esac
exec {held} "$@"
"""
STARTED = """#!{python}
import json, os, time
folder = os.environ.get("CLAUDE_CONFIG_DIR")
try:
    with open(os.path.join(folder or os.path.expanduser("~/.claude"), "settings.json")) as file:
        found = file.read()
except FileNotFoundError:
    found = None
saw = os.path.join({saw}, "saw-" + os.environ["AGENTKIT_SESSION"] + ".json")
with open(saw + ".part", "w") as out:
    json.dump({{"folder": folder, "settings": found}}, out)
os.replace(saw + ".part", saw)
time.sleep(600)
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ClaudeLogins(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        held = home.bin / "tmux-of-the-home"
        (home.bin / "tmux").rename(held)
        home.fake("tmux", OWN_SOCKET.format(dir=shlex.quote(str(home.tmux_dir)),
                                            real=shlex.quote(REAL_TMUX),
                                            held=shlex.quote(str(held))))
        home.fake("claude", STARTED.format(python=sys.executable, saw=repr(str(home.root))))
        self.usual = home.write(".claude/settings.json", USUAL, ago=86400)
        self.before = (self.usual.read_bytes(), self.usual.stat().st_mtime_ns)
        self.logins = []

    def own(self, login):
        return self.home.path / f".claude-{login}" / "settings.json"

    def open_seat(self, name, login):
        """Open seat `name`, which opens on Claude login `login`; what its claude found on
        starting."""
        home = self.home
        if login not in self.logins:
            home.write(f".claude-{login}/.credentials.json", {"claudeAiOauth": {
                "accessToken": "acme-access", "refreshToken": "acme-refresh",
                "expiresAt": int(time.time() + 86400) * 1000}})
            self.logins.append(login)
        # the login new seats open on while it has room, and the first tried
        akconfig.write(home, {"opus": "claude"}, providers={"anthropic": {
            "mode": "subscription", "seat_account": login,
            "accounts": [login, *(other for other in self.logins if other != login)]}})
        done = home.ak("orch", name, "--model", "opus", "--workers", "opus", tty=True)
        self.assertEqual(done.code, 0, done.err)
        saw = home.root / f"saw-{name}.json"
        deadline = time.monotonic() + 60
        while not saw.exists():
            self.assertLess(time.monotonic(), deadline,
                            home.tmux("capture-pane", "-p", "-t", f"={name}:").out)
            time.sleep(0.05)
        found = json.loads(saw.read_text())
        self.assertEqual(found["folder"], str(home.path / f".claude-{login}"))
        return found

    def assertLinked(self, login):
        own = self.own(login)
        self.assertTrue(own.is_symlink(), f"{own} is not a link")
        self.assertEqual(own.resolve(), self.usual.resolve())

    def assertUsualUntouched(self):
        self.assertEqual((self.usual.read_bytes(), self.usual.stat().st_mtime_ns), self.before)

    def test_seats_on_two_logins_read_the_usual_file_through_links(self):
        for name, login in (("acme", "harbor"), ("beta", "quay")):
            with self.subTest(login=login):
                self.assertEqual(self.open_seat(name, login)["settings"], USUAL)
                self.assertLinked(login)
        self.assertUsualUntouched()

    def test_a_change_made_on_one_login_reaches_the_other_and_outlasts_their_launches(self):
        self.open_seat("acme", "harbor")
        self.open_seat("beta", "quay")
        changed = '{"theme": "dark", "autoCompactWindow": 300000}\n'
        self.own("harbor").write_text(changed)      # as /config on the harbor login saves it
        for name, login in (("fix-api", "quay"), ("fix-web", "harbor")):
            with self.subTest(login=login):
                self.assertEqual(self.open_seat(name, login)["settings"], changed)
                self.assertLinked(login)
        self.assertEqual(self.usual.read_text(), changed)

    def test_a_login_s_own_settings_file_gives_way_to_the_link(self):
        self.home.write(".claude-harbor/settings.json", '{"theme": "light"}\n')
        self.assertEqual(self.open_seat("acme", "harbor")["settings"], USUAL)
        self.assertLinked("harbor")
        self.assertUsualUntouched()


if __name__ == "__main__":
    unittest.main()
