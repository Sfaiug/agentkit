"""A queued run's wait line counts only the runs queued ahead of it, and says when the limit is full."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gate, host  # noqa: E402


class SlotNoteAhead(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"AK_MAX_RUNS": "4"})
        env.start()
        self.addCleanup(env.stop)

    def lines(self, running, ahead, first=False):
        """(claim_slot's saved line, slot_note's own line) for the same counts."""
        state = {"run_id": "r", "run_depth": 0, "first": first}
        with patch.object(gate, "slot_counts", return_value=(running, ahead)), \
                patch.object(host, "host_readings", side_effect=AssertionError("must not read")):
            self.assertFalse(gate.claim_slot(state, 4))
            return state["slot_wait_reason"], gate.slot_note({"run_id": "r", "first": first})

    def test_full_limit_with_nobody_queued_ahead(self):
        line = "waiting for a slot · limit full (4 running) · 0 ahead"
        self.assertEqual(self.lines(4, 0), (line, line))

    def test_full_limit_and_a_queue(self):
        line = "waiting for a slot · limit full (4 running) · 2 ahead"
        self.assertEqual(self.lines(4, 2), (line, line))

    def test_free_limit_counts_only_the_queue(self):
        line = "waiting for a slot · 1 ahead"
        self.assertEqual(self.lines(2, 1), (line, line))

    def test_first_run_reads_as_before(self):
        line = "waiting for a slot · 1 ahead"
        self.assertEqual(self.lines(4, 1, first=True), (line, line))


if __name__ == "__main__":
    unittest.main()
