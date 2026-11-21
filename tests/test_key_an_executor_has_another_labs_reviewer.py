"""A run's own pick of both roles takes its executor among those a marked reviewer of another lab
can review, while one of them can run here: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone reviews.  Where opus and astra,
on another provider, build and astra's window is spent from before the launch, no executor turn
runs on opus's harness: the run waits, and once astra's window resets the tick starts it, astra
builds and opus reviews.  Where the one spent so is fable, on opus's provider, opus builds and
reviews its own work.  Black-box, on the fixtures of
tests/test_key_a_review_waits_for_another_provider.py.  A shortage ends as a meter does: its
window resets.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_key_a_review_waits_for_another_provider import launch
from test_key_writer_reviews_only_without_room import (HOURS, SHORTAGE, launched, meter, record,
                                                       roles, staged, until_true)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AnotherLabsExecutorIsWaitedFor(unittest.TestCase):
    """opus and astra build; astra's window is spent from before the launch."""

    @classmethod
    def setUpClass(cls):
        over, week = time.time() + SHORTAGE, time.time() + 86400
        home = staged(cls, ["opus", "astra"], ["opus"],
                      {"claude": [meter(10, week)],
                       "codex": [meter(100, over, HOURS), meter(10, week)]},
                      workers=["opus", "astra"], claude="work", codex="work")
        launch(cls)
        cls.parked, cls.log = cls.state, (cls.run_dir / "log.txt").read_text()
        cls.turns = roles(cls.fakes["claude"]), roles(cls.fakes["codex"])
        until_true(lambda: time.time() > over + 1)
        cls.ticked = home.tick()
        until_true(lambda: record(cls.run_dir).get("state") not in ("exhausted", "queued",
                                                                    "running"), bound=300)
        cls.state = record(cls.run_dir)

    def test_no_executor_turn_runs_on_opus_s_harness_and_the_run_waits(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(self.turns, ([], []))
        self.assertEqual(self.parked["state"], "exhausted")
        self.assertIn("skipped opus: a marked reviewer of another lab can review astra", self.log)

    def test_after_the_window_reset_the_tick_starts_it_astra_builds_and_opus_reviews(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.out + self.ticked.err)
        self.assertIn(f"resumed {self.run_dir.name}: openai window refilled",
                      self.ticked.out.splitlines())
        self.assertEqual(roles(self.fakes["codex"]), ["executor"])
        self.assertEqual(roles(self.fakes["claude"]), ["reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("astra", "opus"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnLabsExecutorGivesWayToTheReviewer(unittest.TestCase):
    """opus and fable, on opus's provider, build; fable's window is spent from before the
    launch."""

    @classmethod
    def setUpClass(cls):
        over, week = time.time() + SHORTAGE, time.time() + 86400
        # fable's own cap beside the shared week: fable's shortage leaves opus to its meters
        scoped = {**meter(100, over), "name": "weekly_scoped", "scope": "Fable"}
        staged(cls, ["opus", "fable"], ["opus"], {"claude": [meter(10, week), scoped]},
               workers=["opus", "fable"], claude="work")
        launch(cls)

    def test_opus_builds_and_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "opus"))
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-opus-5-5"), ("reviewer", "claude-opus-5-5")])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
