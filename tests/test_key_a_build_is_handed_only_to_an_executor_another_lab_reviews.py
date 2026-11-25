"""A build whose executor's provider refuses it is handed only to an executor a marked reviewer
of another lab can review, while one of them on a provider that has not refused it can run here:
with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone reviews.  Where opus and astra,
on another provider, build and astra's provider refuses its executor turn for a spent window, the
owner, 22 Nov 2026: "Own lab reviews when spent": opus takes the build over and reviews its own
work.  So does it where the one refused so is dart, of opus's lab on astra's provider: a lineup
stored as tests/test_key_a_lab_is_a_models_maker.py stores it makes dart opus's maker's, since a
handover never goes back to the provider that refused.  Nor does a subscription that cannot take
the work keep a payg reviewer out, though its meters show room: where astra, named the executor,
and bolt, on opus's provider, build, astra and opus, payg, review, and astra's harness is gone by
its executor turn, bolt takes the build over and opus reviews it.  Black-box, on the fixtures of
tests/test_key_an_executor_has_another_labs_reviewer.py.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, taskfile
from test_key_a_review_waits_for_another_provider import GONE, launch, refused
from test_key_writer_reviews_only_without_room import launched, meter, record, roles, staged


class AnotherLabsExecutorIsRefused(unittest.TestCase):
    """opus and astra build; astra, picked at launch, is refused at its turn."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        staged(cls, ["opus", "astra"], ["opus"], {"claude": week, "codex": week},
               workers=["opus", "astra"], claude="work", codex=refused(3600))
        launch(cls)

    def test_with_the_other_labs_executor_refused_the_reviewers_lab_takes_the_build_over(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("astra", "opus"))
        self.assertEqual(roles(self.fakes["codex"]), ["executor"])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual([(move["from"], move["to"]) for move in self.state["executor_history"]],
                         [("astra", "opus")])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("opus", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnLabsExecutorGivesWayToTheReviewer(unittest.TestCase):
    """opus and dart, of opus's lab on astra's provider, build; dart, picked at launch, is
    refused at its turn."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        models = {"opus": {}, "dart": {"harness": "codex", "model": "acme-dart-2"}}
        home = staged(cls, models, ["opus"], {"claude": week, "codex": week},
                      workers=["opus", "dart"], claude="work", codex=refused(3600))
        entries = akconfig.read(home)["models"]
        home.write(".agentkit/state/matrix.json", {"matrix": {"lineup": [
            {"release": entries[name]["model"], "name": entries[name]["model"],
             "board_name": entries[name]["model"], "maker": "Acme", "effort": "high",
             "values": {}, "yours": [{key: entries[name][key] for key in ("harness", "model")}]}
            for name in models]}})
        launch(cls)

    def test_opus_takes_the_build_over_and_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("dart", "opus"))
        self.assertEqual(roles(self.fakes["codex"]), ["executor"])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("opus", "opus"))
        self.assertEqual(self.state["verdict"], "PASS")


class ARefusedSubscriptionKeepsNoPaygReviewerOut(unittest.TestCase):
    """astra and bolt build, astra and opus, payg, review; astra, named the executor, reviews
    itself at launch and finds its harness gone at its turn."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, {"opus": {"mode": "payg"}, "astra": {},
                            "bolt": {"harness": "claude", "model": "claude-bolt-1"}},
                      ["astra", "opus"], {"claude": week, "codex": week},
                      workers=["astra", "bolt"], claude=["work", "pass"], codex=GONE)
        cls.done = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                           "--exec", "astra", timeout=300)
        cls.state = record(taskfile.only_run(home))

    def test_bolt_takes_the_build_over_and_opus_reviews_it(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("astra", "astra"))
        self.assertEqual(roles(self.fakes["codex"]), ["executor"])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("bolt", "opus"))
        self.assertEqual(self.state["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
