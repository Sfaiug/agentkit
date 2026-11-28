"""A builder replacing one whose provider refused its turn is picked beside every model that
built before it, so a marked reviewer of another lab than all of them is left where one can be.

The owner, 18 Nov 2026: "Reviewer and executor should come from different labs. I want this to
be the case if chosen models allow it."  The models of
tests/test_key_an_unlisted_model_is_of_its_familys_lab.py, with no lineup stored: nova and dart
of one lab, bolt of another; reef, on a third harness and opening with no family word, is of its
provider's.  nova, bolt and reef build, dart and bolt review, and every window has usage left.
nova builds round one, bolt fails it, and nova's next turn is refused for usage.  In a draw
whose executors come nova, bolt, reef, bolt beside dart is the first pair of another lab beside
the new builder alone, though dart is nova's lab: reef takes the build over, bolt reviews it, and
the run ends PASS, with no executor turn on codex and no reviewer turn on dart's harness.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_a_review_waits_for_another_provider import refused
from test_key_an_unlisted_model_is_of_its_familys_lab import MODELS
from test_key_reviewer_other_provider_first import meters
from test_key_writer_reviews_only_without_room import OFFLINE, launched, record, roles

# executors drawn nova, bolt, reef (`usage.pick_order`): nova builds first, and bolt is drawn
# before reef where nova's lab is refused
DRAW = "20261128-0916"
# what bolt's finding asks (fakeadapter.FAIL): retry.txt gone
FIX = {"sh": "git rm -q retry.txt", "commit": "remove retry.txt",
       "final": "## Summary\nremoved retry.txt", "hand_in": [["done"]]}


class ARefusedBuilderIsReplacedBesideItsWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE)
        rig = Rig(home, "widgets")
        akconfig.write(home, {**MODELS, "reef": {"harness": "muse", "model": "reef-1"}},
                       workers=["nova", "bolt", "reef"], reviewers=["dart", "bolt"])
        cls.fakes = fakeadapter.install(home, claude=["work", refused(3600)],
                                        codex=["fail", "pass"], muse=FIX, opencode="pass")
        for fake in cls.fakes.values():
            fake.answer("usage", json.dumps(meters(10, "weekly")))
        task = taskfile.write(home, rig.path, done_when=("true",))
        cls.done = home.ak("run", str(task), "--no-merge",
                           env={"AK_PICK_DRAW": DRAW}, timeout=300)
        cls.state = record(taskfile.only_run(home))

    def test_reef_takes_the_build_over_and_bolt_reviews_it(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("nova", "bolt"))
        self.assertEqual([(move["from"], move["to"]) for move in self.state["executor_history"]],
                         [("nova", "reef")])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("reef", "bolt"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        # nova's fix turn is the one refused, and reef's the one that fixes
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "fixer"])
        self.assertEqual(roles(self.fakes["muse"]), ["fixer"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer", "reviewer"])
        self.assertEqual(roles(self.fakes["opencode"]), [])


if __name__ == "__main__":
    unittest.main()
