"""The top rebuilt without a culprit is checked whole next, not the stack below it: once a red
check's parts are dealt with, its culprit sent back and each other part run alone on the top
rebuilt without it, that top goes whole, and green it lands every member left.  So a culprit
costs the suite one whole run, where checking the stack below it first cost two.  Red, the top
is narrowed as any red check is.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  Of five members the third turns the suite red.  Of four the third and
the fourth each do, the fourth only without the third, so only the top rebuilt without the third
shows it.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line


class TheRebuiltTopIsCheckedWholeNext(unittest.TestCase):
    def land(self, tests, count, broken):
        """One pass over `count` members, member n adding the file `broken[n]` breaks the test
        of that name: each of those sent back, told its own test, the others landing."""
        line = Line(tests)
        self.addCleanup(line.close)
        for n in range(1, count + 1):
            line.member({f"member-{n}.txt": f"{n}\n",
                         **({f"{broken[n]}.txt": "x\n"} if n in broken else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, count + 1):
            wait = line.verdict(n)
            self.assertEqual([key for key in ("land", "fix") if key in wait],
                             ["fix"] if n in broken else ["land"], (n, line.runs()))
            if n in broken:
                self.assertEqual(wait["fix"]["tests"], [f"{broken[n]}.sh"], line.runs())
        return line

    def test_a_culprit_costs_one_whole_run(self):
        line = self.land({"t/third.sh": "test ! -f third.txt\n"}, 5, {3: "third"})
        # the top, red; the top rebuilt without the third, green
        self.assertEqual(line.whole(), 2, line.runs())

    def test_a_culprit_only_the_rebuilt_top_shows_is_found_there(self):
        line = self.land({"t/third.sh": "test ! -f third.txt\n",
                          "t/fourth.sh": "test ! -f fourth.txt || test -f third.txt\n"},
                         4, {3: "third", 4: "fourth"})
        # the top, red on the third; rebuilt without it, red on the fourth; without both, green
        self.assertEqual(line.whole(), 3, line.runs())


if __name__ == "__main__":
    unittest.main()
