"""A plan line needs its own check, even when the project's suite currently fails."""

import unittest

from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig


SUITE = "sh checks.sh 2>&1"
FOCUSED = "sh checks.sh api"
DECLARATION = f"---\ntests: {SUITE}\n---\n"


class PlanRefusesWholeSuite(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = Rig(self.home, "acme", files={
            "AGENTS.md": DECLARATION,
            "checks.sh": 'if [ "$#" -eq 0 ]; then touch "$HOME/suite-ran"; fi\nexit 1\n',
        })
        Seat(self.home, "fix-api", cwd=self.rig.path, record={"repo": str(self.rig.path)},
             alive=False)
        self.plan = self.home.path / ".agentkit/state/plan-fix-api.md"

    def command(self, *args):
        return self.home.ak("plan", *args, env={"AGENTKIT_SESSION": "fix-api"})

    def refused(self, *args):
        done = self.command(*args)
        self.assertEqual(done.code, 2, done.err)
        for words in ("acme", "whole-suite", "tests:", "every PR", "focused check"):
            self.assertIn(words, done.err)
        self.assertFalse((self.home.path / "suite-ran").exists())

    def add(self, check):
        done = self.command("add", "the api works", "--check", check)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(f"check: `{check}`", self.plan.read_text())

    def test_add_refuses_the_suite_on_origin_before_running_it(self):
        self.rig.git("checkout", "-qb", "fix-api")
        self.rig.commit({"AGENTS.md": None}, push=False)
        for check in (SUITE, "sh   checks.sh  2>&1", "  sh  checks.sh  "):
            with self.subTest(check=check):
                self.refused("add", "the api works", "--check", check)
                self.assertFalse(self.plan.exists())
        self.add(FOCUSED)

    def test_no_declared_suite_allows_a_failing_check(self):
        for agents in ("---\nhealth: none\n---\n", None):
            with self.subTest(agents=agents):
                self.rig.commit({"AGENTS.md": agents})
                (self.rig.path / "AGENTS.md").write_text(DECLARATION)
                self.add(SUITE)
                (self.home.path / "suite-ran").unlink()

    def test_recheck_uses_the_current_suite_even_for_a_line_without_a_base(self):
        self.rig.commit({"AGENTS.md": None})
        self.add(FOCUSED)
        line = self.plan.read_text().rstrip("\n")
        self.rig.branch("trunk", {"AGENTS.md": DECLARATION})
        self.rig.origin("symbolic-ref", "HEAD", "refs/heads/trunk")
        for stored in (line, line.rsplit(" on ", 1)[0]):
            with self.subTest(line=stored):
                self.plan.write_text(stored + "\n")
                self.refused("check", "1", SUITE)
                self.assertEqual(self.plan.read_text(), stored + "\n")


if __name__ == "__main__":
    unittest.main()
