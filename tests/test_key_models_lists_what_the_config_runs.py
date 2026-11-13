"""`Models` lists under a harness every model the config runs there, its catalog listing it or not.

A model the config runs that its harness's catalog does not list had no row, so nothing on the
screen took it out though the page promises `■` for each model the config runs.  It is a `■` row
after the listed ones, named as every screen names it, and Space takes it out of config.toml and
back in as it was.  Black-box: the program `AK_BIN` names, in a person's terminal
(tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py, judged by
what the terminal shows and config.toml; this test fails against `/bin/false`.  The terminal has
no colour (NO_COLOR).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"
MARK_KEYS = "  ↑↓←→ move   ␣ mark   r recommended   a apply to all sessions   esc back"
# the claude adapter's `models` lists Fable and not Nova, which the config runs too
FABLE_LISTED = "claude-fable-5-1\tFable 5.1\tlow medium high xhigh max"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def key_line(screen):
    return next((line for line in reversed(lines(screen)) if line), "")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsListsWhatTheConfigRuns(unittest.TestCase):
    def test_a_model_its_catalog_does_not_list_has_a_row_space_takes_out_and_back(self):
        home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, claude="pass")
        fakes["claude"].answer("models", FABLE_LISTED)
        akconfig.write(home, {"fable": "claude",
                              "nova": {"harness": "claude", "model": "claude-nova-7-1"}})
        given = akconfig.read(home)
        term = Terminal(home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait(lambda screen: key_line(screen) == MAIN_KEYS)
        term.keys("c")
        term.wait(lambda screen: key_line(screen) == MARK_KEYS and "› Fable 5.1" in screen)
        term.keys("j", "j")
        term.wait(lambda screen: "› Models" in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: "› Claude Code  Fable 5.1, Nova 7.1" in lines(screen))
        term.keys("Enter")
        term.wait(lambda screen: "›   ■ Fable 5.1" in lines(screen)
                  and "    ■ Nova 7.1" in lines(screen))
        term.keys("j", "Space")
        term.wait(lambda screen: "›   □ Nova 7.1" in lines(screen))
        self.assertNotIn("nova", akconfig.read(home)["models"])
        term.keys("Space")
        term.wait(lambda screen: "›   ■ Nova 7.1" in lines(screen))
        self.assertEqual(akconfig.read(home)["models"], given["models"])


if __name__ == "__main__":
    unittest.main()
