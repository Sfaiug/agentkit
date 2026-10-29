"""A launch the waiter hands back while the queue still has it behind the first goes back to the
waiter at once, taking no slot lock.  Offline: a temporary runs directory, the exec replaced."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, record, waiter

class Replaced(Exception):
    """The exec into the waiter."""


class HandedBackBehindTheFirst(unittest.TestCase):
    def test_it_goes_back_to_the_waiter_taking_no_lock(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-handed-back-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        runs, run, back = Path(tmp.name), "20990101-0001-acme-fix", []
        (runs / run).mkdir()
        record.save_state(runs / run, {"run_id": run, "state": "queued", "slot_waiting": True,
                                       "queued_at": time.time(), **record.process_owner()})
        (runs / ".slots.queue").write_text(json.dumps(
            {"at": time.time(), "running": 0, "queue": ["20990101-0000-acme-api", run]}))

        def between(counted):
            back.append(counted)
            raise Replaced

        with patch.object(config, "RUNS", runs), patch.object(config, "max_runs", return_value=0), \
                patch.dict(os.environ, {waiter.SLOT_WAIT_ENV: "1000.0 5.0"}), \
                patch.object(gate, "slot_lock", side_effect=AssertionError("took the slot lock")), \
                self.assertRaises(Replaced):
            gate.wait_for_slot(runs / run, between)
        self.assertEqual(back, [(1000.0, 5.0)])


if __name__ == "__main__":
    unittest.main()
