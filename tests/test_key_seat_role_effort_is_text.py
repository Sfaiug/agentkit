"""A seat record's build or review effort that is no text (a hand-edited null) is none of its own:
on the seat's `c` that role shows the model's effort, as one never set does, a step of that effort
leaves the role where it stood, and a mark still saves.  Black-box: `AK_BIN` as the popup over an
akseat.py seat in an akterm.py terminal, its harnesses fakeadapter.py's; it fails against
`/bin/false`."""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


def opus(screen):
    return next((line.split() for line in screen.split("\n")
                 if line.lstrip("› ").startswith("Opus 5.5")), [])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RoleEffortIsText(unittest.TestCase):
    def test_a_null_build_and_review_effort_stay_where_they_stood_and_a_mark_saves(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="pass", codex="pass")
        Seat(home, "acme-fix", record={"workers": ["opus"], "reviewers": ["opus"], "efforts": {
            "opus": {"effort": "low", "exec_effort": None, "review_effort": None}}})
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-fix"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane,
                        "sleep 86400", server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait(lambda screen: opus(screen)[3:] == [
            "[●]", "━────", "low", "■", "━────", "low", "■", "━────", "low"])
        term.keys("Right", "Space")                      # Opus's orchestrator effort
        term.wait(lambda screen: opus(screen)[3:6] == ["●", "━━───", "medium"])
        term.keys("Down", "Right", "Right", "Space")     # Astra's review mark saves the step too
        path = home.path / ".agentkit/state/session-acme-fix.json"
        stood = {"effort": "medium", "exec_effort": "low", "review_effort": "low"}
        deadline = time.monotonic() + 30
        while ((record := json.loads(path.read_text()))["reviewers"],
               record["efforts"]["opus"]) != (["opus", "astra"], stood):
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
