"""Silence never stops a command before the timeout it declared.

A slow test under `timeout N` may print nothing for longer than the silence limit, and stopping
it there throws its work away with no verdict.  While the watched tree holds a live `timeout N`,
silence counts from that bound's end; a command with no declared bound still stops at the
silence limit.  Silence is the command's, so it counts from when its box is up, not from when ak
began building that box.  Black-box: the program `AK_BIN` names checks a landing line from outside
through tests/fixtures/akline.py, its member's record carrying a silence limit of three seconds.

The suite here prints until a test hushes it, so a silence begins where the test says, with any
`timeout` live: a process starting late spends none of the limit.  Each silence under a bound
outlasts the poll the watchdog may see the last line on, so the bound is asked about, and a bound
meant to hold far outlasts that silence, as a process's age counts from before its timer starts.
A command meant to be stopped sleeps far past the limit, and a bound before it outlasts that
sleep, so a bound that held on after it ended would let the sleep finish.
"""

import json
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, SUITE, rules

SILENCE_MINUTES = 0.05
KILLED = "[killed at the limit]"
# Blank lines are output like any other, and no fix line quotes one.  A box's temporary directory
# is its own, so each piece's word is its own.
TALKING = ('export hush="${TMPDIR:-/tmp}/hush"; '
           '(while :; do [ -e "$hush" ] || echo; sleep .1; done) & '
           'trap "kill $! 2>/dev/null" EXIT; ' + SUITE)
HUSH, SPEAK = ': >"$hush"', 'rm "$hush"'


class SilenceHonoursDeclaredTimeout(unittest.TestCase):
    def check(self, test, box_seconds=0):
        """What the lander left a member waiting on, the member adding `test` to the suite, with
        each box taking `box_seconds` longer to build."""
        line = Line({"AGENTS.md": rules(TALKING), "t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        if box_seconds:
            line.home.fake("bwrap", f"#!/bin/sh\nsleep {box_seconds}\n"
                                    f'exec {shutil.which("bwrap")} "$@"\n')
        line.member({"t/slow.sh": test})
        record = line.members[0] / "run.json"
        record.write_text(json.dumps({**json.loads(record.read_text()),
                                      "silence_minutes": SILENCE_MINUTES}))
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return line.verdict(1)

    def test_a_silent_command_under_a_declared_timeout_runs_to_its_end(self):
        verdict = self.check(f"timeout 600 sh -c '{HUSH}; sleep 5; {SPEAK}'\n")
        self.assertIn("land", verdict, verdict)

    def test_a_silence_after_a_declared_timeout_counts_from_its_end(self):
        # Shorter than the limit after the bound's end, however long after the last look found it.
        verdict = self.check(f"timeout 600 sh -c '{HUSH}; sleep 5'; sleep 1\n")
        self.assertIn("land", verdict, verdict)

    def test_a_box_slow_to_build_is_no_silence_of_the_command(self):
        verdict = self.check("true\n", box_seconds=5)
        self.assertIn("land", verdict, verdict)

    def test_a_silent_command_with_no_declared_bound_still_stops_at_the_silence_limit(self):
        verdict = self.check(f"{HUSH}; sleep 60\n")
        self.assertIn(KILLED, verdict["fix"]["line"], verdict)

    def test_a_declared_timeout_that_ended_holds_off_no_silence_after_it(self):
        verdict = self.check(f"timeout 600 sh -c '{HUSH}; sleep 5'; sleep 60\n")
        self.assertIn(KILLED, verdict["fix"]["line"], verdict)

    def test_a_declared_timeout_past_its_bound_holds_off_no_silence(self):
        # A harmless signal, so the bound passes with `timeout` and its command still there.
        verdict = self.check(f"timeout -s CONT 1 sh -c '{HUSH}; sleep 60'\n")
        self.assertIn(KILLED, verdict["fix"]["line"], verdict)

    def test_a_declared_timeout_ends_the_command_by_itself(self):
        # By the signal its timer sends, once the silence is over: no timer can then race the limit.
        verdict = self.check(
            f"timeout 600 sh -c '{HUSH}; sleep 5; {SPEAK}; kill -ALRM $PPID; sleep 60'\n")
        self.assertEqual(verdict["fix"]["tests"], ["slow.sh"], verdict)
        self.assertNotIn(KILLED, verdict["fix"]["line"], verdict)


if __name__ == "__main__":
    unittest.main()
