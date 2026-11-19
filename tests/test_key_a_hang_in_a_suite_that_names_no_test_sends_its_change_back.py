"""A hang in a suite that names no test sends its change back too: a project whose `tests:`
line is one plain command, naming no test as run or failed and cut in no pieces, has the member
whose change makes it hang found by whole checks of the stacks and sent to its fix, while the
others land in the same pass.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, with a silence of seconds on every member's record.  Behind a first
member that landed, one member's change makes the suite never end.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, rules

PLAIN = "if [ -f hang.txt ]; then exec sleep 600; fi\n"


class AHangInASuiteThatNamesNoTestSendsItsChangeBack(unittest.TestCase):
    def test_its_member_is_sent_back_and_the_others_land(self):
        line = Line({"AGENTS.md": rules("sh suite.sh"), "suite.sh": PLAIN})
        self.addCleanup(line.close)

        def member(files):
            line.member(files)
            record = line.members[-1] / "run.json"
            record.write_text(json.dumps({**json.loads(record.read_text()),
                                          "silence_minutes": 0.05}))

        member({"member-1.txt": "1\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1), line.runs())
        for n in range(2, 6):
            member({f"member-{n}.txt": f"{n}\n", **({"hang.txt": "x\n"} if n == 3 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(2, 6):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 3 else ["land"], (n, line.runs()))
        self.assertIn("of silence", line.verdict(3)["fix"]["line"])


if __name__ == "__main__":
    unittest.main()
