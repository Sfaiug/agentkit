"""A Codex seat opened on the usual login runs on the usual login's home, whatever account home
the terminal opening it inherited.

A seat on a named subscription runs with CODEX_HOME=~/.codex-<name>, and everything it starts
inherits it, a person's `ak orch` typed there included.  A seat naming no account is the usual
login's: its Codex reads ~/.codex, the login ak's auth check reads, never the inherited home,
which would spend the other subscription.  Black-box: the program `AK_BIN` names opens a Codex
seat from a person's terminal (tests/fixtures/akterm.py), its `codex` a fake that writes down
the home its TUI was given; no provider is reached.
"""

import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

# Only the TUI, the one call carrying --yolo, stays up; whatever else asks Codex hears no.
FAKE = """#!/bin/sh
case " $* " in *" --yolo "*) ;; *) exit 1 ;; esac
printf %s "${CODEX_HOME:-$HOME/.codex}" >"$HOME/codex-home.tmp"
mv "$HOME/codex-home.tmp" "$HOME/codex-home"
exec sleep 600
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexSeatOnTheUsualLogin(unittest.TestCase):
    def test_an_inherited_account_home_gives_way_to_the_usual_login(self):
        home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: no provider is reached
            probe.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
        home.env.update({"https_proxy": dead, "HTTPS_PROXY": dead})
        home.fake("codex", FAKE)
        for login in (".codex", ".codex-second"):
            home.write(f"{login}/auth.json", {"tokens": {"access_token": "acme-token"}})
        akconfig.write(home, ["astra"], providers={"openai": {"accounts": ["default", "second"]}})
        Terminal(home, "orch", "acme", "--model", "astra", "--workers", "astra",
                 env={"CODEX_HOME": str(home.path / ".codex-second")})
        written = home.path / "codex-home"
        deadline = time.monotonic() + 60
        while not written.exists():
            self.assertLess(time.monotonic(), deadline, "the Codex seat never opened")
            time.sleep(0.05)
        self.assertEqual(written.read_text(), str(home.path / ".codex"))


if __name__ == "__main__":
    unittest.main()
