"""A launch whose refusal needs only git is refused at launch, not after a slot wait.

With every slot taken, `ak run` still runs its preflight first: a seat's PR at the seat size
limit (`run.own_pr_first_review`) and a task `from:` a branch that is not there
(`run.from_refusal`) are refused in the launching terminal with the sentence the run would have
ended on, and no run waits for a slot; a small PR queues as before.  Offline, on the
`fixtures.own_pr` stage.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import OwnPr, URL
from agentkit import box, config, gate, plan, record, run


class RefusedBeforeTheQueue(OwnPr):
    def setUp(self):
        super().setUp()
        # the one slot is taken: the fixture's own review run holds it, alive
        self.assertEqual(record.read_state(self.run_dir)["state"], "running")
        # ... on another PR, as one going on this PR would refuse the launch itself
        with record.record(self.run_dir) as held:
            held["review_pr"] = URL.replace("/pull/7", "/pull/8")
        self.stack.enter_context(patch.dict(os.environ, {"AK_MAX_RUNS": "1"}))
        self.stack.enter_context(patch.object(box, "check"))
        # a seat launches only with an open line in its plan
        plan.write("fix-api", [plan.compose("Mend the gate", "check: `false`", "acme", False,
                                            "2026-10-23 09:00", None)])

    def launch(self, *argv):
        """(the refusal, how many background runs started, the new run's record)."""
        before = set(config.RUNS.iterdir())
        with patch.object(run, "spawn_bg", return_value=0) as spawned, \
                patch.object(gate, "wait_for_slot", side_effect=AssertionError("waited for a slot")):
            try:
                run.main([*argv, "--bg"])
                why = None
            except config.Error as refused:
                why = str(refused)
        # the slot queue's file appears beside the run once a slot is waited on
        launched, = {path for path in config.RUNS.iterdir() if path.is_dir()} - before
        return why, spawned.call_count, record.read_state(launched)

    def test_a_seat_pr_past_the_seat_limit_is_refused_at_launch(self):
        self.hand_push(1)                               # 5000 added lines of fence.txt
        why, spawned, state = self.launch("--review-pr", URL)
        self.assertIn("PR #7 adds 5000 lines", why)
        self.assertIn("too big for the seat", why)
        self.assertEqual((spawned, state["state"], state["error"]), (0, "error", why))

    def test_a_task_from_a_missing_branch_is_refused_at_launch(self):
        task = self.root / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\nfrom: no-such-branch\n---\n# Mend the gate\n\n"
                        "## Goal\nThe gate closes.\n\n## Done when\n```bash\ntest -f fence.txt\n```\n")
        why, spawned, state = self.launch(str(task))
        self.assertIn("from: 'no-such-branch' is not a local branch", why)
        self.assertEqual((spawned, state["state"], state["error"]), (0, "error", why))

    def test_a_small_pr_still_queues(self):
        why, spawned, state = self.launch("--review-pr", URL)     # one changed line
        self.assertEqual((why, spawned), (None, 1))
        self.assertEqual((state["state"], state["slot_waiting"]), ("queued", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
