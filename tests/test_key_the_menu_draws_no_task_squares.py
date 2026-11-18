"""The `ak` screen draws no task's squares: a row counts its tasks, the seat's bar draws them.

The owner, 17 Nov 2026: "on the menu screen, we never show the task status but just have the
'x task' indicator, and then when we open the seat it shows the actual task status".  So the line
a row opens names its crew alone, the row ends `· 2 tasks`, and the seat's bar holds each task's
squares, as `ak orch why` writes it and as a rename writes it again.  Black-box: `AK_BIN` from a
pipe, where every row opens, and in a person's terminal (tests/fixtures/akterm.py) with the row
highlighted and attached to the seat, beside tests/fixtures/akseat.py's seats and run records
like those `ak run` writes; fails on `/bin/false`.
"""

import re
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, owner
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

OPENS = 60      # a loaded host makes a first draw slow
UNDER = " " * 5     # an open line starts under the row's name
CREW = "build: Spark 1.3 Contributor xhigh   review: Opus 5.5 xhigh"
KEY = "Ctrl-b m  menu"
SQUARES = re.compile("[■□]")
COLOURS = re.compile(r"\x1b\[[0-9;]*m")


def opened(screen, name):
    """The row of `name` and the line under it, in the last draw on `screen`, or None."""
    lines = [line.rstrip() for line in COLOURS.sub("", screen).splitlines()] + [""]
    at = [n for n, line in enumerate(lines) if re.match(rf"[›> ] \d+  {name} ", line)]
    return (lines[at[-1]], lines[at[-1] + 1]) if at else None


def bar(name):
    """A test of a seat's screen: its bar names `name` and its line two holds both tasks'
    squares, one building and one in review, after its crew."""
    two = re.compile(rf"^ *{re.escape(CREW)}   ■□□  ■■□ +{re.escape(KEY)}$")

    def holds(screen):
        lines = ["", *screen.rstrip("\n").split("\n")]
        return name in lines[-2] and bool(two.match(lines[-1]))
    return holds


@unittest.skipUnless(REAL_TMUX and Path("/proc/stat").exists(), "no tmux, or no /proc")
class TheMenuDrawsNoTaskSquares(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "spark"])
        loop = subprocess.Popen(["sleep", "600"])
        cls.addClassCleanup(loop.wait)
        cls.addClassCleanup(loop.kill)
        made = int(time.time()) - 900
        Seat(home, "atlas", record={"created": made})
        Seat(home, "fix-api", screen="claude-working-pane.txt",
             record={"created": made + 60, "workers": ["spark"], "reviewers": ["opus"]})
        for run, step in (("0900-aaaa", "executor"), ("0901-bbbb", "reviewer")):
            home.write(f".agentkit/runs/20261117-{run}/run.json",
                       {"state": "running", "step": step, "launched_session": "fix-api",
                        "started_at": time.time(), **owner(loop.pid)})

    def test_from_a_pipe_no_row_opens_a_square(self):
        done = self.home.ak(input="\n", env={"COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        self.assertIsNone(SQUARES.search(done.out), done.out)
        row, line = opened(done.out, "fix-api") or ("", "")
        self.assertRegex(row, r" · 2 tasks$", done.out)
        self.assertEqual(line, UNDER + CREW)

    def test_on_a_terminal_the_highlighted_row_opens_its_crew_alone(self):
        menu = Terminal(self.home, size=(100, 30), env={"TERM": "xterm"})
        self.addCleanup(menu.exit_code)
        self.addCleanup(menu.keys, "Escape")
        menu.wait(lambda screen: opened(screen, "fix-api"), bound=OPENS)
        menu.keys("j")      # the first row's line opens only once the highlight has moved
        screen = menu.wait(lambda screen: (opened(screen, "fix-api") or ("", ""))[0]
                           .startswith("›") and opened(screen, "fix-api")[1].startswith(UNDER),
                           bound=OPENS)
        self.assertIsNone(SQUARES.search(screen), screen)
        row, line = opened(screen, "fix-api")
        self.assertRegex(row, r" · 2 tasks$")
        self.assertEqual(line, UNDER + CREW)

    def test_the_seats_bar_holds_both_tasks_squares_before_and_after_a_rename(self):
        written = self.home.ak("orch", "why", "fix-api")
        self.assertEqual(written.code, 0, written.err)
        seat = Terminal(self.home, "orch", "fix-api", size=(100, 30))
        seat.wait(bar("fix-api"), bound=OPENS)
        renamed = self.home.ak("orch", "rename", "fix-api", "acme-api")
        self.assertEqual(renamed.code, 0, renamed.err)
        seat.wait(bar("acme-api"), bound=OPENS)


if __name__ == "__main__":
    unittest.main()
