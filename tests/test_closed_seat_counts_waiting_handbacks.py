"""A seat the owner closed counts only the hand-backs still waiting for it.

`handback_pending` outlives delivery, so a closed seat's row counts with `handback.waits`: an
ending already handed back (`handed_back` at or after `finished_at`) is no longer waiting,
whatever flag it kept.  Offline: a temporary HOME, no tmux.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, handback, orch, watch  # noqa: E402

SEAT = "acme-api"
CLOSED = "session closed by the owner: reopen it from past sessions"


def ended(name, **marks):
    return (config.RUNS / name, {"state": "pass", "verdict": "PASS", "launched_session": SEAT,
                                 "finished_at": 9000, "handback_pending": "fix-api: PASS",
                                 **marks})


class ClosedSeatCountsWaitingHandbacks(Sandbox):
    def reason(self, records):
        orch.mark_owner_closed(SEAT)
        found = watch.session_state(SEAT, now=10000, session={"name": SEAT, "exited": True},
                                    number=3, records=records, live={}, harness=None,
                                    auth_out={}, gh_out={}, token_out=None, previous={})
        return found["word"], found["reason"]

    def setUp(self):
        super().setUp()
        self.heard = [ended(f"fix-api-{n}", handed_back=9100, reported=True) for n in range(3)]

    def test_handed_back_endings_are_not_waiting(self):
        self.assertEqual(self.reason(self.heard), ("idle", CLOSED))

    def test_one_still_waiting_is_counted_alone(self):
        waiting = ended("fix-api-3", handed_back=False, reported=False)
        self.assertTrue(handback.waits(waiting[1]))
        self.assertEqual(self.reason(self.heard + [waiting]),
                         ("idle", f"{CLOSED} · 1 hand-backs waiting"))


if __name__ == "__main__":
    unittest.main()
