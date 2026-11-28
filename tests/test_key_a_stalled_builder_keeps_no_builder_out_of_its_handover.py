"""A stalled builder keeps no other builder out of the tick's handover.

The owner, 18 Nov 2026: "same provider or model for both roles should still be allowed if only
picked, but if multiple picked then from different."; 22 Nov: "Own lab reviews when spent".
nova builds on claude and hangs; bolt on codex is marked to build too; dash, on codex and bolt's
provider under another model id, is alone marked to review, so it is of another lab than nova
and of bolt's; every window has usage left.  The pick of nova's handover reads the builders
without nova, so the tick that kills the loop resumes the run with a handover to bolt: bolt
builds, dash reviews, and the run passes.  Black-box, staged as tests/test_key_stall_ladder.py
stages a silent run and its ticks, in one box of its own (`rerun_boxed`).
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import BOXED, REAL_TMUX, Home, rerun_boxed
from fixtures.gitrig import Rig
from test_key_stall_ladder import hang, record, silent_for, tick, until


@unittest.skipUnless(REAL_TMUX and BOXED, "no tmux, or no bwrap able to box the test here")
class StalledBuilderHandsOver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, {"nova": "claude", "bolt": "codex", "dash": "codex"},
                       workers=["nova", "bolt"], reviewers=["dash"])
        turn, silent = hang(home)
        cls.fakes = fakeadapter.install(home, claude=turn, codex=["work", "pass"])
        week = {"name": "weekly", "used": 10, "resets_at": int(time.time()) + 86400,
                "window_secs": 604800}
        for fake in cls.fakes.values():
            fake.answer("usage", json.dumps({"meters": [week], "error": None}))
        loop = home.spawn("run", str(taskfile.write(home, rig.path)), "--no-merge")
        until("nova's first turn went silent", lambda: silent() == 1, running=loop)
        cls.run_dir = run_dir = taskfile.only_run(home)
        cls.addClassCleanup(home.ak, "run", "stop", run_dir.name)
        # each turn writes what it names: a box's copy of /run links to the host's own files
        (run_dir / "link").symlink_to(home.root / "adapters" / "entered")
        cls.launched = record(run_dir)
        silent_for(run_dir, 22)
        tick(home)
        until("nova's next turn went silent", lambda: silent() == 2)
        silent_for(run_dir, 22)
        tick(home)
        cls.resumed = record(run_dir)
        # on nova again, the resumed run hangs a third time
        until("the resumed run passed or hung",
              lambda: record(run_dir)["state"] == "pass" or silent() == 3, bound=300)
        cls.state = record(run_dir)

    def test_nova_builds_at_launch_and_dash_reviews(self):
        self.assertEqual((self.launched["executor"], self.launched["reviewer"]), ("nova", "dash"))

    def test_the_tick_that_kills_the_loop_resumes_the_run_with_a_handover_to_bolt(self):
        self.assertEqual([stall["action"] for stall in self.resumed["stalls"]],
                         ["killed step", "resumed with handover to bolt"])
        self.assertEqual([(move["from"], move["to"], move["reason"])
                          for move in self.resumed["executor_history"]],
                         [("nova", "bolt", "stalled")])

    def test_bolt_builds_dash_reviews_and_the_run_passes(self):
        self.assertEqual([run["role"] for run in self.fakes["codex"].runs()],
                         ["executor", "reviewer"])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("bolt", "dash"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
