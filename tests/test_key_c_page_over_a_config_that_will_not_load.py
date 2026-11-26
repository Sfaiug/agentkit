"""A `c` page that reads config.toml itself, `Machines`, brings the owner back to `c` saying why
once the file will not load, open as it broke or opened after:
the menu stays up, one Esc on `c` leaves it, and nothing is written over the file.

Black-box: the program `AK_BIN` names, in a terminal of its own (tests/fixtures/akterm.py), its
harnesses the fakes of tests/fixtures/fakeadapter.py; the other process is this test, which
leaves a table unfinished and puts the file in place as ak's save does.  Fails on an ak whose
page lets the read's error end the menu.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CPageOverAConfigThatWillNotLoad(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass", codex="pass")
        self.path = akconfig.write(self.home, {"fable": {"harness": "claude", "effort": "xhigh"},
                                               "astra": {"harness": "codex", "effort": "high"}})
        self.broken = self.path.read_text() + "\n[unfinished\n"
        self.term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c", *["j"] * 6)     # the two models, Models, Subscriptions, Discord,
        self.term.wait("› Machines")        # Done check

    def breaks(self):
        """The other process's write: a table left unfinished, the file replaced whole."""
        new = self.path.with_name("config.toml.new")
        new.write_text(self.broken)
        new.replace(self.path)

    def back_on_c(self):
        """`c` up, saying why under its rows, and left with one Esc; the file as it was left."""
        self.term.wait(lambda screen: "› Machines" in screen and
                       " ".join(screen.split()).count(str(self.path)) == 2)   # its row too
        self.term.keys("Escape")
        self.term.wait("esc leave")
        self.term.keys("Escape")
        self.assertEqual(self.term.exit_code(), 0)
        self.assertEqual(self.path.read_text(), self.broken)

    def test_machines_open_as_the_file_breaks(self):
        self.term.keys("Enter")
        self.term.wait("+ add a machine")
        self.breaks()
        self.term.keys("j")
        self.back_on_c()

    def test_machines_opened_after(self):
        self.breaks()
        self.term.wait(lambda screen: str(self.path) in " ".join(screen.split()))
        self.term.keys("Enter")
        self.back_on_c()


if __name__ == "__main__":
    unittest.main()
