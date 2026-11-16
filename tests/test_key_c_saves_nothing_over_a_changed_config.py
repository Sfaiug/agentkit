"""A key on `c` writes nothing over a config.toml another process changed since `c` read it: `c`
saves the config it holds whole, so it would take out what the other wrote, a model
`watch.follow_model` just added.  A page `c` opens reads the file again on no tick, so a key
there is read over a changed file however long the other took: Space on `Done check`'s `On`
leaves the added model and the setting in config.toml as they were and says the key was not
taken; Space again, the file unchanged since, turns it off, the model kept.

Black-box: the program `AK_BIN` names, in a terminal of its own (tests/fixtures/akterm.py), its
harnesses the fakes of tests/fixtures/fakeadapter.py; the other process is this test, which
adds a `[models.*]` table and puts the file in place as ak's save does.  Fails on an ak whose
Space writes the config `c` holds.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

ADDED = '\n[models."acme"]\nharness = "claude"\nmodel = "claude-acme-1"\neffort = "high"\n' \
        'provider = "anthropic"\n'
REFUSED = "config.toml changed since this screen read it"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CSavesNothingOverAChangedConfig(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.path = akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                               "astra": {"harness": "codex", "effort": "high"}})

    def add(self):
        """The other process's save: a model added, the file replaced whole."""
        new = self.path.with_name("config.toml.new")
        new.write_text(self.path.read_text() + ADDED)
        new.replace(self.path)

    def test_space_on_a_page_over_a_changed_config_is_not_taken(self):
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait("esc leave")
        term.keys("c", "j", "j", "j", "j", "j")      # the two models, Models, Subscriptions,
        term.wait("› Done check")                   # Discord
        term.keys("Enter")
        term.wait(lambda screen: "config · done check" in screen and "› On" in screen
                  and "● on" in screen)
        self.add()
        term.keys("Space")
        term.wait(REFUSED)
        cfg = akconfig.read(self.home)
        self.assertEqual(cfg["models"]["acme"]["model"], "claude-acme-1")
        self.assertNotIn("done_check", cfg)
        term.keys("Space")
        term.wait("○ off")
        cfg = akconfig.read(self.home)
        self.assertEqual(cfg["done_check"]["on"], False)
        self.assertEqual(cfg["models"]["acme"]["model"], "claude-acme-1")
        term.keys("Escape")
        term.wait("› Done check")
        term.keys("Escape")
        term.wait("esc leave")
        term.keys("Escape")
        self.assertEqual(term.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
