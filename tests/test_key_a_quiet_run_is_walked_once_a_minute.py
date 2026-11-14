"""An open screen walks a quiet run's files once a minute, not on every read.

A run in `running` with no write for an hour had every file under it stat'ed on every read of the
screen, to say how long it went quiet: one run's left-behind sandbox made that 55,528 of an open
screen's 190,829 stats over two minutes.  Silence is told in hours, so a minute never shows.
A walk is what lists a directory deep in the run, which nothing else opens, and listing it moves
the directory's access time once that lies before its change time.  Black-box: the program
`AK_BIN` names runs in a person's terminal (tests/fixtures/akterm.py) beside
tests/fixtures/akseat.py's seat.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, owner
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from test_key_idle_screen_reads_only_what_changed import BOUND, row

SEAT = "acme"
QUIET = 2 * 3600
WATCHED = 150     # seconds: at one a minute three walks at most, however slow the host; a screen
                  # walking on every read, one every ten seconds, makes fifteen
AGED = 86400      # seconds back this sets the access time, so that a listing moves it


@unittest.skipUnless(REAL_TMUX, "no tmux")
class AQuietRunIsWalkedOnceAMinute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        repo, now = home.path / "code" / "acme", time.time()
        Seat(home, SEAT, cwd=repo, record={"created": int(now) - 7200})
        loop = subprocess.Popen(["sleep", "3600"])     # alive, or the screen ends the run
        cls.addClassCleanup(loop.wait)
        cls.addClassCleanup(loop.kill)
        run = ".agentkit/runs/20261022-0000-fix-it"
        cls.left = home.write(f"{run}/sandbox/left/behind.txt", "left\n", ago=QUIET).parent
        cls.walked()
        os.listdir(cls.left)
        if not cls.walked():
            raise unittest.SkipTest("this filesystem keeps no access times")
        home.write(f"{run}/run.json", {
            "run_id": "20261022-0000-fix-it", "title": "fix it", "launched_session": SEAT,
            "state": "running", "verdict": None, "merged": False, "step": "executor",
            "repo": str(repo), "started_at": now - QUIET, "finished_at": None,
            **owner(loop.pid)}, ago=QUIET)
        cls.menu = Terminal(home, "--client", size=(100, 40))
        cls.menu.wait(row(SEAT, "● working"), bound=BOUND)

    @classmethod
    def walked(cls):
        """Whether the sandbox was listed since this last asked."""
        seen = cls.left.stat()
        os.utime(cls.left, (time.time() - AGED, seen.st_mtime))
        return seen.st_atime > time.time() - AGED / 2

    def test_a_quiet_run_is_walked_once_a_minute(self):
        self.walked()
        walks, end = 0, time.monotonic() + WATCHED
        while time.monotonic() < end:
            time.sleep(1)
            walks += self.walked()
        self.assertTrue(1 <= walks <= 3, f"{walks} walks in {WATCHED} seconds")


if __name__ == "__main__":
    unittest.main()
