"""Only moving work holds lines: a run waiting on a person or a spent provider window holds none.

A going run whose expired login, stall or spent window keeps it still (`leases.STILL`) parks
nobody, and a run already parked on it starts again at the next tick, as it would once the
holder had landed; a holder ak still moves keeps its younger waiting.  Offline: the lease
stage (`fixtures.leases`), a fake launch.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, TASK, YOUNGER, LiveRuns
from agentkit import config, leases, run
from agentkit import record

STILL = ({"state": "waiting_login"}, {"state": "stalled"},
         {"state": "exhausted", "quota_dry": True})


class StuckHolderReleases(LiveRuns):
    def holder(self, **fields):
        directory = config.RUNS / OLDER
        record.save_state(directory, {**record.read_state(directory), **fields})

    def restarts(self, now):
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append(d)):
            leases.restart(log=self.logs.append, now=now)
        return launched

    def test_a_holder_standing_still_parks_nobody(self):
        self.collide()
        for fields in STILL:
            with self.subTest(**fields):
                self.holder(**fields)
                self.assertNotIn(YOUNGER, leases.scan(self.repo, self.logs.append, now=2000))
                self.assertEqual(self.state(YOUNGER)["state"], "running")

    def test_a_run_parked_on_a_holder_that_stands_still_starts_again(self):
        self.collide()
        (config.RUNS / YOUNGER / "task.md").write_text(TASK)
        leases.scan(self.repo, now=2000)
        self.assertEqual(self.state(YOUNGER)["state"], "stopped")
        self.assertEqual(self.restarts(3000), [])                   # the holder still moves
        self.holder(state="waiting_login")
        launched = self.restarts(3100)
        self.assertEqual(len(launched), 1)
        self.assertEqual(record.read_state(launched[0])["restarted"],
                         {"run": YOUNGER, "why": f"{OLDER} stands still (waiting_login)"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
