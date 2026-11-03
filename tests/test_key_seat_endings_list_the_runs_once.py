"""A still minute lists the runs fewer times than its seats are owed endings."""

import time
import unittest

from test_key_seat_look_reads_the_runs_once import (
    BOUND, MINUTE, RUNS, SEATS, OpenScreen, ended, listings, row)


class SeatLookReadsTheRunsOnce(OpenScreen):
    def test_a_still_minute_lists_the_runs_fewer_times_than_its_seats_are_owed_endings(self):
        now, endings, owing = time.time(), 8, SEATS[::2]     # every other seat is planned: owing
        for n, seat in enumerate(owing):
            # each seat's run going last, so the last one's row working is a read of them all
            for k in range(endings, -1, -1):
                run = ended(RUNS + 2 + len(SEATS) * k + n, seat, now)
                run.update({"finished_at": now - 2700, "handed_back": None, "reported": False}
                           if k else {"state": "running", "verdict": None, "merged": False,
                                      "started_at": now, "finished_at": None})
                self.home.write(f".agentkit/runs/{run['run_id']}/run.json", run)
        (self.home.path / ".agentkit/state/runs-moved").touch()
        self.menu.wait(row(owing[-1], "● working"), bound=BOUND)
        self.assertLess(listings(self.home.path / ".agentkit/runs", MINUTE),
                        endings * len(owing))


if __name__ == "__main__":
    unittest.main()
