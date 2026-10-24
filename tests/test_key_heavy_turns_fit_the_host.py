"""Heavy suite turns held plus those that fit never pass what the host fits with nothing running.

Black-box through tests/fixtures/akbin.py, held turns as locks on ak's turn files; this test
fails against `/bin/false`.
"""

from contextlib import ExitStack
import fcntl
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

# Pieces of 0.7 core and 410 MB: 8 idle cores fit 11, 4 GB free 9, and 16 GB 39.
IDLE = {"cpus": 8, "free_mb": 4096, "mem_total_mb": 16384, "slice_cpu_pressure": 12}


class HeavyTurnsFitTheHost(unittest.TestCase):
    def test_room_beside_held_turns_stops_at_what_the_host_fits(self):
        for held, limit in ((0, 9), (8, 11), (20, 20)):
            with self.subTest(held=held), Home() as home, ExitStack() as turns:
                (runs := home.path / ".agentkit" / "runs").mkdir(parents=True)
                for index in range(held):
                    fcntl.flock(turns.enter_context((runs / f".heavy-{index}.lock").open("a")),
                                fcntl.LOCK_EX)
                done = home.ak("run", "status", env={"AK_HOST_READINGS": json.dumps(IDLE)})
                self.assertEqual((done.code, done.out.splitlines()[1:2]),
                                 (0, [f"heavy suites: {limit} at once (derived)"]), done.err)


if __name__ == "__main__":
    unittest.main()
