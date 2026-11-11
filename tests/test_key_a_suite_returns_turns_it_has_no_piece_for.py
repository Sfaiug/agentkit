"""Once a sharded suite has started its last piece, each turn a piece ends on goes to the host at
once, but the one the suite keeps for its reruns; while a piece still waits to start, a turn a
piece ends on goes to that piece.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  This host fits three pieces (AK_HOST_READINGS), so the suite holds three
heavy-suite turns and is cut in six, piece k/6 running test `k.sh` alone, which waits until the
test releases it, and a go of its named tests alone (`AK_ONLY`) until the test releases that.  The
test takes a turn as another suite would: a non-blocking flock on one of the host's slot files.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

READINGS = json.dumps({"cpus": 64, "free_mb": 1230, "mem_total_mb": 1230})
HELD = ('until [ -e "$(git rev-parse --git-common-dir)/release-$K${AK_ONLY:+-alone}" ]; '
        'do sleep 0.1; done\n')
RED = "test ! -f api.txt\n"     # fails on the member's tree, passes on the target's tip


class ASuiteReturnsTurnsItHasNoPieceFor(unittest.TestCase):
    def start(self, red=""):
        """The line's one member checked by a lander left running, piece 1/6 then failing with
        `red`, once its first three pieces run."""
        line = Line({f"t/{k}.sh": HELD.replace("$K", str(k)) + (red if k == 1 else "")
                     for k in range(1, 7)})
        self.addCleanup(line.close)
        self.line, self.home = line, line.home
        self.home.env.pop("AK_MAX_RUNS")     # heavy suite turns, which it turns off
        line.member({"api.txt": "x\n"})
        self.lander = self.home.spawn("run", "--lander", line.line,
                                      env={"AK_HOST_READINGS": READINGS})
        self.until(lambda: len(self.started()) == 3, "three pieces running")
        self.assertEqual(sorted(self.started()), ["1/6", "2/6", "3/6"])

    def started(self):
        return [run[1] for run in self.line.runs() if run[0] == "piece"]

    def release(self, *pieces):
        for k in pieces:
            (self.line.rig.path / ".git" / f"release-{k}").touch()

    def take(self):
        """One of the host's heavy-suite turns, held until the test ends, or None while every
        turn is held."""
        for path in sorted((self.home.path / ".agentkit" / "runs").glob(".heavy-*.lock")):
            slot = path.open("a")
            try:
                fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                slot.close()
                continue
            self.addCleanup(slot.close)
            return slot
        return None

    def until(self, check, what, pause=0.2):
        deadline = time.monotonic() + 300
        while not check():
            self.assertIsNone(self.lander.poll(), self.home.log("spawn-1.err").read_text())
            self.assertLess(time.monotonic(), deadline, f"never {what}")
            time.sleep(pause)

    def landed(self):
        self.assertEqual(self.lander.wait(timeout=300), 0, self.home.log("spawn-1.err").read_text())

    def test_a_turn_goes_to_the_next_piece_and_once_none_waits_to_the_host(self):
        self.start()
        self.release(1)

        def fourth():
            self.assertIsNone(self.take(), "a turn went to the host while a piece waited")
            return "4/6" in self.started()
        # without a pause: a turn the host had for a moment would show
        self.until(fourth, "piece 4/6 started", pause=0)
        self.release(2, 3)
        self.until(lambda: len(self.started()) == 6, "every piece started")
        self.release(4)
        self.until(self.take, "a turn given back")
        self.assertIsNone(self.lander.poll(), "pieces 5/6 and 6/6 still run")
        self.release(5, 6)
        self.landed()
        self.assertIn("land", self.line.verdict(1))

    def test_a_red_piece_reruns_its_tests_on_the_turn_the_suite_keeps_after_the_others_end(self):
        self.start(RED)
        self.release(1, 2, 3)
        self.until(lambda: len(self.started()) == 6, "every piece started")
        self.release(4, 5)
        held = []

        def taken():
            if turn := self.take():
                held.append(turn)
            self.assertLess(len(held), 3, "the suite kept no turn for its reruns")
            return len(held)
        self.until(lambda: taken() == 2, "the turns of pieces 4/6 and 5/6 given back")
        self.assertNotIn(("alone", ""), self.line.runs(), "piece 1/6's tests reran before 6/6 ended")
        self.release(6)
        self.until(lambda: taken() and ("alone", "") in self.line.runs(),
                   "piece 1/6's failed tests rerun")
        self.assertIsNone(self.take(), "the rerun runs on a turn the suite holds")
        self.release("1-alone")
        for turn in held:
            turn.close()
        self.landed()
        self.assertEqual(self.line.verdict(1)["fix"]["tests"], ["1.sh"])


if __name__ == "__main__":
    unittest.main()
