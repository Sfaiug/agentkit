"""A change of looks alone brings the tests it edits.

A change of looks alone (tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py) is
one also where, beside an image, it edits tests the project's time record times whose path
says they are tests (a `tests/` directory here).  At its verdict of its own those run by name, with
the target's `tests:` line, on the tree it would land as, before its task's `# once` commands:
passing, it lands with no whole run, its merge ending with `Looks-Alone-Tree: <tree>`; red there,
it waits for the whole run as any member.  A test page with a suffix of looks runs as a test.
A change that adds a test waits, even a page a round already timed; so does one of a timed test
alone, one beside a timed file whose path names no test, and one beside a timed AGENTS.md.

Black-box, as that key and with its fixtures: the program `AK_BIN` names, on a busy host where a
whole suite waits for company, checks a landing line through tests/fixtures/akline.py, whose
suite here runs `tests/*`, or the paths `AK_ONLY` lists, logging each with the tree it ran on;
the run that delivers is scripted by fakeadapter.py and merged by fakegh.py's GitHub, and a parked
member, which no round ran, shows where the lander ran its test.  The time record is written as a
landing keeps it.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akline import Line
from fixtures.fakegh import GitHub
from test_key_a_change_of_looks_alone_lands_on_its_quick_checks import BUSY, IMAGE, RULES, record

RUNNER = """share=${AK_SHARD:-1/1}; k=${share%/*}; n=${share#*/}
git=$(git rev-parse --git-common-dir)
if [ -n "${AK_ONLY:-}" ]; then echo "alone $*" >>"$git/suite.log"; tests=$(cat "$AK_ONLY")
else echo "piece $share $*" >>"$git/suite.log"; tests=; i=0
  for t in tests/*; do [ $((i % n + 1)) = "$k" ] && tests="$tests $t"; i=$((i + 1)); done; fi
code=0
for t in $tests; do
  echo "$t $(git rev-parse 'HEAD^{tree}')" >>"$git/ran.log"
  echo "$t" >>"${AK_RAN:-/dev/null}"
  sh "$t" || { echo "$t" >>"${AK_FAILED:-/dev/null}"; code=1; }
done
exit $code
"""
TEST = "./tests/look_test.sh"    # as the record spells it
# a module whose doctests the suite times: it ships
# a round times a test before its change is on the target: tests/new_test.*
TIMES = {TEST: 1, "widget.py": 1, "tests/new_test.sh": 1, "tests/new_test.md": 1,
         "tests/page_test.md": 1, "tests/AGENTS.md": 1}
EDITED = {**IMAGE, "tests/look_test.sh": "true  # blink\n"}


class AChangeOfLooksAloneBringsItsTests(unittest.TestCase):
    def line(self, **files):
        line = Line({"AGENTS.md": RULES, "suite.sh": RUNNER, "tests/look_test.sh": "true\n",
                     "widget.py": "x\n", **files})
        self.addCleanup(line.close)
        line.home.env.pop("AK_MAX_RUNS")
        line.home.env["AK_HOST_READINGS"] = json.dumps(BUSY)
        line.measured(40 * 60)
        line.rig.git("config", "ak.repository", "0123456789ab")
        line.home.write(".agentkit/state/test-times-0123456789ab.json", TIMES)
        return line

    def join(self, line, files):
        """Park the line's next member, joined now, its branch adding `files`."""
        line.member(files)
        state = record(line.members[-1])
        state["waiting_on"]["joined"] = time.time()
        (line.members[-1] / "run.json").write_text(json.dumps(state))

    def land(self, line):
        done = line.home.ak("run", "--lander", line.line, timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)

    def checked(self, line):
        """How many whole runs of the suite, and each member's verdict: {"land"}, {"fix"}, or none
        yet, still waiting."""
        return line.whole(), [{"land", "fix"} & line.verdict(n).keys()
                              for n in range(1, len(line.members) + 1)]

    def ran(self, line):
        """Each test the suite ran, with the tree it ran on, oldest first."""
        try:
            text = (line.rig.path / ".git" / "ran.log").read_text()
        except FileNotFoundError:
            return []
        return [tuple(entry.split()) for entry in text.splitlines()]

    def test_an_image_and_the_test_it_edits_land_with_no_whole_run(self):
        line = self.line()
        home = line.home
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(home, claude={**fakeadapter.WORK, "write": EDITED,
                                          "commit": "draw"}, codex="pass")
        done = home.ak("run", str(taskfile.write(home, line.rig.path, "Draw the logo",
                                                 done_when=("test -f logo.png",))), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-draw-the-logo"))
        self.assertTrue(record(run_dir).get("merged"), record(run_dir))
        self.assertEqual(line.whole(), 0, line.runs())
        tree = line.rig.origin("rev-parse", "main^{tree}")
        self.assertIn((TEST, tree), self.ran(line))
        self.assertTrue(line.rig.origin("log", "-1", "--format=%B", "main").rstrip().endswith(
            f"\n\nLooks-Alone-Tree: {tree}"))

    def test_one_whose_edited_test_fails_on_the_tree_it_would_land_as_waits(self):
        line = self.line()
        self.join(line, {**IMAGE, "tests/look_test.sh": "[ ! -f news.md ]\n"})
        line.rig.commit({"news.md": "x\n"}, "news")
        self.land(line)
        self.assertEqual(self.checked(line), (0, [set()]), line.runs())
        self.assertEqual({test for test, _ in self.ran(line)}, {TEST})

    def test_a_test_page_runs_as_a_test(self):
        line = self.line(**{"tests/page_test.md": "true\n"})
        self.join(line, {**IMAGE, "tests/page_test.md": "false\n"})
        self.land(line)
        self.assertEqual(self.checked(line), (0, [set()]), line.runs())
        self.assertEqual({test for test, _ in self.ran(line)}, {"tests/page_test.md"})

    def waits(self, files, **target):
        """A member whose branch adds `files` to a target holding `target` too waits, while one
        behind it that brings its test lands.  `files` grow no prose, which outside the project's
        `content:` only shrinks, so only what decides looks keeps it waiting."""
        line = self.line(**target)
        self.join(line, files)
        self.join(line, EDITED)
        self.land(line)
        self.assertEqual(self.checked(line), (0, [set(), {"land"}]), line.runs())
        # no round ran here: the lander ran it, on the tree it gave the member to land
        self.assertEqual(self.ran(line), [(TEST, line.verdict(2)["land"])])

    def test_one_that_adds_a_test_waits(self):
        self.waits({**IMAGE, "tests/new_test.sh": "true\n"})

    def test_one_that_adds_a_test_page_a_round_timed_waits(self):
        self.waits({**IMAGE, "tests/new_test.md": ""})

    def test_one_that_edits_a_timed_test_alone_waits(self):
        self.waits({"tests/look_test.sh": "true  # blink\n"})

    def test_one_beside_a_timed_file_whose_path_names_no_test_waits(self):
        self.waits({**IMAGE, "widget.py": "y\n"})

    def test_one_beside_a_timed_agents_md_waits(self):
        self.waits({**IMAGE, "tests/AGENTS.md": "New rules.\n"},
                   **{"tests/AGENTS.md": "Old rules.\n"})


if __name__ == "__main__":
    unittest.main()
