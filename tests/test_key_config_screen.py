"""`c` in the popup opens the config screen for the seat it is over, named over its headings and
laid out as a matrix of its roles, each marked one's effort beside its mark, and marking a role
there rewrites the seat's record at once.

The config screen is where a person changes which models a seat orchestrates, builds and
reviews with, so a person must read the same rows, marks and keys there, and a mark must land
in the seat's record, the one place its runs read their models from, not in the config's
defaults.  The seat's record names `opus`, a model this config no longer has: the screen
passes it over, and so does the record a mark writes.  The terminal has no colour (NO_COLOR),
so the cell the keys act on is drawn bracketed.  Black-box: the program `AK_BIN` names runs in
a tmux terminal through tests/fixtures/akterm.py, its harnesses are fakes logged in with no
meter to read, and this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

HEADS = "               orch                builds              reviews"
ROWS = ["Claude Code",
        "› Fable 5.1    [●] ▰▰▰▰▱   xhigh    □                   □",
        "Codex",
        "  GPT-6-Astra   ○                   ■  ▰▰▰▱▱▱  high     ■  ▰▰▰▱▱▱  high",
        "",
        "  Models",
        "  Subscriptions",
        "  Discord       not connected",
        # models by their full names, the line wrapped at a word under its value
        "  Weekly audit  off · orch Fable 5.1 · builds Fable 5.1, GPT-6-Astra · reviews Fable 5.1,",
        "                GPT-6-Astra",
        ""]
KEYS = "  ↑↓←→ move   ␣ mark   r recommended   esc back"   # a seat's, on a mark
MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   x stop   c config   esc leave"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def block(screen):
    """The screen's lines from the column heads on, the usage grid over them left out."""
    shown = lines(screen)
    return shown[shown.index(HEADS):] if HEADS in shown else []


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ConfigScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"fable": "claude", "astra": {"harness": "codex", "effort": "high"}},
                       orchestrator="fable")
        fakeadapter.install(home, claude="pass", codex="pass")
        cls.seat = Seat(home, "atoll-ask", model="fable", screen="claude-question-pane.txt",
                        record={"workers": ["opus", "astra"]})
        cls.record_path = home.path / ".agentkit/state/session-atoll-ask.json"

    def setUp(self):
        # each case starts from the record as the seat was opened with it
        self.home.write(".agentkit/state/session-atoll-ask.json", self.seat.record)
        self.term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": "atoll-ask"})
        self.term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
        self.term.keys("c")
        # the subscriptions are read before the matrix is drawn
        self.opened = self.term.wait(lambda screen: HEADS in lines(screen)
                                     and key_line(screen) == KEYS)

    def leave(self):
        """Esc back to the main screen, and Esc again leaves the menu."""
        self.term.keys("Escape")
        main = self.term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
        self.assertTrue(main.startswith("agentkit "), main)
        self.assertNotIn("config", lines(main)[0])
        self.term.keys("Escape")
        self.assertEqual(self.term.exit_code(), 0)

    def record(self):
        return json.loads(self.record_path.read_text())

    def test_c_opens_the_popups_seats_matrix_under_harness_headings(self):
        shown = lines(self.opened)
        self.assertEqual(shown[0].split()[:3], ["agentkit", "·", "config"], shown[0])
        # whom the marks are for, the popup's seat, is said over the heads
        self.assertEqual(shown[shown.index(HEADS) - 1], "  For  atoll-ask")
        self.assertGreater(shown.index(HEADS), 3, "the usage grid comes over the heads")
        self.assertEqual(block(self.opened)[1:len(ROWS) + 1], ROWS)
        # agentkit's build is read under the rows, whatever it is
        self.assertTrue(block(self.opened)[len(ROWS) + 1].startswith("  Version "), self.opened)
        self.leave()

    def test_the_key_line_names_what_space_and_enter_do_under_the_highlight(self):
        self.term.keys("Right")
        on_effort = self.term.wait("› Fable 5.1     ●  ▰▰▰▰▱   xhigh    □                   □")
        self.assertEqual(key_line(on_effort), KEYS.replace("mark", "step"))
        self.term.keys("Down", "Down")
        on_row = self.term.wait("› Models")
        self.assertEqual(block(on_row)[1:7],
                         [ROWS[0], "  Fable 5.1     ●  ▰▰▰▰▱   xhigh    □                   □",
                          *ROWS[2:5], "› Models"])
        self.assertEqual(key_line(on_row), KEYS.replace("␣ mark", "⏎ open"))
        self.leave()

    def test_marking_a_model_for_builds_rewrites_the_seats_record_at_once(self):
        defaults = akconfig.read(self.home)["defaults"]
        self.term.keys("Right", "Right")
        self.term.wait("› Fable 5.1     ●  ▰▰▰▰▱   xhigh   [□]                  □")
        self.term.keys("Space")
        self.term.wait("› Fable 5.1     ●  ▰▰▰▰▱   xhigh   [■] ▰▰▰▰▱   xhigh    □")
        deadline = time.monotonic() + 30
        while self.record().get("workers") != ["astra", "fable"] and time.monotonic() < deadline:
            time.sleep(0.05)
        saved = self.record()
        self.assertEqual((saved["orchestrator"], saved["workers"], saved["reviewers"]),
                         ("fable", ["astra", "fable"], ["astra"]))
        self.assertEqual(akconfig.read(self.home)["defaults"], defaults)
        self.leave()
        self.assertEqual(self.record()["workers"], ["astra", "fable"])


if __name__ == "__main__":
    unittest.main()
