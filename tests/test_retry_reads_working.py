"""A seat whose turn stopped on an error the tick is typing it back past reads working.

The owner's matrix (14 Oct 2026): a retry reads `working`.  A harness that ends a turn on an
API error leaves the seat at its prompt, and the tick (`health`) types it back into motion
after three minutes, every three minutes, for an hour; only then does it give up and ask the
owner.  Until then the seat moves on without them: `working`, `retrying: <error>`.  Offline: a
temporary HOME, no tmux.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import notify, watch  # noqa: E402

SEAT = "acme-api"


class RetryReadsWorking(Sandbox):
    def decide(self, stalls):
        return watch.session_state(SEAT, now=10000, session={"name": SEAT}, records=[],
                                   live={"state": "at_prompt", "began": 9000},
                                   harness="claude", auth_out={}, gh_out={}, token_out=None,
                                   previous={}, stalls=stalls)

    def test_a_stall_the_tick_is_retrying_reads_working(self):
        found = self.decide({SEAT: {"signature": "API Error", "since": 9400}})
        self.assertEqual((found["word"], found["reason"]), ("working", "retrying: API Error"))

    def test_a_usage_window_the_tick_waits_out_says_until_when(self):
        found = self.decide({SEAT: {"signature": "Usage limit", "since": 9400,
                                    "status": "waiting until 2026-10-15 20:00"}})
        self.assertEqual((found["word"], found["reason"]),
                         ("working", "retrying: Usage limit · waiting until 2026-10-15 20:00"))

    def test_once_the_tick_gives_up_and_asks_the_owner_it_needs_them(self):
        told = "acme-api is stalled on API Error for an hour and typing has not moved it"
        notify.record(SEAT, "needs", told, time=9900, watcher=True)
        found = self.decide({SEAT: {"signature": "API Error", "since": 6000, "told": 9900}})
        self.assertEqual((found["word"], found["reason"]), ("needs you", told))

    def test_a_login_or_a_quiet_seat_is_no_retry(self):
        for kind in ("auth", "quiet"):
            with self.subTest(kind=kind):
                found = self.decide({SEAT: {"kind": kind, "signature": "401", "since": 9400}})
                self.assertNotEqual(found["reason"], "retrying: 401")


if __name__ == "__main__":
    unittest.main()
