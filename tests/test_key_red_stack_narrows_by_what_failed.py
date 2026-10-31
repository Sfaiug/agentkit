"""A red stack is narrowed by what failed: each step runs just the failing command's tests that
failed again alone, or with none named its red piece, whichever command failed, and starts just
ahead of the first stack running that command.  A member whose rewritten `tests:` line fails one
test on every tree holding it goes to its fixer and the others land, the suite run whole only on
the deepest stack, the one just below it and the one rebuilt without it; a red only the target's
suite shows narrows as before.  Blame still needs the stack just ahead green on what failed: a
member breaking a test both lines run is the one blamed, not the member whose line runs it.
Black-box: the program `AK_BIN` names checks the line from outside through
tests/fixtures/akline.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import SUITE, Line, rules

# t2 fails on a tree holding bad.txt, t3 under the strict line only.
TESTS = {"t/t1.sh": "true\n", "t/t2.sh": "test ! -f bad.txt\n",
         "t/t3.sh": 'test "${1:-}" != strict\n', "t/t4.sh": "true\n"}


class RedStackNarrowsByWhatFailed(unittest.TestCase):
    def narrow(self, culprit, changes):
        """Four members land, member n adding `changes[n]`: the line, once checked, the
        `culprit` sent to its fixer and the others landing."""
        line = Line(TESTS)
        self.addCleanup(line.close)
        for n in range(1, 5):
            line.member({f"member-{n}.txt": f"{n}\n", **changes.get(n, {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, 5):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == culprit else ["land"], (n, line.runs()))
        return line

    def test_a_rewritten_tests_line_failing_one_test_narrows_by_that_test_alone(self):
        line = self.narrow(2, {2: {"AGENTS.md": rules(f"{SUITE} strict")}})
        self.assertLessEqual(line.whole(), 3, line.runs())
        self.assertEqual(line.verdict(2)["fix"]["tests"], ["t3.sh"])

    def test_a_red_only_the_targets_suite_shows_narrows_by_its_tests_alone(self):
        line = self.narrow(3, {3: {"bad.txt": "bad\n"}})
        self.assertLessEqual(line.whole(), 3, line.runs())
        self.assertEqual(line.verdict(3)["fix"]["tests"], ["t2.sh"])

    def test_a_red_piece_naming_no_test_narrows_by_that_piece_alone(self):
        # every piece of the rewritten line fails, naming no test as failed; the stack ahead of
        # it, which does not run the line, gets its whole check
        line = self.narrow(2, {2: {"AGENTS.md": rules(f"{SUITE} unnamed; false")}})
        self.assertLessEqual(line.whole(), 3, line.runs())

    def test_a_test_broken_for_both_lines_blames_the_member_breaking_it(self):
        # member 2's line fails no test of its own: only t2, which member 1 breaks for both
        line = self.narrow(1, {1: {"bad.txt": "bad\n"}, 2: {"AGENTS.md": rules(f"{SUITE} again")}})
        self.assertEqual(line.verdict(1)["fix"]["tests"], ["t2.sh"])


if __name__ == "__main__":
    unittest.main()
