"""An open menu follows config.toml when another window changes it.

On 5 Nov 2026 the owner added a subscription (`c`, `+ add a subscription`) in one window while a
second had the menu open: that menu's usage block never showed it, though a menu opened after did
at once.  An open menu reads config.toml again whenever it changes on disk, whoever wrote it.

Black-box: the program `AK_BIN` names, its menu in a person's terminal
(tests/fixtures/akterm.py) over a temporary HOME whose ChatGPT is one subscription, its harnesses
the fakes of tests/fixtures/fakeadapter.py.  config.toml is then saved with a second, written
whole and moved into place as `add a subscription` saves it, then with an error, then with a
third, and nothing is typed.  Judged by the terminal; this test fails against `/bin/false`.
"""

import os
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MAIN_KEYS = "  ↑↓←→ move   ⏎ open   n new   c config   esc leave"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpenMenuFollowsTheConfig(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.config = akconfig.write(self.home, {"fable": "claude", "astra": "codex"})

    def save(self, text):
        """config.toml saved as `add a subscription` saves it: written whole, moved over it."""
        draft = self.config.with_suffix(".tmp")
        draft.write_text(text)
        os.replace(draft, self.config)

    def test_a_subscription_saved_elsewhere_shows_in_the_open_menu(self):
        menu = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", menu.pane,
                        "sleep 86400", server=SERVER)
        opened = menu.wait(lambda screen: MAIN_KEYS in screen and "ChatGPT" in screen)
        self.assertNotIn("ChatGPT II", opened)
        table = '[providers."openai"]\n'
        one = self.config.read_text()
        self.assertIn(table, one)
        self.save(one.replace(table, f'{table}accounts = ["default", "two"]\n', 1))
        menu.wait(lambda screen: "ChatGPT II" in screen and MAIN_KEYS in screen, bound=15)
        # a save that does not load, a hand edit's, leaves the menu on the last that did until
        # the next; two seconds outlast its next look, and a host too slow never sees it at all
        self.save(one + "[providers\n")
        time.sleep(2)
        held = menu.screen()
        self.assertIn("ChatGPT II", held)
        self.assertIn(MAIN_KEYS, held)
        self.save(one.replace(table, f'{table}accounts = ["default", "two", "three"]\n', 1))
        menu.wait(lambda screen: "ChatGPT III" in screen and MAIN_KEYS in screen, bound=15)


if __name__ == "__main__":
    unittest.main()
