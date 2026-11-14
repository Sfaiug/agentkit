"""Where no suite helper has a place, a red stack's narrowing runs its rounds on this host: the
stacks between probed at once, each the test that failed run alone, and only the step that
decides the blame runs by itself.

Black-box: `AK_BIN` checks a landing line from outside through tests/fixtures/akline.py, on a
host with no suite helper.  Of eight members the sixth makes one test fail.  Run alone, that test
marks its run in the project's Git storage and goes on only once a second run has marked its own.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

# A run nobody joins within half a minute takes its mark back, notes the stack it ran on and fails.
BAD = """if [ -n "${AK_ONLY:-}" ]; then
  marks="$(git rev-parse --git-common-dir)/marks"
  mkdir -p "$marks"
  mark=$(mktemp "$marks/XXXXXX")
  i=0
  until [ "$(ls "$marks" | wc -l)" -ge 2 ]; do
    if [ $i -ge 300 ]; then
      rm "$mark"
      echo $(ls member-*) >>"$marks.alone"
      exit 1
    fi
    sleep 0.1
    i=$((i + 1))
  done
fi
test -z "$(ls bad-* 2>/dev/null)"
"""


class ANarrowingRoundRunsHere(unittest.TestCase):
    def test_the_stacks_between_are_probed_together_here(self):
        line = Line({"t/bad.sh": BAD, "t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        for n in range(1, 9):
            line.member({f"member-{n}.txt": f"{n}\n", **({"bad-6.txt": "x\n"} if n == 6 else {})})
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        for n in range(1, 9):
            self.assertEqual([key for key in ("land", "fix") if key in line.verdict(n)],
                             ["fix"] if n == 6 else ["land"], (n, line.runs()))
        self.assertEqual(line.verdict(6)["fix"]["tests"], ["bad.sh"])
        # Nobody joined only the whole line's red piece run again alone: no probe runs there.
        alone = line.rig.path / ".git" / "marks.alone"
        whole = " ".join(f"member-{n}.txt" for n in range(1, 9))
        self.assertLessEqual(set(alone.read_text().splitlines() if alone.exists() else ()),
                             {whole})


if __name__ == "__main__":
    unittest.main()
