"""A seat event's fact is written by the warm looker, before it looks (`agentkit/looker.py`).

With the warm server up, a question going up is heard by the looker: its fact is down once the
hook returns, its word is published, and no Python the hook started imports agentkit.  With none
up, the same fact and the same word, cold.  A notice meaning what the fact standing means
writes nothing, warm or cold.

Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), at a seat of tests/fixtures/akseat.py; the warm server is the
checkout's beside the program `AK_BIN` names, started as the first popup after an install starts
it.  Each Python the hook starts writes down each agentkit module it imports, by an audit hook
in the `sitecustomize` its environment alone puts first on the path.
"""

import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import ROOT, Hooks

NAME = "acme"
BOUND = 120       # seconds a look may take on a loaded host
# `pid<TAB>module` to $HOOK_IMPORTS for each agentkit module a Python imports
SITE = r"""
import os, sys
def _imported(event, args, log=os.open(os.environ["HOOK_IMPORTS"],
                                       os.O_WRONLY | os.O_APPEND | os.O_CREAT)):
    if event == "import" and str(args[0]).partition(".")[0] == "agentkit":
        os.write(log, f"{os.getpid()}\t{args[0]}\n".encode())
sys.addaudithook(_imported)
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FactWarm(unittest.TestCase):
    def setUp(self):
        self.home = home = Home(tmux_log=False)
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        self.hooks = Hooks(home)
        self.seat = Seat(home, NAME, screen="claude-permission-pane.txt")
        self.state = home.path / ".agentkit/state"
        self.fact = self.state / f"hook-{NAME}.json"
        site = home.root / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(SITE)
        self.imports = home.root / "imports"
        self.env = {"PYTHONPATH": str(site), "HOOK_IMPORTS": str(self.imports)}

    def warm(self):
        """The warm server up in this Home, its looker listening."""
        done = self.home.run("sh", "-c", 'python3 "$0" serve </dev/null >/dev/null 2>&1 &',
                             str(ROOT / "agentkit" / "warm.py"))
        self.assertEqual(done.code, 0, done.err)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.state)                # a socket by its name: a Home's path may be past 108 bytes
        deadline = time.monotonic() + BOUND
        while True:
            for looker in self.state.glob("*.look"):
                with socket.socket(socket.AF_UNIX) as probe:    # refused until it listens
                    if probe.connect_ex(looker.name) == 0:
                        return
            self.assertLess(time.monotonic(), deadline, "no looker came up")
            time.sleep(0.05)

    def fire(self, event, payload):
        """The event as the seat's harness tells its hook, in its pane: the fact standing once
        the hook has returned."""
        fired = self.hooks.fire(event, payload, seat=NAME, pane=self.seat, env=self.env)
        self.assertEqual((fired.code, fired.said), (0, []), fired.err)
        return json.loads(self.fact.read_text()) if self.fact.exists() else None

    def asked(self):
        """A question goes up, and its word comes: the fact it left."""
        fact = self.fire("PermissionRequest", {"tool_name": "Bash",
                                               "tool_input": {"command": "ls"}})
        self.assertEqual({key: fact.get(key) for key in ("session", "event", "kind", "text")},
                         {"session": NAME, "event": "PermissionRequest", "kind": "Bash",
                          "text": ""})
        deadline = time.monotonic() + BOUND
        while "needs you" not in self.home.tmux("show-options", "-qv", "-t", f"={NAME}:",
                                                "set-titles-string").out:
            self.assertLess(time.monotonic(), deadline, "the word never came")
            time.sleep(0.05)
        return fact

    def notice(self):
        """Claude's permission notice, seconds after the question it adds nothing to."""
        return self.fire("Notification", {"notification_type": "permission_prompt",
                                          "message": "Claude needs your permission to use Bash"})

    def imported(self):
        return self.imports.read_text().splitlines() if self.imports.exists() else []

    def test_with_a_looker_up_no_python_the_hook_starts_imports_agentkit(self):
        self.warm()
        fact = self.asked()
        self.assertEqual(self.notice(), fact, "a notice meaning the same writes nothing")
        self.assertEqual(self.imported(), [])

    def test_with_no_looker_up_the_same_fact_and_word_come_cold(self):
        fact = self.asked()
        self.assertEqual(self.notice(), fact, "a notice meaning the same writes nothing")
        self.assertTrue(self.imported(), "the hook's own Python heard the event")


if __name__ == "__main__":
    unittest.main()
