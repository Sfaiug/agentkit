"""A seat builds under 50 added lines; larger own PRs must become executor tasks.

The same gate refuses at launch and on the checked-out head, before any reviewer runs.
Documents alone stay exempt. Offline: real Git, fake GitHub and workers, a throwaway HOME.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.own_pr import BRANCH, OwnPr


class SeatPrUnderFiftyLines(OwnPr):
    def push_lines(self, count, name="work.py"):
        self.git("checkout", "-qB", "bounded", "main")
        (self.repo / name).write_text("".join(f"line_{n} = {n}\n" for n in range(count)))
        self.git("add", "-A")
        self.git("commit", "-qm", "Bounded change")
        self.git("push", "-q", "--force", "origin", f"HEAD:refs/heads/{BRANCH}")

    def test_49_lines_launch_but_50_must_be_written_as_a_task(self):
        self.push_lines(49)
        self.assertEqual(self.launch()[:2], (None, 1))
        self.push_lines(50)
        why, spawned, state = self.launch()
        self.assertEqual(spawned, 0)
        self.assertEqual(state["state"], "error")
        self.assertIn("adds 50 lines", why)
        self.assertIn("too big for the seat", why)
        self.assertIn("Write it as a task and launch it; a worker builds it", why)

    def test_200_lines_of_documents_launch(self):
        self.push_lines(200, "README.md")
        self.assertEqual(self.launch()[:2], (None, 1))

    def test_growth_after_launch_is_refused_on_the_checked_out_head(self):
        self.push_lines(49)
        self.assertEqual(self.launch()[:2], (None, 1))
        self.push_lines(50)
        state = self.review([])
        self.assertEqual(state["state"], "blocked")
        self.assertIn("Write it as a task", state["error"])
        self.assertEqual(self.prompts, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
