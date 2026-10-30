"""A line narrowing a red to the tests it named runs them at once, taking no heavy turn on this host;
a piece it has to run whole still waits for one.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  The line's first whole check stays on this host's one turn
(AK_HOST_READINGS fits no piece beside it) until the test queues for that turn, so the test holds
it from the moment the check lets go.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 4, "load": 0, "free_mb": 400})}
HOLD = """storage=$(git rev-parse --git-common-dir)
touch "$storage/reached"
until [ -f "$storage/go" ]; do sleep 0.1; done
"""


class ALinesNamedTestsTakeNoTurn(unittest.TestCase):
    def land(self, tests, culprit):
        """Two members land, the second adding `culprit`, which turns the line red: the line once
        checked, the first landing and the second sent to its fixer, and the suite's runs when
        its lander first said it waits for the turn the test holds."""
        line = Line(tests)
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        line.member({"api.txt": "x\n"})
        line.member(culprit)
        lander = home.spawn("run", "--lander", line.line, env=READINGS)

        def until(done, what):
            deadline = time.monotonic() + 300
            while not done():
                self.assertIsNone(lander.poll(), home.log("spawn-1.err").read_text())
                self.assertLess(time.monotonic(), deadline, what)
                time.sleep(0.2)

        until((storage / "reached").exists, "the line's whole check never ran")
        with (home.path / ".agentkit" / "runs" / ".heavy-0.lock").open("a") as turn:
            (storage / "go").touch()
            fcntl.flock(turn, fcntl.LOCK_EX)
            until(lambda: "heavy suite turn" in home.log("spawn-1.out").read_text(),
                  "the lander never waited for a turn")
            waiting = line.runs()
        self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertIn("land", line.verdict(1))
        self.assertIn("fix", line.verdict(2))
        return line, waiting

    def test_named_tests_go_at_once(self):
        line, waiting = self.land({"t/bad.sh": "test ! -f bad.txt\n", "t/hold.sh": HOLD},
                                  {"bad.txt": "x\n"})
        # the go confirming the red and the narrowing's: only the rebuilt stack's check waited
        self.assertEqual(waiting.count(("alone", "")), 2, waiting)
        self.assertEqual(line.verdict(2)["fix"]["tests"], ["bad.sh"])

    def test_a_piece_naming_no_test_waits_to_run_whole(self):
        # the culprit's own runner holds, then fails naming nothing, logging no run of its own
        line, waiting = self.land({"t/a.sh": "true\n", "t/b.sh": "true\n"},
                                  {"suite.sh": f"{HOLD}exit 1\n"})
        self.assertEqual(waiting, [])
        # the red piece on the stack ahead, then that stack's whole check starting
        self.assertEqual(line.runs()[:2], [("piece", "1/2", "")] * 2, line.runs())


if __name__ == "__main__":
    unittest.main()
