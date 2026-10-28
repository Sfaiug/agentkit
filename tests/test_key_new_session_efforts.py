"""A new session's models screen (`n`, then Tab) is `c`'s: each marked role's effort beside its
mark, at [defaults]' efforts, stepped there for the new seat alone; its record holds them, its
harness is launched at its orchestrator's, and the config is left as it was.

The owner (27 Oct 2026): "In the config screen, we have a new feature to change effort depending
on role, now this feature does not exist when creating a new session. Fix this."  Black-box: the
program `AK_BIN` names, its menu in a person's terminal (tests/fixtures/akterm.py), its harnesses
the fakes of tests/fixtures/fakeadapter.py, judged by the terminal, the seat's record, the config
file and the launches its harness is asked for.
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
KEYS = "  ↑↓←→ move   ␣ mark   ⏎ start   esc back"
EFFORTS = {"effort": "low", "exec_effort": "high", "review_effort": "medium"}


def opus(screen):
    """Opus 5.5's line from its marks on, the highlight's `›` off."""
    return next(line.lstrip("› ").split()[2:] for line in screen.split("\n")
                if line.lstrip("› ").startswith("Opus 5.5"))


def key_line(screen):
    return next((line.rstrip() for line in reversed(screen.split("\n")) if line.strip()), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewSessionEfforts(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        self.config = akconfig.write(self.home, {"opus": EFFORTS})    # its workers review
        self.menu = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.menu.wait("esc leave")
        self.menu.keys("n")
        self.menu.wait(ROW_KEYS)
        self.menu.type("fix-api")
        self.menu.keys("Tab")
        self.screen = self.menu.wait(lambda screen: key_line(screen) == KEYS
                                     and "Opus 5.5" in screen)

    def started(self):
        """The record of the seat fix-api, once it is made."""
        path = self.home.path / ".agentkit/state/session-fix-api.json"
        deadline = time.monotonic() + 30
        while not path.exists():
            self.assertLess(time.monotonic(), deadline,
                            f"fix-api never started; the terminal shows:\n{self.menu.screen()}")
            time.sleep(0.05)
        return json.loads(path.read_text())

    def test_each_marked_role_shows_its_effort_beside_its_mark(self):
        self.assertEqual(opus(self.screen), [
            "[●]", "▰▱▱▱▱", "low", "■", "▰▰▰▱▱", "high", "■", "▰▰▱▱▱", "medium"])

    def test_a_reviewer_effort_stepped_is_the_new_seat_s_and_the_config_s_bytes_stay(self):
        before = self.config.read_bytes()
        self.menu.keys(*["Right"] * 5)          # past each mark and effort to the review one
        self.menu.wait(lambda screen: key_line(screen) == KEYS.replace("mark", "step"))
        self.menu.keys("Space")
        self.menu.wait(lambda screen: opus(screen)[-3:] == ["■", "▰▰▰▱▱", "high"])
        self.menu.keys("Escape")
        self.menu.wait(ROW_KEYS)
        self.menu.keys("Enter")
        self.assertEqual(self.started()["efforts"]["opus"], {**EFFORTS, "review_effort": "high"})
        self.assertEqual(self.config.read_bytes(), before)

    def test_the_orchestrator_effort_stepped_launches_the_seat_at_it(self):
        self.menu.keys("Right", "Space")
        self.menu.wait(lambda screen: opus(screen)[1:3] == ["▰▰▱▱▱", "medium"])
        self.menu.keys("Enter")                  # on the effort: the session starts
        self.assertEqual(self.started()["efforts"]["opus"]["effort"], "medium")
        deadline = time.monotonic() + 30
        while not self.fakes["claude"].calls("interactive"):
            self.assertLess(time.monotonic(), deadline, "the seat's harness was never launched")
            time.sleep(0.1)
        self.assertEqual(self.fakes["claude"].calls("interactive")[-1]["argv"][:2],
                         ["claude-opus-5-5", "medium"])


if __name__ == "__main__":
    unittest.main()
