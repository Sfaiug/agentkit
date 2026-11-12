"""A landing check that holds no heavy-suite turn takes the next that fits it, before an older
line's check takes one more for its pieces; turns past each check's first go to the longest wait.

Black-box: `AK_BIN` checks two projects' landing lines in one Home through
tests/fixtures/akline.py, on a host that fits three pieces (AK_HOST_READINGS), so each suite is
cut in six, each piece running one test that waits until the test releases its project.  The
test holds two of the host's turns at first, as other suites would: flocks on its slot files.  A
check waiting for a turn, a first one or more for its pieces, holds a wait file of its own in the
Home's runs (`.landing-wait-*`).
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 64, "free_mb": 1230, "mem_total_mb": 1230})}
HELD = 'until [ -e "$(git rev-parse --git-common-dir)/release" ]; do sleep 0.1; done\n'


class ALandingCheckSFirstTurnWaitsForRoom(unittest.TestCase):
    def setUp(self):
        tests = {f"t/{k}.sh": HELD for k in range(1, 7)}
        self.older = Line(tests)
        self.addCleanup(self.older.close)
        self.younger = Line(tests, home=self.older.home, name="widgets")
        self.home = self.older.home
        self.home.env.pop("AK_MAX_RUNS")     # heavy suite turns, which it turns off
        for line in (self.older, self.younger):
            line.member({"api.txt": f"{line.rig.name}\n"})
            self.addCleanup(self.release, line)
        self.runs = self.home.path / ".agentkit" / "runs"
        self.turns = [self.hold(k) for k in range(2)]
        self.checkers = []

    def hold(self, k):
        """The host's turn `k`, held as another suite holds it."""
        turn = (self.runs / f".heavy-{k}.lock").open("a")
        self.addCleanup(turn.close)
        fcntl.flock(turn, fcntl.LOCK_EX)
        return turn

    @staticmethod
    def release(line):
        (line.rig.path / ".git" / "release").touch()

    def check(self, line):
        self.checkers.append(self.home.spawn("run", "--lander", line.line, env=READINGS))

    @staticmethod
    def pieces(line):
        return sum(run[0] == "piece" for run in line.runs())

    def until(self, done, what):
        deadline = time.monotonic() + 300
        while not done():
            for n, checker in enumerate(self.checkers, 1):
                self.assertIsNone(checker.poll(), self.home.log(f"spawn-{n}.err").read_text())
            self.assertLess(time.monotonic(), deadline, f"never {what}")
            time.sleep(0.2)

    def test_a_check_holding_no_turn_takes_one_before_an_older_check_takes_more(self):
        self.check(self.older)
        self.until(lambda: self.pieces(self.older), "the older check's first piece started")
        self.check(self.younger)
        self.until(lambda: len(list(self.runs.glob(".landing-wait-*"))) == 2,
                   "the younger check waiting for a turn beside the older one's pieces")

        self.turns.pop().close()
        self.until(lambda: self.pieces(self.younger) or self.pieces(self.older) > 1,
                   "the freed turn taken")
        self.assertEqual(self.pieces(self.older), 1,
                         "the older suite took a second turn while the younger check held none")

        self.turns.pop().close()
        self.until(lambda: self.pieces(self.older) > 1 or self.pieces(self.younger) > 1,
                   "the second freed turn taken")
        self.assertEqual((self.pieces(self.older), self.pieces(self.younger)), (2, 1),
                         "the younger suite's second piece went before the older one's")

        for n, line in enumerate((self.older, self.younger), 1):
            self.release(line)
            self.assertEqual(self.checkers[n - 1].wait(timeout=300), 0,
                             self.home.log(f"spawn-{n}.err").read_text())
            self.assertIn("land", line.verdict(1))


if __name__ == "__main__":
    unittest.main()
