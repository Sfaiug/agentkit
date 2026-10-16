"""A seat whose turn stopped on an error the tick is typing it back past reads working.

The owner's matrix (14 Oct 2026): a retry reads `working`.  A harness that ends a turn on an
API error leaves the seat at its prompt, and the tick (`health`) types it back into motion
after three minutes, every three minutes, for an hour; only then does it give up and ask the
owner.  Until then the seat moves on without them: `working`, `retrying: <error>`, for as long
as it is still stopped on an error, which a turn since -- the tick's retry or the owner's -- may
have ended before the tick's next pass.  Offline: a temporary HOME, captured panes, no tmux.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import notify, watch  # noqa: E402

SEAT = "acme-api"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class RetryReadsWorking(Sandbox):
    def setUp(self):
        super().setUp()
        self.pane = (FIXTURES / "claude-stall-pane.txt").read_text()
        self.stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda _: self.pane))

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

    def test_a_turn_since_the_tick_last_looked_reads_as_it_ended(self):
        typed = {"signature": "API Error", "since": 9400, "nudged_at": 9600}
        # the tick's retry ended on the error again: it retries again, so the seat still works
        self.pane = self.pane.replace("Say OK", "continue")
        found = self.decide({SEAT: typed})
        self.assertEqual((found["word"], found["reason"]), ("working", "retrying: API Error"))
        # ... or it worked, and the seat said it was done before the tick's next pass
        self.pane = (FIXTURES / "claude-prompt-pane.txt").read_text()
        notify.record(SEAT, "done", "Shipped the parser", time=9700)
        found = self.decide({SEAT: typed})
        self.assertEqual((found["word"], found["reason"]), ("done", "Shipped the parser"))

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
