"""The line naming a seat's crew names each role, then the models in it.

`build`, then `review`, each followed by the models in it at the effort each runs that role at,
joined by `, `, the roles three cells apart; one `build and review:` where both hold the same
models at the same efforts; a role nobody is in left out.  It never names the orchestrator, which
its row already does, and a seat with nobody beside its orchestrator opens no such line.  No glyph
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
LINES = {"fix-api": "build: Vega low, Fable 5.1 low   review: Fable 5.1 low, Lyra low",
         "same": "build and review: Vega low, Fable 5.1 low",
         "split": "build: Fable 5.1 medium   review: Fable 5.1 high"}


# The owner's pick of 17 Nov 2026, in their words at menu.crew.
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheCrewLinePutsRolesFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"opus": {"effort": "low"}, "fable": {"effort": "low"},
                              "vega": {"harness": "codex", "effort": "low"},
                              "lyra": {"harness": "claude", "effort": "low"}})
        Seat(home, "fix-api", record={"workers": ["vega", "fable"], "reviewers": ["fable", "lyra"]})
        Seat(home, "same", record={"workers": ["vega", "fable"]})
        Seat(home, "split", record={"workers": ["fable"], "efforts": {
            "fable": {"effort": "low", "exec_effort": "medium", "review_effort": "high"}}})
        Seat(home, "calm", record={"workers": []})        # names nobody beside its orchestrator
        cls.menus = {}
        for name, locale in (("utf-8", {}), ("C", C)):
            done = home.ak(input="\n", env={"COLUMNS": str(WIDTH), **locale})
            assert done.code == 0, done.err
            cls.menus[name] = done.out
        cls.bars = {name: cls.bar(name, locale)
                    for name, locale in (("fix-api", {}), ("same", C), ("split", {}))}

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

    def test_each_role_names_its_models_and_never_the_orchestrator(self):
        for menu in self.menus:
            for name, line in LINES.items():
                self.assertEqual(self.under(menu, name).strip(), line, (menu, name))
        for name, line in self.bars.items():
            self.assertRegex(line, rf"^ *{re.escape(LINES[name])} +{re.escape(KEY)}$", name)
            self.assertNotIn("Opus", line)
            self.assertNotIn("orchestrates", line)

    def test_a_seat_with_nobody_beside_its_orchestrator_opens_no_crew_line(self):
        for menu in self.menus:
            self.assertRegex(self.under(menu, "calm"), r"^$|^[›> ] \d+  ")   # the gap, or a row


if __name__ == "__main__":
    unittest.main()
