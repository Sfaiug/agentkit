"""A Claude seat starts claude on its recorded conversation, cut off from every other session.

A seat keeps its conversation: `ak orch` writes down a new one's id before the harness starts
and claude opens it under that id.  Seats never message one another, so claude refuses messages
from other sessions; `/background`'s daemon stays off, since it moved a seat's conversation into
a process that spoke for another seat; Remote Control carries the seat's name, so the owner
finds it in the Claude app.  Its only instructions are its rulebook: claude's own instruction
files and memory are off, and the caller's Claude login and config folder do not reach it.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and a
fake `claude` keeps what it was started with.  A seat's pane asks its own tmux server by the
socket path tmux gives it; the Home refuses every socket path, so here its own, and no other,
goes through.  This test fails against `/bin/false`.
"""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home

OWN_RULE = "Acme rule: keep fix-api small.\n"
CALLER = {"CLAUDE_CODE_OAUTH_TOKEN": "acme-worker-token", "CLAUDE_CONFIG_DIR": "/srv/acme/claude"}
OWN_SOCKET = """#!/bin/sh
case $1:$2 in
  -S:*..*) ;;
  -S:{dir}/*) exec {real} "$@" ;;
esac
exec {held} "$@"
"""
STARTED = """#!{python}
import json, os, sys, time
with open({part}, "w") as out:
    json.dump({{"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd()}}, out)
os.replace({part}, {saw})
time.sleep(600)
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClaudeSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        held = home.bin / "tmux-of-the-home"
        (home.bin / "tmux").rename(held)
        home.fake("tmux", OWN_SOCKET.format(dir=shlex.quote(str(home.tmux_dir)),
                                            real=shlex.quote(REAL_TMUX),
                                            held=shlex.quote(str(held))))
        saw = home.root / "claude-started.json"
        home.fake("claude", STARTED.format(python=sys.executable, saw=repr(str(saw)),
                                           part=repr(f"{saw}.part")))
        home.write(".agentkit/rules.md", OWN_RULE)
        cls.cwd = home.path / "code" / "acme"
        cls.cwd.mkdir(parents=True)
        done = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", tty=True,
                       env=CALLER, cwd=cls.cwd)
        assert done.code == 0, done.err
        deadline = time.monotonic() + 60
        while not saw.exists():
            assert time.monotonic() < deadline, home.tmux("capture-pane", "-p", "-t", "=acme:").out
            time.sleep(0.05)
        started = json.loads(saw.read_text())
        cls.argv, cls.env, cls.where = started["argv"], started["env"], started["cwd"]
        cls.record = json.loads((home.path / ".agentkit/state/session-acme.json").read_text())

    def value(self, flag):
        """What claude was given after `flag`, as its own word or after `=`."""
        for at, word in enumerate(self.argv):
            if word == flag and at + 1 < len(self.argv):
                return self.argv[at + 1]
            if word.startswith(f"{flag}="):
                return word.split("=", 1)[1]
        self.fail(f"claude was not given {flag}: {self.argv}")

    def test_it_opens_the_conversation_its_record_names_in_the_seats_folder(self):
        self.assertTrue(self.record["conversation"])
        self.assertEqual(self.value("--session-id"), self.record["conversation"])
        self.assertEqual(Path(self.where), self.cwd)

    def test_it_refuses_messages_from_other_sessions(self):
        given = self.value("--settings")
        settings = json.loads(given if given.lstrip().startswith("{")
                              else Path(given).read_text())
        self.assertEqual(settings["crossSessionInbound"], "refuse")

    def test_the_background_agent_view_is_off(self):
        self.assertEqual(self.env.get("CLAUDE_CODE_DISABLE_AGENT_VIEW"), "1")

    def test_remote_control_carries_the_seats_name(self):
        self.assertEqual(self.value("--remote-control"), "acme")

    def test_its_rulebook_is_its_only_instruction(self):
        rulebook = self.home.path / ".agentkit/state/rulebook-acme.md"
        self.assertEqual(Path(self.value("--append-system-prompt-file")), rulebook)
        self.assertIn(OWN_RULE, rulebook.read_text())
        for switch in ("CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_DISABLE_AUTO_MEMORY"):
            with self.subTest(switch=switch):
                self.assertEqual(self.env.get(switch), "1")

    def test_the_callers_claude_login_and_config_folder_stay_out(self):
        for name in CALLER:
            with self.subTest(variable=name):
                self.assertNotIn(name, self.env)


if __name__ == "__main__":
    unittest.main()
