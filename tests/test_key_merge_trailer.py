"""A merge names the tree its repository's suite passed on, and only when a suite is declared.

A repository declares its whole suite once, as `tests:` in its AGENTS.md front matter, and ak
runs it once, at landing, on the commit it merges, never in a round.  The merge commit then
ends with `Suite-Passed-Tree: <tree>` after the body GitHub would have written, so whatever
reads the target can tell the tree it holds is the one that suite passed; without a declared
suite there is nothing to certify and GitHub's own body stands.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, against the bare origin of
gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Each run of the suite leaves a line where the test can count it: the clone's own .git, which
# every checkout of the project shares.
SUITE = 'echo suite-ran >> "$(git rev-parse --git-common-dir)/suite.log"; test -f retry.txt'
DEFAULT_BODY = "* add retry.txt"    # what fakegh's GitHub writes for a squash of the work


def merged_run(test, files):
    """A task merged from a project holding `files`: (home, rig, ak's answer, run.json)."""
    home = Home()
    test.addClassCleanup(home.close)
    rig = Rig(home, "widgets", files=files)
    GitHub(home).grant(rig.slug, "WRITE")
    akconfig.write(home, ["opus", "astra"])
    fakeadapter.install(home, claude="work", codex="pass")
    done = home.ak("run", str(taskfile.write(home, rig.path, "Add retry file")), timeout=300)
    state = json.loads((taskfile.only_run(home) / "run.json").read_text())
    return home, rig, done, state


class SuitePasses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.rig, cls.done, cls.state = merged_run(
            cls, {"AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n"})

    def test_the_declared_suite_runs_once_at_landing_and_the_run_records_it(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertTrue(self.state["merged"], self.state)
        self.assertEqual((self.rig.path / ".git/suite.log").read_text().splitlines(),
                         ["suite-ran"])
        checked = self.state["final_check"]
        self.assertEqual({key: checked.get(key) for key in ("outcome", "where", "suite")},
                         {"outcome": "passed", "where": "landing", "suite": SUITE})
        self.assertEqual(checked["tested"], checked["tree_sha"])

    def test_the_merge_keeps_github_s_body_and_names_the_tree_the_suite_passed(self):
        tree = self.rig.origin("rev-parse", "main^{tree}")
        self.assertEqual(tree, self.state["final_check"]["tree_sha"])
        self.assertEqual(self.rig.origin("log", "-1", "--format=%b", "main"),
                         f"{DEFAULT_BODY}\n\nSuite-Passed-Tree: {tree}")


class NoSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.rig, cls.done, cls.state = merged_run(cls, {})

    def test_without_a_declared_suite_the_merge_carries_github_s_body_alone(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertTrue(self.state["merged"], self.state)
        self.assertEqual(self.state["final_check"]["outcome"], "passed")
        self.assertIsNone(self.state["final_check"]["suite"])
        self.assertEqual(self.rig.origin("log", "-1", "--format=%b", "main"), DEFAULT_BODY)


if __name__ == "__main__":
    unittest.main()
