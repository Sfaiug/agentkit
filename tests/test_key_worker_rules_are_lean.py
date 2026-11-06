"""A worker's rules say only what no refusal tells it, and each judgement says why it is one.

A rule ak enforces with a refusal that names the fix teaches itself when it bites, so the rules a
turn opens with hold only what a worker cannot learn as it acts.  Every `[worker judgement]` line,
in every role, says `because` no check holds it, which names the check to build next; every
`[checked by ak: X]` line names a test file of this checkout; and the executor's rules stay under
240 words and the fixer's under 280, counted before the task.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, one `ak worker` turn per role scripted
by fakeadapter.py, in a workspace whose AGENTS.md says `users: real` so a reviewer's rules carry
the rule that adds; judged by the prompt files ak writes, this test fails against `/bin/false`.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home

REPO = Path(__file__).resolve().parents[1]
TASK = "Add a retry to the acme widget.\n"
ROLES = ("executor", "fixer", "reviewer", "reviewer-pr",
         "executor-scratch", "fixer-scratch", "reviewer-scratch")
WORDS = {"executor": 240, "fixer": 280}


class LeanRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        akconfig.write(cls.home, ["opus"])
        fakeadapter.install(cls.home, claude="silent")
        task = cls.home.write("prompt.md", TASK)
        workspace = cls.home.path / "code" / "widgets"
        workspace.mkdir(parents=True)
        (workspace / "AGENTS.md").write_text("---\nusers: real\n---\n# widgets\n")
        cls.turns = {}
        for role in ROLES:
            out = cls.home.root / f"out-{role}"
            done = cls.home.ak("worker", "opus", str(task), "--role", role,
                               "--workspace", str(workspace), "--out", str(out))
            prompt = out / "prompt.md"
            cls.turns[role] = done, prompt.read_text() if prompt.is_file() else ""

    def rules(self, role):
        """What the turn of `role` opens with, before its task."""
        done, prompt = self.turns[role]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(prompt.endswith(f"\n\n{TASK}"), prompt)
        return prompt.removesuffix(TASK)

    def test_every_judgement_says_why_no_check_holds_it(self):
        for role in ROLES:
            judgements = re.findall(r"^\[worker judgement\] .*", self.rules(role), re.M)
            self.assertTrue(judgements, role)
            for line in judgements:
                with self.subTest(role=role, rule=line):
                    self.assertIn("because", line)

    def test_every_checked_rule_names_a_test_that_exists(self):
        for role in ROLES:
            checked = re.findall(r"^\[checked by ak: ([^\]]*)\]", self.rules(role), re.M)
            self.assertTrue(checked, role)
            for name in checked:
                with self.subTest(role=role, test=name):
                    self.assertRegex(name, r"^tests/test_[a-z0-9_]+\.py$")
                    self.assertTrue((REPO / name).is_file())

    def test_the_executor_and_the_fixer_get_few_words(self):
        for role, most in WORDS.items():
            with self.subTest(role=role):
                self.assertLess(len(self.rules(role).split()), most)


if __name__ == "__main__":
    unittest.main()
