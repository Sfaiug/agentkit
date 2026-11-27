"""A model running its harness's default is no other lab than a named sibling on the same
harness and provider: the reviewer is of another lab than the writer's where one is marked
(the owner, 18, 22 and 27 Nov 2026).

nova builds on claude through provider `dune`, its id opening with claude's family word; mist,
on claude through `dune`, runs `default`; bolt is on codex.  No lineup is stored, and every
window has usage left:

- mist and bolt marked to review: bolt reviews and no reviewer turn runs on claude, in a draw
  that puts mist first and in one that puts bolt first;
- mist alone marked to review: mist reviews.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on the
fixtures of tests/test_key_an_unlisted_model_is_of_its_familys_lab.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_an_unlisted_model_is_of_its_familys_lab import DRAWS
from test_key_reviewer_other_provider_first import meters
from test_key_writer_reviews_only_without_room import OFFLINE, launched, record, roles

MODELS = {"nova": {"harness": "claude", "provider": "dune", "model": "claude-nova-2"},
          "mist": {"harness": "claude", "provider": "dune", "model": "default"},
          "bolt": {"harness": "codex", "model": "bolt-3"}}


def reviewed(case, reviewers, *, draws=("",)):
    """Run one task per draw in `draws`, nova building and `reviewers` marked to review."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    rig = Rig(home, "widgets")
    akconfig.write(home, MODELS, workers=["nova"], reviewers=reviewers)
    case.fakes = fakeadapter.install(home, claude="work", codex="pass")
    case.fakes["claude"].answer("usage", json.dumps(meters(60, "weekly")))
    case.fakes["codex"].answer("usage", json.dumps(meters(40, "weekly")))
    case.runs = []
    for n, draw in enumerate(draws, 1):
        before = set(taskfile.runs(home))
        task = taskfile.write(home, rig.path, f"Add retry file {n}")
        done = home.ak("run", str(task), "--no-merge", env={"AK_PICK_DRAW": draw}, timeout=300)
        (run_dir,) = set(taskfile.runs(home)) - before
        case.runs.append((draw, done, record(run_dir)))


class MistAndBoltMarkedToReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["mist", "bolt"], draws=DRAWS)

    def test_bolt_reviews_and_no_reviewer_turn_runs_on_claude_whichever_draw_puts_first(self):
        for draw, done, state in self.runs:
            with self.subTest(draw=draw):
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(launched(done), ("nova", "bolt"))
                self.assertEqual(state["review"]["reviewer"], "bolt")
        self.assertEqual(roles(self.fakes["claude"]), ["executor"] * len(DRAWS))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"] * len(DRAWS))


class MistAloneMarkedToReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["mist"])

    def test_mist_reviews_when_marked_alone(self):
        (_, done, state), = self.runs
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(launched(done), ("nova", "mist"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(roles(self.fakes["codex"]), [])
        self.assertEqual(state["review"]["reviewer"], "mist")


if __name__ == "__main__":
    unittest.main()
