"""A turn refused for usage parks the models that refusal can have been meant for.

A reading is up to fifteen minutes old, so the turn crossing a cap is usually refused before
any meter reads 100%.  A Fable turn refused so may have hit Fable's own cap, which does not gate
Opus: Opus is left to its own meters, even where its own cap shares that cap's name.  An Opus
turn's every gate is shared, so its refusal parks the whole login.

Black-box: the program `AK_BIN` names runs a task in a temporary HOME over one Claude login whose
injected reading holds the shared week and a weekly cap scoped to Fable, two workers naming no
`meter`, and a scripted harness refusing the turn for usage; no real login or meter is reached.
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

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"


def refused(case, model, *meters):
    """`ak usage --json` after a turn of `model` is refused for usage, beside `meters`."""
    with Home() as home:
        rig = Rig(home)
        akconfig.write(home, {OPUS: "claude", FABLE: "claude"})
        assert not any("meter" in entry for entry in akconfig.read(home)["models"].values())
        home.fake("claude", "#!/bin/sh\nexit 0\n")
        fake = fakeadapter.install(home, claude="dead")["claude"]
        now = time.time()
        week = {"used": 60, "window_secs": 604800, "resets_at": now + 3 * 86400}
        reading = {"provider": "anthropic", "resets": 0, "meters": [
            {"name": "weekly_all", **week},
            {"name": "weekly_scoped", **week, "used": 90, "scope": "Fable"},
            *({"name": name, **week, "used": used, "scope": scope} for name, used, scope in meters)]}
        fake.answer("usage", json.dumps(reading))      # a probe reads the same
        home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": reading}})
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--exec", model,
                       timeout=300)
        case.assertEqual(done.code, 1, done.out + done.err)
        case.assertEqual([call["step"] for call in fake.runs()], ["dead"])
        state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        case.assertEqual((state["state"], state["executor"]), ("exhausted", model))
        read = home.ak("usage", "--json")
        case.assertEqual(read.code, 0, read.out + read.err)
        blob = json.loads(read.out)
        return blob["pick_order"], blob["providers"]["anthropic"]["exhausted"]


class RefusalParksItsModels(unittest.TestCase):
    def test_a_refused_fable_turn_leaves_opus_its_own_meters(self):
        self.assertEqual(refused(self, FABLE), ([OPUS], False))

    def test_a_refused_fable_turn_leaves_opus_its_own_cap_of_the_same_name(self):
        self.assertEqual(refused(self, FABLE, ("weekly_scoped", 30, "Opus")), ([OPUS], False))

    def test_a_refused_opus_turn_parks_the_whole_login(self):
        self.assertEqual(refused(self, OPUS), ([], True))


if __name__ == "__main__":
    unittest.main()
