"""A rebuilt top's red parts run alone only while quicker than a whole check: run one after
another, where the whole check runs its pieces at once, they cost what the suite's timing record
holds for their tests together, and where that is more than the whole check that confirmed them
took, none runs alone and the top rebuilt without the culprit goes whole at once.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its suite cut in pieces so that each test runs in the piece its name
begins with, however many pieces there are, each passing test claiming an hour, which a first
member's whole check keeps in the record.  Of six members behind it the second turns a test in
each of two pieces red.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import RUNNER, Line

# Tests named by their paths, as the record keeps them; a run of named tests logs the members its
# tree holds.
PIECES = (RUNNER.replace('[ $((i % n + 1)) = "$k" ]', '[ $(((${t%%-*} - 1) % n + 1)) = "$k" ]')
          .replace('tests=$(cat "$AK_ONLY")', 'tests=$(sed "s|^t/||" "$AK_ONLY")')
          .replace('echo "alone $*"', 'echo "alone" $(ls member-*.txt)')
          .replace('echo "$t" >>', 'echo "t/$t" >>')
          .replace('sh "t/$t" "$@" ||', 'sh "t/$t" "$@" && echo "PASS  t/$t (3600.0s)" ||'))
# Each test fails on a tree holding the file its name ends with.
TESTS = {f"t/{name}.sh": f"test ! -f {name.split('-')[1]}.txt\n" for name in ("1-a", "2-c")}


class RedPartsRunAloneOnlyWhileQuickerThanAWholeCheck(unittest.TestCase):
    def test_parts_slower_than_a_whole_check_leave_the_rebuilt_top_whole(self):
        line = Line({**TESTS, "suite.sh": PIECES})
        self.addCleanup(line.close)
        line.member({"member-1.txt": "1\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1), line.runs())
        for n in range(2, 8):
            line.member({f"member-{n}.txt": f"{n}\n", **({"a.txt": "x\n", "c.txt": "x\n"}
                                                         if n == 3 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(2, 8):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 3 else ["land"], (n, line.runs()))
        # only the top rebuilt without the culprit holds the last member and not the culprit
        self.assertNotIn(("alone", " ".join(f"member-{n}.txt" for n in (1, 2, 4, 5, 6, 7))),
                         line.runs())


if __name__ == "__main__":
    unittest.main()
