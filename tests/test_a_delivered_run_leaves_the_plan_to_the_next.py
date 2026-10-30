"""A delivered run ends at once while another holds the place next in line to verify the plan."""

import fcntl
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, plan


class ADeliveredRunLeavesThePlanToTheNext(Sandbox):
    def test_it_ends_with_another_next_in_line_and_otherwise_frees_the_place_and_checks(self):
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        place, checks = config.seat_file("nextverify", "fix-api"), []
        # A check finds that place free again, as a run delivering meanwhile needs it.
        with patch.object(plan, "_verify_held", lambda name: checks.append(
                fcntl.flock(place.open("a"), fcntl.LOCK_EX | fcntl.LOCK_NB))):
            with place.open("a") as taken, plan.verifying("fix-api"):
                fcntl.flock(taken, fcntl.LOCK_EX)
                plan.verify_delivered("fix-api")    # joining the wait would hang here
                self.assertEqual(checks, [])
            plan.verify_delivered("fix-api")
        self.assertEqual(checks, [None])


if __name__ == "__main__":
    unittest.main()
