"""Tests of one file the landing line saw fail, then pass, on two trees get one repair run of
the target between them: its command is the file, its text names each of them, and a third
tree that week starts none.  A test's file is its name up to its first `::` (a pytest node)
or `#` (a smoke block); tests of two files get one repair each.
Black-box: the program `AK_BIN` names checks the line from outside through
tests/fixtures/akline.py; no harness is logged in, so each repair's launch is refused before
it starts, leaving its task and record.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line, rules

# Fails on the first run of each test it is given on each tree.
FLAKY = ('mark="$(git rev-parse --git-common-dir)/ran-$(git rev-parse HEAD^{tree})-'
         '$(echo "$1" | tr / -)"\n'
         '[ -f "$mark" ] || { : >"$mark"; exit 1; }\n')
# Runs each test `names` lists with its file, again once it fails, naming it in `AK_FLAKY`
# when it then passes.
SUITE = ('for t in $(cat names); do f=${t%%::*}; f=${f%%#*}\n'
         '  sh "$f" "$t" || { sh "$f" "$t" && echo "$t" >>"$AK_FLAKY"; } || exit 1\n'
         'done\n')


class FlakyFileGetsOneRepair(unittest.TestCase):
    def repairs(self, names):
        """How many repair runs the line holds after each of three passes, each checking the
        newest member's tree alone with the suite running `names`, and each repair's task by
        its command."""
        files = {test.split("::")[0].split("#")[0]: FLAKY for test in names}
        line = Line({"AGENTS.md": rules("sh suite-names.sh"), "suite-names.sh": SUITE,
                     "names": " ".join(names) + "\n", **files})
        self.addCleanup(line.close)
        line.home.write(".agentkit/state/session-seat.json",
                        {"orchestrator": "opus", "workers": ["opus"]})
        counts = []
        for n in (1, 2, 3):
            line.member({f"member-{n}.txt": f"{n}\n"})
            record = line.members[-1] / "run.json"
            record.write_text(json.dumps({**json.loads(record.read_text()),
                                          "launched_session": "seat"}))
            done = line.land()
            self.assertEqual(done.code, 0, done.out + done.err)
            repairs = [path for path in line.members[0].parent.iterdir()
                       if path.is_dir() and path not in line.members]
            counts.append(len(repairs))
        return counts, {json.loads((path / "run.json").read_text())["repair"]["command"]:
                        (path / "task.md").read_text() for path in repairs}

    def test_tests_of_one_file_get_one_repair_naming_each(self):
        for file, sep in (("t/flaky.sh", "::"), ("t/smoke.sh", "#")):
            with self.subTest(file):
                names = [f"{file}{sep}a", f"{file}{sep}b"]
                counts, tasks = self.repairs(names)
                self.assertEqual(counts, [0, 1, 1])     # the third tree's sightings are its
                self.assertEqual(list(tasks), [file])
                self.assertIn(f"# Make {file} deterministic", tasks[file])
                for name in names:
                    self.assertIn(f"`{name}`", tasks[file])

    def test_tests_of_two_files_get_one_repair_each(self):
        counts, tasks = self.repairs(["t/one.sh::a", "t/two.sh::a"])
        self.assertEqual(counts, [0, 2, 2])
        self.assertEqual(sorted(tasks), ["t/one.sh", "t/two.sh"])
        for file in tasks:
            self.assertIn(f"`{file}::a`", tasks[file])


if __name__ == "__main__":
    unittest.main()
