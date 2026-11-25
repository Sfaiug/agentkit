"""A model no stored lineup holds is of the lab its family word names: the reviewer is of another
lab than the writer's where one is marked (the owner, 18 and 22 Nov 2026).

nova builds on claude's provider, its id opening with claude's family word.  dart, on another
provider and harness, has an id opening with that same family word after a `provider/` prefix;
bolt, on a third provider, opens with none.  Every window has usage left:

- no lineup stored, dart and bolt marked to review: bolt reviews, and no reviewer turn runs on
  dart's harness, whichever of the two the draw puts first;
- a lineup stored that holds nova and not dart, the same marks: the same;
- no lineup stored, dart alone marked to review: dart reviews, as today.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on the
fixtures of tests/test_key_a_lab_is_a_models_maker.py.
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

MODELS = {"nova": {"harness": "claude", "model": "claude-nova-2"},
          "dart": {"harness": "opencode", "provider": "dune", "model": "dune/claude-dart-2"},
          "bolt": {"harness": "codex", "model": "bolt-3"}}
# Draws that put dart first and bolt first in the reviewer draw (`usage.pick_order`).
DRAWS = ("20261125-0900", "20261125-0901")


def lineup():
    """A stored lineup holding nova under its maker, and not dart."""
    entry = MODELS["nova"]
    return {"matrix": {"lineup": [
        {"release": entry["model"], "name": entry["model"], "board_name": entry["model"],
         "maker": "Acme", "effort": "high", "values": {}, "yours": [entry]}]}}


def reviewed(case, reviewers, *, stored=False, draws=("",)):
    """Run one task per draw in `draws`, nova building and `reviewers` marked to review."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    rig = Rig(home, "widgets")
    akconfig.write(home, MODELS, workers=["nova"], reviewers=reviewers)
    if stored:
        home.write(".agentkit/state/matrix.json", lineup())
    case.fakes = fakeadapter.install(home, claude="work", opencode="pass", codex="pass")
    case.fakes["claude"].answer("usage", json.dumps(meters(60, "weekly")))
    case.fakes["opencode"].answer("usage", json.dumps(meters(10, "weekly")))
    case.fakes["codex"].answer("usage", json.dumps(meters(40, "weekly")))
    case.runs = []
    for n, draw in enumerate(draws, 1):
        before = set(taskfile.runs(home))
        task = taskfile.write(home, rig.path, f"Add retry file {n}")
        done = home.ak("run", str(task), "--no-merge", env={"AK_PICK_DRAW": draw}, timeout=300)
        (run_dir,) = set(taskfile.runs(home)) - before
        case.runs.append((draw, done, record(run_dir)))


class NoLineupStored(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["dart", "bolt"], stored=False, draws=DRAWS)

    def test_bolt_reviews_and_darts_harness_never_does_whichever_draw_puts_first(self):
        for draw, done, state in self.runs:
            with self.subTest(draw=draw):
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(launched(done), ("nova", "bolt"))
                self.assertEqual(state["review"]["reviewer"], "bolt")
        self.assertEqual(roles(self.fakes["claude"]), ["executor"] * len(DRAWS))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"] * len(DRAWS))
        self.assertEqual(roles(self.fakes["opencode"]), [])


class LineupHoldsNovaAndNotDart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["dart", "bolt"], stored=True, draws=DRAWS)

    def test_bolt_reviews_and_darts_harness_never_does_whichever_draw_puts_first(self):
        for draw, done, state in self.runs:
            with self.subTest(draw=draw):
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(launched(done), ("nova", "bolt"))
                self.assertEqual(state["review"]["reviewer"], "bolt")
        self.assertEqual(roles(self.fakes["claude"]), ["executor"] * len(DRAWS))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"] * len(DRAWS))
        self.assertEqual(roles(self.fakes["opencode"]), [])


class DartAloneMarkedToReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["dart"], stored=False)

    def test_dart_reviews_when_marked_alone(self):
        (_, done, state), = self.runs
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(launched(done), ("nova", "dart"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])
        self.assertEqual(roles(self.fakes["opencode"]), ["reviewer"])
        self.assertEqual(roles(self.fakes["codex"]), [])
        self.assertEqual(state["review"]["reviewer"], "dart")


if __name__ == "__main__":
    unittest.main()
