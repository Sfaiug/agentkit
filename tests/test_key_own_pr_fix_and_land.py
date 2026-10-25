"""A seat's own PR under `ak run --review-pr` is fixed between reviews and lands only when green.

The orchestrator's own pull request goes the one path every change goes: a FAIL is handed to a
fresh fixer turn on the model that wrote it, never typed into the seat, and what it commits is
pushed to the PR branch for the next round to review; a PASS joins the landing line, which runs
the repository's suite on it and merges it only once the checks the target requires are green.
A red required check leaves the PR open and the run failed, and a rebase onto main that
conflicts goes to the writer's model to resolve, as a finding does.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, from the seat of akseat.py, against
the bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from
fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

RULES = "---\ntests: test -f contrib.txt\n---\n# widgets\n"
FIND = {"final": "Found one.", "hand_in": [
    ["finding", "contrib.txt:1", "contrib.txt is unfinished", "nothing reads it", "--run",
     "grep -q fixed contrib.txt"], ["done"]]}
FOUND = "- contrib.txt:1 - contrib.txt is unfinished - nothing reads it"
FIX = {"write": {"contrib.txt": "fixed\n"}, "commit": "finish contrib.txt", "final": "Fixed.",
       "hand_in": [["done"]]}
RESOLVE = {"sh": "printf 'main\\nc\\n' > contrib.txt && git add contrib.txt && "
                 "GIT_EDITOR=true git rebase --continue", "final": "Resolved.", "hand_in": [["done"]]}


def reviewed(case, claude, codex, check=None, main=None):
    """The acme seat, whose orchestrator is opus, reviews its own PR adding contrib.txt, with
    astra reviewing; `check` is the conclusion of the `ci` check main requires, if any, and
    `main` files main gains once the PR is open."""
    case.home = Home()
    case.addClassCleanup(case.home.close)
    case.rig = Rig(case.home, "widgets", files={"AGENTS.md": RULES})
    case.gh = GitHub(case.home)
    akconfig.write(case.home, ["opus", "astra"])
    case.fakes = fakeadapter.install(case.home, claude=claude, codex=codex)
    Seat(case.home, "acme", cwd=case.rig.path, alive=False,
         record={"workers": ["opus", "astra"]}, planned=True)
    case.head = case.rig.branch("contrib", {"contrib.txt": "c\n"})
    case.url = case.gh.open_pr(case.rig, "contrib", title="Add contrib")
    if main:
        case.rig.commit(main, "main moves")
    if check:
        case.gh.require(case.rig.slug, "main", "ci")
        case.gh.check(case.head, "ci", conclusion=check)
    case.done = case.home.ak("run", "--review-pr", case.url, env={"AGENTKIT_SESSION": "acme"},
                             cwd=case.rig.path, timeout=300)
    case.run_dir = taskfile.only_run(case.home)
    case.state = json.loads((case.run_dir / "run.json").read_text())


class LandedMixin:
    def test_the_run_ends_pass_merged_through_the_line_with_the_suite_passed(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "merged",
                                                               "own_pr")},
                         {"state": "pass", "verdict": "PASS", "merged": True, "own_pr": True})
        merged = self.gh.pr(1)["merge"]
        self.assertEqual({key: self.state["final_check"].get(key) for key in (
            "outcome", "where", "sha", "suite")}, {"outcome": "passed", "where": "landing",
                                                   "sha": merged["head"],
                                                   "suite": "test -f contrib.txt"})
        self.assertEqual((merged["method"], merged["match"]), ("squash", merged["head"]))
        self.assertEqual(self.rig.head(), merged["commit"])


class FixedBetweenReviews(LandedMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, FIX, [FIND, "pass"])

    def test_the_writer_s_model_gets_one_fixer_turn_handed_the_finding(self):
        turns = self.fakes["claude"].runs()
        self.assertEqual([turn["role"] for turn in turns], ["fixer"])
        self.assertIn(FOUND, Path(turns[0]["argv"][3]).read_text().splitlines())
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "PASS"])

    def test_its_commit_is_pushed_to_the_pr_branch_and_reviewed_next(self):
        fix = self.gh.pr(1)["merge"]["head"]
        self.assertNotEqual(fix, self.head)
        parent = self.home.run("git", "-C", str(self.rig.bare), "rev-parse", f"{fix}^")
        self.assertEqual(parent.out.strip(), self.head)
        self.assertEqual([review["commit"]["oid"] for review in self.gh.pr(1)["reviews"]],
                         [self.head, fix])
        shown = self.home.run("git", "-C", str(self.rig.bare), "show", "main:contrib.txt")
        self.assertEqual(shown.out, "fixed\n")


class GreenCheck(LandedMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, "pass", "pass", check="success")

    def test_the_head_it_merged_is_the_one_reviewed_and_green(self):
        self.assertEqual(self.gh.pr(1)["merge"]["head"], self.head)
        self.assertEqual(self.fakes["claude"].runs(), [])


class ConflictedRebase(LandedMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, RESOLVE, "pass", main={"contrib.txt": "main\n"})

    def test_the_writer_s_model_resolves_the_conflict_keeping_both_sides(self):
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], ["fixer"])
        shown = self.home.run("git", "-C", str(self.rig.bare), "show", "main:contrib.txt")
        self.assertEqual(shown.out, "main\nc\n")


class FlawedResolution(LandedMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flawed = {**RESOLVE, "sh": RESOLVE["sh"].replace("main\\nc\\n", "main\\nc\\nbroken\\n")}
        found = {"final": "Found one.", "hand_in": [
            ["finding", "contrib.txt:3", "the resolution adds a broken line", "neither side has it",
             "--run", "! grep -q broken contrib.txt"], ["done"]]}
        fix = {**FIX, "write": {"contrib.txt": "main\nc\n"}}
        reviewed(cls, [flawed, fix], ["pass", found, "pass"], main={"contrib.txt": "main\n"})

    def test_the_writer_s_fix_of_its_resolution_is_reviewed_and_lands(self):
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], ["fixer", "fixer"])
        shown = self.home.run("git", "-C", str(self.rig.bare), "show", "main:contrib.txt")
        self.assertEqual(shown.out, "main\nc\n")


class RedCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, "pass", "pass", check="failure")

    def test_a_red_required_check_leaves_the_pr_open_and_the_run_failed(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["merged"]), ("fail", False))
        self.assertEqual({key: self.state["final_check"].get(key) for key in (
            "outcome", "where", "line")}, {"outcome": "failed", "where": "landing",
                                           "line": "required checks failed: ci"})
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["merge"]), ("OPEN", None))
        self.assertNotIn("contrib.txt", self.rig.files())

    def test_the_red_goes_to_the_writer_s_model_as_a_fixer(self):
        roles = [turn["role"] for turn in self.fakes["claude"].runs()]
        self.assertTrue(roles, "no fixer turn")
        self.assertEqual(set(roles), {"fixer"})


if __name__ == "__main__":
    unittest.main()
