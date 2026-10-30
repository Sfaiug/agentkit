"""A delivered run checks no plan line once each open line was checked by a verification begun
after it delivered."""

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
    def test_runs_delivered_meanwhile_leave_each_line_to_a_check_begun_after_them_that_finished(self):
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        config.plan_path("fix-api").write_text(plan.compose(
            "the feature exists", "check: `test -f feature.txt`", "~/acme", False, "2026-10-30 10:00", None) + "\n")
        queued, checks, runs, real = threading.Semaphore(0), [], [], plan.verifying

        @contextmanager
        def verifying(name):
            queued.release()        # it read how many verifications began before its turn
            with real(name):
                yield

        @contextmanager
        def default_branch(repo):
            @contextmanager
            def checkout():
                yield repo
            yield "0123456789ab deliver feature", {}, checkout

        def fails(tree, check, env):
            checks.append(check)
            if len(checks) == 1:        # four runs deliver while the first checks
                runs.extend(threading.Thread(target=plan.verify_delivered, args=("fix-api",))
                            for _ in range(4))
                for run in runs:
                    run.start()
                for _ in range(5):      # the first's own too
                    self.assertTrue(queued.acquire(timeout=10))
            elif len(checks) == 2:
                raise SystemExit(137)   # killed while checking: it records nothing
            elif len(checks) == 3:      # the seat replaces the check meanwhile
                with plan.held("fix-api") as current:
                    plan.write(current, [line.replace("-f", "-s") for line in plan.lines(current)])
            return True

        with patch.object(plan, "verifying", verifying), patch.object(plan, "default_branch", default_branch), \
                patch.object(plan, "place", lambda name, project: self.root), patch.object(plan, "fails", fails):
            plan.verify_delivered("fix-api")
            for run in runs:
                run.join(10)
        self.assertFalse(any(run.is_alive() for run in runs))
        # begun before they delivered, the first proves nothing of theirs, the killed one nothing
        # at all, and the next not the check put in while it ran: the one after checks that, and
        # the last checks nothing
        self.assertEqual(checks, ["test -f feature.txt"] * 3 + ["test -s feature.txt"])


if __name__ == "__main__":
    unittest.main()
