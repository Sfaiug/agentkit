"""A run's own pick of both roles takes its executor among those a marked reviewer of another lab
can review, while one of them can run here: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone reviews.  Where opus and astra,
on another provider, build and astra's window is spent from before the launch, the owner, 22 Nov
2026: "Own lab reviews when spent": opus builds and reviews its own work.  So does it where the
one spent so is fable, on opus's provider.  Black-box, on the fixtures of
tests/test_key_a_review_waits_for_another_provider.py.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_a_review_waits_for_another_provider import launch
from test_key_writer_reviews_only_without_room import (HOURS, SHORTAGE, launched, meter, roles,
                                                       staged)


class AnotherLabsExecutorIsSpent(unittest.TestCase):
    """opus and astra build; astra's window is spent from before the launch."""

    @classmethod
    def setUpClass(cls):
        week = time.time() + 86400
        staged(cls, ["opus", "astra"], ["opus"],
               {"claude": [meter(10, week)],
                "codex": [meter(100, time.time() + 3600, HOURS), meter(10, week)]},
               workers=["opus", "astra"], claude="work", codex="work")
        launch(cls)

    def test_with_the_other_labs_executor_spent_the_reviewers_lab_builds(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual(roles(self.fakes["codex"]), [])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("opus", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnLabsExecutorGivesWayToTheReviewer(unittest.TestCase):
    """opus and fable, on opus's provider, build; fable's window is spent from before the
    launch."""

    @classmethod
    def setUpClass(cls):
        over, week = time.time() + SHORTAGE, time.time() + 86400
        # fable's own cap beside the shared week: fable's shortage leaves opus to its meters
        scoped = {**meter(100, over), "name": "weekly_scoped", "scope": "Fable"}
        staged(cls, ["opus", "fable"], ["opus"], {"claude": [meter(10, week), scoped]},
               workers=["opus", "fable"], claude="work")
        launch(cls)

    def test_opus_builds_and_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-opus-5-5"), ("reviewer", "claude-opus-5-5")])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
