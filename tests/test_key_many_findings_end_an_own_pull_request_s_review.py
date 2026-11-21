"""A seat's own pull request whose review leaves `rescope_findings` blocking findings or more ends there.

As for a task's run (tests/test_key_many_findings_end_a_run_for_rescoping.py), with ak's six a
seat's own pull request whose first review leaves six ends FAIL after that round with no fixer
turn, its review posted on GitHub as any FAIL is, its budget cut to the one round it recorded,
its result naming six, the number and rescoping with no resume offered, and its resume refused
in that sentence.  One left five gets its fixer turn and passes, as does one left six under
`rescope_findings = 0`; under two, two left at the third round end it there with no extra round
(tests/test_key_an_own_pull_request_gets_extra_rounds.py).  Somebody else's pull request
reviewed with six ends as it does today, with no rescope error.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, from the seat of akseat.py, against the
bare origin of gitrig.py and the GitHub of fakegh.py, with scripted harnesses from
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
import test_key_an_own_pull_request_gets_extra_rounds as extra
import test_key_many_findings_end_a_run_for_rescoping as rescope_key

LINES = 6
FIX = {"write": {"contrib.txt": "ready\n" * LINES}, "commit": "fix contrib.txt",
       "final": "Fixed.", "hand_in": [["done"]]}


def review(count):
    """A review leaving `count` blocking findings, one on each of contrib.txt's first lines,
    each proven until its line reads `ready`."""
    return {"final": f"Found {count}.", "hand_in": [
        *(["finding", f"contrib.txt:{n}", f"line {n} is wrong", "breaks callers", "--run",
           f"sed -n {n}p contrib.txt | grep -qx ready"] for n in range(1, count + 1)), ["done"]]}


def reviewed(cls, claude, codex, *, own=True, settings=None, rules=extra.RULES, fail_first_post=False):
    """Review a PR adding contrib.txt (the acme seat's own when `own`, else another author's),
    astra reviewing and opus fixing."""
    cls.home = Home()
    cls.addClassCleanup(cls.home.close)
    cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": rules})
    cls.gh = GitHub(cls.home)
    akconfig.write(cls.home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                   settings=settings)
    cls.fakes = fakeadapter.install(cls.home, claude=claude, codex=codex)
    if own:
        Seat(cls.home, "acme", cwd=cls.rig.path, alive=False,
             record={"workers": ["opus", "astra"]}, planned=True)
    cls.head = cls.rig.branch("contrib", {"contrib.txt": "wrong\n" * LINES})
    url = cls.gh.open_pr(cls.rig, "contrib", title="Add contrib",
                         author="acme" if own else "other-dev")
    if fail_first_post:
        cls.gh.reply(f"api repos/{cls.rig.slug}/pulls/1/reviews --method POST",
                     err="HTTP 502", code=1, times=1)
    env = {"AGENTKIT_SESSION": "acme"} if own else None
    cls.done = cls.home.ak("run", "--review-pr", url, env=env, cwd=cls.rig.path, timeout=600)
    cls.run_dir = taskfile.only_run(cls.home)
    cls.state = json.loads((cls.run_dir / "run.json").read_text())
    cls.result = (cls.run_dir / "result.md").read_text()


class SixLeft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, [FIX], [review(6), "pass"])

    def test_the_run_ends_failed_after_its_first_round_with_no_fixer_turn(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(extra.rounds(self.state), [(1, "FAIL", 6)])
        self.assertEqual((self.state["state"], self.state["merged"], self.state["rounds"],
                          self.state["own_pr"]), ("fail", False, 1, True))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 1))
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["merge"]), ("OPEN", None))
        reviews = self.gh.pr(1)["reviews"]
        self.assertEqual([(item["state"], item["commit"]["oid"]) for item in reviews],
                         [("COMMENTED", self.head)])

    def test_its_result_counts_against_the_cut_budget_and_says_why(self):
        lines = self.result.splitlines()
        self.assertTrue(lines[0].startswith("# FAIL (1 of 1) "), lines[0])
        self.assertEqual(lines[2], "Next: split the task")
        self.assertIn("rounds: 1 of 1", lines)
        at = lines.index("## Why this run stopped")
        self.assertEqual(lines[at + 2], "The review left 6 blocking findings, at or past "
                                        "rescope_findings = 6: rescope the task.")
        self.assertNotIn("ak run resume", self.result)

    def test_its_resume_is_refused_for_rescoping(self):
        for more in ((), ("--rounds", "3")):
            with self.subTest(more=more):
                rescope_key.refused(self, self.home, self.run_dir, *more)
                self.assertEqual(json.loads((self.run_dir / "run.json").read_text()), self.state)
        ran = rescope_key.older(self.home)
        record = {**self.state, "ak_checkout": str(ran.parent)}
        self.home.write(self.run_dir / "run.json", record)
        for step in ("older", "cleaned", "no box"):
            with self.subTest(step):
                if step == "cleaned":
                    self.assertEqual(self.home.ak("run", "clean", self.run_dir.name).code, 0)
                if step == "no box":
                    self.home.fake("bwrap", "#!/bin/sh\nexit 1\n")
                rescope_key.refused(self, self.home, self.run_dir, "--rounds", "3")
                self.assertFalse(ran.exists())
                self.assertEqual(json.loads((self.run_dir / "run.json").read_text()), record)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 1))


class GoesOn:
    """The first review hands findings to the fixer, and the second passes and lands the PR."""
    count = 0

    def test_it_gets_its_fixer_turn_and_lands(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(extra.rounds(self.state), [(1, "FAIL", self.count), (2, "PASS", 0)])
        self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()], ["fixer"])
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (1, 2))


class FiveLeft(GoesOn, unittest.TestCase):
    count = 5

    @classmethod
    def setUpClass(cls):
        reviewed(cls, [FIX], [review(5), "pass"])


class SixLeftWithRescopeOff(GoesOn, unittest.TestCase):
    count = 6

    @classmethod
    def setUpClass(cls):
        reviewed(cls, [FIX], [review(6), "pass"], settings={"rescope_findings": 0})


class TwoLeftAtTheThirdRoundUnderTwo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        two = {"final": "Found two.", "hand_in": [extra.finding("contrib.txt"),
                                                  extra.finding("other.txt"), ["done"]]}
        reviewed(cls, [extra.DISPUTE, extra.DISPUTE_ADDING],
                 [extra.ONE, extra.ONE, two, "pass"], settings={"rescope_findings": 2})

    def test_the_run_ends_failed_after_three_with_no_extra_round(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(extra.rounds(self.state), [(1, "FAIL", 1), (2, "FAIL", 1), (3, "FAIL", 2)])
        self.assertEqual((self.state["state"], self.fakes["claude"].n, self.fakes["codex"].n),
                         ("fail", 2, 3))
        self.assertEqual(self.state["error"], "The review left 2 blocking findings, at or past "
                                              "rescope_findings = 2: rescope the task.")


class SomebodyElsesPullRequestWithSixLeft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, [FIX], [review(6)], own=False)

    def test_it_ends_as_it_does_today(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["verdict"], self.state["own_pr"],
                          self.state["review_posted"], self.state["rounds"]),
                         ("fail", "FAIL", False, True, 1))
        self.assertIsNone(self.state.get("error"))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 1))
        reviews = self.gh.pr(1)["reviews"]
        self.assertEqual([(item["state"], item["commit"]["oid"]) for item in reviews],
                         [("CHANGES_REQUESTED", self.head)])
        self.assertNotIn("## Why this run stopped", self.result)
        self.assertNotIn("rescope_findings", self.result)


class PostRetryAfterSixLeft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, [FIX], [review(6), "pass"], fail_first_post=True)
        cls.recovered = cls.home.ak("run", "resume", cls.run_dir.name, "--rounds", "3", timeout=600)
        cls.after = json.loads((cls.run_dir / "run.json").read_text())
        cls.after_result = (cls.run_dir / "result.md").read_text()

    def test_a_post_retry_with_more_rounds_keeps_the_cut_budget_and_offers_no_recovery(self):
        self.assertEqual((self.done.code, self.state["state"], self.state["rounds"]), (2, "error", 1))
        self.assertEqual(self.recovered.code, 1, self.recovered.out + self.recovered.err)
        self.assertEqual(extra.rounds(self.after), [(1, "FAIL", 6)])
        self.assertEqual((self.after["state"], self.after["merged"], self.after["rounds"],
                          self.after["review_posted"]), ("fail", False, 1, True))
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 1))
        self.assertEqual((self.gh.pr(1)["state"], self.gh.pr(1)["merge"]), ("OPEN", None))
        self.assertIn("rounds: 1 of 1", self.after_result.splitlines())
        self.assertIn("The review left 6 blocking findings, at or past rescope_findings = 6: "
                      "rescope the task.", self.after_result)
        for args in (("run", "status", self.run_dir.name), ("run", "status", "--plain")):
            with self.subTest(args=args):
                shown = self.home.ak(*args)
                self.assertEqual(shown.code, 0, shown.err)
                self.assertNotIn(f"ak run resume {self.run_dir.name} offers recovery", shown.out)
        rescope_key.refused(self, self.home, self.run_dir)


if __name__ == "__main__":
    unittest.main()
