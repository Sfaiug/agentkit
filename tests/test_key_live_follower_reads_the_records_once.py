"""A project's one live follower reads the run records once an interval, however many runs it
follows.

Black-box: AK_BIN on the Home of `test_key_merges_going_live_share_one_follower`, its seat working,
so never at its prompt.  Six runs of one project merge while health is red, then go live, each
owed its live line, which its thread asks after every interval.  A read of every run's record
lists the runs, and opens a record again only once it changed: by the kernel's count (inotify),
over three intervals the follower lists the runs at most once an interval, and once more for the
interval under way when the count starts, where each thread's asks listed them each.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_merges_going_live_share_one_follower import FollowedMerges, followers
from test_key_seat_look_reads_the_runs_once import listings

INTERVAL = 15   # seconds a follower waits between a run's asks (`watch.LIVE_INTERVAL`)


class LiveFollowerReadsTheRecordsOnce(FollowedMerges):
    def setUp(self):
        super().setUp()
        self.seat.show("claude-working-pane.txt")

    def test_six_runs_owed_their_live_line_read_the_records_once_an_interval(self):
        directories = [self.merge("api", name)
                       for name in ("one", "two", "three", "four", "five", "six")]
        self.home.write("live-ok", "")
        self.until(lambda: all(json.loads((directory / "run.json").read_text()).get("live_at")
                               for directory in directories), "took every run live")
        self.assertLessEqual(listings(self.home.path / ".agentkit" / "runs", 3 * INTERVAL), 3 + 1)
        # still following, every line still owed: the count spans their asks
        self.assertEqual(followers(self.home), {"api": 1})
        self.assertFalse([line for line in self.seat.lines() if "is live" in line])


if __name__ == "__main__":
    unittest.main()
