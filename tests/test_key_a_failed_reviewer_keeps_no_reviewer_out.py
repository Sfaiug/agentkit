"""A reviewer that already failed this round keeps no other marked reviewer out of it.

The owner, 18 Nov 2026: "Reviewer and executor should come from different labs. I want this
to be the case if chosen models allow it."  And 22 Nov: "Own lab reviews when spent".
nova builds on claude; bolt on codex (another lab) and mist on claude (nova's lab, another
model id) are marked to review, every window with usage left, in a draw that puts bolt first.
bolt's reviewer turn answers twice without a verdict; mist then reviews in the same round and
the run ends PASS, reviewed by mist.  Black-box, staged as
tests/test_key_a_review_waits_for_another_provider.py stages it.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from test_key_writer_reviews_only_without_room import launched, meter, record, roles, staged

MODELS = {"nova": {"harness": "claude", "model": "claude-nova-2"},
          "mist": {"harness": "claude", "model": "claude-mist-2"},
          "bolt": {"harness": "codex", "model": "bolt-3"}}
# Puts bolt before mist in the reviewer draw (`usage.pick_order`).
DRAW = "20261125-0901"
NO_VERDICT = {"final": "No verdict yet."}


class SilentOtherLabReviewerGivesWay(unittest.TestCase):
    """bolt and mist review beside executor nova; bolt answers twice without a verdict."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, MODELS, ["bolt", "mist"], {"claude": week, "codex": week},
                      workers=("nova",), claude=["work", "pass"], codex=NO_VERDICT)
        cls.done = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                           env={"AK_PICK_DRAW": DRAW}, timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = record(cls.run_dir)

    def test_mist_reviews_in_the_same_round_and_the_run_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("nova", "bolt"))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer", "reviewer"])
        self.assertEqual([(run["role"], run["argv"][0]) for run in self.fakes["claude"].runs()],
                         [("executor", "claude-nova-2"), ("reviewer", "claude-mist-2")])
        self.assertEqual(len(self.state["round_summaries"]), 1)
        self.assertEqual((self.state["reviewer"], self.state["review"]["reviewer"]),
                         ("mist", "mist"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


if __name__ == "__main__":
    unittest.main()
