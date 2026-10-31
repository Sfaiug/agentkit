"""A screen pass follows every seat's renames once, however many plans it looks up.

Each lookup of a seat's plan listed every session file and followed every rename pointer again,
and a pass looks up several plans for every seat.  With ten pointers `ak orch rename` left leading
to each seat, a still minute costs less than twice the CPU of one with none, the screen's reaped
children's included.  Black-box, on the idle key's open screen.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_idle_screen_reads_only_what_changed import MINUTE, SEATS, OpenScreen


class ScreenPassFollowsSeatRenamesOnce(OpenScreen):
    def still_minute(self):
        """What the screen runs over a still minute, once it is done with what changed."""
        self.quiet(self.held())
        start = self.cpu()
        time.sleep(MINUTE)
        return self.cpu() - start

    def test_ten_renames_leading_to_each_seat_cost_less_than_twice_none(self):
        none = self.still_minute()
        for seat in SEATS:
            for k in range(10):     # a rename points every older name at the newest
                self.home.write(f".agentkit/state/session-{seat}-was-{k}.json", {"renamed": seat})
        self.assertLess(self.still_minute(), 2 * none)


if __name__ == "__main__":
    unittest.main()
