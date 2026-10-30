"""A delivered run checks no plan line once a verification begun after it delivered has finished."""

from contextlib import contextmanager
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, plan


class ADeliveredRunLeavesThePlanToTheNext(Sandbox):
    def test_runs_delivered_meanwhile_leave_it_to_the_first_check_after_them_that_finishes(self):
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        queued, checks, runs, real = threading.Semaphore(0), [], [], plan.verifying

        @contextmanager
        def verifying(name):
            queued.release()        # its delivery is numbered by now
            with real(name):
                yield

        def deliver():
            try:
                plan.verify_delivered("fix-api")
            except config.Error:
                pass        # its check died, as `handback.settle_delivered_line` logs

        def check(name):
            checks.append(name)
            if len(checks) == 1:        # three runs deliver while the first checks
                runs.extend(threading.Thread(target=deliver) for _ in range(3))
                for run in runs:
                    run.start()
                for _ in range(4):      # the first's own too
                    self.assertTrue(queued.acquire(timeout=10))
            elif len(checks) == 2:
                raise config.Error("killed while checking")

        with patch.object(plan, "verifying", verifying), patch.object(plan, "_verify_held", check):
            deliver()
            for run in runs:
                run.join(10)
        self.assertFalse(any(run.is_alive() for run in runs))
        # begun before they delivered, the first proves none of theirs, and the one that died
        # none at all: the next checks for the last too, which checks nothing
        self.assertEqual(len(checks), 3)


if __name__ == "__main__":
    unittest.main()
