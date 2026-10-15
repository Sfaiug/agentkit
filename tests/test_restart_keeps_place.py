"""A run started again after a park keeps its first attempt's place.

The restart (`leases.restart`) carries the first attempt's start (`first_started_at`), so a
run launched after that first attempt waits on it in the lease scan instead of the other way
round, and the slot queue admits it from where the first attempt queued, not behind every run
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

NEWER = "20260101-1100-newer"


class RestartKeepsPlace(LiveRuns):
    def restarted(self):
        """The younger run, parked on the older and started again once the older landed."""
        self.collide()
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
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

    def test_a_run_launched_after_the_first_attempt_waits_on_the_restart(self):
        fresh = self.restarted()
        name = fresh.name
        # the restart has its own checkout now, building again on line 5
        worktree = config.WT / name
        self.git(self.repo, "worktree", "add", "-q", "-b", f"ak/{name}", str(worktree), self.base)
        record.save_state(fresh, {**record.read_state(fresh), "state": "running",
                                  "repo": str(self.repo), "worktree": str(worktree),
                                  "branch": f"ak/{name}", "base_sha": self.base,
                                  "started_at": 3000, "step": "executor", "round_summaries": [],
                                  "artifacts": []})
        self.edit(worktree, "api.py", 5, "the restart's line 5", commit=True)
        newer = self.run_on(NEWER, 1500, step="executor", rounds=0)
        self.edit(newer, "api.py", 5, "the newer run's line 5")
        found = leases.scan(self.repo, self.logs.append, now=4000)
        self.assertEqual(found[NEWER]["waits_on"], name)
        self.assertNotIn(name, found)
        self.assertEqual(self.state(name)["state"], "running")

    def test_the_slot_queue_admits_the_restart_from_its_first_place(self):
        restart = {"run_id": "b-restart", "queued_at": 3000, "started_at": 3000,
                   "first_started_at": 1000}
        queued_meanwhile = {"run_id": "a-meanwhile", "queued_at": 1500, "started_at": 1500}
        self.assertLess(gate.slot_order(restart), gate.slot_order(queued_meanwhile))


if __name__ == "__main__":
    unittest.main(verbosity=2)
