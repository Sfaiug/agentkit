"""A test the landing line saw fail, then pass, on two trees gets one repair run of the target
naming it, owned by the member whose check saw it on the second tree; one tree starts none,
nor does a third that week.  It is seen whether the suite ran it again itself, naming it in
the file `AK_FLAKY` names, or the lander ran it again after the suite named it failed: alone
from a piece, or the whole suite where it is not split.
Black-box: the program `AK_BIN` names checks the line from outside through
tests/fixtures/akline.py; no harness is logged in, so the repair's launch is refused before
it starts, leaving its task and record.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, rules

# Fails on its first run on each tree.
FLAKY = ('mark="$(git rev-parse --git-common-dir)/ran-$(git rev-parse HEAD^{tree})"\n'
         '[ -f "$mark" ] || { : >"$mark"; exit 1; }\n')
AGAIN = 'for t in t/*; do sh $t || { sh $t && echo $t >>"$AK_FLAKY"; } || exit 1; done'
WHOLE = 'for t in t/*; do sh $t || { echo $t >>"$AK_FAILED"; exit 1; }; done'


class FlakyTestGetsARepair(unittest.TestCase):
    def test_a_test_flaky_on_two_trees_gets_one_repair(self):
        for how, name, files in (("the suite", "t/flaky.sh", {"AGENTS.md": rules(AGAIN)}),
                                 ("the lander", "flaky.sh", {}),
                                 ("the whole suite", "t/flaky.sh", {"AGENTS.md": rules(WHOLE)})):
            with self.subTest(how):
                line = Line({"t/flaky.sh": FLAKY, "t/fine.sh": "true\n", **files})
                self.addCleanup(line.close)
                line.home.write(".agentkit/state/session-seat.json",
                                {"orchestrator": "opus", "workers": ["opus"]})
                for n in (1, 2, 3):     # each pass checks the newest member's tree alone
                    line.member({f"member-{n}.txt": f"{n}\n"})
                    record = line.members[-1] / "run.json"
                    record.write_text(json.dumps({**json.loads(record.read_text()),
                                                  "launched_session": "seat"}))
                    done = line.land()
                    self.assertEqual(done.code, 0, done.out + done.err)
                    repairs = [path for path in line.members[0].parent.iterdir()
                               if path.is_dir() and path not in line.members]
                    self.assertEqual(len(repairs), n > 1, (n, done.out))
                repair = json.loads((repairs[0] / "run.json").read_text())
                self.assertEqual(repair["followup"]["run"], "fix-2")
                self.assertEqual(repair["repair"]["command"], name)
                task = (repairs[0] / "task.md").read_text()
                self.assertIn(f"# Make {name} deterministic", task)
                self.assertIn(f"`{name}` in {line.rig.path}", task)
                self.assertIn("2 times", task)


if __name__ == "__main__":
    unittest.main()
