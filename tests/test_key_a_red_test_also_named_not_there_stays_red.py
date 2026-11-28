"""A test a run named as run and as failed was there, whatever else it named it: a red stack's
narrowing reads a stack whose suite named its red test so, and failed, as red, never as one
whose tree lacks that test.

Black-box: `AK_BIN` checks a landing line from outside through tests/fixtures/akline.py, its
suite naming every test `AK_ONLY` lists as not there (`AK_NOT_THERE`) before it runs them.  Of
four members the second makes one test fail.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import RUNNER, Line

ALL_NOT_THERE = RUNNER.replace(
    'tests=$(cat "$AK_ONLY")', 'tests=$(cat "$AK_ONLY"); cat "$AK_ONLY" >>"${AK_NOT_THERE:-/dev/null}"')


class ARedTestAlsoNamedNotThereStaysRed(unittest.TestCase):
    def test_the_member_that_turned_it_red_is_blamed(self):
        line = Line({"suite.sh": ALL_NOT_THERE, "t/bad.sh": "test ! -f bad.txt\n",
                     "t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        for n in range(1, 5):
            line.member({f"member-{n}.txt": f"{n}\n", **({"bad.txt": "x\n"} if n == 2 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, 5):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 2 else ["land"], (n, line.runs()))
        self.assertEqual(line.verdict(2)["fix"]["tests"], ["bad.sh"])


if __name__ == "__main__":
    unittest.main()
