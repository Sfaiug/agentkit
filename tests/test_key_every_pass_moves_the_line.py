"""Every pass of a landing line moves it.  A member that changes under a pass costs only the
verdicts stacked on it: those ahead of it are written, and it and those behind it get none and
wait for the next pass.  A pass killed mid-check before it wrote a verdict is followed by one of
half the members, the first in line, and a pass that writes one gives the next the whole line
again, as does a pass killed after it wrote one.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py.  A test of the suite holds a check until the test lets it go, and
meanwhile the test changes a member's record, as its seat would, or kills the pass.
In-process: test_lander_every_pass_moves_the_line.
"""

import json
import os
from pathlib import Path
import signal
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import _strays
from fixtures.akline import READINGS, Line

HOLD = """storage=$(git rev-parse --git-common-dir)
[ -f "$storage/go" ] && exit 0
{only}touch "$storage/reached"
until [ -f "$storage/go" ]; do sleep 0.1; done
"""
# every check, until the test lets it go
EVERY = {"t/hold.sh": HOLD.format(only="")}
# member 1 turns the suite red; the stacks rebuilt without it are held
FIRST_RED = {"t/bad.sh": "test ! -f bad-1.txt\n",
             "t/hold.sh": HOLD.format(only="[ -f member-2.txt ] && [ ! -f bad-1.txt ] || exit 0\n")}


class EveryPassMovesTheLine(unittest.TestCase):
    def line(self, tests, count=4, red=None):
        """A line of `count` members, member `red` adding what turns the suite red."""
        line = Line(tests)
        self.addCleanup(line.close)
        for n in range(1, count + 1):
            line.member({f"member-{n}.txt": f"{n}\n", **({f"bad-{n}.txt": "x\n"} if n == red else {})})
        return line

    def held(self, line):
        """A pass of the line, held at its first held check."""
        lander = line.home.spawn("run", "--lander", line.line, env={"AK_HOST_READINGS": READINGS})
        deadline = time.monotonic() + 300
        while not (line.rig.path / ".git" / "reached").exists():
            self.assertIsNone(lander.poll(), line.home.log("spawn-1.err").read_text())
            self.assertLess(time.monotonic(), deadline, "no check was held")
            time.sleep(0.2)
        return lander

    def go(self, line):
        (line.rig.path / ".git" / "go").touch()

    def killed(self, line, lander):
        """Kill the held pass, as a reboot or the memory cap would, and let its check end."""
        os.killpg(lander.pid, signal.SIGKILL)
        lander.wait()
        self.go(line)
        deadline = time.monotonic() + 120
        while _strays(line.home.root, line.home.tmux_dir):
            self.assertLess(time.monotonic(), deadline, "the killed pass's check is still running")
            time.sleep(0.1)

    def landed(self, line):
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)

    def answers(self, line):
        return [[key for key in ("land", "fix") if key in line.verdict(n)]
                for n in range(1, len(line.members) + 1)]

    def test_a_member_changed_under_a_pass_costs_only_the_verdicts_stacked_on_it(self):
        # member 3 turns the suite red, and its record changes while every check is held
        line = self.line({"t/bad.sh": "test ! -f bad-3.txt\n", **EVERY}, red=3)
        lander = self.held(line)
        path = line.members[2] / "run.json"
        fresh = path.with_name("run.json.new")
        fresh.write_text(json.dumps({**json.loads(path.read_text()),
                                     "error": "its seat pushed a new head"}))
        fresh.replace(path)
        self.go(line)
        self.assertEqual(lander.wait(timeout=600), 0, line.home.log("spawn-1.err").read_text())
        self.assertEqual(self.answers(line), [["land"], ["land"], [], []], line.runs())

    def test_a_pass_killed_before_a_verdict_is_followed_by_one_of_half_the_line(self):
        line = self.line(EVERY)
        self.killed(line, self.held(line))
        self.assertEqual(self.answers(line), [[], [], [], []])
        self.landed(line)
        self.assertEqual(self.answers(line), [["land"], ["land"], [], []], line.runs())
        self.landed(line)       # it wrote verdicts: the next takes every member waiting
        self.assertEqual(self.answers(line), [["land"]] * 4, line.runs())

    def test_a_pass_killed_after_a_verdict_is_followed_by_one_of_the_whole_line(self):
        line = self.line(FIRST_RED, count=3, red=1)
        lander = self.held(line)
        self.assertEqual(self.answers(line), [["fix"], [], []], line.runs())
        self.killed(line, lander)
        self.landed(line)
        self.assertEqual(self.answers(line), [["fix"], ["land"], ["land"]], line.runs())


if __name__ == "__main__":
    unittest.main()
