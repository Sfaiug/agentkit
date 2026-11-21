"""A seat's own pull request is reviewed by a model of its writer's lab only while no marked
reviewer of another lab can run here: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  The acme seat, whose orchestrator opus
wrote the pull request, has it reviewed with `--review-pr`.  Where astra, on another provider,
reviews beside opus and its window was spent before the launch, no reviewer turn runs on opus's
harness: the run parks, a tick leaves it parked while astra's window is spent, and once that
window is past its reset the tick resumes it and astra reviews.  Where the reviewer spent so is
fable, of opus's lab, opus reviews its own work.  Launched with `--bg`, the parent picks beside
the writer preflight recorded, as the child does: with GitHub's login failing after preflight
asked it, the parent names no reviewer, and the child parks.  Black-box, on the fixtures of
tests/test_key_a_pull_requests_new_reviewer_starts_fresh.py.  No clock ends a shortage: the
window stays spent until the test moves it past its reset.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.akbin import boxable
from fixtures.akseat import Seat
from fixtures.fakegh import OFFLINE, GitHub
from test_key_a_review_starts_on_another_provider import past_its_reset
from test_key_writer_reviews_only_without_room import meter, record, roles, staged, until_true


def opened(case, reviewers, meters, **turns):
    """The acme seat's own pull request, opus its orchestrator and `reviewers` marked to review,
    each harness's meters as given."""
    home = staged(case, reviewers, reviewers, meters, **turns)
    Seat(home, "acme", cwd=case.rig.path, record={"workers": ["opus"], "reviewers": reviewers},
         planned=True)
    case.gh = GitHub(home)
    case.head = case.rig.branch("contrib", {"contrib.txt": "c\n"})
    case.url = case.gh.open_pr(case.rig, "contrib", title="Add contrib")


def launched(case, *flags):
    """`case`'s run of the review of `opened`'s pull request, launched from its seat."""
    case.done = case.home.ak("run", "--review-pr", case.url, *flags,
                             env={"AGENTKIT_SESSION": "acme"}, cwd=case.rig.path, timeout=300)
    case.run_dir = taskfile.only_run(case.home)
    case.state = record(case.run_dir)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AnotherLabsReviewerIsWaitedFor(unittest.TestCase):
    """opus and astra review; astra's window was spent before the launch."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        opened(cls, ["opus", "astra"], {"claude": [meter(10, day)], "codex": [meter(100, day)]},
               claude="pass", codex="pass")
        launched(cls)
        cls.parked = cls.state
        cls.early = cls.home.tick()
        cls.kept = record(cls.run_dir)
        past_its_reset(cls, "codex")
        cls.ticked = cls.home.tick()       # its box outlives it until the resumed run has ended
        cls.state = record(cls.run_dir)

    def test_no_reviewer_turn_runs_on_opus_s_harness_and_the_run_parks(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.parked["state"], self.parked["own_pr"]), ("exhausted", True))
        self.assertEqual(self.fakes["claude"].runs(), [])

    def test_a_tick_before_the_reset_leaves_it_parked(self):
        self.assertEqual(self.early.code, 0, self.early.out + self.early.err)
        self.assertEqual(self.kept["state"], "exhausted")
        self.assertEqual([line for line in self.early.out.splitlines()
                          if line.startswith(f"resumed {self.run_dir.name}:")], [])

    def test_after_the_reset_the_tick_resumes_it_and_astra_reviews(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.out + self.ticked.err)
        self.assertIn(f"resumed {self.run_dir.name}: reviewer astra eligible again",
                      self.ticked.out.splitlines())
        self.assertEqual(self.fakes["claude"].runs(), [])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])

    def test_its_verdict_stands(self):
        self.assertEqual((self.state["verdict"], self.state["review"]["reviewer"]),
                         ("PASS", "astra"))
        [review] = self.gh.pr(1)["reviews"]
        self.assertEqual(review["commit"]["oid"], self.head)
        self.assertEqual(review["body"].splitlines()[0],
                         f"agentkit review of {self.head[:12]} by astra "
                         f"(run {self.run_dir.name})")


class OwnLabsReviewerGivesWayToTheWriter(unittest.TestCase):
    """opus and fable, of opus's lab, review; fable's window was spent the same way."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        # fable's own cap beside the shared week: fable's shortage leaves opus to its meters
        scoped = {**meter(100, day), "name": "weekly_scoped", "scope": "Fable"}
        opened(cls, ["opus", "fable"], {"claude": [meter(10, day), scoped]}, claude="pass")
        launched(cls)

    def test_opus_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("reviewer", "claude-opus-5-5")])
        self.assertEqual((self.state["verdict"], self.state["review"]["reviewer"]),
                         ("PASS", "opus"))



class ABackgroundLaunchNamesTheReviewerTheChildKeeps(unittest.TestCase):
    """As astra's spent window above, launched with `--bg`; GitHub's login answers preflight,
    then fails once."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        opened(cls, ["opus", "astra"], {"claude": [meter(10, day)], "codex": [meter(100, day)]},
               claude="pass", codex="pass")
        cls.gh.reply("api user", json.dumps({"login": "acme"}), times=1)
        cls.gh.reply("api user", err=OFFLINE, code=1, times=1)
        launched(cls, "--bg")
        until_true(lambda: record(cls.run_dir).get("state") == "exhausted")
        cls.state = record(cls.run_dir)

    def test_the_parent_names_no_reviewer_and_the_child_parks(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([line for line in self.done.out.splitlines()
                          if line.startswith(f"run {self.run_dir.name} launched:")], [])
        self.assertEqual((self.state["own_pr"], self.state["reviewer"]), (True, None))
        self.assertEqual((self.fakes["claude"].runs(), self.fakes["codex"].runs()), ([], []))


if __name__ == "__main__":
    unittest.main()
