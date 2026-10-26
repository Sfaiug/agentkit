"""On `c`, each role a model is marked for shows that role's effort right after its mark, and no
column heads a single effort; a step on one, by Enter or a click on its bar, changes that role's
key alone, in the seat's record.

The owner (24 Oct 2026): the matrix shows and sets the orchestrating, building and reviewing
efforts.  Black-box: the program `AK_BIN` names, as the popup over a seat whose one model
orchestrates, builds and reviews at three efforts (tests/fixtures/akseat.py), in a person's
terminal (tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py,
judged by what the terminal shows and the seat's record; this test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

EFFORTS = {"effort": "low", "exec_effort": "high", "review_effort": "medium"}
KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   esc back"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def opus_row(screen):
    """Opus 5.5's line and its row on the terminal, counted from 1."""
    return next((line, number) for number, line in enumerate(lines(screen), 1)
                if line.lstrip("› ").startswith("Opus 5.5"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EffortBesideMark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seat = Seat(home, "acme-fix", model="opus",
                        record={"reviewers": ["opus"], "efforts": {"opus": EFFORTS}})

    def setUp(self):
        # each case starts from the record as the seat was opened with it
        self.home.write(".agentkit/state/session-acme-fix.json", self.seat.record)
        self.term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-fix"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.opened = self.term.wait(lambda screen: key_line(screen) == KEYS
                                     and "› Opus 5.5" in screen)

    def stepped_to(self, **efforts):
        """The record once its efforts are EFFORTS with `efforts` changed, waited on."""
        path = self.home.path / ".agentkit/state/session-acme-fix.json"
        deadline = time.monotonic() + 30
        while json.loads(path.read_text())["efforts"]["opus"] != {**EFFORTS, **efforts}:
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)

    def test_each_mark_has_its_role_s_effort_after_it_and_no_effort_column(self):
        row, _ = opus_row(self.opened)
        self.assertEqual(row.split()[3:], ["[●]", "▰▱▱▱▱", "low", "■", "▰▰▰▱▱", "high",
                                           "■", "▰▰▱▱▱", "medium"])
        [heads] = [line for line in lines(self.opened) if line.split()[:1] == ["orch"]]
        self.assertEqual(heads.split(), ["orch", "builds", "reviews"])

    def test_enter_steps_the_build_effort_and_a_click_takes_a_review_level(self):
        self.term.keys("Right", "Right", "Right", "Enter")    # past orch's effort, build's mark
        self.term.wait(lambda screen: opus_row(screen)[0].split()[8] == "xhigh")
        self.stepped_to(exec_effort="xhigh")
        row, y = opus_row(self.term.screen())
        bar = list(re.finditer("[▰▱]+", row))[2]             # the review effort's
        x = bar.start() + 5                                   # its fifth cell, from 1
        self.term.type(f"\x1b[<0;{x};{y}M")
        self.term.type(f"\x1b[<0;{x};{y}m")
        self.stepped_to(exec_effort="xhigh", review_effort="max")


if __name__ == "__main__":
    unittest.main()
