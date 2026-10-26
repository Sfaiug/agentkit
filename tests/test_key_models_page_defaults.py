"""Taking out on `Models` the model new seats orchestrate with moves its place to the first model
left, on `c` and in config.toml alike, and the weekly audit, which follows [defaults], with it.

Before, the place stayed with the model gone: no orchestrator mark was full, `Weekly audit` read
`unknown model`, and config.toml kept naming it.  Black-box: the program `AK_BIN` names, in a
person's terminal (tests/fixtures/akterm.py), its harnesses the fakes of
tests/fixtures/fakeadapter.py, judged by what the terminal shows and config.toml; this test
fails against `/bin/false`.  The terminal has no colour (NO_COLOR).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ choose   n new   x stop   c config   esc leave"
MARK_KEYS = "  ↑↓←→ move   ⏎ choose   r recommended   a apply to all sessions   esc back"
FABLE_LISTED = "claude-fable-5-1\tFable 5.1\tlow medium high xhigh max"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


def orch_mark(screen, label):
    """The orchestrator mark on `label`'s row of the matrix, the first mark after its name."""
    row = next(line for line in lines(screen) if line[2:].startswith(f"{label} "))
    return row[2 + len(label):].split()[0]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsPageDefaults(unittest.TestCase):
    def test_taking_out_new_seats_orchestrator_hands_its_place_to_the_first_model_left(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass", codex="pass")
        fakes["claude"].answer("models", FABLE_LISTED)
        akconfig.write(home, {"fable": "claude", "astra": {"harness": "codex", "effort": "high"}},
                       workers=["fable", "astra"])
        term = Terminal(home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
        term.keys("c")
        screen = term.wait(lambda screen: key_line(screen) == MARK_KEYS and "› Fable 5.1" in screen)
        self.assertIn("  For  new seats", lines(screen))
        term.keys("j", "j")
        term.wait(lambda screen: "› Models" in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: "› Claude Code  Fable 5.1" in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: "›   ■ Fable 5.1" in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: "›   □ Fable 5.1" in lines(screen))
        term.keys("Escape")
        term.wait(lambda screen: "› Claude Code" in screen and "■" not in screen)
        term.keys("Escape")
        screen = term.wait(lambda screen: key_line(screen) == MARK_KEYS and "› Models" in screen)
        self.assertEqual(orch_mark(screen, "GPT-6-Astra"), "●")
        self.assertFalse(any(line[2:].startswith("Fable 5.1 ") for line in lines(screen)), screen)
        self.assertIn("  Weekly audit  off · orch GPT-6-Astra · builds GPT-6-Astra · reviews "
                      "GPT-6-Astra", lines(screen))
        self.assertEqual(akconfig.read(home)["defaults"],
                         {"orchestrator": "astra", "workers": ["astra"]})


if __name__ == "__main__":
    unittest.main()
