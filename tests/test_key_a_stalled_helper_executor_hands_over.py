"""A stalled executor turn on a helper machine hands over to a marked spare on the second stall.

nova builds on claude and hangs; bolt on codex builds too; dash on codex alone reviews, so nova is
picked at launch.  After the first stall is killed locally, turns move to the helper machine
(tests/fixtures/akmachine.py, `turns_on_machines = true` and a crowded host), where nova's next
turn runs in docker and hangs again.  The second stall tick must recognise the helper turn as
`worker: nova`, not a done-when gate, and hand over to bolt so bolt builds, dash reviews and the
run passes.  Black-box, in one box of its own (`rerun_boxed`).
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, akmachine, fakeadapter, taskfile
from fixtures.akbin import BOXED, REAL_TMUX, Home, rerun_boxed
from fixtures.gitrig import Rig
from test_key_stall_ladder import record, silent_for, tick, until


@unittest.skipUnless(REAL_TMUX and BOXED, "no tmux, or no bwrap able to box the test here")
class StalledHelperExecutorHandsOver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets", files={
            "tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        models = {"nova": "claude", "bolt": "codex", "dash": "codex"}
        settings = {"suite_helper": "acme-linux", "turns_on_machines": False}
        akconfig.write(home, models, workers=["nova", "bolt"], reviewers=["dash"],
                       settings=settings)
        cls.machine = machine = akmachine.install(home, cpus=4)
        for harness, version in (("claude", "1.2.3"), ("codex", "4.5.6")):
            home.fake(harness, f"#!/bin/sh\necho {version}\n")
            place = machine / "home/.agentkit-helper/harness" / harness / version
            place.mkdir(parents=True)
            (place / harness).touch(0o755)
        entered = home.root / "adapters" / "entered"
        places = lambda: entered.read_text().splitlines() if entered.exists() else []
        # Empty session: a resume of a session whose file is absent stays local (machine_turn.call).
        turn = {"sh": f'echo "${{container:-here}}" >>"{entered}"; exec sleep 600', "session": ""}
        cls.fakes = fakeadapter.install(home, claude=turn, codex=["work", "pass"])
        week = {"name": "weekly", "used": 10, "resets_at": int(time.time()) + 86400,
                "window_secs": 604800}
        for fake in cls.fakes.values():
            fake.answer("usage", json.dumps({"meters": [week], "error": None}))
        loop = home.spawn("run", str(taskfile.write(home, rig.path)), "--no-merge",
                          env={"AK_HOST_READINGS": akmachine.CROWDED})
        until("nova's first turn went silent", lambda: len(places()) == 1, running=loop)
        cls.run_dir = run_dir = taskfile.only_run(home)
        cls.addClassCleanup(home.ak, "run", "stop", run_dir.name)
        cls.launched = record(run_dir)
        akconfig.write(home, models, workers=["nova", "bolt"], reviewers=["dash"],
                       settings={**settings, "turns_on_machines": True})
        silent_for(run_dir, 22)
        tick(home)
        until("nova's second turn went silent on the helper", lambda: len(places()) == 2)
        cls.places = places()
        silent_for(run_dir, 22)
        tick(home)
        cls.resumed = record(run_dir)
        until("the resumed run passed or hung",
              lambda: record(run_dir)["state"] == "pass" or len(places()) == 3, bound=300)
        cls.state = record(run_dir)

    def test_nova_stalled_on_the_helper_machine(self):
        self.assertEqual((self.launched["executor"], self.launched["reviewer"]), ("nova", "dash"))
        self.assertEqual(self.places, ["here", "docker"])
        self.assertTrue([*self.machine.glob("docker/roots/*-turn")])

    def test_the_second_stall_classifies_the_helper_turn_as_worker_and_hands_over_to_bolt(self):
        self.assertEqual([(stall["step"], stall["action"]) for stall in self.resumed["stalls"]],
                         [("worker: nova", "killed step"),
                          ("worker: nova", "resumed with handover to bolt")])
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
