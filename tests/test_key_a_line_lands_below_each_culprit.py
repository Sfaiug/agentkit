"""A line lands the stack below each culprit before it looks for the next one: once narrowing
blames a member, the stack just below where it stood gets its whole check, and green it lands,
before the rebuilt stack, which may hold another culprit, is checked.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  Of four members the third and the fourth each turn the suite red; the
check of the stack rebuilt without the third, holding the fourth, holds until the test lets it go.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import READINGS, Line

TESTS = {"t/bad.sh": 'test -z "$(ls bad-* 2>/dev/null)"\n',
         "t/hold.sh": """[ -f bad-4.txt ] && [ ! -f bad-3.txt ] || exit 0
storage=$(git rev-parse --git-common-dir)
touch "$storage/reached"
until [ -f "$storage/go" ]; do sleep 0.1; done
"""}


class ALineLandsBelowEachCulprit(unittest.TestCase):
    def test_the_stack_below_a_culprit_lands_before_the_rebuilt_stack_is_checked(self):
        line = Line(TESTS)
        self.addCleanup(line.close)
        for n in range(1, 5):
            line.member({f"member-{n}.txt": f"{n}\n", **({f"bad-{n}.txt": "x\n"} if n > 2 else {})})
        storage = line.rig.path / ".git"
        lander = line.home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
        deadline = time.monotonic() + 300
        while not (storage / "reached").exists():
            self.assertIsNone(lander.poll(), line.home.log("spawn-1.err").read_text())
            self.assertLess(time.monotonic(), deadline, "the rebuilt stack was never checked")
            time.sleep(0.2)
        seen = [line.verdict(n) for n in (1, 2)]
        (storage / "go").touch()
        self.assertEqual(lander.wait(timeout=300), 0, line.home.log("spawn-1.err").read_text())
        for wait in seen:
            self.assertIn("land", wait, line.runs())
        for n, key in enumerate(("land", "land", "fix", "fix"), 1):
            self.assertEqual([k for k in ("land", "fix") if k in line.verdict(n)], [key],
                             (n, line.runs()))


if __name__ == "__main__":
    unittest.main()
