"""A test that hangs in a line's check sends its change back, as one that fails does: a piece
stopped for silence on both its goes is red in the tests it had begun and not ended, those run
alone and are narrowed over the stacks, and the member whose change hangs them gets its fix,
which names them and whose line names the silence, beside a FAIL line and output shaped like
another command's record, and after a command too long for the line, while the others land in
the same pass.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its suite cut in pieces, its runner naming each test as run as it
starts and printing `PASS  <test> (<seconds>s)` for each that passes, and a silence of seconds on
every member's record.  Behind a first member that landed, one member's change makes one test
say it failed and never end.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import RUNNER, Line, rules

SILENCE_MINUTES = 0.05
SUITE = ': "$AK_SHARD" ' + "acme-api " * 30 + "; sh suite.sh"
TIMED = RUNNER.replace('sh "t/$t" "$@" ||', 'sh "t/$t" "$@" && echo "PASS  $t (0.1s)" ||')
HANGS = ("if [ -f hang.txt ]; then printf 'FAIL acme-api\\n\\n$ sh child.sh\\n[exit 1]\\n'; "
         "exec sleep 600; fi\n")


class ATestThatHangsSendsItsChangeBack(unittest.TestCase):
    def test_its_member_is_sent_back_naming_the_silence_and_the_others_land(self):
        line = Line({"AGENTS.md": rules(SUITE), "suite.sh": TIMED, "t/hang.sh": HANGS,
                     **{f"t/{name}.sh": "true\n" for name in "abc"}})
        self.addCleanup(line.close)

        def member(files):
            line.member(files)
            record = line.members[-1] / "run.json"
            record.write_text(json.dumps({**json.loads(record.read_text()),
                                          "silence_minutes": SILENCE_MINUTES}))

        member({"member-1.txt": "1\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn("land", line.verdict(1), line.runs())
        for n in range(2, 8):
            member({f"member-{n}.txt": f"{n}\n", **({"hang.txt": "x\n"} if n == 4 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(2, 8):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 4 else ["land"], (n, line.runs()))
        fix = line.verdict(4)["fix"]
        self.assertEqual(fix["tests"], ["hang.sh"], fix)
        self.assertIn(f"stopped after {SILENCE_MINUTES:g} min of silence", fix["line"])


if __name__ == "__main__":
    unittest.main()
