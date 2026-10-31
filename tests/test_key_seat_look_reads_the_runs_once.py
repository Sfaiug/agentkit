"""A look at every seat reads the runs once, however many endings its seats are owed.

When nothing moves, the clock has the screen look at every seat again (`menu.TICK`) in a thread of
its own, where each merge's ending a seat owing work was owed listed and statted every run twice.
With those seats' runs going, eight such endings each cost a still minute less than twice the CPU
none do, the screen's reaped children's included.  Black-box, on the idle key's open screen.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import MINUTE, RUNS, SEATS, OpenScreen, ended


class SeatLookReadsTheRunsOnce(OpenScreen):
    def owed_minute(self, endings):
        """What the screen runs over a still minute once each seat owing work has a run going
        and `endings` merges of today's whose endings nobody has told it."""
        now = time.time()
        for n, seat in enumerate(SEATS[::2]):     # every other seat is planned: it owes work
            for k in range(endings + 1):
                run = ended(RUNS + 2 + len(SEATS) * k + n, seat, now)
                run.update({"finished_at": now - 2700, "handed_back": None, "reported": False}
                           if k else {"state": "running", "verdict": None, "merged": False,
                                      "started_at": now, "finished_at": None})
                self.home.write(f".agentkit/runs/{run['run_id']}/run.json", run)
        (self.home.path / ".agentkit/state/runs-moved").touch()
        self.quiet(self.held())
        start = self.cpu()
        time.sleep(MINUTE)
        return self.cpu() - start

    def test_seats_owed_eight_endings_each_cost_less_than_twice_seats_owed_none(self):
        none = self.owed_minute(0)
        self.assertLess(self.owed_minute(8), 2 * none)


if __name__ == "__main__":
    unittest.main()
