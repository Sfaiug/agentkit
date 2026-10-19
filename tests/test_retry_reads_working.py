"""A seat whose turn stopped on an error the tick types it back past reads working.

The owner's rule (14 Oct 2026): a retry reads `working`.  The error is read by the seat's own
look, on the capture it already took, so the word follows the screen: a retry that ended on the
error again still reads `retrying`, one that worked reads as its turn ended, and a capture that
failed changes nothing.  An error that may be a login is never typed past, nor is a legacy seat,
and once the tick gives up and tells the owner, the seat needs them.  Offline: a temporary HOME, captured panes,
no tmux.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, notify, watch  # noqa: E402

SEAT = "acme-api"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
STALL = (FIXTURES / "claude-stall-pane.txt").read_text()
PROMPT = (FIXTURES / "claude-prompt-pane.txt").read_text()
RETRYING = ("working", "retrying: API Error")


class RetryReadsWorking(Sandbox):
    def word(self, pane, **seat):
        """The seat's word once its look has seen that capture."""
        seat = {"name": SEAT, **seat}
        found = watch.live_state(seat, harness="claude", pane=pane, now=10000)
        answer = watch.session_state(SEAT, now=10000, session=seat, records=[], live=found,
                                     harness="claude", auth_out={}, gh_out={}, token_out=None,
                                     previous={})
        return answer["word"], answer["reason"]

    def test_a_stall_reads_working_until_a_turn_since_answers_it(self):
        self.assertEqual(self.word(STALL), RETRYING)
        self.assertEqual(self.word(""), RETRYING)       # a capture that failed says nothing
        self.assertEqual(self.word(PROMPT), ("idle", ""))  # the retry worked
        self.assertEqual(self.word(STALL), RETRYING)    # ... or ended on the error again
        config.plan_path(SEAT).write_text("- [x] Shipped the parser\n")
        self.assertEqual(self.word(PROMPT), ("done", "Shipped the parser"))

    def test_a_login_is_no_retry(self):
        login = STALL.replace("400 upstream connect error", "401 OAuth token expired, run /login")
        self.assertNotEqual(self.word(login), RETRYING)

    def test_once_the_tick_gives_up_and_tells_the_owner_it_needs_them(self):
        told = "acme-api is stalled on API Error for an hour and typing has not moved it"
        notify.record(SEAT, "needs", told, time=9900, watcher=True)
        state = watch.load_state()
        state["stalls"][SEAT] = {"signature": "API Error", "since": 6000, "told": 9900}
        watch.save_state(state)
        self.assertEqual(self.word(STALL), ("needs you", told))

    def test_once_it_gives_up_on_a_bare_rate_limit_it_needs_them_too(self):
        told = "acme-api (claude) is stuck with no progress for an hour"
        notify.record(SEAT, "needs", told, time=9900, watcher=True)
        watch.seat_write(SEAT, usage_refusal={"line": "API Error: 429", "at": 6000, "told": 9900})
        self.assertEqual(self.word(STALL), ("needs you", told))
        watch.forget(SEAT, acknowledge=False, opening=True)    # the owner takes it over
        self.assertEqual(self.word(STALL), RETRYING)

    def test_a_legacy_seat_the_tick_never_types_into_is_no_retry(self):
        self.assertEqual(self.word(STALL, legacy=True), ("idle", ""))


if __name__ == "__main__":
    unittest.main()
