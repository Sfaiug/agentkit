"""A killed checker's scratch checkouts go when a checker next starts: of whichever line, before
it makes its own, and no living checker's.

Black-box: `AK_BIN` checks two landing lines in one Home through tests/fixtures/akline.py.  Each
line's one test marks its start in its project's Git storage and runs until the test here lets
it end.  A line's scratch checkouts are those its repository's `git worktree list` holds beside
the project's own clone.
"""

import os
from pathlib import Path
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import READINGS, Line

HELD = """cd "$(git rev-parse --git-common-dir)" && touch started
until [ -e release ]; do sleep 0.1; done
"""


class AKilledCheckerSScratchGoes(unittest.TestCase):
    def setUp(self):
        self.one = Line({"t/held.sh": HELD})
        self.addCleanup(self.one.close)
        self.two = Line({"t/held.sh": HELD}, home=self.one.home, name="widgets")
        for line in (self.one, self.two):
            line.member({"api.txt": f"{line.rig.name}\n"})
            self.addCleanup((line.rig.path / ".git" / "release").touch)

    def check(self, line):
        """A checker of `line`, left once its suite started."""
        started = line.rig.path / ".git" / "started"
        started.unlink(missing_ok=True)
        checker = line.home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
        deadline = time.monotonic() + 300
        while not started.exists() and checker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(started.exists(), "the suite never started")
        return checker

    def scratches(self, line):
        """The line's scratch checkouts, as its repository lists them."""
        listed = line.rig.git("worktree", "list", "--porcelain").splitlines()
        return {Path(entry.removeprefix("worktree ")) for entry in listed
                if entry.startswith("worktree ")} - {line.rig.path}

    def test_the_next_checker_takes_a_killed_one_s_scratch_and_no_living_one_s(self):
        killed = self.check(self.one)
        left = self.scratches(self.one)
        os.kill(killed.pid, signal.SIGKILL)
        killed.wait()
        self.assertTrue(left)
        self.assertTrue(all(path.is_dir() for path in left))
        for path in left:   # as one killed before it unlocked its new checkout leaves it
            self.one.rig.git("worktree", "lock", str(path))

        living = self.check(self.two)
        self.assertEqual(self.scratches(self.one), set())
        self.assertFalse(any(path.exists() for path in left))
        own = self.scratches(self.two)
        self.assertTrue(own)
        self.assertTrue(all(path.is_dir() for path in own))

        self.check(self.one)
        self.assertEqual(self.scratches(self.two), own)
        self.assertTrue(all(path.is_dir() for path in own))
        self.assertIsNone(living.poll())


if __name__ == "__main__":
    unittest.main()
