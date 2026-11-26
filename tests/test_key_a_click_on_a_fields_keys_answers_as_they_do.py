"""A click on a field's key line answers as its key does: `⏎ save` takes what was typed, as
Enter does, and `esc back` goes back with nothing taken, as Esc does.

Black-box: AK_BIN's menu in a terminal (tests/fixtures/akterm.py) under a temporary HOME,
judged by what it shows; NO_COLOR.  The field is `+ add a machine`'s on `c`, typed the name of a
machine config.toml has already, which ak refuses without asking anything.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

ADD, NAME = "+ add a machine", "acme-linux"
REFUSED = f"{NAME} is a machine already"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClickOnAFieldsKeys(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass")
        akconfig.write(home, ["fable"], extra=f"\n[machines.{NAME}]\n")
        self.term = Terminal(home, "attach", "--overlay", size=(120, 40), env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen and ADD in screen)
        self.term.keys("Down", "Down", "Enter")     # past this one and acme-linux, then open
        self.term.wait("⏎ save")
        self.term.type(NAME)

    def click(self, item):
        """A click on the key line's `item` once the field shows the name typed."""
        screen = self.term.wait(lambda text: NAME in map(str.strip, text.splitlines()))
        row, line = next(at for at in enumerate(screen.splitlines(), 1) if item in at[1])
        at = f"{line.index(item) + 1};{row}"
        self.term.type(f"\x1b[<0;{at}M\x1b[<0;{at}m")

    def test_a_click_on_save_takes_what_was_typed(self):
        self.click("⏎ save")
        self.term.wait(REFUSED)

    def test_a_click_on_back_goes_back_with_nothing_taken(self):
        self.click("esc back")
        screen = self.term.wait(lambda text: "⏎ save" not in text and f"› {ADD}" in text)
        self.assertNotIn(REFUSED, screen)


if __name__ == "__main__":
    unittest.main()
