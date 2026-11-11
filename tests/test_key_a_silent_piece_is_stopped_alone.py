"""A piece of a suite that prints nothing for the silence limit is stopped alone.

Its siblings run to their ends and keep their results, and it goes once more, alone, after
them, with the whole limit again where its suite has no pace; silent on that go too, it fails
the check.  Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, its member's record carrying a silence limit of three seconds, its
suite in a fresh Home and so without a pace, cut in four pieces on three CPUs: `t/a.sh` to
`t/d.sh`, one a piece, the member's own, so a probe of the target's tip runs none of them.
Each go of a test marks its start and end in the project's Git storage, where a boxed check
may write.  The silent test holds a lock while silent, and a sibling prints until it is free:
that sibling ends only once the silent go was stopped.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line

SILENCE_MINUTES = 0.05
READINGS = json.dumps({"cpus": 3, "load": 0, "free_mb": 16000})    # four pieces
MARK = 's="$(git rev-parse --git-common-dir)"; mark() { echo "$1 $0" >>"$s/goes.log"; }\n'
TALKS = MARK + "mark start; echo talking; mark end\n"
WAITS = MARK + ('mark start\n'
                'until grep -qx "start t/b.sh" "$s/goes.log" && flock -n "$s/b.lock" true; do\n'
                '  echo waiting; sleep .2\n'
                'done\n'
                'mark end\n')
# Silent past the limit, holding the lock, on the go `{silent}` says, and talking otherwise.
SILENT = MARK + ('if {silent}; then exec 9>"$s/b.lock"; flock 9; mark start; sleep 60; fi\n'
                 'mark start; echo talking; mark end\n')
FIRST_GO = '! grep -qx "start t/b.sh" "$s/goes.log"'


class ASilentPieceIsStoppedAlone(unittest.TestCase):
    def land(self, silent):
        """What the lander left the member waiting on, with what the check printed, and each
        test's goes as marked, in order: the member adds the four tests, `t/b.sh` silent on
        the goes `silent` says."""
        line = Line({})
        self.addCleanup(line.close)
        line.member({"t/a.sh": TALKS, "t/b.sh": SILENT.replace("{silent}", silent),
                     "t/c.sh": WAITS, "t/d.sh": TALKS})
        record = line.members[0] / "run.json"
        record.write_text(json.dumps({**json.loads(record.read_text()),
                                      "silence_minutes": SILENCE_MINUTES}))
        done = line.home.ak("run", "--lander", line.line, timeout=600,
                            env={"AK_HOST_READINGS": READINGS})
        self.assertEqual(done.code, 0, done.out + done.err)
        verdict = line.verdict(1)
        said = Path(verdict["fix"]["log"]).read_text() if "fix" in verdict else ""
        goes = (line.rig.path / ".git" / "goes.log").read_text().splitlines()
        self.assertEqual({run[1] for run in line.runs() if run[0] == "piece"},
                         {"1/4", "2/4", "3/4", "4/4"})
        return verdict, said, goes

    def assertEachGo(self, goes, **each):
        """Each test's goes, its marks in order, are as `each` names them by test."""
        for name, marks in each.items():
            self.assertEqual([go.split()[0] for go in goes if go.endswith(f" t/{name}.sh")],
                             marks.split(), goes)

    def test_a_piece_silent_once_goes_again_after_its_siblings_and_the_member_lands(self):
        verdict, said, goes = self.land(FIRST_GO)
        self.assertIn("land", verdict, verdict)
        once = "start end"
        self.assertEachGo(goes, a=once, b="start start end", c=once, d=once)
        # the sibling waiting on the silent go ends once it was stopped, the second go after it
        silent = [index for index, go in enumerate(goes) if go == "start t/b.sh"]
        self.assertLess(silent[0], goes.index("end t/c.sh"), goes)
        self.assertEqual(goes[silent[1]:], ["start t/b.sh", "end t/b.sh"], goes)

    def test_a_piece_silent_on_both_goes_fails_the_check_and_its_siblings_run_to_their_ends(self):
        verdict, said, goes = self.land("true")
        self.assertIn("fix", verdict, verdict)
        self.assertIn("--- AK_SHARD=2/4 ---\n[killed at the limit]", said)
        self.assertIn(f"stopped after {SILENCE_MINUTES:g} min of silence", said)
        once = "start end"
        self.assertEachGo(goes, a=once, b="start start", c=once, d=once)


if __name__ == "__main__":
    unittest.main()
