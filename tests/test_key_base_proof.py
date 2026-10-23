"""A change is proven to fail on the old code where ak can, and the proof never fails a round.

The owner's rule: a behaviour change needs a check that fails on the old code, which ak proves
where it can and never fails a round for.  Once a round's checks pass, ak replays the task's own
checks on the base commit with only the branch's test files laid over, then with all of its
changes: a check that fails the first way and passes the second proves the change, and
run.json, result.md and the PR say so.  A check that passes on base proves nothing, which the
run says too, and the work still passes and is delivered.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, with
scripted harnesses from fakeadapter.py and, where the work is merged, the GitHub of fakegh.py.
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

PROVEN = "base proof: a check fails on the old code and passes with this change"
NONE_SHOWN = "base proof: none shown ("
TEST = "tests/test_retry.py"
# The test of the change: it fails until retry.txt exists.
FAILS_BEFORE = "import pathlib, sys\nsys.exit(0 if pathlib.Path('retry.txt').exists() else 1)\n"
# A test that shows nothing: the old code passes it too, but only once it is there to run.
PASSES_BEFORE = "import pathlib, sys\nsys.exit(0 if pathlib.Path('.keep').exists() else 1)\n"


def with_test(test):
    """An executor turn that writes retry.txt and a test, and commits both."""
    return {"write": {"retry.txt": "hello\n", TEST: test}, "commit": "add retry.txt and a test",
            "final": "## Summary\nwrote retry.txt and its test", "hand_in": [["done"]]}


def launch(case, *, files=None, executor="work", check="test -f retry.txt", merge=False):
    """Run the task once in a Home of the class's own; its run, record and result."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    case.rig = Rig(case.home, "widgets", files=files)
    case.base = case.rig.head()
    if merge:
        case.gh = GitHub(case.home)
        case.gh.grant(case.rig.slug, "WRITE")      # enough to push and merge without a fork
    akconfig.write(case.home, ["opus", "astra"])
    fakeadapter.install(case.home, claude=executor, codex="pass")
    task = taskfile.write(case.home, case.rig.path, "Add retry file", done_when=(check,))
    case.done = case.home.ak("run", str(task), *([] if merge else ["--no-merge"]), timeout=300)
    case.run_dir = taskfile.only_run(case.home)
    case.state = json.loads((case.run_dir / "run.json").read_text())
    case.result = (case.run_dir / "result.md").read_text().splitlines()


class Passes:
    def assertPassed(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["PASS"])

    def assertNoneShown(self, lines, prefix=""):
        self.assertNotEqual(self.state.get("base_proof"), "proven")
        self.assertNotIn(prefix + PROVEN, lines)
        self.assertEqual(len([line for line in lines
                              if line.startswith(prefix + NONE_SHOWN)]), 1, lines)


class CheckFailingOnBase(Passes, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launch(cls)

    def test_a_check_failing_on_base_and_passing_with_the_change_is_recorded_proven(self):
        self.assertPassed()
        self.assertEqual(self.state["base_proof"], "proven")
        self.assertIn(PROVEN, self.result)

    def test_each_replay_keeps_its_log_in_the_run(self):
        for name in ("base.log", "head.log"):
            with self.subTest(name):
                self.assertIn(self.base, (self.run_dir / name).read_text())


class CheckPassingOnBase(Passes, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launch(cls, files={"retry.txt": "old\n"})

    def test_a_check_already_passing_on_base_proves_nothing_and_the_round_still_passes(self):
        self.assertPassed()
        self.assertNoneShown(self.result)


class NewTestFailingOnBase(Passes, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launch(cls, executor=with_test(FAILS_BEFORE), check=f"python3 {TEST}", merge=True)

    def test_the_branch_s_new_test_failing_on_the_old_code_proves_the_change(self):
        self.assertPassed()
        self.assertEqual(self.state["base_proof"], "proven")
        self.assertIn(PROVEN, self.result)

    def test_the_merged_pr_says_the_change_is_proven(self):
        self.assertTrue(self.state["merged"])
        body = self.gh.pr(1)["body"]
        self.assertEqual(body, (self.run_dir / "pr-body.md").read_text())
        self.assertIn(f"- {PROVEN}", body.splitlines())


class NewTestPassingOnBase(Passes, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launch(cls, executor=with_test(PASSES_BEFORE), check=f"python3 {TEST}", merge=True)

    def test_the_branch_s_test_runs_on_the_old_code_so_one_passing_there_proves_nothing(self):
        # Run on base without the branch's test file, the check could not pass, and would
        # seem to prove the change.
        self.assertPassed()
        self.assertNoneShown(self.result)

    def test_the_unproven_change_is_still_merged_and_its_pr_says_none_was_shown(self):
        self.assertTrue(self.state["merged"])
        self.assertIn("retry.txt", self.rig.files())
        self.assertNoneShown(self.gh.pr(1)["body"].splitlines(), prefix="- ")


if __name__ == "__main__":
    unittest.main()
