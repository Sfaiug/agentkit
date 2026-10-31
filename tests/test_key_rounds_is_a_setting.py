"""The review rounds a change has are the host's setting: `rounds` at the top of config.toml.

Unset, the budget is three rounds.  Set, it is the budget everywhere a round count is judged: a
`--rounds` over it is refused before any run is made, a run asking for none gets that many, and
a run whose reviewer fails every round ends FAIL once they are spent.  `review_lines` and
`seat_lines` sit beside it.  A number under its floor or not a whole number, or `seat_lines`
over `review_lines`, refuses the launch, naming the file, the numbers and what they mean.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py, a config from akconfig.py, a task from taskfile.py and scripted harnesses
from fakeadapter.py; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

ROUNDS = ("rounds must be a whole number of at least 1, the review rounds a change has before "
          "it goes back to its orchestrator to split or re-scope")
REVIEW = "the most added lines a first review reads"
SEAT = "the added lines a seat's own change stays under"
OVER = ("--rounds 6 is over the budget: 5 rounds, then a run goes back to its orchestrator to "
        "split or re-scope")
# `false` fails on the change and on its base alike: a proof nothing the fixer does can pass.
FAILING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}


def project(cls, rounds, claude, codex):
    """A Home of the class's whose config.toml sets `rounds`, and its one --no-merge run."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets")
    akconfig.write(cls.home, ["opus", "astra"], settings={"rounds": rounds})
    cls.fakes = fakeadapter.install(cls.home, claude=claude, codex=codex)
    cls.task = taskfile.write(cls.home, cls.rig.path, "Add retry file")


def finish(cls):
    cls.done = cls.home.ak("run", str(cls.task), "--no-merge", timeout=300)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text().splitlines()


class FiveRounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project(cls, 5, "blocked", "pass")
        cls.refused = [cls.home.ak(*argv, timeout=60) for argv in (
            ("run", str(cls.task), "--rounds", "6"), ("run", str(cls.task), "--rounds", "6", "--bg"),
            ("run", "resume", "MISSING", "--rounds", "6"))]
        cls.made = taskfile.runs(cls.home)
        finish(cls)

    def test_a_rounds_over_the_setting_is_refused_before_any_run_is_made(self):
        for done in self.refused:
            with self.subTest(err=done.err):
                self.assertEqual(done.code, 2, done.out)
                self.assertEqual(done.err, f"ak run: {OVER}\n")
        self.assertEqual(self.made, [])

    def test_a_run_asking_for_no_rounds_gets_the_setting(self):
        self.assertEqual(self.state["rounds"], 5)
        self.assertIn("rounds: 0 of 5", self.result)


class TwoRounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # each fixer disputes it, as a fixer's done waits on every earlier finding's proof
        project(cls, 2, ["work", "dispute"], FAILING)
        finish(cls)

    def test_a_reviewer_failing_every_round_ends_the_run_fail_after_two(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"], self.state["rounds"]),
                         ("fail", "FAIL", 2))
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "FAIL"])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (2, 2))
        self.assertIn("rounds: 2 of 2", self.result)
        # two is all the host gives: no more rounds to ask for
        self.assertFalse([line for line in self.result if line.startswith("continue:")],
                         self.result)


class Refused(unittest.TestCase):
    def test_a_number_nobody_could_mean_refuses_the_launch_naming_floor_and_meaning(self):
        home = Home()
        self.addCleanup(home.close)
        task = taskfile.write(home, "none", done_when=("true",))
        config = home.path / ".agentkit" / "config.toml"
        for settings, why in (
                ({"rounds": 0}, f"{ROUNDS} (got 0)"),
                ({"rounds": 2.5}, f"{ROUNDS} (got 2.5)"),
                ({"rounds": True}, f"{ROUNDS} (got True)"),
                ({"review_lines": 0}, f"review_lines must be a whole number of at least 1, "
                                      f"{REVIEW} (got 0)"),
                ({"seat_lines": -1}, f"seat_lines must be a whole number of at least 0, "
                                     f"{SEAT} (got -1)"),
                ({"seat_lines": 400, "review_lines": 300},
                 f"seat_lines 400, {SEAT}, is over review_lines 300, {REVIEW}")):
            with self.subTest(settings=settings):
                akconfig.write(home, ["opus"], settings=settings)
                done = home.ak("run", str(task), timeout=60)
                self.assertEqual(done.code, 2, done.out)
                self.assertEqual(done.err, f"ak run: {config}: {why}\n")
                self.assertEqual(taskfile.runs(home), [])


if __name__ == "__main__":
    unittest.main()
