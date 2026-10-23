"""`ak plan add` refuses a line that could prove nothing, and leaves the plan as it was.

A check that already passes on the project's default branch proves nothing about the work; one
naming the seat's own checkout tests what that checkout holds, not the default branch; and an
outcome or check the line's format cannot hold would break every later read of the plan.  Each
is refused with exit 2 and words that tell the model what to write instead, so those are
pinned, and the plan keeps its bytes (no plan stays no plan).  A refusal of the text comes
before the check runs.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

PASSES = ("ak plan: this check already passes on acme's default branch, so it proves nothing; "
          "write one that fails until the work is done\n")
OUTCOME = "ak plan: an outcome is plain words without `·`\n"
ONE_COMMAND = "ak plan: a check is one shell command without backticks or line breaks\n"
CHECKOUT = ("ak plan: this check holds ~/code/acme, the path of the project's checkout, but a "
            "check runs in a clean checkout of its default branch: name paths relative to the "
            "repository, as in `python3 tests/test_x.py`\n")
# a check that leaves a mark wherever it runs, so a refusal can show it never ran
RAN = 'touch "$HOME/ran"; '


class PlanAddRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "acme", files={"done.txt": "done\n",
                                              "tests/test_parser.py": "import sys; sys.exit(1)\n"})
        # gone from the clone, still on main: the check is judged on main
        (cls.rig.path / "done.txt").unlink()
        cls.plans = {}
        for name in ("fix-api", "beta"):
            Seat(cls.home, name, cwd=cls.rig.path, record={"repo": str(cls.rig.path)},
                 alive=False)
            cls.plans[name] = cls.home.path / ".agentkit" / "state" / f"plan-{name}.md"
        done = cls.home.ak("plan", "add", "the parser works",
                           "--check", "python3 tests/test_parser.py",
                           env={"AGENTKIT_SESSION": "fix-api"}, cwd=cls.rig.path)
        assert done.code == 0, done.err
        cls.before = {name: cls.contents(plan) for name, plan in cls.plans.items()}
        assert cls.before["fix-api"] and cls.before["beta"] is None

    @staticmethod
    def contents(plan):
        return plan.read_bytes() if plan.exists() else None

    def refused(self, outcome, check, env=None):
        """What each seat's `ak plan add` printed as it was refused; neither plan changed."""
        errors = set()
        for name in self.plans:
            done = self.home.ak("plan", "add", outcome, "--check", check,
                                env={"AGENTKIT_SESSION": name, **(env or {})},
                                cwd=self.rig.path)
            self.assertEqual(done.code, 2, done.out)
            self.assertEqual(done.out, "")
            errors.add(done.err)
        self.assertEqual({name: self.contents(plan) for name, plan in self.plans.items()},
                         self.before)
        self.assertEqual(list(self.home.path.glob(".agentkit/wt/plan-*")), [])
        self.assertEqual(len(errors), 1, errors)
        return errors.pop()

    def assertNeverRan(self):
        self.assertFalse((self.home.path / "ran").exists())

    def test_a_check_that_already_passes_on_the_default_branch_proves_nothing(self):
        for check in ("true", "test -f done.txt", "touch made.txt"):
            with self.subTest(check=check):
                self.assertEqual(self.refused("the work is done", check), PASSES)
        # it ran in a checkout of its own, never in the seat's
        self.assertFalse((self.rig.path / "made.txt").exists())

    def test_an_outcome_must_be_plain_words_without_a_middle_dot(self):
        for outcome in ("the parser · works", "   "):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.refused(outcome, RAN + "false"), OUTCOME)
        self.assertNeverRan()

    def test_a_check_must_be_one_command_without_backticks_or_line_breaks(self):
        for check in ("echo `x`; false", RAN + "\nfalse", "false\nfalse"):
            with self.subTest(check=check):
                self.assertEqual(self.refused("the parser works", check), ONE_COMMAND)
        self.assertNeverRan()

    def test_a_check_naming_the_checkout_is_refused_however_it_spells_the_path(self):
        spellings = (str(self.rig.path), "~/code/acme", "$HOME/code/acme", "${HOME}/code/acme",
                     '"$HOME"/code/acme', "'~/code/acme'", "~/code/acme-old")
        for path in spellings:
            with self.subTest(path=path):
                check = f"{RAN}cd {path} && python3 tests/test_parser.py"
                self.assertEqual(self.refused("the parser works", check), CHECKOUT)
        self.assertNeverRan()

    def test_outside_a_seat_nothing_is_added_to_any_plan(self):
        done = self.home.ak("plan", "add", "the parser works", "--check", RAN + "false",
                            cwd=self.rig.path)
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual({name: self.contents(plan) for name, plan in self.plans.items()},
                         self.before)
        self.assertNeverRan()


if __name__ == "__main__":
    unittest.main()
