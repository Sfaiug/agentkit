"""A killed checker's folder in a run's folder goes at the next `ak run gc`, and a living
checker's stays through it.

Black-box: `AK_BIN` checks two landing lines in one Home through tests/fixtures/akline.py, each
suite one command, never split into pieces that end at once.  Each line's one test marks its
start in its project's Git storage and runs until the test here lets it end.  A checker's
folders are those its member's run folder gains once its suite started; the run is waiting in
its line, as a stopped lander leaves it.  The collection is boxed with a /tmp of its own
(`home.ak(boxed=True)`), on the host's processes.
"""

import os
from pathlib import Path
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import READINGS, Line, rules
from fixtures.garbage import ROOM

HELD = {"t/held.sh": """cd "$(git rev-parse --git-common-dir)" && touch started
until [ -e release ]; do sleep 0.1; done
""", "AGENTS.md": rules("sh suite.sh")}


class AKilledProcessSRunScratchGoes(unittest.TestCase):
    def setUp(self):
        self.one = Line(HELD)
        self.addCleanup(self.one.close)
        self.two = Line(HELD, home=self.one.home, name="widgets")
        for line in (self.one, self.two):
            line.member({"api.txt": f"{line.rig.name}\n"})
            self.addCleanup((line.rig.path / ".git" / "release").touch)

    def check(self, line):
        """A checker of `line`, left once its suite started, and the folders it made in its
        member's run folder."""
        before = self.folders(line)
        started = line.rig.path / ".git" / "started"
        checker = line.home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
        deadline = time.monotonic() + 300
        while not started.exists() and checker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(started.exists(), "the suite never started")
        made = self.folders(line) - before
        self.assertTrue(made)
        return checker, made

    def folders(self, line):
        return {path for path in line.members[0].iterdir() if path.is_dir()}

    def test_a_killed_checker_s_folder_goes_and_a_living_one_s_stays(self):
        killed, left = self.check(self.one)
        os.kill(killed.pid, signal.SIGKILL)
        killed.wait()
        self.assertTrue(all(path.is_dir() for path in left))
        living, own = self.check(self.two)

        done = self.one.home.ak("run", "gc", boxed=True, env=ROOM)
        self.assertEqual(done.code, 0, done.err)
        self.assertFalse(any(path.exists() for path in left))
        self.assertTrue(all(path.is_dir() for path in own))
        self.assertIsNone(living.poll())


if __name__ == "__main__":
    unittest.main()
