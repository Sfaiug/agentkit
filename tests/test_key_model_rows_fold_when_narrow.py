"""On `c`, a terminal where a model's role cells do not fit beside even one cell of its label draws
each role on a line of its own under the label, named there instead of over a column, so no row
wraps; the keys and the pointer act on the role whose line they are on, and a wider terminal has
its columns back.  Black-box: `AK_BIN` as the popup over an akseat.py seat in an akterm.py
terminal, its harnesses fakeadapter.py's; it fails against `/bin/false`."""

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

EFFORTS = {"effort": "medium", "exec_effort": "medium", "review_effort": "medium"}
FOLDED = ["› Opus 5.5",
          "    orch     [●]medium",
          "    builds    ■ medium",
          "    reviews   ■ medium"]


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def opus(screen):
    """The lines from Opus 5.5's label through its last role's, and the label's terminal row
    from 1; none under a screen that has no such label yet."""
    shown = lines(screen)
    at = next((row for row, line in enumerate(shown) if line.lstrip("› ") == "Opus 5.5"), None)
    return (shown[at:at + 4], at + 1) if at is not None else ([], 0)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelRowsFold(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        fakeadapter.install(self.home, claude="pass", codex="pass")
        Seat(self.home, "acme-fix", record={"reviewers": ["opus"], "efforts": {"opus": EFFORTS}})
        self.term = Terminal(self.home, "attach", "--overlay", size=(32, 60),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-fix"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: opus(screen)[0] == FOLDED)

    def stepped_to(self, **efforts):
        """Waits for the seat's record to hold EFFORTS with `efforts` changed."""
        path = self.home.path / ".agentkit/state/session-acme-fix.json"
        deadline = time.monotonic() + 30
        while json.loads(path.read_text())["efforts"]["opus"] != {**EFFORTS, **efforts}:
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)

    def test_the_keys_walk_the_folded_cells_and_step_the_role_they_are_on(self):
        self.term.keys("Right", "Right")
        self.term.wait(lambda screen: opus(screen)[0][2:] == ["    builds   [■]medium",
                                                              "    reviews   ■ medium"])
        self.term.keys("Right", "Space")
        self.stepped_to(exec_effort="high")
        self.term.wait(lambda screen: opus(screen)[0][1:] == ["    orch      ● medium",
                                                              "    builds    ■ high",
                                                              "    reviews   ■ medium"])

    def test_a_click_on_a_folded_effort_steps_that_role_alone(self):
        shown, label = opus(self.term.screen())
        column = shown[3].index("medium") + 1
        row = label + 3
        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        self.stepped_to(review_effort="high")
        self.term.wait(lambda screen: opus(screen)[0][1:] == ["    orch      ● medium",
                                                              "    builds    ■ medium",
                                                              "    reviews   ■ high"])

    def test_a_wider_terminal_has_the_columns_back(self):
        self.term.resize(100, 60)
        wide = self.term.wait(lambda screen: "builds" in screen and any(
            line.split() == ["orch", "builds", "reviews"] for line in lines(screen)))
        row = next(line for line in lines(wide) if line.lstrip("› ").startswith("Opus 5.5"))
        self.assertEqual([word for word in row.split() if word == "medium"], ["medium"] * 3, wide)
        self.term.resize(32, 60)
        self.term.wait(lambda screen: opus(screen)[0] == FOLDED)


if __name__ == "__main__":
    unittest.main()
