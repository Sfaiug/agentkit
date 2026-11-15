"""A prompt is heard by the warm looker (`agentkit/looker.py`), as every other seat event is.

With the warm server up, the owner's prompt answering an open question prints that question as
its context once, its turn's start and its fact are down once the hook returns, the seat's word
reads working, and no Python the hook started imports agentkit.  With none up, the same output,
records and word, cold.

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
QUESTION = "Which schema should the parser read?"
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
class PromptWarm(unittest.TestCase):
    def setUp(self):
        self.home = home = Home(tmux_log=False)
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        self.hooks = Hooks(home)
        self.seat = Seat(home, NAME, screen="claude-prompt-pane.txt")
        self.state = home.path / ".agentkit/state"
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

    def record(self, name):
        path = self.state / f"{name}-{NAME}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def word(self):
        return self.home.tmux("show-options", "-qv", "-t", f"={NAME}:", "set-titles-string").out

    def answered(self):
        """The seat asks the owner, then the owner's prompt answers: what its hook printed, its
        turn's start and fact as it returned, and the seat's word reads working."""
        done = self.home.ak("notify", "needs", QUESTION, "--session", NAME,
                            env={"AK_NOTIFY_SINK": "off"})
        self.assertEqual(done.code, 0, done.err)
        fired = self.hooks.prompt("the new one", self.seat, env=self.env,
                                  session_id=self.seat.record["conversation"])
        turn, fact = self.record("stop"), self.record("hook")
        self.assertEqual(fired.code, 0, fired.err)
        answer, = fired.said
        self.assertEqual(answer["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertEqual(answer["hookSpecificOutput"]["additionalContext"].count(QUESTION), 1)
        self.assertEqual(turn, {"session": NAME, "turn": turn["turn"], "blocks": 0})
        self.assertEqual(fact, {"session": NAME, "event": "UserPromptSubmit", "kind": "",
                                "text": "", "at": turn["turn"]})
        deadline = time.monotonic() + BOUND
        while "working" not in self.word():
            self.assertLess(time.monotonic(), deadline, f"the word never came: {self.word()!r}")
            time.sleep(0.05)

    def imported(self):
        return self.imports.read_text().splitlines() if self.imports.exists() else []

    def test_with_a_looker_up_no_python_the_hook_starts_imports_agentkit(self):
        self.warm()
        self.answered()
        self.assertEqual(self.imported(), [])

    def test_with_no_looker_up_the_same_output_records_and_word_come_cold(self):
        self.answered()
        self.assertTrue(self.imported(), "the hook's own Python heard the prompt")


if __name__ == "__main__":
    unittest.main()
