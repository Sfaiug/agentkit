"""Runs delivered while a verification of their seat's plan checks never wait for it: they leave
each line to one more verification begun after them, which the one checking runs once it lets go,
and which a verifier killed meanwhile leaves to the next delivery, a fix run's too."""

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
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        config.plan_path("fix-api").write_text(plan.compose(
            "the feature exists", "check: `test -f feature.txt`", "~/acme", False, "2026-10-30 10:00", None) + "\n")
        self.passes = []        # one per verification that reached its project's default branch

        @contextmanager
        def default_branch(repo):
            @contextmanager
            def checkout():
                yield repo
            self.passes.append(repo)
            yield "0123456789ab deliver feature", {}, checkout

        self.stack.enter_context(patch.object(plan, "default_branch", default_branch))
        self.stack.enter_context(patch.object(plan, "place", lambda name, project: self.root))

    def test_runs_delivered_meanwhile_leave_each_line_to_one_verification_begun_after_them(self):
        checks = []

        def deliver():
            # another run's ending, which finds the plan being checked and goes on at once
            run = threading.Thread(target=plan.verify_delivered, args=("fix-api",))
            run.start()
            run.join(10)
            self.assertFalse(run.is_alive())

        def fails(tree, check, env):
            checks.append(check)
            if len(checks) == 1:        # four runs deliver while the first checks
                for _ in range(4):
                    deliver()
            elif len(checks) == 2:
                raise SystemExit(137)   # killed while checking again for them
            elif len(checks) == 3:      # one more delivers, and the seat replaces the check
                deliver()
                with plan.held("fix-api") as current:
                    plan.write(current, [line.replace("-f", "-s") for line in plan.lines(current)])
            return True

        with patch.object(plan, "fails", fails):
            with self.assertRaises(SystemExit):
                plan.verify_delivered("fix-api")
            # the next delivery is a fix run's, its own line ticked meanwhile: it checks nothing
            # of its own, and lets go of the lock to what the killed one owed
            plan.delivery("fix-api", "test -f fix.txt")
        # the four leave the line to one more check, not four; the killed one leaves it to the
        # fix run, and the last delivery's to one more after it, which checks the new check
        self.assertEqual(checks, ["test -f feature.txt"] * 3 + ["test -s feature.txt"])

    def test_a_line_left_without_a_verdict_leaves_the_delivery_owed(self):
        with plan.held("fix-api") as current:   # a line naming its root, which the tree must hold
            plan.write(current, [line.replace("~/acme", "~/acme#0123456789ab") for line in plan.lines(current)])
        unfinished = config.Error("this check did not finish within 600 s")
        for way, holds, fails in (("its check unfinished", [True, True], [unfinished, True]),
                                  ("git never proved its tree the line's repository", [False, True], [True])):
            with self.subTest(way), patch.object(plan, "holds", side_effect=holds), \
                    patch.object(plan, "fails", side_effect=fails):
                self.passes.clear()
                plan.verify_delivered("fix-api")
                self.assertEqual(len(self.passes), 1)   # never again at once: it would fail alike
                for _ in range(2):      # the next delivery, a fix run's, verifies; the one after, not
                    plan.delivery("fix-api", "test -f fix.txt")
                self.assertEqual(len(self.passes), 2)


if __name__ == "__main__":
    unittest.main()
