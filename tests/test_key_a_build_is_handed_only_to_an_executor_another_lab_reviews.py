"""A build whose executor's provider refuses it is handed only to an executor a marked reviewer
of another lab can review, while one of them can run here: with no lineup stored, as here, each
provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone reviews.  Where opus and astra,
on another provider, build and astra's provider refuses its executor turn for a spent window, no
executor turn runs on opus's harness: the run waits on astra, and once the window is past its
reset the tick resumes it, astra builds and opus reviews.  Where the one refused so is dart, of
opus's lab on astra's provider, opus takes the build over and reviews its own work: a lineup
stored as tests/test_key_a_lab_is_a_models_maker.py stores it makes dart opus's maker's, since a
handover never goes back to the provider that refused.  Black-box, on the fixtures of
tests/test_key_an_executor_has_another_labs_reviewer.py.  A refusal ends as its window does.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import boxable
from test_key_a_review_waits_for_another_provider import SHORTAGE, launch, refused
from test_key_writer_reviews_only_without_room import launched, meter, record, roles, staged, until_true


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AnotherLabsExecutorIsWaitedFor(unittest.TestCase):
    """opus and astra build; astra, picked at launch, is refused at its turn."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, ["opus", "astra"], ["opus"], {"claude": week, "codex": week},
                      workers=["opus", "astra"], claude="work", codex=[refused(SHORTAGE), "work"])
        launch(cls)
        cls.parked = cls.state
        cls.turns = roles(cls.fakes["claude"]), roles(cls.fakes["codex"])
        back = time.time() + SHORTAGE       # astra's turn was refused before the run ended
        until_true(lambda: time.time() > back + 1)
        cls.ticked = home.tick()
        until_true(lambda: record(cls.run_dir).get("state") not in ("exhausted", "queued",
                                                                    "running"), bound=300)
        cls.state = record(cls.run_dir)

    def test_no_executor_turn_runs_on_opus_s_harness_and_the_run_waits(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("astra", "opus"))
        self.assertEqual(self.turns, ([], ["executor"]))
        self.assertEqual((self.parked["state"], self.parked["executor"]), ("exhausted", "astra"))
        self.assertEqual(self.parked.get("executor_history") or [], [])

    def test_after_the_window_reset_the_tick_resumes_it_astra_builds_and_opus_reviews(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.out + self.ticked.err)
        self.assertIn(f"resumed {self.run_dir.name}: openai window refilled",
                      self.ticked.out.splitlines())
        self.assertEqual(roles(self.fakes["codex"]), ["executor", "executor"])
        self.assertEqual(roles(self.fakes["claude"]), ["reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("astra", "opus"))
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

if __name__ == "__main__":
    unittest.main()
