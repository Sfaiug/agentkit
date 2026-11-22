"""A seat's own pull request is reviewed by a model of its writer's lab only while no marked
reviewer of another lab can run here with usage left: with no lineup stored, as here, each
provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."; 22 Nov: "Own lab reviews when spent".
The acme seat, whose orchestrator opus wrote the pull request, has it reviewed with
`--review-pr`.  Where astra, on another provider, reviews beside opus and its window was spent
before the launch, opus reviews its own work, as where the reviewer spent so is fable, of opus's
lab.  Launched with `--bg`, the parent picks beside the writer preflight recorded, as the child
does: with GitHub's login failing after preflight asked it, the parent names opus, and the child
keeps it.  Black-box, on the fixtures of
tests/test_key_a_pull_requests_new_reviewer_starts_fresh.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.akseat import Seat
from fixtures.fakegh import OFFLINE, GitHub
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


class AnotherLabsReviewerIsSpent(unittest.TestCase):
    """opus and astra review; astra's window was spent before the launch."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        opened(cls, ["opus", "astra"], {"claude": [meter(10, day)], "codex": [meter(100, day)]},
               claude="pass", codex="pass")
        launched(cls)

    def test_opus_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["state"], self.state["own_pr"]), ("pass", True))
        self.assertEqual(roles(self.fakes["claude"]), ["reviewer"])
        self.assertEqual(self.fakes["codex"].runs(), [])

    def test_its_verdict_stands(self):
        self.assertEqual((self.state["verdict"], self.state["review"]["reviewer"]),
                         ("PASS", "opus"))
        [review] = self.gh.pr(1)["reviews"]
        self.assertEqual(review["commit"]["oid"], self.head)
        self.assertEqual(review["body"].splitlines()[0],
                         f"agentkit review of {self.head[:12]} by opus "
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
        until_true(lambda: record(cls.run_dir).get("state") not in (None, "queued", "running"),
                   bound=300)
        cls.state = record(cls.run_dir)

    def test_the_parent_names_opus_and_the_child_keeps_it(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        [line] = [line for line in self.done.out.splitlines()
                  if line.startswith(f"run {self.run_dir.name} launched:")]
        self.assertIn("(opus review, self-reviewed)", line)
        self.assertEqual((self.state["own_pr"], self.state["reviewer"]), (True, "opus"))
        self.assertEqual((roles(self.fakes["claude"]), self.fakes["codex"].runs()),
                         (["reviewer"], []))


if __name__ == "__main__":
    unittest.main()
