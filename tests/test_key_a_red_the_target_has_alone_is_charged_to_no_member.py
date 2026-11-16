"""A red the target has alone is charged to no member behind green stacks: the tests a member
failed, red again on the target's tip with it alone, answer on the bare tip before its verdict,
and red there too they are the target's own, its repair started, and nobody's fix.  A test the
member added, which its runner names nowhere on the tip, leaves the red the member's own, and no
piece runs on the tip.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, the repair's worker scripted by fakeadapter.py and its GitHub by
fakegh.py.  In each case the first member's stack is checked green by a pass of its own, as a
line's top stack goes first, and the next pass checks the members joining behind it.  In the
first the suite holds a test that fails on any tree once a file outside every checkout exists,
the clock, which appears only once the first member's stack is green.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akline import READINGS, Line
from fixtures.fakegh import GitHub

TESTS = {"t/date.sh": 'test ! -f "$(git rev-parse --git-common-dir)/clock"\n'}
# akline's suite.sh, but a test listed alone that its tree lacks is named nowhere, the run failing
# as one that ran no test does, and a piece run on a tree holding no member, the target's bare
# tip, leaves `tip` in the project's Git storage
NAMES_NOTHING = """share=${AK_SHARD:-1/1}; k=${share%/*}; n=${share#*/}
if [ -n "${AK_ONLY:-}" ]; then tests=$(cat "$AK_ONLY")
else ls member-* >/dev/null 2>&1 || touch "$(git rev-parse --git-common-dir)/tip"; tests=; i=0
  for t in $(ls t); do [ $((i % n + 1)) = "$k" ] && tests="$tests $t"; i=$((i + 1)); done; fi
code=0
for t in $tests; do
  [ -f "t/$t" ] || { echo "no tests ran"; exit 5; }
  echo "$t" >>"${AK_RAN:-/dev/null}"
  sh "t/$t" || { echo "FAIL $t"; echo "$t" >>"${AK_FAILED:-/dev/null}"; code=1; }
done
exit $code
"""


def record(run):
    return json.loads((run / "run.json").read_text())


class ARedTheTargetHasAloneIsChargedToNoMember(unittest.TestCase):
    def land(self, line):
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out + done.err

    def test_a_test_the_clock_turned_red_is_the_targets_to_repair(self):
        line = Line(TESTS)
        self.addCleanup(line.close)
        home = line.home
        home.env.update(AK_HOST_READINGS=READINGS)
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(home, claude="blocked", codex="pass")
        home.write(".agentkit/state/session-seat.json", {"orchestrator": "opus", "workers": ["opus"]})

        def join(n):
            line.member({f"member-{n}.txt": f"{n}\n"})
            path = line.members[-1] / "run.json"
            path.write_text(json.dumps({**record(line.members[-1]), "launched_session": "seat"}))

        join(1)
        self.land(line)
        self.assertIn("land", line.verdict(1))
        (line.rig.path / ".git" / "clock").touch()
        join(2)
        join(3)
        said = self.land(line)
        self.assertEqual([n for n in (1, 2, 3) if "fix" in line.verdict(n)], [], said)
        repair, = (path for path in line.members[0].parent.iterdir()
                   if path.is_dir() and path not in line.members)
        self.assertEqual(record(repair)["repair_tip"], line.base, said)

    def test_a_test_its_member_added_is_its_own_and_runs_no_piece_on_the_tip(self):
        line = Line({"suite.sh": NAMES_NOTHING, "t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        line.member({"member-1.txt": "1\n"})
        self.land(line)
        self.assertIn("land", line.verdict(1))
        line.member({"member-2.txt": "2\n", "t/new.sh": "false\n"})
        said = self.land(line)
        self.assertEqual(line.verdict(2)["fix"]["tests"], ["new.sh"], said)
        self.assertFalse((line.rig.path / ".git" / "tip").exists(), said)


if __name__ == "__main__":
    unittest.main()
