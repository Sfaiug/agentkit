"""A round's review begins on a model of its writer's lab only while no marked reviewer of
another lab can run here with usage left: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."; 22 Nov: "Own lab reviews when spent".
opus alone builds.  Where astra, on another provider, reviews and its window was spent before
the launch, the launch picks opus to review its own work, and opus does, as where the reviewer
spent so is fable, on opus's provider.  A handover's pick in place of the reviewer the launch
named, of opus's lab while the one of another is spent, reviews too.  Black-box, on the fixtures
of tests/test_key_a_review_waits_for_another_provider.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, taskfile
from fixtures.akconfig import PROVIDER
from test_key_a_review_waits_for_another_provider import launch
from test_key_writer_reviews_only_without_room import WEEK, launched, meter, record, roles, staged


def past_its_reset(case, harness):
    """`harness`'s window past its reset: ak's snapshot of it ends now, and its probe, due
    again, reads the next window."""
    now, provider = time.time(), PROVIDER[harness]
    case.fakes[harness].answer("usage", json.dumps({"meters": [meter(0, now + WEEK)],
                                                    "error": None}))
    snapshot = case.home.path / ".agentkit/state/usage.json"
    blob = json.loads(snapshot.read_text())
    for held in blob["providers"][provider]["meters"]:
        held["resets_at"] = now
    snapshot.write_text(json.dumps(blob))
    case.home.write(f".agentkit/state/{provider}-probe.lock", "0")


class AnotherProvidersReviewerIsSpent(unittest.TestCase):
    """opus and astra review; astra's window was spent before the launch."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        staged(cls, ["opus", "astra"], ["opus", "astra"],
               {"claude": [meter(10, day)], "codex": [meter(100, day)]},
               claude=["work", "pass"], codex="pass")
        launch(cls)

    def test_opus_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.fakes["codex"].runs(), [])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnProvidersReviewerGivesWayToTheWriter(unittest.TestCase):
    """opus and fable, on opus's provider, review; fable's window was spent the same way."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        # fable's own cap beside the shared week: fable's shortage leaves opus to its meters
        scoped = {**meter(100, day), "name": "weekly_scoped", "scope": "Fable"}
        staged(cls, ["opus", "fable"], ["opus", "fable"], {"claude": [meter(10, day), scoped]},
               claude=["work", "pass"])
        launch(cls)

    def test_opus_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-opus-5-5"), ("reviewer", "claude-opus-5-5")])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


class NamedReviewersStandInReviews(unittest.TestCase):
    """astra builds and opus, named, reviews; astra's turn is refused, so opus builds and the
    handover picks fable, of opus's lab, to review while mimo, of another, is spent."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        models, reviewers = ["astra", "opus", "fable", "mimo"], ["opus", "fable", "mimo"]
        home = staged(cls, models, reviewers, {"claude": [meter(10, day)],
                                               "codex": [meter(10, day)],
                                               "opencode": [meter(100, day)]},
                      claude=["work", "pass"], codex="dead", opencode="pass")
        akconfig.write(home, models, workers=["astra", "opus"], reviewers=reviewers)
        cls.done = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                           "--exec", "astra", "--review", "opus", timeout=300)
        cls.state = record(taskfile.only_run(home))

    def test_fable_reviews_while_mimo_is_spent(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual((self.state["executor"], self.state["reviewer"]), ("opus", "fable"))
        self.assertEqual(self.state["state"], "pass")
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.fakes["opencode"].runs(), [])


if __name__ == "__main__":
    unittest.main()
