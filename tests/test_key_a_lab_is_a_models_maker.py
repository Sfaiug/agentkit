"""Two models of one maker are one lab, whichever provider runs them: the reviewer is of another
lab than the writer's where one is marked (the owner, 18 Nov 2026).  A model's lab is the maker
the lineup last stored names for it; a model no lineup holds whose id opens with no family word
is of its harness's family, here its provider's
(tests/test_key_an_unlisted_model_is_of_its_familys_lab.py).

nova, Acme's, builds on claude's provider.  Two reviewers have room: dart, another model of
Acme's on codex's provider, listed first, and bolt, Bolt's, on nova's
provider.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, with harnesses from fakeadapter.py whose meters the test sets, on the
bare origin of gitrig.py, and the lineup a `ak models` stores written as it stores it, its rows
without scores so it turns off none of them.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_reviewer_other_provider_first import meters
from test_key_writer_reviews_only_without_room import OFFLINE, launched, record, roles

MODELS = {"nova": {"harness": "claude", "model": "acme-nova-2"},
          "dart": {"harness": "codex", "model": "acme-dart-2"},
          "bolt": {"harness": "claude", "model": "bolt-3"}}
MAKERS = {"nova": "Acme", "dart": "Acme", "bolt": "Bolt"}


def lineup():
    """A row of every model marked, under its maker, holding it as `yours`."""
    return {"matrix": {"lineup": [
        {"release": entry["model"], "name": entry["model"], "board_name": entry["model"],
         "maker": MAKERS[name], "effort": "high", "values": {}, "yours": [entry]}
        for name, entry in MODELS.items()]}}


def reviewed(case, stored):
    """Run one task nova builds and dart or bolt reviews, the lineup `stored` or none."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    rig = Rig(home, "widgets")
    akconfig.write(home, MODELS, workers=["nova"], reviewers=["dart", "bolt"])
    if stored:
        home.write(".agentkit/state/matrix.json", lineup())
    case.fakes = fakeadapter.install(home, claude="work", codex="pass")
    case.fakes["claude"].answer("usage", json.dumps(meters(60, "weekly")))
    case.fakes["codex"].answer("usage", json.dumps(meters(10, "weekly")))
    case.done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
    case.state = record(taskfile.only_run(home))


class AnotherMakersModelReviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, stored=True)

    def test_the_other_makers_model_on_the_writers_provider_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("nova", "bolt"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(roles(self.fakes["codex"]), [])
        self.assertEqual(self.state["review"]["reviewer"], "bolt")


class WithoutALineupTheProviderIsTheLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, stored=False)

    def test_the_model_on_another_provider_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("nova", "dart"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "dart")


if __name__ == "__main__":
    unittest.main()
