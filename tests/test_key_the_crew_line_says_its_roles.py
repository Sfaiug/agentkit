"""The line naming a seat's crew says in words who orchestrates, who builds and who reviews.

It opens with the seat's orchestrator, as its row names it, then names each model once at each
effort it runs at with what it does there after it: `orchestrates`, `builds`, `reviews`, in that
order, joined by `, `.  A seat with nobody beside its orchestrator opens no such line.  No glyph
stands for a role, so the line is the same in a C locale.  Black-box: `AK_BIN` from a pipe, where
every row opens, and on a seat's bar as a person attached to it sees it, written by
`ak orch why` (tests/fixtures/akterm.py), beside seats of tests/fixtures/akseat.py.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

WIDTH = 160
OPENS = 60      # a loaded host makes a first draw slow
KEY = "Ctrl-b m  menu"
C = {"LANG": "C", "LC_ALL": "C"}
# whole in the 95 cells a row's line has on the menu, whose rows stop at 100 columns
FOUR = ("Opus 5.5 low orchestrates   Vega low builds   Fable 5.1 low builds, reviews   "
        "Lyra low reviews")
TWO = "Opus 5.5 low orchestrates, reviews   Vega low builds"


# The owner, 10 Nov 2026, of ⚒ and ◎: the config screen's words in their place, and "also add it
# for orchestrates."
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheCrewLineSaysItsRoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"opus": {"effort": "low"}, "fable": {"effort": "low"},
                              "vega": {"harness": "codex", "effort": "low"},
                              "lyra": {"harness": "claude", "effort": "low"}})
        Seat(home, "fix-api", record={"workers": ["vega", "fable"], "reviewers": ["fable", "lyra"]})
        Seat(home, "web", record={"workers": ["vega"], "reviewers": ["opus"]})
        Seat(home, "calm", record={"workers": []})        # names nobody beside its orchestrator
        cls.menus = {}
        for name, locale in (("utf-8", {}), ("C", C)):
            done = home.ak(input="\n", env={"COLUMNS": str(WIDTH), **locale})
            assert done.code == 0, done.err
            cls.menus[name] = done.out
        cls.bars = {name: cls.bar(name, locale) for name, locale in (("fix-api", {}), ("web", C))}

    @classmethod
    def bar(cls, name, locale):
        """Line two of the seat's bar, written by `ak orch why` in `locale`, as one attached to
        the seat then sees it."""
        done = cls.home.ak("orch", "why", name, env=locale)
        assert done.code == 0, done.err
        term = Terminal(cls.home, "orch", name, size=(WIDTH, 30))
        return term.wait(lambda screen: screen.rstrip().endswith(KEY),
                         bound=OPENS).rstrip("\n").split("\n")[-1]

    def under(self, menu, name):
        """The line under `name`'s row on that menu."""
        lines = [line.rstrip() for line in self.menus[menu].splitlines()] + [""]
        at = next((n for n, line in enumerate(lines) if re.match(rf"[›> ] \d+  {name} ", line)),
                  None)
        self.assertIsNotNone(at, "\n".join(lines))
        return lines[at + 1]

    def test_each_of_four_is_named_once_with_its_effort_and_its_roles_the_orchestrator_first(self):
        self.assertEqual(self.under("utf-8", "fix-api").strip(), FOUR)
        self.assertRegex(self.bars["fix-api"], rf"^ *{re.escape(FOUR)} +{re.escape(KEY)}$")

    def test_an_orchestrator_that_reviews_at_its_effort_is_named_once_with_both(self):
        self.assertEqual(self.under("utf-8", "web").strip(), TWO)

    def test_a_seat_with_nobody_beside_its_orchestrator_opens_no_crew_line(self):
        for menu in self.menus:
            self.assertRegex(self.under(menu, "calm"), r"^$|^[›> ] \d+  ")   # the gap, or a row

    def test_no_screen_holds_a_role_glyph_and_a_c_locale_reads_the_same(self):
        for name in ("fix-api", "web"):
            self.assertEqual(self.under("C", name), self.under("utf-8", name), name)
        self.assertRegex(self.bars["web"], rf"^ *{re.escape(TWO)} +{re.escape(KEY)}$")
        for screen in (*self.menus.values(), *self.bars.values()):
            self.assertNotRegex(screen, "[⚒◎]")


if __name__ == "__main__":
    unittest.main()
