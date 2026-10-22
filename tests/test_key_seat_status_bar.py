"""A seat's own bar is its row on the ak screen with its line always open: two rows, no percent.

Inside a seat the owner reads what it is from its bar.  Line one is the seat's word, `! needs
you` or `● working`, then its name and the model that orchestrates it, and while it has a plan
the line of how much is done with its count, `1 of 2`: never a percentage or a finish estimate
(owner rules).  Line two is who builds and who reviews, with `Ctrl-b m  menu`, the one key, at
its right end; a click on line one's right end is bound, where other seats needing the owner
are named.  A read of the seat writes the bar, `ak orch why` and the tick alike.  Black-box:
the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before a seat of
tests/fixtures/akseat.py with a person's terminal of tests/fixtures/akterm.py attached by `ak
orch NAME`, judged by what that terminal shows and by the bindings ak's tmux holds.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

KEY = "Ctrl-b m  menu"


class Bar(unittest.TestCase):
    """A seat on `screen`, its terminal attached, then read once by `ak` with `READ`."""

    NAME = SCREEN = READ = None

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus"])     # the audit off: a tick opens no seat of its own
        cls.seat(cls.home)
        cls.terminal = Terminal(cls.home, "orch", cls.NAME, size=(100, 24))
        cls.terminal.wait(lambda screen: cls.NAME in screen)
        done = cls.home.ak(*cls.READ)
        assert done.code == 0, done.err
        cls.screen = cls.terminal.wait(lambda screen: screen.rstrip().endswith(KEY))

    @classmethod
    def seat(cls, home):
        Seat(home, cls.NAME, screen=cls.SCREEN)

    def bar(self):
        """Its two rows, at the bottom of the terminal."""
        return [row.rstrip() for row in self.screen.rstrip("\n").split("\n")[-2:]]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AQuestionSeat(Bar):
    NAME, SCREEN, READ = "acme", "claude-question-pane.txt", ("orch", "why", "acme")

    def test_line_one_is_its_word_its_name_and_its_model(self):
        self.assertRegex(self.bar()[0], r"^ *! needs you +acme +Opus 5\.5$")

    def test_line_two_is_who_builds_and_reviews_with_the_menu_key_at_its_end(self):
        line = self.bar()[1]
        self.assertRegex(line, r"^ *Opus 5\.5 ⚒◎ +" + KEY + "$")
        # against the terminal's right edge, whatever margin a build leaves there
        self.assertGreaterEqual(len(line), 100 - 2, line)

    def test_a_click_on_the_bar_s_right_end_is_bound(self):
        # a server's own defaults bind nothing there
        done = self.home.tmux("list-keys", "-T", "root", "MouseDown1StatusRight")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("MouseDown1StatusRight", done.out)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AWorkingSeatWithAPlan(Bar):
    NAME, SCREEN, READ = "wrk", "claude-working-pane.txt", ("watch",)

    @classmethod
    def seat(cls, home):
        super().seat(home)
        home.write(".agentkit/state/plan-wrk.md",
                   "- [x] the parser parses\n- [ ] the parser reports\n")

    def test_the_tick_draws_its_word_name_model_and_its_plan_as_a_count(self):
        self.assertRegex(self.bar()[0], r"^ *● working +wrk +Opus 5\.5 +\S+ 1 of 2$")
        self.assertRegex(self.bar()[1], r"^ *Opus 5\.5 ⚒◎ +" + KEY + "$")

    def test_no_row_of_the_bar_is_a_percentage(self):
        for row in self.bar():
            self.assertNotIn("%", row)

    def test_the_tick_titles_its_terminal_with_the_name_and_word_too(self):
        deadline, want = time.monotonic() + 30, "wrk · working"
        while True:
            title = self.home.tmux("display-message", "-p", "-t", self.terminal.pane,
                                   "#{pane_title}", server=SERVER).out.rstrip("\n")
            if title == want or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        self.assertEqual(title, want)


del Bar     # a base, not a case

if __name__ == "__main__":
    unittest.main()
