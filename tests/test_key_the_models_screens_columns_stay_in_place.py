"""The `c` screen's three role columns stand in the same place whatever is marked (the owner,
26 Nov 2026).  Black-box: `AK_BIN` as the popup over akseat.py seats in an akterm.py terminal."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

MODELS = {"opus": {}, "haiku": {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}}


def heads(screen):
    return next(line for line in screen.splitlines() if line.split() == ["orch", "builds", "reviews"])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ColumnsStayInPlace(unittest.TestCase):
    def open_c(self, home, seat, record):
        Seat(home, seat, record=record)
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        return term.wait(lambda screen: "esc back" in screen and "Haiku 4.5" in screen)

    def test_the_heads_stand_where_they_stood_whatever_is_marked(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, MODELS, orchestrator="opus", workers=["opus"], reviewers=["opus"])
        fakeadapter.install(home, claude="pass")
        full = self.open_c(home, "acme-full", {
            "orchestrator": "opus", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
            "efforts": {"opus": {"effort": "medium", "exec_effort": "low"}}})
        bare = self.open_c(home, "acme-bare", {
            "orchestrator": "haiku", "workers": [], "reviewers": ["haiku"]})
        self.assertEqual(heads(bare), heads(full))  # only an orchestrator, on a one-effort model


if __name__ == "__main__":
    unittest.main()
