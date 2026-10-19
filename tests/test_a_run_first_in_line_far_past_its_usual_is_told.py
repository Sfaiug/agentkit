"""The run first in line for a slot is a stall once it has waited there three times the median
wait of the last firsts let in, and half an hour at least.  Offline: a temporary runs directory,
the clock and the host gates injected."""

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, stuck

NOW = 1_800_000_000.0
WEB = "20270115-0901-fix-web"


class FirstInLineFarPastItsUsual(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-far-past-usual-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        for patcher in (patch.object(config, "RUNS", Path(tmp.name)),
                        patch.dict(os.environ, {"AK_MAX_RUNS": "4"}),
                        patch.object(gate, "SLOT_POLL", 30),
                        patch.object(gate, "time", SimpleNamespace(time=lambda: self.clock))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def polls(self, run_id, start, end, let_in=False):
        """`run_id`'s polls first in line each half minute, the host gates letting it in at
        `end` if `let_in`: whether its last poll let it in."""
        with patch.object(gate, "slot_counts", return_value=(0, 0, [])), \
                patch.object(gate, "_host_admits", lambda *_: let_in and self.clock >= end):
            for self.clock in [*range(int(start), int(end), 30), end]:
                admitted = gate.claim_slot({"run_id": run_id, "run_depth": 0}, 4)
        return admitted

    def firsts_let_in_after(self, wait):
        for index in range(3):      # a gap of ten minutes between them: nobody polls
            start = NOW - 20_000 + index * (wait + 600)
            self.assertTrue(self.polls(f"20270115-080{index}-fix-api", start, start + wait, True))

    def lines(self, now):
        return [line for _key, _what, line in stuck.stalls(now)]

    def test_a_wait_past_three_times_the_usual_of_the_firsts_let_in_is_a_stall(self):
        self.firsts_let_in_after(20 * 60)
        self.polls(WEB, NOW - 7200, NOW - 4200)
        self.assertEqual(self.lines(NOW - 4200), [None])    # fifty minutes, under an hour
        self.polls(WEB, NOW - 4170, NOW)
        self.assertEqual(self.lines(NOW), [
            f"ak stalled: {WEB} has been first in line for a slot for 2h, more than 1h, with 0 "
            "behind it; `ak run status` shows what it waits on. Find why and build the smallest "
            "change to ak that keeps it from happening again, through the line."])

    def test_half_an_hour_holds_however_quick_the_firsts_let_in(self):
        self.firsts_let_in_after(60)
        self.polls(WEB, NOW - 1830, NOW)
        self.assertEqual([key for key, _what, line in stuck.stalls(NOW) if line],
                         [f"slot:{WEB}:{NOW - 1830}"])


if __name__ == "__main__":
    unittest.main()
