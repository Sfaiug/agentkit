"""A check's piece starts beside another of its own only while the host's cores, less the threads
that want one now, leave room for it.

Black-box: `AK_BIN` checks a landing line through tests/fixtures/akline.py on a host whose
readings (AK_HOST_READINGS) fit four pieces at the initial cost and give the threads that want a
core as `cpu_wanted`.  Each test marks its start in the project's Git storage and runs until the
test here releases it.
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
CORES = 3
FIT = 4         # the pieces the host's readings fit at the initial cost
# Seconds more the rest of those FIT have to start once a check's first has: a slow start only
# hides a place, so load can pass a fault here but never fail a fix.
MORE = 10


class APlaceIsGivenByWhatThePiecesNeedNow(unittest.TestCase):
    def started_together(self, wanted):
        """How many pieces of a member's check start side by side while `wanted` threads want
        a core; the check lands once they are released."""
        line = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        line.member({"fix-1.txt": "x\n"})
        lander = home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": json.dumps(
            {"cpus": CORES, "load": 0, "free_mb": 16000, "cpu_wanted": wanted})})

        def started():
            return len(list(storage.glob("started-*")))

        for pieces, seconds in ((1, 300), (FIT, MORE)):
            deadline = time.monotonic() + seconds
            while started() < pieces and lander.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
        together = started()
        (storage / "release").touch()
        self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertIn("land", line.verdict(1))
        return together

    def test_pieces_run_one_after_another_while_the_threads_waiting_fill_the_cores(self):
        self.assertEqual(self.started_together(CORES), 1)

    def test_pieces_run_side_by_side_while_the_cores_have_room_for_one(self):
        self.assertEqual(self.started_together(CORES - 1), FIT)


if __name__ == "__main__":
    unittest.main()
