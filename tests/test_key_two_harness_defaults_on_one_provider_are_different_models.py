"""Two harness defaults on one provider are not the same model: the reviewer is of another lab
than the writer's where one is marked (the owner, 18, 22 and 27 Nov 2026).

nova builds on claude through provider `dune` running `default`, and echo runs `older-1` on
claude through `dune`; the stored lineup places both under maker Acme.  mist runs `default` on
codex through `dune`, unlisted, so its lab is `dune`.  With every window holding usage left and
mist and echo marked to review:

- mist reviews and no reviewer turn runs on claude, in a draw that puts mist first and in one
  that puts echo first;
- the completed run's status does not mark the pair self-reviewed.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on the
fixtures of tests/test_key_a_default_model_is_no_other_lab_than_its_sibling.py.
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

MODELS = {"nova": {"harness": "claude", "provider": "dune", "model": "default"},
          "mist": {"harness": "codex", "provider": "dune", "model": "default"},
          "echo": {"harness": "claude", "provider": "dune", "model": "older-1"}}
LINEUP = {"matrix": {"lineup": [
    {"release": release, "name": release, "board_name": release, "maker": "Acme",
     "effort": "high", "values": {}, "yours": [{"harness": "claude", "model": model}]}
    for release, model in (("current-1", "default"), ("older-1", "older-1"))]}}
# Draws that put mist first and echo first in the reviewer draw (`usage.pick_order`).
DRAWS = ("20261127-0900", "20261127-0901")


class TwoHarnessDefaultsOnOneProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE)
        rig = Rig(home, "widgets")
        akconfig.write(home, MODELS, workers=["nova"], reviewers=["mist", "echo"])
        home.write(".agentkit/state/matrix.json", LINEUP)
        cls.fakes = fakeadapter.install(home, claude="work", codex="pass")
        cls.fakes["claude"].answer("usage", json.dumps(meters(60, "weekly")))
        cls.fakes["codex"].answer("usage", json.dumps(meters(40, "weekly")))
        cls.runs = []
        for n, draw in enumerate(DRAWS, 1):
            before = set(taskfile.runs(home))
            task = taskfile.write(home, rig.path, f"Add retry file {n}")
            done = home.ak("run", str(task), "--no-merge", env={"AK_PICK_DRAW": draw}, timeout=300)
            (run_dir,) = set(taskfile.runs(home)) - before
            status = home.ak("run", "status", run_dir.name, timeout=60)
            cls.runs.append((draw, done, record(run_dir), status))

    def test_mist_reviews_and_is_not_self_reviewed_whichever_draw_puts_first(self):
        for draw, done, state, status in self.runs:
            with self.subTest(draw=draw):
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(launched(done), ("nova", "mist"))
                self.assertEqual(state["review"]["reviewer"], "mist")
                self.assertEqual(status.code, 0, status.out + status.err)
                self.assertIn("nova/mist", status.out)
                self.assertNotIn("nova/mist self-reviewed", status.out)
        self.assertEqual(roles(self.fakes["claude"]), ["executor"] * len(DRAWS))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"] * len(DRAWS))


if __name__ == "__main__":
    unittest.main()
