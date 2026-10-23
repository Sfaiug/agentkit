"""A seat's pull request mostly re-adding a budget-failed one's lines inherits its spent rounds.

Review rounds are three per pull request.  A seat whose pull request failed all three could
close it and open the same lines again on a new branch for three fresh rounds, so the first
review of a seat's own pull request is refused when more than half the lines it adds that hold
a letter or digit were added by one whose review failed after three rounds and never merged,
unless it is a real split, at most half that one's size.  The seat hears `split it ... or
redesign it` where it typed the command and no reviewer is spent; a split, or a redesign whose
lines are at least half its own, is reviewed.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, from the seat of akseat.py, against the bare origin of
gitrig.py and the GitHub of fakegh.py, with scripted harnesses from fakeadapter.py; the failed
review is one ak ran itself.
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

FAILED = [f"def fetch{n}(): return {n}" for n in range(40)]
OWN = [f"def store{n}(key): return key * {n}" for n in range(30)]
# A finding that holds on every head: the fixer, which commits nothing, never mends it.
FIND = {"final": "Found one.", "hand_in": [
    ["finding", "api.py:1", "fetch is wrong", "callers break", "--run", "test ! -f api.py"],
    ["done"]]}


def refusal(number, shared, written):
    return (f"PR #{number} re-adds {shared} of its {written} lines holding a letter or digit "
            f"from https://github.com/acme/widgets/pull/1, whose review failed after 3 rounds; "
            f"a replacement inherits them: split it into parts under 21 lines, or redesign it")


class ReplacementRounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        cls.gh = GitHub(cls.home)
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="pass", codex=FIND)
        Seat(cls.home, "acme", cwd=cls.rig.path, alive=False,
             record={"workers": ["opus", "astra"]})
        failed = cls.open_pr("fix-api", "api.py", FAILED)
        done, _, state = cls.review(failed)
        assert (done.code, state["state"], len(state["round_summaries"])) == (1, "fail", 3), (
            done.out + done.err)
        cls.gh.edit(1, state="CLOSED")
        cls.again = cls.open_pr("fix-api-again", "api.py", FAILED[:30] + OWN[:5])   # #2
        cls.over = cls.open_pr("fetch-part", "part.py", FAILED[:21])                # #3
        cls.split = cls.open_pr("fetch-half", "half.py", FAILED[:20])               # #4
        # under the seat's 50 lines, re-adding more than a split may, half of them its own
        cls.redesign = cls.open_pr("store", "store.py", FAILED[:24] + OWN[:24])     # #5

    @classmethod
    def open_pr(cls, branch, path, lines):
        """The seat's own pull request of a branch adding those lines; its URL."""
        cls.rig.branch(branch, {path: "".join(f"{line}\n" for line in lines)})
        return cls.gh.open_pr(cls.rig, branch, title=f"Add {path}")

    @classmethod
    def review(cls, url, *flags):
        """The seat reviews its pull request: what ak said, and the one run it recorded, its
        directory and its record."""
        before = set(taskfile.runs(cls.home))
        done = cls.home.ak("run", "--review-pr", url, *flags, env={"AGENTKIT_SESSION": "acme"},
                           cwd=cls.rig.path, timeout=300)
        new = [run for run in taskfile.runs(cls.home) if run not in before]
        assert len(new) == 1, f"one run expected, found {new}: {done.out}{done.err}"
        state = json.loads((new[0] / "run.json").read_text())
        assert state["review_pr"] == url, state
        return done, new[0], state

    def turns(self):
        return self.fakes["claude"].n + self.fakes["codex"].n

    def assertRefused(self, url, flags, sentence):
        before = self.turns()
        done, run, state = self.review(url, *flags)
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(done.err, f"ak run: {sentence}\n")
        self.assertEqual(self.turns(), before)
        self.assertEqual((state["state"], state["error"]), ("error", sentence))
        self.assertIn(f"## Why this run stopped\n\n{sentence}\n",
                      (run / "result.md").read_text())
        number = int(url.rsplit("/", 1)[1])
        self.assertEqual((self.gh.pr(number)["state"], self.gh.pr(number)["reviews"]),
                         ("OPEN", []))

    def assertReviewed(self, url):
        self.fakes["codex"].behave("pass")
        before = self.fakes["codex"].n
        done, _, state = self.review(url)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual([call["role"] for call in self.fakes["codex"].runs()[before:]],
                         ["reviewer"])
        self.assertEqual(state["verdict"], "PASS")

    def test_re_adding_most_of_a_failed_one_s_lines_is_refused_before_any_review(self):
        # the seat's own line detaches with --bg; the refusal comes before it would
        for flags in (("--bg",), ()):
            with self.subTest(flags=flags):
                self.assertRefused(self.again, flags, refusal(2, 30, 35))

    def test_a_part_over_half_the_failed_one_s_size_is_no_split(self):
        self.assertRefused(self.over, ("--bg",), refusal(3, 21, 21))

    def test_a_split_of_half_the_failed_one_s_size_is_reviewed(self):
        self.assertReviewed(self.split)

    def test_a_redesign_whose_lines_are_half_its_own_is_reviewed(self):
        self.assertReviewed(self.redesign)


if __name__ == "__main__":
    unittest.main()
