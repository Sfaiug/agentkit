"""The reviewer is picked in the owner's order of 21 Oct: a marked model on another provider,
then another marked model on the writer's provider, then the writer itself.

opus builds alone.  fable shares its provider and, listed first with the most budget left,
ranks first among the reviewers; astra is on another provider.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, with harnesses from fakeadapter.py
whose meters the test sets, on the bare origin of gitrig.py.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_writer_reviews_only_without_room import OFFLINE, WEEK, launched, record, roles


def meters(used, *names):
    return {"meters": [{"name": name, "used": used, "resets_at": int(time.time() + 86400),
                        "window_secs": WEEK} for name in names], "error": None}


def reviewed(case, reviewers):
    """Run one task opus builds and `reviewers` review."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus", "fable", "astra"], workers=["opus"], reviewers=reviewers)
    case.fakes = fakeadapter.install(home, claude="work", codex="pass")
    # fable's own meter is `weekly_scoped`; astra's provider has the least left
    case.fakes["claude"].answer("usage", json.dumps(meters(10, "weekly", "weekly_scoped")))
    case.fakes["codex"].answer("usage", json.dumps(meters(60, "weekly")))
    case.done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", timeout=300)
    case.state = record(taskfile.only_run(home))


class AnotherProviderFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["fable", "astra"])

    def test_the_other_providers_model_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "astra"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "astra")


class TheWritersProviderNext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["opus", "fable"])

    def test_its_other_model_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "fable"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "fable")


class TheWriterLast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviewed(cls, ["opus"])

    def test_the_writer_reviews_itself(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "opus")


if __name__ == "__main__":
    unittest.main()
