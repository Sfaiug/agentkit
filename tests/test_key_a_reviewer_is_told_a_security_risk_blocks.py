"""A reviewer is told a security risk blocks, as a safety or data-loss risk does.

ak builds production software, so the rule saying what a blocking finding is names security
beside safety and data loss: an input reaching a shell unescaped, a secret left readable or a
missing access check is not left to each reviewer model to weigh.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, one `ak worker` turn per reviewer role
scripted by fakeadapter.py, judged by the prompt files ak writes; this test fails against
`/bin/false`.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home

ROLES = ("reviewer", "reviewer-pr", "reviewer-scratch")


class SecurityBlocks(unittest.TestCase):
    def test_each_reviewers_blocking_rule_names_a_security_risk(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="silent")
        task = home.write("prompt.md", "Review the acme widget.\n")
        workspace = home.path / "code" / "widgets"
        workspace.mkdir(parents=True)
        for role in ROLES:
            with self.subTest(role):
                out = home.root / f"out-{role}"
                done = home.ak("worker", "opus", str(task), "--role", role,
                               "--workspace", str(workspace), "--out", str(out))
                self.assertEqual(done.code, 0, done.out + done.err)
                rule = re.search(r"^.*Hand in a \*\*blocking\*\* finding.*$",
                                 (out / "prompt.md").read_text(), re.M)
                self.assertIsNotNone(rule)
                self.assertIn("a safety, security or data-loss risk", rule[0])


if __name__ == "__main__":
    unittest.main()
