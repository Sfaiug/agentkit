"""A task's review that loses its reviewer goes to a model on its writer's provider only while
no marked reviewer on another provider can run here.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone builds.  Where astra, on
another provider, reviews and its window is spent by its turn, no reviewer turn runs on opus's
harness: the run parks, and once astra's window resets the tick resumes it and astra reviews.
Where the reviewer spent so is fable, on opus's provider, opus reviews its own work.  Where
astra's harness is gone from the machine by its turn, opus reviews.  Black-box, staged as
tests/test_key_writer_reviews_only_without_room.py stages it.  A shortage ends as a meter does:
its window resets.
"""

import shlex
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter, taskfile
from fixtures.akbin import boxable
from test_key_writer_reviews_only_without_room import (launched, meter, record, roles, staged,
                                                       until_true)

# long enough for a run to reach its review before the window its reviewer was refused on resets
SHORTAGE = 30
# a turn of an adapter whose program is gone: the shell's exec found nothing, and nothing streamed
GONE = {"stderr": "codex.sh: 1: exec: codex: not found\n", "exit": 127}


def at(moment):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


def refused(moment):
    """A turn its harness refuses, the window spent until `moment`."""
    return {"final": f"You have hit your usage limit. Try again at {at(moment)}.", "exit": 1}


def launch(case):
    home = case.home
    case.done = home.ak("run", str(taskfile.write(home, case.rig.path)), "--no-merge",
                        timeout=300)
    case.run_dir = taskfile.only_run(home)
    case.state = record(case.run_dir)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AnotherProvidersReviewerIsWaitedFor(unittest.TestCase):
    """opus and astra review; astra, picked at launch, is refused at its turn."""

    @classmethod
    def setUpClass(cls):
        back = time.time() + SHORTAGE
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, ["opus", "astra"], ["opus", "astra"], {"claude": week, "codex": week},
                      claude="work", codex=[refused(back), "pass"])
        launch(cls)
        cls.parked = cls.state
        until_true(lambda: time.time() > back + 1)
        cls.ticked = home.tick()
        until_true(lambda: record(cls.run_dir).get("state") not in ("exhausted", "queued",
                                                                    "running"), bound=300)
        cls.state = record(cls.run_dir)

    def test_no_reviewer_turn_runs_on_opus_s_harness_and_the_run_parks(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "astra"))
        self.assertEqual((self.parked["state"], self.parked["reviewer"]), ("exhausted", "astra"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])

    def test_after_the_window_reset_the_tick_resumes_it_and_astra_reviews(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.out + self.ticked.err)
        self.assertIn(f"resumed {self.run_dir.name}: reviewer astra eligible again",
                      self.ticked.out.splitlines())
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer", "reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "astra")
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


class OwnProvidersReviewerGivesWayToTheWriter(unittest.TestCase):
    """opus and fable, on opus's provider, review; fable, picked at launch, is refused at its
    turn."""

    @classmethod
    def setUpClass(cls):
        now = time.time()
        # fable's own cap beside the shared week: fable's refusal leaves opus to its meters
        scoped = {**meter(10, now + 86400), "name": "weekly_scoped", "scope": "Fable"}
        staged(cls, ["opus", "fable"], ["opus", "fable"],
               {"claude": [meter(10, now + 86400), scoped]},
               claude=["work", refused(now + 3600), "pass"])
        launch(cls)

    def test_opus_reviews_its_own_work(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "fable"))
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-opus-5-5"), ("reviewer", "claude-fable-5-1"),
                          ("reviewer", "claude-opus-5-5")])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


class AnotherProvidersHarnessIsGone(unittest.TestCase):
    """As the first, but codex, astra's harness, is gone from the machine during the build."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, ["opus", "astra"], ["opus", "astra"], {"claude": week, "codex": week},
                      claude="work", codex=GONE)
        release = cls.fakes["claude"].dir / "release"
        cls.fakes["claude"].behave(
            {**fakeadapter.WORK,
             "sh": f"until [ -f {shlex.quote(str(release))} ]; do sleep 0.2; done"}, "pass")

        def uninstall():
            until_true(lambda: cls.fakes["claude"].n)      # the build has begun
            (home.bin / "codex").unlink()
            release.touch()

        threading.Thread(target=uninstall, daemon=True).start()
        launch(cls)

    def test_opus_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "astra"))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "opus")
        self.assertEqual(self.state["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
