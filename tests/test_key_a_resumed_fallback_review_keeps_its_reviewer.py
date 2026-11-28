"""A review resumed in its round keeps the reviewer that took it over from one that failed it.

nova builds on claude; bolt on codex (another lab) and mist on claude (nova's lab) are marked to
review, every window with usage left, in a draw that puts bolt first.  bolt answers twice without
a verdict, so mist reviews in the same round
(tests/test_key_a_failed_reviewer_keeps_no_reviewer_out.py); the run is killed while mist is at
work.  `ak run resume ID` goes on with mist's review on mist's own conversation, though bolt, of
another lab, has room: bolt is not asked again this round, and the run ends PASS, reviewed by
mist.  Black-box, staged as that test stages it.
"""

import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from test_key_a_failed_reviewer_keeps_no_reviewer_out import DRAW, MODELS, NO_VERDICT
from test_key_writer_reviews_only_without_room import meter, record, roles, staged


class ResumedFallbackReview(unittest.TestCase):
    """bolt fails the round's review; mist's review of it is cut off, then resumed."""

    @classmethod
    def setUpClass(cls):
        week = [meter(10, time.time() + 86400)]
        home = staged(cls, MODELS, ["bolt", "mist"], {"claude": week, "codex": week},
                      workers=("nova",), claude="work", codex=NO_VERDICT)
        reviewing = home.root / "adapters" / "reviewing"
        # mist's review only says it began and waits there, as a turn does when its run dies
        # under it; bounded, so nothing outlives the test if a build left it orphaned
        cls.fakes["claude"].behave("work", {"sh": f"touch {reviewing}; sleep 60"}, "pass")
        env = {"AK_PICK_DRAW": DRAW}
        proc = home.spawn("run", str(taskfile.write(home, cls.rig.path)), "--no-merge", env=env)
        deadline = time.monotonic() + 120
        while not reviewing.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("the run never reached mist's review: "
                                     + home.log("spawn-1.err").read_text())
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        cls.run_dir = taskfile.only_run(home)
        cls.done = home.ak("run", "resume", cls.run_dir.name, env=env, timeout=300)
        cls.state = record(cls.run_dir)

    def test_mists_review_goes_on_on_its_own_conversation_and_passes(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer", "reviewer"])
        claude = self.fakes["claude"].runs()
        self.assertEqual([(run["role"], run["argv"][0]) for run in claude],
                         [("executor", "claude-nova-2"), ("reviewer", "claude-mist-2")])
        self.assertEqual(claude[-1]["argv"][5:], ["sid-claude-2"])
        self.assertEqual([entry["round"] for entry in self.state["round_summaries"]], [1])
        self.assertEqual((self.state["reviewer"], self.state["review"]["reviewer"]),
                         ("mist", "mist"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


if __name__ == "__main__":
    unittest.main()
