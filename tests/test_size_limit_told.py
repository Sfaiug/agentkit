"""The first review's size limit ak enforces is the one every task is written to up front.

The orchestrator's rulebook and the task template carry the host's `executor_lines`, so a task is
cut to fit before anyone builds it; the builder's done is refused past it
(tests/test_key_done_counts_the_lines.py).
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config

DEFAULT = config.POLICY["executor_lines"][0]


class SizeLimitTold(unittest.TestCase):
    def test_the_orchestrator_and_the_task_template_carry_the_limit(self):
        for name in ("orchestrator.md", "templates/task.md"):
            with self.subTest(file=name):
                written = (REPO / name).read_text()
                self.assertIn(f"at most {DEFAULT} added lines with its tests",
                              config.in_force(written, {}))
                self.assertIn("at most 150 added lines with its tests",
                              config.in_force(written, {"executor_lines": 150}))


if __name__ == "__main__":
    unittest.main()
