"""An older ak's lease park is a stopped run, with no work in flight for its seat.

Black-box through AK_BIN and akbin: the seat's only run is a stopped record that
still carries lease_wait. Its status stays stopped and its seat is idle.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

RUN = "20261001-0900-fix-api"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ParkedRecordReadsAsStopped(unittest.TestCase):
    def test_a_legacy_park_has_ended(self):
        with Home() as home:
            Seat(home, "acme")
            home.write(f".agentkit/runs/{RUN}/run.json", {
                "run_id": RUN, "title": "Fix the API", "launched_session": "acme",
                "state": "stopped", "verdict": "STOPPED", "started_at": time.time() - 60,
                "finished_at": time.time(), "error": "waits on an older change",
                "lease_wait": {"on": "20261001-0800-fix-docs", "files": ["api.py"], "since": 1}})

            shown = home.ak("run", "status", RUN, "--plain")
            self.assertEqual(shown.code, 0, shown.err)
            row = next(line for line in shown.out.splitlines() if line.startswith(RUN))
            self.assertEqual(row.split()[1], "stopped", shown.out)

            seat = home.ak("orch", "why", "acme")
            self.assertEqual(seat.code, 0, seat.err)
            self.assertEqual(seat.out.splitlines()[0], "acme  idle", seat.out)


if __name__ == "__main__":
    unittest.main()
