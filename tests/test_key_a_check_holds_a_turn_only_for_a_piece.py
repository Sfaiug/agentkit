"""A check's pieces at once are the turns it holds: one that started beside another line's check
runs as many pieces side by side as the host fits once that check ends.

Black-box: `AK_BIN` checks two repositories' landing lines in one Home through
tests/fixtures/akline.py, on a host whose readings (AK_HOST_READINGS) show 3 idle cores: four
pieces at the initial cost.  The first line's suite is on record at two cores a piece
(`suite-<key>.json` in the Home's state), so it runs one piece at a time and, while it does, the
second line's check has room for one of its own.  A test given `held` marks its start in its
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
READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 3, "load": 0, "free_mb": 16000})}
FIT = 4         # the second line's pieces the 3 idle cores fit at the initial cost
# Seconds a check has to start a piece where it could: a slow start only hides a piece, so load
# can pass a fault here but never fail a fix.
MORE = 10


class ACheckHoldsATurnOnlyForAPiece(unittest.TestCase):
    def setUp(self):
        # Two pieces: the first line's last holds its one place until released.
        self.first = Line({"t/a.sh": "true\n", "t/b.sh": HELD})
        self.addCleanup(self.first.close)
        self.second = Line({f"t/{name}.sh": HELD for name in "abcdef"}, home=self.first.home,
                           name="widgets")
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

    def until(self, done, checker, seconds):
        deadline = time.monotonic() + seconds
        while not done() and checker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)

    def landed(self, line, checker, n):
        (self.storage(line) / "release").touch()
        self.assertEqual(checker.wait(timeout=300), 0, self.home.log(f"spawn-{n}.err").read_text())
        self.assertIn("land", line.verdict(1))

    def test_a_check_started_beside_another_runs_what_the_host_fits_once_that_one_ends(self):
        first = self.home.spawn("run", "--lander", self.first.line, env=READINGS)
        self.until(lambda: self.started(self.first), first, 300)
        self.assertEqual(self.started(self.first), 1, "the first line's held piece never started")

        second = self.home.spawn("run", "--lander", self.second.line, env=READINGS)
        self.until(lambda: self.started(self.second), second, 300)
        self.until(lambda: self.started(self.second) > 1, second, MORE)
        self.assertEqual(self.started(self.second), 1)

        self.landed(self.first, first, 1)
        self.until(lambda: self.started(self.second) >= FIT, second, 300)
        self.assertEqual(self.started(self.second), FIT)
        self.landed(self.second, second, 2)


if __name__ == "__main__":
    unittest.main()
