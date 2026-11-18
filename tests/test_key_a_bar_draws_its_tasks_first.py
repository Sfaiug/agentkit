"""A seat's bar draws its tasks first: line two opens with their squares, then the crew.

The squares are the only place a task's state shows, so they stand where a narrow client keeps
them: three cells before who builds and reviews, the key at the line's right end.  Where both do
not fit beside the key, the crew is cut with one `…` and the squares and the key stay whole.
Black-box: a person attaches to a seat of tests/fixtures/akseat.py by `AK_BIN`'s `ak orch NAME`
(tests/fixtures/akterm.py), two runs start in flight, records like those `ak run` writes, and
`ak orch why` writes its bar, read on a wide client and then on one too narrow for all three.
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
CREW = "build: Spark 1.3 Contributor xhigh   review: Opus 5.5 xhigh"
KEY = "Ctrl-b m  menu"
SQUARES = "■□□  ■■□"    # one building, one in review
WIDE = re.compile(rf"^ *{SQUARES}   {re.escape(CREW)} +{re.escape(KEY)}$")
NARROW = re.compile(rf"^ *{SQUARES}   (.+)… *{re.escape(KEY)}$")


def line_two(screen):
    return screen.rstrip("\n").split("\n")[-1].rstrip()


# The owner's pick of 17 Nov 2026: `■■□   build: Opus 5.5 xhigh, …   Ctrl-b m  menu`.
@unittest.skipUnless(REAL_TMUX and Path("/proc/stat").exists(), "no tmux, or no /proc")
class ABarDrawsItsTasksFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "spark"])
        loop = subprocess.Popen(["sleep", "600"])
        cls.addClassCleanup(loop.wait)
        cls.addClassCleanup(loop.kill)
        Seat(home, "fix-api", screen="claude-working-pane.txt",
             record={"workers": ["spark"], "reviewers": ["opus"]})
        cls.seat = Terminal(home, "orch", "fix-api", size=(100, 30))
        cls.seat.wait("fix-api", bound=OPENS)     # attached: Go opens no seat with runs in flight
        for run, step in (("0900-aaaa", "executor"), ("0901-bbbb", "reviewer")):
            home.write(f".agentkit/runs/20261117-{run}/run.json",
                       {"state": "running", "step": step, "launched_session": "fix-api",
                        "started_at": time.time(), **owner(loop.pid)})
        written = home.ak("orch", "why", "fix-api")
        assert written.code == 0, written.err

    def test_a_wide_client_draws_the_squares_then_the_crew_then_the_key(self):
        self.seat.resize(100, 30)
        self.seat.wait(lambda screen: WIDE.match(line_two(screen)), bound=OPENS)

    def test_a_narrow_client_keeps_the_squares_and_the_key_whole_and_cuts_the_crew(self):
        self.seat.resize(60, 30)
        line = line_two(self.seat.wait(lambda screen: NARROW.match(line_two(screen)), bound=OPENS))
        cut = NARROW.match(line)[1]
        self.assertTrue(CREW.startswith(cut) and len(cut) < len(CREW), line)


if __name__ == "__main__":
    unittest.main()
