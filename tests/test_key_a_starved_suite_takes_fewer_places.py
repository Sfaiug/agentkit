"""A suite's cost counts what its pieces waited for a core: a suite whose pieces starved records
more than they spent, and its next run takes fewer places.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py on a host whose
readings (AK_HOST_READINGS) fit four pieces at the initial cost and give the seconds each box's
processes waited for a core.  Each test marks its start in the project's Git storage and runs
until the test here releases it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

HELD = """cd "$(git rev-parse --git-common-dir)" && touch "started-${0##*/}"
until [ -e release ]; do sleep 0.1; done
"""
# Seconds after a check's first piece starts by which the pieces beside it have started: a slow
# start only hides a place, so load can pass a fault here but never fail a fix.
TOGETHER = 10


class AStarvedSuiteTakesFewerPlaces(unittest.TestCase):
    def together(self, waited):
        """How many pieces each of two members' checks starts side by side, one after the other,
        on a host fitting four where each box's processes waited `waited` seconds for a core."""
        line = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        readings = {"AK_HOST_READINGS": json.dumps(
            {"cpus": 3, "load": 0, "free_mb": 16000, "cpu_wait_seconds": waited})}
        counts = []

        def started():
            return len(list(storage.glob("started-*")))

        for n in (1, 2):
            line.member({f"fix-{n}.txt": "x\n"})
            lander = home.spawn("run", "--lander", line.line, env=readings)
            deadline = time.monotonic() + 300
            while started() < 4 and lander.poll() is None and time.monotonic() < deadline:
                if started() and deadline - time.monotonic() > TOGETHER:
                    deadline = time.monotonic() + TOGETHER
                time.sleep(0.2)
            counts.append(started())
            (storage / "release").touch()
            self.assertEqual(lander.wait(timeout=300), 0, home.log(f"spawn-{n}.err").read_text())
            self.assertIn("land", line.verdict(n))
            for mark in (*storage.glob("started-*"), storage / "release"):
                mark.unlink()
        return counts

    def test_pieces_that_never_waited_keep_their_places(self):
        self.assertEqual(self.together(0), [4, 4])

    def test_pieces_that_waited_longer_than_the_check_leave_the_next_one_a_place(self):
        self.assertEqual(self.together(86400), [4, 1])


if __name__ == "__main__":
    unittest.main()
