"""The `c` screen's three role columns stand in the same place whatever is marked, at whatever
effort (the owner, 26 Nov 2026), wherever every model's name is whole beside them; a narrower
terminal keeps the names.  Black-box: `AK_BIN` as the popup over akseat.py seats in an akterm.py
terminal."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

MODELS = {"opus": {}, "haiku": {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}}
FULL = {"orchestrator": "opus", "workers": ["opus", "haiku"], "reviewers": ["opus", "haiku"],
        "efforts": {"opus": {"effort": "medium", "exec_effort": "low"}}}
BARE = {"orchestrator": "haiku", "workers": [], "reviewers": ["haiku"]}  # no builder, one effort


def heads(screen):
    return next(line for line in screen.splitlines() if line.split() == ["orch", "builds", "reviews"])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ColumnsStayInPlace(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, MODELS, orchestrator="opus", workers=["opus"], reviewers=["opus"])
        fakeadapter.install(self.home, claude="pass")

    def open_c(self, seat, record, columns):
        Seat(self.home, seat, record=record)
        term = Terminal(self.home, "attach", "--overlay", size=(columns, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": seat})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        return term.wait(lambda screen: "esc back" in screen and "Haiku 4.5" in screen)

    def test_the_heads_stand_where_they_stood_whatever_is_marked(self):
        for columns in (100, 60):       # with the bars, and where they have given way
            with self.subTest(columns=columns):
                self.assertEqual(heads(self.open_c(f"acme-bare-{columns}", BARE, columns)),
                                 heads(self.open_c(f"acme-full-{columns}", FULL, columns)))

    def test_on_40_cells_no_name_is_cut_for_a_word_no_mark_shows(self):
        self.open_c("acme-bare", BARE, 40)      # it waits for Haiku's whole name


if __name__ == "__main__":
    unittest.main()
