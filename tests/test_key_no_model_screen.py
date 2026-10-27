"""On `c` a model's label is no stop: ← on a row's first mark stays there, so Space flips that
mark and no screen of the model's own opens.

Before, ← reached the label and Enter opened `config · <model>`, which only repeated what the
matrix and `Models` set.  Black-box: the program `AK_BIN` names, in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, judged by
what the terminal shows and config.toml; this test fails against `/bin/false`.  The terminal
has no colour (NO_COLOR).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal
from test_key_models_page_defaults import (FABLE_LISTED, MAIN_KEYS, MARK_KEYS, key_line, lines,
                                           orch_mark)


def mark(screen, label):
    """`label`'s orchestrator mark, the brackets that show the keys on it without colour aside."""
    return orch_mark(screen, label).strip("[]")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NoModelScreen(unittest.TestCase):
    def test_left_on_the_first_mark_stays_and_enter_flips_it(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", FABLE_LISTED)
        akconfig.write(home, {"fable": "claude", "astra": {"harness": "codex", "effort": "high"}},
                       workers=["fable", "astra"])
        term = Terminal(home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == MARK_KEYS and "› Fable 5.1" in screen)
        term.keys("Down")
        term.wait(lambda screen: "› GPT-6-Astra" in screen)
        term.keys("Left", "Space")
        screen = term.wait(lambda screen: "config · GPT-6-Astra" in screen
                           or mark(screen, "GPT-6-Astra") == "●")
        self.assertEqual(lines(screen)[0].split()[:-1], ["agentkit", "·", "config"], screen)
        self.assertEqual(mark(screen, "GPT-6-Astra"), "●")
        self.assertEqual(akconfig.read(home)["defaults"]["orchestrator"], "astra")


if __name__ == "__main__":
    unittest.main()
