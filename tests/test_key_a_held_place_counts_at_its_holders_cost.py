"""A held place counts for what its holder's pieces cost: a check fits its own pieces into what
the places another line's check holds leave of the host, each at that check's own cost.

Black-box: `AK_BIN` checks two repositories' landing lines in one Home through
tests/fixtures/akline.py, on a host whose readings (AK_HOST_READINGS) show 8 idle cores and
memory to spare.  The first line's suite is on record at two cores a piece (`suite-<key>.json`
in the Home's state), the second's at the initial estimate.  Each test marks its start in its
project's Git storage and runs until the test here releases it.
"""

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
# Seconds a check has to start a piece once it could: a slow start only hides a piece, so load
# can pass a fault here but never fail a fix.
MORE = 10


class AHeldPlaceCountsAtItsHoldersCost(unittest.TestCase):
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

    def test_a_check_waits_while_another_line_s_pieces_take_every_core(self):
        first = self.home.spawn("run", "--lander", self.first.line, env=READINGS)
        self.until(lambda: self.started(self.first) >= FIT, first, 300)
        self.until(lambda: self.started(self.first) > FIT, first, MORE)
        self.assertEqual(self.started(self.first), FIT)

        second = self.home.spawn("run", "--lander", self.second.line, env=READINGS)
        self.until(lambda: self.checking(self.second), second, 300)
        self.assertTrue(self.checking(self.second), "the second line's check never started")
        self.until(lambda: self.started(self.second), second, MORE)
        self.assertEqual(self.started(self.second), 0)

        for n, (line, checker) in enumerate(((self.first, first), (self.second, second)), 1):
            (self.storage(line) / "release").touch()
            self.assertEqual(checker.wait(timeout=300), 0,
                             self.home.log(f"spawn-{n}.err").read_text())
            self.assertIn("land", line.verdict(1))
        self.assertTrue(self.started(self.second))


if __name__ == "__main__":
    unittest.main()
