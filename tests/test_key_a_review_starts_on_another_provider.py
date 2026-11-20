"""A round's review begins on a model of its writer's lab only while no marked reviewer of
another lab can run here: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone builds.  Where astra, on
another provider, reviews and its window was spent before the launch, the launch picks opus to
review its own work, yet no reviewer turn runs on opus's harness: the run parks, and once
astra's window resets the tick resumes it and astra reviews.  Where the reviewer spent so is
fable, on opus's provider, opus reviews its own work.  A reviewer the launch named begins as
named, but not one a handover picked in its place.  Black-box, on the fixtures of
tests/test_key_a_review_waits_for_another_provider.py.  No clock ends a shortage: the window
stays spent until the launch has returned, and the test then moves it past its reset.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, taskfile
from fixtures.akbin import boxable
from fixtures.akconfig import PROVIDER
from test_key_a_review_waits_for_another_provider import launch
from test_key_writer_reviews_only_without_room import (WEEK, launched, meter, record, roles,
                                                       staged, until_true)


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


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AnotherProvidersReviewerIsWaitedFor(unittest.TestCase):
    """opus and astra review; astra's window was spent before the launch."""

    @classmethod
    def setUpClass(cls):
        day = time.time() + 86400
        home = staged(cls, ["opus", "astra"], ["opus", "astra"],
                      {"claude": [meter(10, day)], "codex": [meter(100, day)]},
                      claude="work", codex="pass")
        launch(cls)
        cls.parked = cls.state
        past_its_reset(cls, "codex")
        cls.ticked = home.tick()
        until_true(lambda: record(cls.run_dir).get("state") not in ("exhausted", "queued",
                                                                    "running"), bound=300)
        cls.state = record(cls.run_dir)

    def test_no_reviewer_turn_runs_on_opus_s_harness_and_the_run_parks(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual(self.parked["state"], "exhausted")
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])

    def test_after_the_reset_the_tick_resumes_it_and_astra_reviews(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.out + self.ticked.err)
        self.assertIn(f"resumed {self.run_dir.name}: reviewer astra eligible again",
                      self.ticked.out.splitlines())
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "astra")
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


class NamedReviewersStandInWaits(unittest.TestCase):
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

    def test_fable_does_not_review_and_the_run_waits_for_mimo(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual((self.state["executor"], self.state["reviewer"]), ("opus", "fable"))
        self.assertEqual(self.state["state"], "exhausted")
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])
        self.assertEqual(self.fakes["opencode"].runs(), [])


if __name__ == "__main__":
    unittest.main()
