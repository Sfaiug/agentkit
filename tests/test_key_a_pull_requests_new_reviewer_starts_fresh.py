"""A pull request's review that another model takes over on a resume starts fresh, as a task's
review taken over does: the conversation of the one that began it is not the new reviewer's,
whose turn reads the pull request's diff as a first one does.  The one that began it, picked
again, goes on in its own conversation.

Somebody else's pull request is reviewed with `--review-pr`, opus and astra marked to review,
astra spent at launch so opus is the pick.  opus's turn is refused and leaves its session; with
astra still spent, the run parks.  Black-box, on the fixtures of
tests/test_key_a_review_waits_for_another_provider.py.  A shortage ends as a meter does: its
window resets.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.fakegh import GitHub
from test_key_a_review_waits_for_another_provider import refused
from test_key_writer_reviews_only_without_room import (HOURS, meter, record, roles, staged,
                                                       until_true)

# long enough for a launch to pick, and to park, while the shortage lasts
SHORTAGE = 30
ADDED = "+a line the pull request adds"


def parked(case, codex, claude):
    """`case`'s run of the review of other-dev's pull request, parked, with astra's meters
    `codex` and opus's turns `claude`."""
    week = time.time() + 86400
    home = staged(case, ["opus", "astra"], ["opus", "astra"],
                  {"claude": [meter(10, week)], "codex": codex}, claude=claude, codex="pass")
    case.gh = GitHub(home)
    case.head = case.rig.branch("contrib", {"contrib.txt": ADDED[1:] + "\n"})
    case.url = case.gh.open_pr(case.rig, "contrib", body="adds a line", author="other-dev")
    case.launched = home.ak("run", "--review-pr", case.url, timeout=300)
    case.run_dir = taskfile.only_run(home)
    case.parked = record(case.run_dir)


def resumed(case):
    case.resumed = case.home.ak("run", "resume", case.run_dir.name, timeout=300)
    case.state = record(case.run_dir)


class LaunchParks:
    def test_opus_s_turn_is_refused_and_the_run_parks_on_its_session(self):
        self.assertEqual(self.launched.code, 1, self.launched.out + self.launched.err)
        self.assertEqual({key: self.parked.get(key) for key in (
            "state", "reviewer", "review_session")}, {
            "state": "exhausted", "reviewer": "opus", "review_session": "sid-claude-1"})


class AnotherReviewerTakesItOver(LaunchParks, unittest.TestCase):
    """astra's window resets while opus's stays spent."""

    @classmethod
    def setUpClass(cls):
        over = time.time() + SHORTAGE
        parked(cls, [meter(100, over, HOURS), meter(10, time.time() + 86400)],
               refused(3600))
        until_true(lambda: time.time() > over + 1)
        resumed(cls)

    def test_astra_reviews_the_diff_on_no_session(self):
        self.assertEqual(self.resumed.code, 0, self.resumed.out + self.resumed.err)
        self.assertEqual(roles(self.fakes["claude"]), ["reviewer"])
        [turn] = self.fakes["codex"].runs()
        self.assertEqual((turn["role"], turn["argv"][5:]), ("reviewer", []))
        self.assertIn(ADDED, Path(turn["argv"][3]).read_text().splitlines())

    def test_its_verdict_stands(self):
        self.assertEqual((self.state["state"], self.state["verdict"], self.state["reviewer"],
                          self.state["review"]["reviewer"]), ("pass", "PASS", "astra", "astra"))
        [review] = self.gh.pr(1)["reviews"]
        self.assertEqual((review["state"], review["commit"]["oid"]), ("COMMENTED", self.head))
        self.assertEqual(review["body"].splitlines()[0],
                         f"agentkit review of {self.head[:12]} by astra "
                         f"(run {self.run_dir.name})")


class TheReviewerThatBeganItGoesOn(LaunchParks, unittest.TestCase):
    """opus's window resets while astra's stays spent."""

    @classmethod
    def setUpClass(cls):
        parked(cls, [meter(100, time.time() + 86400)], [refused(SHORTAGE), "pass"])
        back = time.time() + SHORTAGE       # opus's turn was refused before the run parked
        until_true(lambda: time.time() > back + 1)
        resumed(cls)

    def test_opus_goes_on_in_its_own_session(self):
        self.assertEqual(self.resumed.code, 0, self.resumed.out + self.resumed.err)
        self.assertEqual(self.fakes["codex"].runs(), [])
        self.assertEqual([(run["role"], run["argv"][5:]) for run in self.fakes["claude"].runs()],
                         [("reviewer", []), ("reviewer", ["sid-claude-1"])])
        self.assertEqual((self.state["state"], self.state["verdict"],
                          self.state["review"]["reviewer"]), ("pass", "PASS", "opus"))


if __name__ == "__main__":
    unittest.main()
