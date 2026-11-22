"""⏎ on the models screen draws the why page at once: its plans' weeks (menu.plans_checked), which
took the owner seconds a provider on 16 Nov 2026, are computed off the drawing thread, and the
page is drawn again with them once they land; Esc leaves while they are still computed.

In this process, the models screen read off keys on a pipe as tests/test_hover.py reads it, its
answer stood in for and its why page too (menu.models_why: a heading, then a line of each week),
the computing of the weeks held back on an event.  Judged by the screens drawn.
"""

from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import menu
from fixtures.sandbox import Sandbox
from test_hover import ESC, run, texts

ENTER = b"\r"
HEADING, WEEK = "  why Alpha orchestrates", "  Max's week: no day checked yet"


class WhyOpensAtOnce(Sandbox):
    def setUp(self):
        super().setUp()
        said = [(role, {"name": "Alpha", "effort": "high"}, ("100.0", "$1.00"))
                for role in menu.quality.ROLES]
        empty = {role: {"choices": [], "others": [], "whys": {}} for role in menu.quality.ROLES}
        used = dict.fromkeys(menu.quality.ROLES, (None, None, {"provider": "acme", "yours": [],
                                                               "quality": 100.0}))
        for name, value in (("stored", {}), ("refresh", ({}, None)), ("answer", empty),
                            ("uses", used)):
            self.stack.enter_context(patch.object(menu.matrix, name, return_value=value))
        self.stack.enter_context(patch.object(menu, "models_said", return_value=said))
        self.stack.enter_context(patch.object(menu, "models_why", self.why))
        self.stack.enter_context(patch.object(menu, "plans_checked", self.checked))
        # the weeks held back till `let_go`, which a test may make the page's opening; else
        # they go as it ends
        self.opened, self.let_go = threading.Event(), threading.Event()
        self.addCleanup(self.let_go.set)

    def why(self, found, role, row, kept, unit, weeks, runs):
        """The page: its heading, then a line of each of `weeks`."""
        self.opened.set()
        return [HEADING, *("  " + menu.week_checked(*week) for week in weeks)]

    def checked(self, cfg, provider):
        # held on the drawing thread, as before this change, they would hold the page back
        if threading.current_thread() is threading.main_thread():
            raise AssertionError("the weeks are computed on the drawing thread")
        self.let_go.wait()
        return [("Max", [])]

    def drawn(self, *keys):
        """Each screen the models screen drew, read off `keys`, as its lines."""
        return [texts(grid) for grid in
                run(lambda: menu.models_screen(self.cfg, None, {}, {}), *keys)[1]]

    def test_enter_draws_the_why_without_its_weeks_and_again_once_they_land(self):
        self.let_go = self.opened
        pages = [lines for lines in self.drawn(ENTER, ESC) if HEADING in lines]
        self.assertNotIn(WEEK, pages[0])
        self.assertIn(WEEK, pages[-1])

    def test_esc_leaves_while_the_weeks_are_held_back(self):
        screens = self.drawn(ENTER + ESC)
        self.assertTrue(any(HEADING in lines for lines in screens))
        self.assertNotIn(HEADING, screens[-1])          # back on the models screen
        self.assertFalse(any(WEEK in lines for lines in screens))


if __name__ == "__main__":
    unittest.main()
