"""A change cannot weaken the target's landing suite by rewriting its own tests: line.

Offline: local Git and real checks, isolated state and fake workers and wakes.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lander import LanderFixture, SUITE
from test_repo_suite import RepoSuiteFixture
from agentkit import land, run


class FinalCheckFromTarget(RepoSuiteFixture, unittest.TestCase):
    def test_branch_declaring_true_fails_the_targets_landing_check(self):
        self.add_origin()
        self.commit("---\ntests: false\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "main")
        self.git("checkout", "-q", "-b", "fix-api")
        self.commit("---\ntests: true\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "fix-api")
        with patch.object(run, "start_followups", return_value=None):
            state = self.launch("target-suite", ["test -d ."],
                                front="base: fix-api\ntarget: main\n", expected="waiting")
        self.assertEqual(self.finals(), [["test -d ."], ["false"]], self.gates)
        self.assertEqual(state["final_check"]["outcome"], "failed")
        self.assertEqual(state["final_check"]["where"], "landing")


class StackedSuiteFromTarget(LanderFixture, unittest.TestCase):
    def test_branch_declaring_true_cannot_skip_the_stack_check(self):
        directory = self.member(once="true", **{
            "AGENTS.md": "---\ntests: true\n---\n",
            "broken.txt": "branch breakage\n"})
        self.advance()
        land.check_line(self.turn)
        self.assertIn("fix", self.wait(directory))
        self.assertIn(SUITE, self.wait(directory)["fix"]["line"])
        self.assertEqual(self.checks[0][0], ["true", SUITE])
        self.assert_cleaned()


if __name__ == "__main__":
    unittest.main()
