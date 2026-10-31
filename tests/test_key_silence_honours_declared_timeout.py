"""Silence never stops a command before the timeout it declared.

A slow test under `timeout N` may print nothing for longer than the silence limit, and stopping
it there throws its work away with no verdict.  While the watched tree holds a live `timeout N`,
silence counts from that bound's end; a command with no declared bound still stops at the
silence limit.  Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its member's record carrying a silence limit of three seconds.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

SILENCE_MINUTES = 0.05
KILLED = "[killed at the limit]"


class SilenceHonoursDeclaredTimeout(unittest.TestCase):
    def check(self, test):
        """What the lander left a member waiting on, the member adding `test` to the suite."""
        line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        line.member({"t/slow.sh": test})
        record = line.members[0] / "run.json"
        record.write_text(json.dumps({**json.loads(record.read_text()),
                                      "silence_minutes": SILENCE_MINUTES}))
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return line.verdict(1)

    def test_a_silent_command_under_a_declared_timeout_runs_to_its_end(self):
        verdict = self.check("timeout 30 sh -c 'sleep 6'\n")
        self.assertIn("land", verdict, verdict)

    def test_a_silent_command_with_no_declared_bound_still_stops_at_the_silence_limit(self):
        verdict = self.check("sleep 6\n")
        self.assertIn(KILLED, verdict["fix"]["line"], verdict)

    def test_a_declared_timeout_that_ended_holds_off_no_silence_after_it(self):
        verdict = self.check("timeout 30 sleep 4; sleep 6\n")
        self.assertIn(KILLED, verdict["fix"]["line"], verdict)

    def test_a_declared_timeout_ends_the_command_by_itself(self):
        # Its bound ends a second past the silence limit: a start read to the whole second, as
        # the kernel's boot time gives it, can take all of that second away.
        verdict = self.check("timeout 4 sleep 60\n")
        self.assertEqual(verdict["fix"]["tests"], ["slow.sh"], verdict)
        self.assertNotIn(KILLED, verdict["fix"]["line"], verdict)


if __name__ == "__main__":
    unittest.main()
