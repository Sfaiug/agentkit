"""A run the lander blamed whose red is its own is woken for its fix at once, not once the runs
ahead of it leave the line: the tests it failed, red again on the target's tip with it alone,
give its verdict, which waits on none of them.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  Of three members the second turns a test red by itself, the first in
the line or not, and is blamed; the check of the stack rebuilt without it holds until the test
lets it go.  Meanwhile, the first still in the line, the second's resume is started, opening its
`log.txt`.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import READINGS, Line

TESTS = {"t/bad.sh": 'test ! -f bad.txt\n',
         "t/hold.sh": """storage=$(git rev-parse --git-common-dir)
[ -f member-3.txt ] && [ ! -f bad.txt ] || exit 0
touch "$storage/reached"
until [ -f "$storage/go" ]; do sleep 0.1; done
"""}


class ABlamedRunRedOnItsOwnIsFixedAtOnce(unittest.TestCase):
    def test_its_fix_starts_while_the_run_ahead_is_still_in_the_line(self):
        line = Line(TESTS)
        self.addCleanup(line.close)
        for n in range(1, 4):
            line.member({f"member-{n}.txt": f"{n}\n", **({"bad.txt": "x\n"} if n == 2 else {})})
        storage, woken = line.rig.path / ".git", line.members[1] / "log.txt"
        lander = line.home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
        said = line.home.log("spawn-1.err")

        def until(done, why):
            deadline = time.monotonic() + 300
            while not done():
                self.assertIsNone(lander.poll(), said.read_text())
                self.assertLess(time.monotonic(), deadline, why)
                time.sleep(0.2)

        until((storage / "reached").exists, "the stack rebuilt without the blamed run was never checked")
        wait = line.verdict(2)
        self.assertEqual(wait["fix"]["tests"], ["bad.sh"], line.runs())
        self.assertNotIn("after", wait)
        until(woken.exists, "the blamed run was not woken while the run ahead was in the line")
        (storage / "go").touch()
        self.assertEqual(lander.wait(timeout=300), 0, said.read_text())
        self.assertIn("land", line.verdict(1))
        self.assertIn("land", line.verdict(3))


if __name__ == "__main__":
    unittest.main()
