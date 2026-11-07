"""The tests a piece red on the suite helper named run here at once, one piece at a time, taking no
turn on this host, and one of them failing again settles the suite.  What then runs whole here, a
piece that named none or one whose named tests passed alone or ran out of memory, waits for a turn.
Named tests that said busy (exit 75) never ran: they go again alone after a poll, still taking none.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py on the suite helper acme-mac, a fake `ssh` failing the pieces a test names,
naming their tests.  The test holds this host's one heavy-suite turn (AK_HOST_READINGS fits no
piece beside it) from before the lander starts until it says it waits for one, so whatever ran
before took none.  Each go here marks its start and end in the project's Git storage, so no two
overlap unseen.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akline import Line, RUNNER

READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 4, "load": 0, "free_mb": 400})}
# acme-mac fits two pieces, each piece `named` holds failing there, naming those tests.
SSH = """import shlex, sys
words = shlex.split(sys.argv[-1])
verb, *args = words[words.index('mac.sh') + 1:]
if verb == 'probe':
    print('cpus 2\\nload 0\\nroom_mb 65536')
elif verb == 'prepare':
    sys.stdin.buffer.read()
elif verb == 'run':
    sys.exit(args[6] in named)
elif verb == 'failed' and args[2] == 'failed':
    print(*named.get('/'.join(args[1].rsplit('-', 2)[1:]), []), sep='\\n')
"""
# Each go here marks its start and end around the line's runner, which logs the tests it runs
# alone as its words; `{then}` may change its `code`.
GOES = """storage=$(git rev-parse --git-common-dir)
echo "start $(date +%s)" >>"$storage/marks"
sh run.sh $(cat "${AK_ONLY:-/dev/null}"); code=$?
{then}echo "end $(date +%s)" >>"$storage/marks"
exit $code
"""
BUSY = 'if mkdir "$storage/busy" 2>/dev/null; then code=75; fi\n'    # the first go says busy
RED = "test ! -f api.txt\n"     # fails on the member's tree, passes on the target's tip
UNIT = "acme.slice/lander.service"
# On its first go the test ends its runner by SIGKILL as its cgroup's `oom_kill` rises.
KILLED = f"""storage=$(git rev-parse --git-common-dir)
if mkdir "$storage/killed" 2>/dev/null; then
  events="$storage/cgroups/{UNIT}/memory.events"; n=$(sed -n "s/^oom_kill //p" "$events")
  printf "oom %s\\noom_kill %s\\n" $((n + 1)) $((n + 1)) >"$events"
  kill -9 $PPID
fi
"""


class RedTestsRerunAtOnce(unittest.TestCase):
    def land(self, named, tests, then=""):
        """The line's one member checked once, the helper failing the pieces `named` holds, each
        naming those of `tests`: the line, the suite's runs when the lander said it waits for the
        turn the test holds (None where it never did), and each go's start and end, in seconds."""
        line = Line({**tests, "suite.sh": GOES.replace("{then}", then), "run.sh": RUNNER,
                     "tools/helper/Containerfile": "FROM acme/base\n"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        akconfig.write(home, ["opus"], settings={"suite_helper": "acme-mac"})
        home.fake("ssh", f"#!{sys.executable}\nnamed = {named!r}\n{SSH}")
        # heavy suite turns, and the test's cgroup, kept where a boxed check may write
        unit = storage / "cgroups" / UNIT
        unit.mkdir(parents=True)
        (unit / "memory.events").write_text("oom 0\noom_kill 0\n")
        (home.root / "cgroup").write_text(f"0::/{UNIT}\n")
        home.env.update(AK_MAX_RUNS="", AK_CGROUP_ROOT=str(storage / "cgroups"),
                        AK_CGROUP_FILE=str(home.root / "cgroup"))
        line.member({"api.txt": "x\n"})
        with (home.path / ".agentkit" / "runs" / ".heavy-0.lock").open("a") as turn:
            fcntl.flock(turn, fcntl.LOCK_EX)
            lander = home.spawn("run", "--lander", line.line, env=READINGS)
            deadline = time.monotonic() + 300
            while lander.poll() is None and (
                    "heavy suite turn" not in home.log("spawn-1.out").read_text()):
                self.assertLess(time.monotonic(), deadline, "the lander neither ended nor waited")
                time.sleep(0.2)
            waiting = None if lander.poll() is not None else line.runs()
        self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        marks = [mark.split() for mark in (storage / "marks").read_text().splitlines()]
        self.assertEqual([word for word, _ in marks], ["start", "end"] * (len(marks) // 2),
                         "two goes here overlapped")
        return line, waiting, [int(second) for _, second in marks]

    def whole_on_a_turn(self, alone, test, then=""):
        """Piece 1/2 red on the helper naming its test `test`, which goes `alone` times here before
        the turn; the piece then runs whole and its member lands.  Each go's marks."""
        line, waiting, marks = self.land({"1/2": ["a.sh"]}, {"t/a.sh": test, "t/b.sh": "true\n"},
                                         then)
        self.assertEqual(waiting, [("alone", "a.sh")] * alone)
        self.assertEqual(line.runs()[:alone + 1], [*waiting, ("piece", "1/2", "")])
        self.assertIn("land", line.verdict(1))
        return marks

    def test_named_tests_take_no_turn_and_go_one_piece_at_a_time(self):
        line, waiting, _ = self.land({"1/2": ["a.sh"], "2/2": ["b.sh"]},
                                     {"t/a.sh": RED, "t/b.sh": RED})
        self.assertIsNone(waiting, line.runs())
        # a.sh confirming the stack red, then the target's tip passing it: b.sh never went alone
        self.assertEqual(line.runs(), [("alone", "a.sh")] * 2)
        red = line.verdict(1)["fix"]
        self.assertEqual((red["piece"], red["tests"]), ("1/2", ["a.sh"]))

    def test_named_tests_go_before_a_piece_that_named_none_waits_for_a_turn(self):
        line, waiting, _ = self.land({"1/2": [], "2/2": ["b.sh"]},
                                     {"t/a.sh": "true\n", "t/b.sh": RED})
        self.assertEqual(waiting, [("alone", "b.sh")])
        self.assertEqual(line.runs()[:2], [("alone", "b.sh"), ("piece", "1/2", "")])
        red = line.verdict(1)["fix"]
        self.assertEqual((red["piece"], red["tests"]), ("2/2", ["b.sh"]))

    def test_a_piece_whose_named_tests_pass_alone_waits_for_a_turn_to_run_whole(self):
        self.whole_on_a_turn(1, "true\n")

    def test_a_piece_whose_named_tests_said_busy_first_waits_for_a_turn_to_run_whole(self):
        busy_ended, again = self.whole_on_a_turn(2, "true\n", BUSY)[1:3]
        self.assertGreaterEqual(again - busy_ended, 15, "no poll (15 s) after the busy go")

    def test_a_piece_whose_named_tests_ran_out_of_memory_waits_for_a_turn_to_run_whole(self):
        self.whole_on_a_turn(1, KILLED)


if __name__ == "__main__":
    unittest.main()
