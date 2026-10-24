"""Three review rounds is a change's budget across all its runs, and a fourth is never spent.

A task relaunched `from:` a branch of an earlier run continues that run's change, so it has
only the rounds the change has left, counted from the moment each round starts; a run that
still has rounds of its own ends blocked rather than spend one another run of its change took;
and once three are spent, no launch from any branch of it and no resume asking for more starts
another turn.  A seat's own pull request has the same three across every review run of it.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py
whose reviewer files a finding every round.
"""

import json
import shlex
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

REVIEW = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fake defect", "it matters", "--run", "false"], ["done"]]}
SPENT = "3 review rounds spent on {} across 2 runs: "


def finished(run_dir, bound=120):
    """The run's record once it has ended."""
    deadline = time.monotonic() + bound
    while not (state := json.loads((run_dir / "run.json").read_text())).get("finished_at"):
        assert time.monotonic() < deadline, (run_dir / "log.txt").read_text()
        time.sleep(0.1)
    return state


class FromABranch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(home, claude="work", codex=REVIEW)
        folder = cls.fakes["claude"].dir
        held, released = folder / "held", folder / "release"
        cls.addClassCleanup(released.touch)
        # The first run's round 2 fixer holds its turn while the relaunch spends a round, then
        # disputes the finding, as a done is refused while its proof still fails.
        hold = (f"touch {shlex.quote(str(held))}; while [ ! -f {shlex.quote(str(released))} ]"
                f" && [ -d {shlex.quote(str(folder))} ]; do sleep 0.1; done")
        cls.fakes["claude"].behave("work", {**fakeadapter.DISPUTE, "sh": hold}, "work")
        launched = home.ak("run", str(taskfile.write(home, cls.rig.path, "Add retry file")),
                           "--no-merge", "--bg")
        assert launched.code == 0, launched.out + launched.err
        cls.first = taskfile.only_run(home)
        deadline = time.monotonic() + 120
        while not held.exists():
            assert time.monotonic() < deadline, (cls.first / "log.txt").read_text()
            time.sleep(0.1)
        cls.relaunch = cls.launch("Finish retry file", "ak/add-retry-file")
        cls.second = next(run for run in taskfile.runs(home) if run != cls.first)
        released.touch()
        cls.state = finished(cls.first)
        cls.again = json.loads((cls.second / "run.json").read_text())
        cls.turns = cls.fakes["claude"].n + cls.fakes["codex"].n
        cls.refused = {branch: cls.launch(f"Redo {branch}", branch)
                       for branch in ("ak/add-retry-file", "ak/finish-retry-file")}
        cls.resumed = home.ak("run", "resume", cls.second.name, "--rounds", "2")

    @classmethod
    def launch(cls, title, branch):
        task = taskfile.write(cls.home, cls.rig.path, title, front={"from": branch})
        return cls.home.ak("run", str(task), "--no-merge", timeout=300)

    def test_a_relaunch_has_only_the_rounds_its_change_has_left(self):
        self.assertEqual(self.relaunch.code, 1, self.relaunch.out + self.relaunch.err)
        self.assertEqual({key: self.again.get(key) for key in ("state", "rounds", "change")},
                         {"state": "fail", "rounds": 1, "change": self.first.name})
        self.assertEqual([summary["verdict"] for summary in self.again["round_summaries"]],
                         ["FAIL"])

    def test_the_run_it_took_a_round_from_ends_blocked_before_its_third(self):
        self.assertEqual({key: self.state.get(key) for key in ("state", "verdict", "rounds")},
                         {"state": "blocked", "verdict": "BLOCKED", "rounds": 3})
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL", "FAIL"])
        self.assertTrue(self.state["error"].startswith(SPENT.format("this change")),
                        self.state["error"])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (3, 3))

    def test_a_launch_from_any_branch_of_the_change_is_refused_before_any_turn(self):
        for branch, done in self.refused.items():
            with self.subTest(branch=branch):
                self.assertEqual(done.code, 2, done.out + done.err)
                self.assertIn(SPENT.format(f"branch {branch}"), done.err)
        self.assertEqual(self.fakes["claude"].n + self.fakes["codex"].n, self.turns)

    def test_a_resume_asking_for_more_rounds_is_refused(self):
        self.assertEqual(self.resumed.code, 2, self.resumed.out + self.resumed.err)
        self.assertIn(SPENT.format("this change"), self.resumed.err)
        self.assertEqual(self.fakes["claude"].n + self.fakes["codex"].n, self.turns)


class OwnPullRequest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig, cls.gh = Rig(home, "widgets"), GitHub(home)
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(home, claude="pass", codex=REVIEW)
        Seat(home, "acme", cwd=rig.path, alive=False, record={"workers": ["opus", "astra"]},
             planned=True)
        rig.branch("fix-api", {"retry.txt": "one\n"})
        cls.url = cls.gh.open_pr(rig, "fix-api", title="Add retry file")
        cls.done = cls.review(rig)
        cls.state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        cls.turns = cls.fakes["claude"].n + cls.fakes["codex"].n
        cls.reviews = cls.gh.pr(1)["reviews"]
        # the seat fixes it by hand and asks again
        rig.git("checkout", "-q", "fix-api")
        rig.commit({"retry.txt": "two\n"}, "retry two")
        cls.again = cls.review(rig)

    @classmethod
    def review(cls, rig):
        return cls.home.ak("run", "--review-pr", cls.url, env={"AGENTKIT_SESSION": "acme"},
                           cwd=rig.path, timeout=300)

    def test_its_review_spends_three_rounds_and_fails(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual([summary["verdict"] for summary in self.state["round_summaries"]],
                         ["FAIL"] * 3)

    def test_a_second_review_run_of_it_is_refused_before_any_turn(self):
        self.assertEqual(self.again.code, 2, self.again.out + self.again.err)
        self.assertIn("3 review rounds spent on PR #1 across 1 run: ", self.again.err)
        self.assertEqual(self.fakes["claude"].n + self.fakes["codex"].n, self.turns)
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["reviews"]),
                         ("OPEN", self.reviews))


if __name__ == "__main__":
    unittest.main()
