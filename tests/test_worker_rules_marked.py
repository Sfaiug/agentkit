"""Every worker rule names who keeps it; ak's claims cite existing enforcement tests."""

from pathlib import Path
import re
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import worker


class WorkerRulesMarked(unittest.TestCase):
    def rules(self, text):
        for line in text.splitlines():
            with self.subTest(rule=line):
                if line.startswith("[worker judgement] "):
                    self.assertTrue(line.removeprefix("[worker judgement] ").strip())
                    continue
                match = re.fullmatch(r"\[checked by ak: (tests/test_[a-z0-9_]+\.py)\] ak .+", line)
                self.assertIsNotNone(match, "rule needs a mark and ak's action when checked")
                if match:
                    self.assertTrue((REPO / match[1]).is_file(), match[1])

    def test_every_roles_rules_are_marked(self):
        for role, preamble in worker.PREAMBLES.items():
            with self.subTest(role=role):
                opener, separator, rules = preamble.partition("\n")
                expected = ("You are the reviewer of a pull request by another author." if role == "reviewer-pr"
                            else "You are the reviewer." if role.startswith("reviewer")
                            else "You are the executor, continuing." if role.startswith("fixer")
                            else "You are the executor.")
                self.assertEqual(opener, expected)
                self.assertTrue(separator and rules)
                self.rules(rules)

    def test_conditional_real_users_rule_is_marked(self):
        self.rules(worker.REAL_USERS)


if __name__ == "__main__":
    unittest.main()
