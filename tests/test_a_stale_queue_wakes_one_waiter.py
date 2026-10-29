"""A queue its first stopped rewriting is counted again by the run next in line after two polls,
by the one behind it a poll later, and so on: one comes back, never the whole line at once.
Offline: a temporary queue file, the clock passed in."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import waiter

POLL, AT = 30, 1_800_000_000.0
LINE = [f"20270115-090{n}-fix-api" for n in range(4)]


class StaleQueueWakesOneWaiter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-stale-queue-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.queue = Path(tmp.name) / ".slots.queue"
        self.queue.write_text(json.dumps({"at": AT, "running": 0, "queue": LINE}))

    def back(self, polls):
        """The runs that come back to count the queue `polls` polls after it was rewritten."""
        return [run_id for run_id in LINE
                if not waiter.behind_first(self.queue, run_id, AT + polls * POLL, POLL)]

    def test_one_run_comes_back_a_poll_at_a_time(self):
        self.assertEqual(self.back(1.9), LINE[:1])     # rewritten in time: only its first polls
        self.assertEqual(self.back(2), LINE[:2])       # its first stopped: the next comes back
        self.assertEqual(self.back(3), LINE[:3])       # and a poll later the one behind it
        self.assertEqual(self.back(4), LINE)

    def test_a_run_the_queue_does_not_list_comes_back(self):
        self.assertFalse(waiter.behind_first(self.queue, "20270115-0999-fix-web", AT, POLL))


if __name__ == "__main__":
    unittest.main()
