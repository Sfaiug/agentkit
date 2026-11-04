"""A run started again after a park keeps its first attempt's place.

The restart (`leases.restart`) carries the first attempt's start (`first_started_at`), so the
slot queue admits it from where the first attempt queued, not behind every run
queued while it was parked.  Offline: the lease stage (`fixtures.leases`), a fake launch.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, TASK, YOUNGER, LiveRuns
from agentkit import config, gate, leases, run, transitions
from agentkit import record


class RestartKeepsPlace(LiveRuns):
    def restarted(self):
        """The younger run, queued at 950 and admitted at 1000, parked on the older and started
        again once the older landed."""
        self.collide()
        record.save_state(config.RUNS / YOUNGER, {**self.state(YOUNGER), "queued_at": 950})
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        self.parked()
        holder = config.RUNS / OLDER
        record.save_state(holder, {**record.read_state(holder), "state": "pass", "merged": True})
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append(d)):
            leases.restart(log=self.logs.append, now=3000)
        return launched[0]

    def test_the_restart_carries_its_first_start_through_every_restart(self):
        fresh = self.restarted()
        self.assertEqual(record.read_state(fresh)["first_started_at"], 1000)
        # a restart parked again hands on that same start, not its own
        self.assertEqual(transitions.first_started({"first_started_at": 1000, "started_at": 3000}), 1000)

    def test_the_slot_queue_admits_the_restart_from_its_first_place(self):
        restart = record.read_state(self.restarted())
        # queued while the first attempt waited for its slot, so behind it then
        queued_meanwhile = {"run_id": "a-meanwhile", "queued_at": 975, "started_at": 975}
        self.assertLess(gate.slot_order(restart), gate.slot_order(queued_meanwhile))


if __name__ == "__main__":
    unittest.main(verbosity=2)
