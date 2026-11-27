"""`ak plan add` writes one open line in the plan format, and keeps the line a check already has.

A seat's plan is the file its bar counts and its done is read from, and later builds parse its
lines: each names the outcome, the check that proves it, the project (its checkout and root
commit) and when it was written on which commit of the default branch, where the check failed
then.  The check runs on origin's default branch as it is now, never on the seat's checkout, so
the line proves the work is still to do, and without what the seat's launch set for the seat
alone: a variable the owner sets too is the launch's only where the launch named it in
AGENTKIT_SEAT_ENV.  Adding the same check again keeps the one line: a seat that repeats itself
must not owe the work twice.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

CHECK = "python3 tests/test_parser.py"
WRITTEN = r"written \d{4}-\d\d-\d\d \d\d:\d\d"


class PlanAdd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "acme",
                      files={"tests/test_parser.py": "import sys; sys.exit(1)\n"})
        cls.root = cls.rig.git("rev-list", "--max-parents=0", "HEAD")[:12]
        # origin moves on after the clone last fetched, and the clone holds an uncommitted fix:
        # the line must name origin's head, and the check fail there
        cls.rig.commit({"README.md": "acme\n"}, "readme")
        cls.main = cls.rig.head()[:12]
        cls.rig.git("reset", "-q", "--hard", "HEAD~1")
        cls.rig.git("update-ref", "refs/remotes/origin/main", "HEAD")
        (cls.rig.path / "tests" / "test_parser.py").write_text("")

    def seat(self, name):
        Seat(self.home, name, cwd=self.rig.path, record={"repo": str(self.rig.path)},
             alive=False)
        return self.home.path / ".agentkit" / "state" / f"plan-{name}.md"

    def add(self, name, outcome, check=CHECK, code=0, **env):
        done = self.home.ak("plan", "add", outcome, "--check", check,
                            env={"AGENTKIT_SESSION": name, **env}, cwd=self.rig.path)
        self.assertEqual(done.code, code, done.err)
        return done.out

    def line(self, outcome, check=CHECK):
        return (rf"- \[ \] {re.escape(outcome)} · check: `{re.escape(check)}` · "
                rf"~/code/acme#{self.root} · {WRITTEN} on {self.main}")

    def test_a_check_failing_on_the_default_branch_is_added_as_one_open_line(self):
        plan = self.seat("fix-api")
        out = self.add("fix-api", "the parser works")
        self.assertRegex(out, rf"\A{self.line('the parser works')}\n\Z")
        self.assertEqual(plan.read_text(), out)
        # the clean checkout the check ran in is gone
        self.assertEqual(list(self.home.path.glob(".agentkit/wt/plan-*")), [])

    def test_the_same_check_added_again_keeps_the_line_it_has(self):
        plan = self.seat("beta")
        first = self.add("beta", "the parser works")
        written = plan.read_bytes()
        self.assertEqual(self.add("beta", "the parser works"), first)
        self.assertEqual(plan.read_bytes(), written)
        # the check in this project is the line's identity: other words keep the first ones
        self.assertEqual(self.add("beta", "parsing is fixed"), first)
        self.assertEqual(plan.read_bytes(), written)

    def test_another_check_is_appended_after_the_lines_already_there(self):
        plan = self.seat("gamma")
        plan.write_text("- [x] set up the repository\n")
        first = self.add("gamma", "the parser works")
        readme = "grep -q parser README.md"
        second = self.add("gamma", "the readme names the parser", readme)
        self.assertRegex(second, rf"\A{self.line('the readme names the parser', readme)}\n\Z")
        self.assertEqual(plan.read_text(), "- [x] set up the repository\n" + first + second)

    def test_a_check_is_handed_the_owners_variable_and_never_one_the_launch_set(self):
        plan = self.seat("epsilon")
        seen = 'test -n "$ACME_INLINE"'
        # the owner's own reaches the check, which so passes on the default branch: refused
        self.assertEqual(self.add("epsilon", "the owner set it", seen, 2, ACME_INLINE="set"), "")
        self.assertFalse(plan.exists())
        out = self.add("epsilon", "the launch set it", seen, ACME_INLINE="set",
                       AGENTKIT_SEAT_ENV="ACME_OTHER ACME_INLINE")
        self.assertRegex(out, rf"\A{self.line('the launch set it', seen)}\n\Z")

    def test_an_outcome_is_written_with_its_spaces_folded(self):
        self.seat("delta")
        out = self.add("delta", "  the   parser\tworks  ")
        self.assertRegex(out, rf"\A{self.line('the parser works')}\n\Z")


if __name__ == "__main__":
    unittest.main()
