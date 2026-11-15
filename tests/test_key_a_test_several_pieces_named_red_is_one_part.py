"""A test several pieces named red is one red part, not one for each piece: a test every piece
runs, red in each, runs alone once on the top rebuilt without the culprit, where it ran there once
for each piece but the first.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its suite cut in pieces with one test that every piece runs, however
many pieces there are.  Of six members behind a first that landed the second turns that test red.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import RUNNER, Line

# A run of named tests logs the members its tree holds.
PIECES = (RUNNER.replace('[ $((i % n + 1)) = "$k" ]',
                         '{ [ "$t" = every.sh ] || [ $((i % n + 1)) = "$k" ]; }')
          .replace('echo "alone $*"', 'echo "alone" $(ls member-*.txt)'))


class ATestSeveralPiecesNamedRedIsOnePart(unittest.TestCase):
    def test_it_runs_alone_once_on_the_top_rebuilt_without_the_culprit(self):
        line = Line({"t/every.sh": "test ! -f broken.txt\n", "suite.sh": PIECES,
                     **{f"t/{name}.sh": "true\n" for name in "abc"}})
        self.addCleanup(line.close)
        line.member({"member-1.txt": "1\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1), line.runs())
        for n in range(2, 8):
            line.member({f"member-{n}.txt": f"{n}\n", **({"broken.txt": "x\n"} if n == 3 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(2, 8):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 3 else ["land"], (n, line.runs()))
        self.assertEqual(line.verdict(3)["fix"]["tests"], ["every.sh"], line.runs())
        # the whole check ran in pieces, each naming the test red
        self.assertTrue(any(run[0] == "piece" and run[1].startswith("2/") for run in line.runs()),
                        line.runs())
        # only the top rebuilt without the culprit holds the last member and not the culprit
        self.assertEqual(line.runs().count(
            ("alone", " ".join(f"member-{n}.txt" for n in (1, 2, 4, 5, 6, 7)))), 1, line.runs())


if __name__ == "__main__":
    unittest.main()
