"""A red the first stack's check found without naming a test is asked of the target's whole
suite on its tip, never of the piece of the stack's number: the suite deals each tree's own test
files into its pieces, so on the tip, without the files the stack adds, that piece holds other
tests.  Red there, the red is the target's: the line waits and nobody is blamed.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, with the suite tests/test_key_an_unnamed_red_narrows_by_whole_checks.py
uses: each tree's test files dealt into its pieces in name order, a piece failing before it names
any test where one of its files cannot be loaded, each piece logging the stack it ran on.  The
target holds a test that cannot be loaded, and the one change adds a test sorting ahead of it, so
the piece holding the broken test has another number on the change's stack than on the tip.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line
from test_key_an_unnamed_red_narrows_by_whole_checks import TESTS


class ARedThatNamedNoTestIsAskedOfTheWholeTarget(unittest.TestCase):
    def test_the_tip_red_whole_holds_the_line_and_blames_nobody(self):
        line = Line({**TESTS, "t/b.sh": ". ./gone.sh\n"})
        self.addCleanup(line.close)
        line.member({"member-1.txt": "1\n", "t/a.sh": "true\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([key for key in ("land", "fix") if key in line.verdict(1)], [],
                         done.out + done.err)
        stacks = {}
        for share, *members in (row.split(" ") for row in
                                (line.rig.path / ".git" / "stacks").read_text().splitlines()):
            stacks.setdefault(frozenset(members), set()).add(share)
        # the tip, holding no member's file, leaves the glob unmatched
        tip, stack = frozenset({"member-*"}), frozenset({"member-1.txt"})
        self.assertGreater(len(stacks[stack]), 1, stacks)
        self.assertEqual(stacks[tip], stacks[stack], stacks)


if __name__ == "__main__":
    unittest.main()
