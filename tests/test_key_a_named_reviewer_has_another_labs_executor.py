"""A launch naming only its reviewer picks its executor among those of another lab while one of
them can run here: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  22 Nov: "Own lab reviews when spent".
Launched with `--review opus`, opus on a subscription below pace: where opus and astra, on
credits on another provider, build, astra builds and opus reviews; where opus and fable, on
credits on opus's provider, build, opus builds and reviews its own work; and where opus and
astra build with astra's window spent, opus builds and reviews its own work.  Black-box, on the
fixtures of tests/test_key_an_executor_has_another_labs_reviewer.py.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from test_key_writer_reviews_only_without_room import (HOURS, launched, meter, record, roles,
                                                       staged)


def launch(case):
    home = case.home
    case.done = home.ak("run", str(taskfile.write(home, case.rig.path)), "--no-merge",
                        "--review", "opus", timeout=300)
    case.run_dir = taskfile.only_run(home)
    case.state = record(case.run_dir)


class AnotherLabsPaygExecutorBuilds(unittest.TestCase):
    """opus on a subscription below pace and astra on credits build; opus is named to review."""

    @classmethod
    def setUpClass(cls):
        week = time.time() + 86400
        staged(cls, {"opus": {}, "astra": {"mode": "payg"}}, ["opus", "astra"],
               {"claude": [meter(10, week)], "codex": [meter(10, week)]},
               workers=["opus", "astra"], claude="pass", codex="work")
        launch(cls)

    def test_astra_builds_and_opus_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("astra", "opus"))
        self.assertEqual(roles(self.fakes["codex"]), ["executor"])
        self.assertEqual(roles(self.fakes["claude"]), ["reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("astra", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnLabsPaygExecutorStaysOut(unittest.TestCase):
    """opus on a subscription below pace and fable, on credits of opus's lab, build; opus is
    named to review."""

    @classmethod
    def setUpClass(cls):
        week = time.time() + 86400
        scoped = {**meter(10, week), "name": "weekly_scoped", "scope": "Fable"}
        staged(cls, {"opus": {}, "fable": {"mode": "payg"}}, ["opus"],
               {"claude": [meter(10, week), scoped]},
               workers=["opus", "fable"], claude=["work", "pass"])
        launch(cls)

    def test_opus_builds_and_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-opus-5-5"), ("reviewer", "claude-opus-5-5")])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("opus", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class AnotherLabsExecutorIsSpent(unittest.TestCase):
    """opus and astra build, astra with nothing left; opus is named to review."""

    @classmethod
    def setUpClass(cls):
        week = time.time() + 86400
        staged(cls, ["opus", "astra"], ["opus"],
               {"claude": [meter(10, week)],
                "codex": [meter(100, time.time() + 3600, HOURS), meter(10, week)]},
               workers=["opus", "astra"], claude=["work", "pass"], codex="work")
        launch(cls)

    def test_with_the_other_labs_executor_spent_opus_builds_and_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual(roles(self.fakes["codex"]), [])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("opus", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


if __name__ == "__main__":
    unittest.main()
