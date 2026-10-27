"""On a seat's `c` each role its one model is marked for shows that role's effort after its mark,
under no effort column, and Space on a build or review one, or a click on its bar, steps that
role's key alone in the seat's record (the owner, 24 Oct 2026).  Black-box: `AK_BIN` as the popup over an akseat.py
seat in an akterm.py terminal, its harnesses fakeadapter.py's; it fails against `/bin/false`."""

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


def opus(screen):
    """Opus 5.5's line, and its row on the terminal from 1."""
    return next((line, row) for row, line in enumerate(screen.split("\n"), 1)
                if line.lstrip("› ").startswith("Opus 5.5"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EffortBesideMark(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        fakeadapter.install(self.home, claude="pass", codex="pass")
        Seat(self.home, "acme-fix", record={"reviewers": ["opus"], "efforts": {"opus": EFFORTS}})
        self.term = Terminal(self.home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-fix"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.opened = self.term.wait(lambda screen: "esc back" in screen and "› Opus" in screen)

    def stepped_to(self, **efforts):
        """Waits for the seat's record to hold EFFORTS with `efforts` changed."""
        path = self.home.path / ".agentkit/state/session-acme-fix.json"
        deadline = time.monotonic() + 30
        while json.loads(path.read_text())["efforts"]["opus"] != {**EFFORTS, **efforts}:
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)

    def test_each_mark_has_its_role_s_effort_after_it_and_no_effort_column(self):
        self.assertEqual(opus(self.opened)[0].split()[3:], [
            "[●]", "▰▱▱▱▱", "low", "■", "▰▰▰▱▱", "high", "■", "▰▰▱▱▱", "medium"])
        heads = [line.split() for line in self.opened.split("\n") if line.split()[:1] == ["orch"]]
        self.assertEqual(heads, [["orch", "builds", "reviews"]])

    def test_space_steps_the_build_effort_and_a_click_takes_a_review_level(self):
        self.term.keys("Right", "Right", "Right", "Space")    # past orch's effort, build's mark
        self.stepped_to(exec_effort="xhigh")
        line, row = opus(self.term.wait(lambda screen: "xhigh" in opus(screen)[0]))
        column = list(re.finditer("[▰▱]+", line))[2].start() + 5   # the review bar's fifth
        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        self.stepped_to(exec_effort="xhigh", review_effort="max")


if __name__ == "__main__":
    unittest.main()
