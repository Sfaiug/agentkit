"""`↻ log in again` says which harness it opens on the terminal it gives back, before that harness
draws anything.

The owner (20 Oct 2026): "I just performed a relogin for a claude code window, and it took
forever. This should be snappy and fast and not hang."  A harness can take seconds to draw its
login, and the terminal stood blank meanwhile.  Black-box: the program `AK_BIN` names in a
person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, the login refused so what it said stays; fails against `/bin/false`.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SignInSaysItStarts(unittest.TestCase):
    def test_log_in_again_names_the_harness_it_opens_before_it_draws(self):
        home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")["claude"].answer("login", "<refused>", 1)
        akconfig.write(home, {"fable": "claude", "astra": "codex"})
        # a login ending tomorrow, so `↻ log in again` is offered
        home.write(".agentkit/state/logins.json", {"anthropic": {"default": {
            "ends": time.time() + 86400, "checked_at": time.time()}}})
        term = Terminal(home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("c config")
        term.keys("c")
        term.wait("› Fable 5.1")
        term.keys("Down", "Down", "Down")        # past GPT-6-Astra and `Models`
        term.wait("› Subscriptions")
        term.keys("Enter")
        term.wait(lambda screen: screen.startswith("agentkit · config · subscriptions")
                  and "[↻ log in again]" in screen)
        term.keys("Enter")
        shown = [line.rstrip() for line in term.wait("<refused>").split("\n") if line.strip()]
        self.assertEqual(shown[shown.index("<refused>") - 1], "Opening Claude Code to log in…")


if __name__ == "__main__":
    unittest.main()
