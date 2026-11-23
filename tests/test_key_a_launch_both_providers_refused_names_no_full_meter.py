"""A launch every provider has refused waits, and its reason claims no meter it never read full.

Opus builds and reviews, astra builds; both providers refused a turn within the hour and their
meters read 10% used.  `ak run` parks the run `exhausted` on a quota wait, its turns unspent,
and the reason it records says no worker can execute, not that a gate meter reads 100% used.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on
gitrig.py's checkout and fakeadapter.py's harnesses, the refusals held in the usage snapshot
ak keeps, whose endpoints refused an ask two minutes ago for an hour so none is asked again.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

STATE = ".agentkit/state"


class ALaunchBothProvidersRefusedNamesNoFullMeter(unittest.TestCase):
    def test_the_run_waits_saying_no_worker_can_execute(self):
        home = Home()
        self.addCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"], workers=["opus", "astra"], reviewers=["opus"])
        fakes = fakeadapter.install(home, claude="work", codex="work")
        now = time.time()
        week = {"name": "weekly", "used": 10, "window_secs": 604800,
                "resets_at": int(now) + 86400}
        for fake in fakes.values():
            fake.answer("usage", json.dumps({"meters": [week], "error": None}))
        models = akconfig.read(home)["models"]
        providers = {}
        for name in ("opus", "astra"):
            provider = models[name]["provider"]
            providers[provider] = {"provider": provider, "resets": 0, "probed_at": now - 120,
                                   "meters": [week], "exhausted_until": now + 3600}
            home.write(f"{STATE}/{provider}-probe.lock", repr(now - 120))
            home.write(f"{STATE}/{provider}-probe.retry", repr(now + 3600))
        home.write(f"{STATE}/usage.json", {"fetched_at": now - 120, "providers": providers})

        done = home.ak("run", str(taskfile.write(home, rig.path)))
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.assertEqual((state["state"], state.get("quota_dry")), ("exhausted", True),
                         done.out + done.err)
        self.assertNotIn("100%", state["error"])
        self.assertEqual([fake.n for fake in fakes.values()], [0, 0])


if __name__ == "__main__":
    unittest.main()
