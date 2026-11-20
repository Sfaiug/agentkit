"""A run parked for its review names no executor's window.

opus alone builds; astra, on another provider, alone reviews.  After the build both windows
are spent, so the run parks for its review.  Only a reviewer's window lets it go on, and the
tick picks that reviewer when it resumes the run: `ak run status` names no window of its own,
which could part from the tick's pick, and says `waiting for a provider window` -- both while
opus is spent and once its window has reset.  Black-box, staged as
tests/test_key_a_parked_review_resumes_onto_another_provider.py stages it.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter, taskfile
from fixtures.akbin import boxable
from test_key_a_parked_review_resumes_onto_another_provider import GAP, SHORTAGE, at
from test_key_writer_reviews_only_without_room import meter, record, staged, until_true


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ParkedReviewNamesNoExecutorsWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = time.time()
        opus_back, astra_back = now + SHORTAGE, now + SHORTAGE + GAP
        windows = {"five_hour": {"utilization": 1, "resetsAt": int(opus_back)},
                   "seven_day": {"utilization": .1, "resetsAt": int(now + 86400)}}
        spent = json.dumps({"type": "rate_limit_event",
                            "rate_limit_info": {"unifiedWindows": windows}}) + "\n"
        refused = {"final": f"You have hit your usage limit. Try again at {at(astra_back)}.",
                   "exit": 1}
        week = [meter(10, now + 86400)]
        home = staged(cls, ["opus", "astra"], ["astra"], {"claude": week, "codex": week},
                      claude={**fakeadapter.WORK, "events": spent}, codex=[refused])
        cls.ran = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                          timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.parked = record(cls.run_dir)
        cls.spent = home.ak("run", "status", cls.run_dir.name)
        until_true(lambda: time.time() > opus_back + 1)
        cls.refilled = home.ak("run", "status", cls.run_dir.name)

    def test_both_windows_spent_after_the_build_park_it_for_its_review(self):
        self.assertEqual(self.ran.code, 1, self.ran.out + self.ran.err)
        self.assertEqual((self.parked["state"], self.parked["executor"]), ("exhausted", "opus"))

    def test_while_both_are_spent_it_waits_for_a_provider_window(self):
        self.assertEqual(self.spent.code, 0, self.spent.err)
        self.assertIn("waiting for a provider window", self.spent.out)

    def test_once_opus_s_window_resets_it_still_does(self):
        self.assertEqual(self.refilled.code, 0, self.refilled.err)
        self.assertIn("waiting for a provider window", self.refilled.out)


if __name__ == "__main__":
    unittest.main()
