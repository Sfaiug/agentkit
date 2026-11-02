"""The first review's size limit ak enforces is the one every builder is told up front.

The orchestrator's rulebook, the executor's and fixer's rules and the task template each carry
ak's default for `review_lines`: a builder that learns the limit only when ak refuses its change
has already built past it.  tests/test_key_lines_are_settings.py holds a turn to a host's own.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, worker

DEFAULT = config.POLICY["review_lines"][0]


class SizeLimitTold(unittest.TestCase):
    def test_the_orchestrator_and_the_task_template_carry_the_limit(self):
        for name in ("orchestrator.md", "templates/task.md"):
            with self.subTest(file=name):
                self.assertIn(f"at most {DEFAULT} added lines with its tests",
                              (REPO / name).read_text())

    def test_the_executor_and_the_fixer_are_told_the_limit(self):
        # a fixer can start in a fresh conversation before the first review, never having read
        # the executor's rules
        for role in ("executor", "fixer"):
            with self.subTest(role=role):
                self.assertIn(f"more than {DEFAULT} added lines", worker.PREAMBLES[role])


if __name__ == "__main__":
    unittest.main()
