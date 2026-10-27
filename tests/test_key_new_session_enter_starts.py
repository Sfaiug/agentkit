"""On a new session's models screen (`n`, then Tab) Space marks a model and Enter starts the
session with the marks shown, without going back to the row.

The owner's rule (27 Oct 2026, docs/cli-design.md's Keys): Space changes the highlighted thing
in place, Enter goes forward.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, its menu on a terminal of tests/fixtures/akterm.py and its harness
tests/fixtures/fakeadapter.py's, so it holds whichever screen draws the models.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

ROW_KEYS = "  ⏎ start   tab models   esc back"
PICKER_KEYS = "  ↑↓←→ move   ␣ mark   ⏎ start   esc back"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EnterStarts(unittest.TestCase):
    """The defaults: fable orchestrates, fable and astra build and review."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        config = akconfig.write(self.home, {"fable": {}, "astra": {"effort": "high"}})
        config.write_text(config.read_text().replace(
            "[defaults]\n", '[defaults]\nreviewers = ["fable", "astra"]\n'))
        self.menu = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.menu.wait("esc leave")
        self.menu.keys("n")
        self.menu.wait(ROW_KEYS)
        self.menu.type("fix-api")
        self.menu.keys("Tab")
        self.screen = self.menu.wait(PICKER_KEYS)

    def started(self):
        """The record of the seat fix-api, once Enter on the models screen has made it."""
        path = self.home.path / ".agentkit/state/session-fix-api.json"
        deadline = time.monotonic() + 30
        while not path.exists():
            self.assertLess(time.monotonic(), deadline,
                            f"fix-api never started; the terminal shows:\n{self.menu.screen()}")
            time.sleep(0.05)
        return json.loads(path.read_text())

    def test_the_key_line_names_space_and_enter(self):
        self.assertEqual(self.screen.rstrip("\n").split("\n")[-1].rstrip(), PICKER_KEYS)

    def test_space_marks_and_enter_starts_with_that_mark(self):
        self.menu.keys("Right", "Down", "Space")    # astra no longer builds
        self.menu.wait("[□]")
        self.menu.keys("Enter")
        record = self.started()
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("fable", ["fable"], ["fable", "astra"]))

    def test_enter_starts_with_the_default_marks(self):
        self.menu.keys("Enter")
        record = self.started()
        self.assertEqual((record["orchestrator"], record["workers"], record["reviewers"]),
                         ("fable", ["fable", "astra"], ["fable", "astra"]))


if __name__ == "__main__":
    unittest.main()
