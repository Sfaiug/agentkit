"""A line's check waiting for a turn holds nothing an older ak reads as a reason to start no run.

A run keeps the version of ak it was admitted on and waits for its slot on it.  An ak from before
11 Nov 2026 (#3101) lets a run start only when it can take `runs/.heavy-landing.wait` for itself
alone, so a waiting check that held a share of it kept every such run out.

Black-box: `AK_BIN` checks two repositories' landing lines in one Home through
tests/fixtures/akline.py, on a host whose readings (AK_HOST_READINGS) show 8 idle cores and
memory to spare.  The first line's suite is on record at two cores a piece (`suite-<key>.json`
in the Home's state), so its pieces take every core, and the second line's check waits for a
turn.  Each test marks its start in its project's Git storage and runs until the test here
releases it.
"""

import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import SUITE, Line

HELD = """cd "$(git rev-parse --git-common-dir)" && touch "started-${0##*/}"
until [ -e release ]; do sleep 0.1; done
"""
READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 8, "load": 0, "free_mb": 64000})}
FIT = 4         # the first line's pieces the 8 cores fit at two cores each
# Seconds the second line's check has to reach its wait: a slow host only lets a fault pass.
MORE = 10


class AWaitingLineCheckHoldsNoStart(unittest.TestCase):
    def setUp(self):
        tests = {f"t/{name}.sh": HELD for name in "abcdef"}
        self.first = Line(tests)
        self.addCleanup(self.first.close)
        self.second = Line(tests, home=self.first.home, name="widgets")
        self.home = self.first.home
        self.home.env["AK_MAX_RUNS"] = ""   # heavy suite turns
        key = hashlib.sha256(f"{self.first.rig.path}\n{SUITE}".encode()).hexdigest()
        self.home.write(f".agentkit/state/suite-{key}.json", {"cpus": 2.0})
        for line in (self.first, self.second):
            line.member({"api.txt": f"{line.rig.name}\n"})
            self.addCleanup((self.storage(line) / "release").touch)

    @staticmethod
    def storage(line):
        return line.rig.path / ".git"

    def started(self, line):
        return len(list(self.storage(line).glob("started-*")))

    def checking(self, line):
        """Whether `line`'s checker has made its scratch checkout, as its repository lists it."""
        listed = line.rig.git("worktree", "list", "--porcelain").splitlines()
        return sum(entry.startswith("worktree ") for entry in listed) > 1

    def until(self, done, checker, seconds):
        deadline = time.monotonic() + seconds
        while not done() and checker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)

    def test_an_older_ak_finds_no_landing_check_waiting(self):
        first = self.home.spawn("run", "--lander", self.first.line, env=READINGS)
        self.until(lambda: self.started(self.first) >= FIT, first, 300)
        self.assertEqual(self.started(self.first), FIT)

        second = self.home.spawn("run", "--lander", self.second.line, env=READINGS)
        self.until(lambda: self.checking(self.second), second, 300)
        self.assertTrue(self.checking(self.second), "the second line's check never started")
        self.until(lambda: self.started(self.second), second, MORE)
        self.assertEqual(self.started(self.second), 0,
                         "the second line's check never waited for a turn")

        # Held to the end: no check of either line takes it, waiting or not.
        with (self.home.path / ".agentkit" / "runs" / ".heavy-landing.wait").open("a") as old:
            try:
                fcntl.flock(old, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.fail("a waiting line's check keeps an older ak from starting any run")
            for n, (line, checker) in enumerate(((self.first, first), (self.second, second)), 1):
                (self.storage(line) / "release").touch()
                self.assertEqual(checker.wait(timeout=300), 0,
                                 self.home.log(f"spawn-{n}.err").read_text())
                self.assertIn("land", line.verdict(1))
        self.assertTrue(self.started(self.second))


if __name__ == "__main__":
    unittest.main()
