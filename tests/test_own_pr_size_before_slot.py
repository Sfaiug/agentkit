"""A seat's own PR too large for its first review is refused at launch, before it waits for a slot.

`ak run --review-pr` checks the PR's size in its preflight, beside its round budget: at the
seat's task threshold (`task.SEAT_TASK_LINES`, moved lines aside) or mostly a budget-failed PR's
lines, the launch is refused with the same sentence the review would end on, so the seat hears
to write a task at once instead of after the queue (16 Oct 2026: refused PRs had waited 34 hours in
all for a slot first).  A PR of wording alone, one a review already judged and somebody else's
PR launch whatever their size.  Offline, on the `fixtures.own_pr` stage.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import BRANCH, OwnPr, URL
from agentkit import config, record


class OwnPrSizeBeforeSlot(OwnPr):
    def test_a_pr_past_the_ceiling_is_refused_before_any_slot(self):
        self.hand_push(1)                               # 5000 added lines of fence.txt
        why, spawned, state = self.launch()
        self.assertIn("PR #7 adds 5000 lines", why)
        self.assertIn("Write it as a task", why)
        self.assertEqual(spawned, 0)
        self.assertEqual(state["state"], "error")
        self.assertIn("Write it as a task", state["error"])

    def test_a_pr_within_the_ceiling_is_launched(self):
        why, spawned, _ = self.launch()                 # one changed line
        self.assertEqual((why, spawned), (None, 1))

    def test_wording_a_reviewed_pr_and_somebody_elses_launch_whatever_their_size(self):
        self.git("checkout", "-qb", "notes", "main")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/notes.md").write_text("note\n" * 500)
        self.git("add", "docs/notes.md")
        self.git("commit", "-qm", "Notes")
        self.git("push", "-q", "--force", "origin", f"{self.git('rev-parse', 'HEAD')}:refs/heads/{BRANCH}")
        self.assertEqual(self.launch()[:2], (None, 1))
        self.hand_push(1)
        earlier = config.RUNS / "own-pr-earlier"        # an earlier run spent round 1 on this PR
        earlier.mkdir()
        record.save_state(earlier, {"run_id": earlier.name, "state": "fail", "review_pr": URL, "pr": URL,
                                    "launched_session": "fix-api", "own_pr": True,
                                    "round_summaries": [{"round": 1, "verdict": "FAIL", "summary": ""}]})
        self.assertEqual(self.launch()[:2], (None, 1))
        record.save_state(earlier, {"run_id": earlier.name, "state": "stopped"})
        self.pr.update(author="stranger")
        self.assertEqual(self.launch()[:2], (None, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
