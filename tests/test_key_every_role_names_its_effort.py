"""Every role's model is named with the effort the seat runs it at, as line one of its bar names
its orchestrator: on its menu row, on the line under it when highlighted, and on line two of its
bar.

The seat's record runs its orchestrator, executor and reviewer each at an effort of its own,
none of them config.toml's.  A model building and reviewing at one effort is named once with
both roles; at two, once for each; one running at `none` is named alone.  The menu's line stops
at its rows' edge, a bar's runs on.  Black-box: the program `AK_BIN` names runs in a person's
terminal (tests/fixtures/akterm.py) beside seats of tests/fixtures/akseat.py, the bar written by
`ak orch why`, as in test_key_bar_names_effort.py.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

OPENS = 60      # the first draw looks at every seat, which a loaded host makes slow
KEY = "Ctrl-b m  menu"
COLOURS = re.compile(r"\x1b\[[0-9;]*m")
CREW = ("Opus 5.5 xhigh orchestrates   Opus 5.5 medium builds   Fable 5.1 low builds, reviews   "
        "Opus 5.5 low reviews   Haiku 4.5 reviews")


def opened(screen, name):
    """The row of `name` while highlighted and the line under it, or None."""
    lines = [line.rstrip() for line in COLOURS.sub("", screen).splitlines()] + [""]
    at = next((n for n, line in enumerate(lines) if re.match(rf"› \d+  {name} ", line)), None)
    return None if at is None else (lines[at], lines[at + 1])


# The owner, 5 Nov 2026: "For all roles I want the effort to be displayed just like we have it
# for the orch in sessions right now."
@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EveryRoleNamesItsEffort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"opus": {"effort": "high"}, "fable": {"effort": "low"},
                              "haiku": {"harness": "claude", "model": "claude-haiku-4-5",
                                        "effort": "none"}})
        fakeadapter.install(home, claude="pass")
        Seat(home, "beta", record={"created": 1})
        Seat(home, "fix-api", record={
            "workers": ["opus", "fable"], "reviewers": ["fable", "opus", "haiku"],
            "efforts": {"opus": {"effort": "xhigh", "exec_effort": "medium",
                                 "review_effort": "low"}}})
        menu = Terminal(home, size=(100, 30), env={"TERM": "xterm"})
        menu.wait(lambda screen: "fix-api" in screen, bound=OPENS)
        menu.keys("j")          # the first row's line opens only once the highlight has moved
        cls.row, cls.under = opened(menu.wait(
            lambda screen: (opened(screen, "fix-api") or ("", ""))[1].strip()), "fix-api")
        menu.keys("Escape")
        menu.exit_code()
        bar = Terminal(home, "orch", "fix-api", size=(160, 30))
        bar.wait("fix-api")
        done = home.ak("orch", "why", "fix-api")
        assert done.code == 0, done.err
        cls.bar = [line.rstrip() for line in bar.wait(
            lambda screen: screen.rstrip().endswith(KEY)).rstrip("\n").split("\n")[-2:]]

    def test_the_menu_row_names_the_orchestrator_at_its_effort(self):
        self.assertRegex(self.row, r"^› \d+  fix-api +Opus 5\.5 xhigh  ")

    def test_the_line_under_the_row_names_each_builder_and_reviewer_at_its_effort(self):
        shown = self.under.strip()
        self.assertTrue(shown.endswith("…") and CREW.startswith(shown[:-1]), shown)
        self.assertIn("Fable 5.1 low builds, reviews", shown)

    def test_line_two_of_the_bar_names_each_builder_and_reviewer_at_its_effort(self):
        self.assertEqual(self.bar[0].split()[-3:], ["Opus", "5.5", "xhigh"])
        self.assertRegex(self.bar[1], rf"^ *{re.escape(CREW)} +{KEY}$")


if __name__ == "__main__":
    unittest.main()
