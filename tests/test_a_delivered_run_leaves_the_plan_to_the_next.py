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
        self.checks = []

        @contextmanager
        def default_branch(repo):
            @contextmanager
            def checkout():
                yield repo
            yield "0123456789ab deliver feature", {}, checkout

        self.stack.enter_context(patch.object(plan, "default_branch", default_branch))
        self.stack.enter_context(patch.object(plan, "place", lambda name, project: self.root))

    def checking(self, then):
        """Each check recorded, then `then` run on how many ran: failing, unless it raises."""
        def fails(tree, check, env):
            self.checks.append(check)
            then(len(self.checks))
            return True
        return patch.object(plan, "fails", fails)

    def test_runs_delivered_meanwhile_leave_each_line_to_one_verification_begun_after_them(self):
        def deliver():
            # another run's ending, which finds the plan being checked and goes on at once
            run = threading.Thread(target=plan.verify_delivered, args=("fix-api",))
            run.start()
            run.join(10)
            self.assertFalse(run.is_alive())

        def then(checked):
            if checked == 1:            # four runs deliver while the first checks
                for _ in range(4):
                    deliver()
            elif checked == 2:
                raise SystemExit(137)   # killed while checking again for them
            elif checked == 3:          # one more delivers, and the seat replaces the check
                deliver()
                with plan.held("fix-api") as current:
                    plan.write(current, [line.replace("-f", "-s") for line in plan.lines(current)])

        with self.checking(then):
            with self.assertRaises(SystemExit):
                plan.verify_delivered("fix-api")
            # the next delivery is a fix run's, its own line ticked meanwhile: it checks nothing
            # of its own, and lets go of the lock to what the killed one owed
            plan.delivery("fix-api", "test -f fix.txt")
        # the four leave the line to one more check, not four; the killed one leaves it to the
        # fix run, and the last delivery's to one more after it, which checks the new check
        self.assertEqual(self.checks, ["test -f feature.txt"] * 3 + ["test -s feature.txt"])

    def test_a_verification_that_reaches_no_verdict_on_a_line_leaves_the_delivery_owed(self):
        def then(checked):
            if checked == 1:
                raise config.Error("this check did not finish within 600 s")

        with self.checking(then):
            plan.verify_delivered("fix-api")
            self.assertEqual(len(self.checks), 1)       # never again at once: it would fail alike
            for _ in range(2):      # the next delivery, a fix run's, checks it; the one after, nothing
                plan.delivery("fix-api", "test -f fix.txt")
        self.assertEqual(len(self.checks), 2)


if __name__ == "__main__":
    unittest.main()
