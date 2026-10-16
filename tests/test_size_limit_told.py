"""The first review's size limit ak enforces is the one every builder is told up front.

The orchestrator's rulebook, the executor's rules and the task template each carry
`task.MAX_PR_LINES`: a builder that learns the limit only when ak refuses its change has
already built past it.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import task, worker


class SizeLimitTold(unittest.TestCase):
    def test_the_orchestrator_and_the_task_template_carry_the_limit(self):
        for name in ("orchestrator.md", "templates/task.md"):
            with self.subTest(file=name):
                self.assertIn(f"at most {task.MAX_PR_LINES} added lines with its tests",
                              (REPO / name).read_text())

    def test_the_executor_is_told_the_limit(self):
        self.assertIn(f"more than {task.MAX_PR_LINES} added lines", worker.PREAMBLES["executor"])


if __name__ == "__main__":
    unittest.main()
