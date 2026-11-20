"""A run parked for its review resumes only onto a reviewer of another lab than its writer
while one is marked: with no lineup stored, as here, each provider is a lab.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."  opus alone builds; opus and astra, on
another provider, review.  After the build both windows are spent, so the run parks for its
review.  opus's window resets first: the tick leaves the run waiting for astra.  Once astra's
resets, the tick resumes it and astra reviews.  Black-box, staged as
tests/test_key_writer_reviews_only_without_room.py stages it.  A shortage ends as a meter does:
its window resets.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter, taskfile
from fixtures.akbin import boxable
from test_key_writer_reviews_only_without_room import meter, record, roles, staged, until_true

# long enough for a run to reach its review while opus's window is spent
SHORTAGE = 30
# how much longer astra's lasts: a tick in between sees opus's reset alone
GAP = 20


def at(moment):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ParkedReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = time.time()
        opus_back, astra_back = now + SHORTAGE, now + SHORTAGE + GAP
        # the build's own stream reports opus's five hours spent; astra's review is refused
        windows = {"five_hour": {"utilization": 1, "resetsAt": int(opus_back)},
                   "seven_day": {"utilization": .1, "resetsAt": int(now + 86400)}}
        spent = json.dumps({"type": "rate_limit_event",
                            "rate_limit_info": {"unifiedWindows": windows}}) + "\n"
        refused = {"final": f"You have hit your usage limit. Try again at {at(astra_back)}.",
                   "exit": 1}
        week = [meter(10, now + 86400)]
        home = staged(cls, ["opus", "astra"], ["opus", "astra"], {"claude": week, "codex": week},
                      claude={**fakeadapter.WORK, "events": spent}, codex=[refused, "pass"])
        cls.ran = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                          timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.parked = record(cls.run_dir)
        until_true(lambda: time.time() > opus_back + 1)
        cls.early = home.tick()
        cls.waiting = record(cls.run_dir)
        until_true(lambda: time.time() > astra_back + 1)
        cls.late = home.tick()
        until_true(lambda: record(cls.run_dir).get("state") not in ("exhausted", "queued",
                                                                    "running"), bound=300)
        cls.state = record(cls.run_dir)

    def test_both_windows_spent_after_the_build_park_it_for_its_review(self):
        self.assertEqual(self.ran.code, 1, self.ran.out + self.ran.err)
        self.assertEqual((self.parked["state"], self.parked["executor"]), ("exhausted", "opus"))

    def test_once_opus_s_window_resets_the_tick_leaves_it_parked(self):
        self.assertEqual(self.early.code, 0, self.early.out + self.early.err)
        self.assertEqual(self.waiting["state"], "exhausted")
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])

    def test_once_astra_s_resets_the_tick_resumes_it_and_astra_reviews(self):
        self.assertIn(f"resumed {self.run_dir.name}: reviewer astra eligible again",
                      self.late.out.splitlines())
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer", "reviewer"])
        self.assertEqual(self.state["review"]["reviewer"], "astra")
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


if __name__ == "__main__":
    unittest.main()
