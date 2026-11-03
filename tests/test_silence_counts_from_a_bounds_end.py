"""Silence after a declared bound counts from that bound's end, however slow the look for it.

`worker.limited` asks past the silence limit whether a declared bound holds the command, and on a
busy host that look (a scan of every process) takes a while.  A bound that ended since the last
look ended no earlier than that look's end, so a command still gets the whole limit after it:
counting from the start of the last look that found the bound stopped a landing piece in the
fraction of a second between its timeout's end and its own.
"""

from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import worker

SILENCE = 1.5
LOOK = 1    # each look outlasts the poll, so poll and look together pass the limit


class SilenceCountsFromABoundsEnd(unittest.TestCase):
    def test_a_slow_look_leaves_the_whole_limit_after_a_bound_ends(self):
        looks, gone, stopped = [], [], []

        def declared(_pid):
            """A bound found once, then gone."""
            time.sleep(LOOK)
            looks.append(None)
            if len(looks) > 1 and not gone:
                gone.append(time.monotonic())
            return len(looks) == 1

        with tempfile.TemporaryDirectory(prefix="bound-") as tmp:
            _, _, killed = worker.limited(
                ["sleep", "60"], None, silence=SILENCE, activity=Path(tmp, "events"),
                declared=declared, on_timeout=lambda *_: stopped.append(time.monotonic()))
        self.assertTrue(killed)
        self.assertGreaterEqual(stopped[0] - gone[0], SILENCE)


if __name__ == "__main__":
    unittest.main()
