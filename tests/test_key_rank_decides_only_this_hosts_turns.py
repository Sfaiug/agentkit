"""Rank decides who takes this host's turns, never who may ask the suite helper.

The older of two landers ranks first for a turn here, where it waits to run again the piece the
helper failed, asking nothing there; the later, which found no room there on arrival, goes there
once it has room, while the first still waits.  Black-box: the program `AK_BIN` names checks two
projects' landing lines from outside through tests/fixtures/akline.py, the test holding this
host's one turn throughout (AK_HOST_READINGS fits no piece beside it).  The helper is a fake ssh
whose probe answers what the test writes, and fails every piece while the test says so.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akline import Line

READINGS = {"AK_HOST_READINGS": json.dumps({"cpus": 4, "load": 0, "free_mb": 400})}
TESTS = {"t/a.sh": "true\n", "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"}
ONE, NONE, TWO = ("cpus 2\nload 0\nroom_mb 65536", "cpus 4\nload 4\nroom_mb 0",
                  "cpus 4\nload 0\nroom_mb 65536")    # the helper's room, in VMs
# The words after the alias are one `bash -c <mac.sh> mac.sh <verb> ...` line; a call is logged
# once its answer is decided.
SSH = f"""#!{sys.executable}
import os, shlex, sys
words = shlex.split(sys.argv[-1])
verb = words[words.index("mac.sh") + 1]
failed = verb == "run" and os.path.exists({{fail!r}})
if verb == "probe":
    print(open({{room!r}}).read())
elif verb == "prepare":
    sys.stdin.buffer.read()
with open({{calls!r}}, "a") as calls:
    calls.write(verb + "\\n")
sys.exit(1 if failed else 0)
"""


class RankDecidesOnlyThisHostsTurns(unittest.TestCase):
    def test_a_later_lander_goes_to_the_helper_while_an_older_one_waits_here(self):
        older = Line(TESTS)
        self.addCleanup(older.close)
        home = older.home
        later = Line(TESTS, home, "widgets")
        akconfig.write(home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        calls, room, fail = (home.root / name for name in ("calls", "room", "fail"))
        home.fake("ssh", SSH.format(calls=str(calls), room=str(room), fail=str(fail)))
        older.member({"api.txt": "x\n"})
        later.member({"api.txt": "x\n"})
        room.write_text(ONE)
        fail.touch()

        def sent(verb):
            return (calls.read_text().split() if calls.exists() else []).count(verb)

        def until(done, what):
            deadline = time.monotonic() + 300
            while not done():
                self.assertIsNone(first.poll(), home.log("spawn-1.err").read_text())
                self.assertLess(time.monotonic(), deadline, what)
                time.sleep(0.2)

        with (home.path / ".agentkit" / "runs" / ".heavy-0.lock").open("a") as turn:
            fcntl.flock(turn, fcntl.LOCK_EX)
            first = home.spawn("run", "--lander", older.line, env=READINGS)
            until(lambda: sent("run"), "the older lander's piece never went to the helper")
            room.write_text(NONE)
            fail.unlink()
            asked = sent("probe")
            second = home.spawn("run", "--lander", later.line, env=READINGS)
            until(lambda: sent("probe") >= asked + 2 or second.poll() is not None,
                  "the later lander never asked the helper while it waited")
            room.write_text(TWO)
            until(lambda: second.poll() is not None, "the later lander never went to the helper")
            self.assertEqual(second.returncode, 0, home.log("spawn-2.err").read_text())
            self.assertIn("land", later.verdict(1))
            self.assertEqual(later.runs(), [])
            self.assertIsNone(first.poll(), home.log("spawn-1.err").read_text())
            self.assertEqual(older.runs(), [])
        self.assertEqual(first.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertIn("land", older.verdict(1))
        self.assertTrue(older.runs())    # the piece the helper failed, here


if __name__ == "__main__":
    unittest.main()
