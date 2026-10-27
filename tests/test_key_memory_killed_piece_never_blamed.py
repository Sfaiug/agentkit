"""A test piece the kernel killed for memory is run again, never blamed on a change.

A piece that died by SIGKILL while its cgroup's `oom_kill` count rose meanwhile ran out of
memory: it runs again after its siblings, and still out of memory it is nobody's red -- the
pass ends with no verdict, no member sent to its fixer and the target's tip never probed.  A
piece killed the same way with no count rising is a red like any other.  Black-box: the program
`AK_BIN` names checks a landing line from outside through tests/fixtures/akline.py, its cgroup
the test's (`AK_CGROUP_ROOT`, `AK_CGROUP_FILE`), kept in the project's Git storage, where a
boxed check may write.  The member's tree kills its piece every go; the tip's passes it, as a
piece run alone on a quieter unit does.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

UNIT = "acme.slice/lander.service"
# `$PPID` is the suite's runner: the piece dies by SIGKILL; on the tip it passes, logged
BIG = """storage=$(git rev-parse --git-common-dir)
if [ -f api.txt ]; then
  {raise}
  kill -9 $PPID; exit 1
fi
echo tip >>"$storage/tip.log"
"""
RAISE = (f'events="$storage/cgroups/{UNIT}/memory.events"; n=$(sed -n "s/^oom_kill //p" '
         '"$events"); printf "oom %s\\noom_kill %s\\n" $((n + 1)) $((n + 1)) >"$events"')


class MemoryKilledPieceNeverBlamed(unittest.TestCase):
    def land(self, raise_count):
        """What the lander left its one member waiting on, and whether the tip ran the test."""
        line = Line({"t/ok.sh": "true\n",
                     "t/big.sh": BIG.replace("{raise}", RAISE if raise_count else ":")})
        self.addCleanup(line.close)
        storage = line.rig.path / ".git"
        unit = storage / "cgroups" / UNIT
        unit.mkdir(parents=True)
        (unit / "memory.events").write_text("oom 0\noom_kill 0\n")
        (line.home.root / "cgroup").write_text(f"0::/{UNIT}\n")
        line.home.env.update(AK_CGROUP_ROOT=str(storage / "cgroups"),
                             AK_CGROUP_FILE=str(line.home.root / "cgroup"))
        line.member({"api.txt": "x\n"})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return line.verdict(1), (storage / "tip.log").exists()

    def test_a_piece_killed_for_memory_blames_nobody(self):
        verdict, probed = self.land(raise_count=True)
        self.assertNotIn("fix", verdict, verdict)
        self.assertNotIn("land", verdict, verdict)
        self.assertFalse(probed, "the target's tip was probed")

    def test_a_piece_killed_with_no_memory_kill_is_the_members_red(self):
        verdict, _ = self.land(raise_count=False)
        self.assertIn("fix", verdict, verdict)


if __name__ == "__main__":
    unittest.main()
