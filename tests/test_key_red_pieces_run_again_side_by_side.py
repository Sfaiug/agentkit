"""A suite's red pieces that go again whole do so at once, each on a turn of its own here, and one
that has ended gives its turn back while another still runs; a piece killed for memory goes again
alone, after every other piece has ended.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py on a host that fits three pieces, or two (AK_HOST_READINGS), so its suite
runs in six, or four.  A held test fails its piece's first go, passes alone, and holds its piece's
second go until the test releases it.  A killed test's first go dies by SIGKILL as its cgroup's
`oom_kill` rises (`AK_CGROUP_ROOT`, `AK_CGROUP_FILE`).  Each go marks its start and end, in the
order they happen, in the project's Git storage, where a boxed check may write.  The test takes a
turn as another suite would: a non-blocking flock on one of the host's slot files.
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, RUNNER

THREE = json.dumps({"cpus": 4, "load": 0, "free_mb": 1300})
TWO = json.dumps({"cpus": 4, "load": 0, "free_mb": 900})
UNIT = "acme.slice/lander.service"
# Each go marks its start and end around the line's runner: a piece by its share, named tests run
# alone as `alone`.
GOES = """storage=$(git rev-parse --git-common-dir)
go=$AK_SHARD; [ -z "${AK_ONLY:-}" ] || go=alone
echo "start $go" >>"$storage/marks"
sh run.sh; code=$?
echo "end $go" >>"$storage/marks"
exit $code
"""
HELD = """storage=$(git rev-parse --git-common-dir)
[ -z "${AK_ONLY:-}" ] || exit 0
mkdir "$storage/failed-${0##*/}" 2>/dev/null && exit 1
until [ -e "$storage/release-${0##*/}" ]; do sleep 0.1; done
"""
KILLED = f"""storage=$(git rev-parse --git-common-dir)
if mkdir "$storage/killed" 2>/dev/null; then
  events="$storage/cgroups/{UNIT}/memory.events"; n=$(sed -n "s/^oom_kill //p" "$events")
  printf "oom %s\\noom_kill %s\\n" $((n + 1)) $((n + 1)) >"$events"
  kill -9 $PPID
fi
"""


class RedPiecesRunAgainSideBySide(unittest.TestCase):
    def member(self, tests):
        """The line's one member, its suite `suite.sh` around the line's runner, on heavy suite
        turns."""
        line = Line({"suite.sh": GOES, "run.sh": RUNNER, **tests})
        self.addCleanup(line.close)
        self.line, self.home, self.storage = line, line.home, line.rig.path / ".git"
        self.home.env.update(AK_MAX_RUNS="")
        line.member({"api.txt": "x\n"})

    def land(self, readings):
        """A lander left running on a host `readings` describe."""
        self.lander = self.home.spawn("run", "--lander", self.line.line,
                                      env={"AK_HOST_READINGS": readings})

    def goes(self):
        marks = self.storage / "marks"
        return marks.read_text().splitlines() if marks.exists() else []

    def again(self, *shares):
        """Whether each of `shares` has started its second go."""
        return all(self.goes().count(f"start {share}") > 1 for share in shares)

    def release(self, *tests):
        for test in tests:
            (self.storage / f"release-{test}").touch()

    def take(self):
        """One of the host's heavy-suite turns, held until the test ends, or None while every
        turn is held."""
        for path in sorted((self.home.path / ".agentkit" / "runs").glob(".heavy-*.lock")):
            slot = path.open("a")
            try:
                fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                slot.close()
                continue
            self.addCleanup(slot.close)
            return slot
        return None

    def until(self, check, what):
        deadline = time.monotonic() + 300
        while not check():
            self.assertIsNone(self.lander.poll(), self.home.log("spawn-1.err").read_text())
            self.assertLess(time.monotonic(), deadline, f"never {what}: {self.goes()}")
            time.sleep(0.2)

    def landed(self):
        self.assertEqual(self.lander.wait(timeout=300), 0, self.home.log("spawn-1.err").read_text())
        self.assertIn("land", self.line.verdict(1))

    def test_red_pieces_go_again_whole_at_once_and_one_killed_for_memory_after_them(self):
        # six pieces: 1/6 killed for memory, 2/6 to 4/6 held
        self.member({"t/a.sh": KILLED, "t/b.sh": HELD, "t/c.sh": HELD, "t/d.sh": HELD,
                   "t/e.sh": "true\n", "t/f.sh": "true\n"})
        # the test's cgroup, kept where a boxed check may write
        unit = self.storage / "cgroups" / UNIT
        unit.mkdir(parents=True)
        (unit / "memory.events").write_text("oom 0\noom_kill 0\n")
        (self.home.root / "cgroup").write_text(f"0::/{UNIT}\n")
        self.home.env.update(AK_CGROUP_ROOT=str(self.storage / "cgroups"),
                             AK_CGROUP_FILE=str(self.home.root / "cgroup"))
        self.land(THREE)
        self.until(lambda: self.again("2/6", "3/6", "4/6"), "three second goes side by side")
        self.release("b.sh", "c.sh", "d.sh")
        self.landed()
        # its second go the last, nothing starting or ending after it starts
        ended = self.goes()
        self.assertEqual((ended.count("start 1/6"), ended[-2:]), (2, ["start 1/6", "end 1/6"]),
                         ended)

    def test_a_second_go_that_has_ended_gives_its_turn_back_while_another_runs(self):
        # four pieces: 1/4 and 2/4 held, their second goes on both of the host's turns
        self.member({"t/a.sh": HELD, "t/b.sh": HELD, "t/c.sh": "true\n", "t/d.sh": "true\n"})
        self.land(TWO)
        self.until(lambda: self.again("1/4", "2/4"), "two second goes side by side")
        self.assertIsNone(self.take(), "a turn free while both second goes run")
        self.release("a.sh")
        self.until(self.take, "the turn of 1/4's ended second go given back while 2/4 runs")
        self.assertIsNone(self.take(), "the suite kept no turn")
        self.release("b.sh")
        self.landed()


if __name__ == "__main__":
    unittest.main()
