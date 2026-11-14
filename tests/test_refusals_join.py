"""Each refusal on a login parks the models it can have been meant for until it ends itself.

Turns already running refuse one after another.  A refused Opus turn parks every model of the
login, and a Fable turn refused after it frees none of them; a refusal marked without a model
parks every model, whatever was marked before.  Each refusal ends at its own deadline or at a
fresh window on the meter that showed it, and neither ends another: Fable's refusals alone, or
Fable's and Nova's, leave Opus to its own meters.

Fake meters in a temporary HOME: nothing here reaches a real usage endpoint or a real
credential.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage

NOW = 1_800_000_000.0
WEEK = 604800

CONFIG = """
[models.opus]
harness = "fake"
model = "acme-opus-5-5"
effort = "high"
provider = "acme"

[models.fable]
harness = "fake"
model = "acme-fable-5-2"
effort = "high"
provider = "acme"

[models.nova]
harness = "fake"
model = "acme-nova-1"
effort = "high"
provider = "acme"

[providers.acme]
mode = "subscription"
"""


def week(name, used, **keys):
    return {"name": name, "used": used, "window_secs": WEEK, "resets_at": NOW + 3 * 86400, **keys}


class RefusalsJoin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-refusals-join-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root)}))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        self.now = NOW
        stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now))
        stack.enter_context(patch.object(usage, "_probe_gently",
                                         side_effect=AssertionError("the cache is fresh")))
        self.cfg = config.load()
        self.read(week("weekly_all", 60), week("weekly_scoped", 90, scope="Fable"),
                  week("weekly_nova", 10, scope="Nova"))

    def read(self, *meters):
        (config.STATE / "usage.json").write_text(json.dumps({
            "fetched_at": self.now, "providers": {"acme": {"resets": 0, "meters": list(meters)}}}))

    def reads(self, *meters):
        """The login's reading holding `meters` alone from now on, its marks as they stand."""
        cache = config.STATE / "usage.json"
        blob = json.loads(cache.read_text())
        blob["providers"]["acme"]["meters"] = list(meters)
        cache.write_text(json.dumps(blob))

    def refused(self, *models, until=NOW + 7200):
        for model in models:
            usage.mark_exhausted(self.cfg, "acme", until, model=model)

    def parked(self):
        """(the models parked, whether the login reads exhausted)."""
        providers = usage.collect(self.cfg)
        return (sorted(name for name in self.cfg["models"]
                       if usage.model_exhausted(self.cfg, name, providers)[0]),
                providers["acme"]["exhausted"])

    def test_a_fable_refusal_after_an_opus_one_frees_no_model(self):
        self.refused("opus", "fable")
        self.assertEqual(self.parked(), (["fable", "nova", "opus"], True))

    def test_a_refusal_marked_without_a_model_parks_every_model(self):
        self.refused("fable", None)
        self.assertEqual(self.parked(), (["fable", "nova", "opus"], True))

    def test_fable_refusals_alone_leave_the_others_their_own_meters(self):
        self.refused("fable", "fable")
        self.assertEqual(self.parked(), (["fable"], False))

    def test_refusals_of_two_private_caps_leave_opus_its_own_meters(self):
        self.refused("fable", "nova")
        self.assertEqual(self.parked(), (["fable", "nova"], False))

    def test_each_refusal_ends_at_its_own_deadline(self):
        self.refused("opus", until=NOW + 60)
        self.refused("fable")
        self.now = NOW + 120
        self.assertEqual(self.parked(), (["fable"], False))
        self.refused("opus")
        self.refused("fable", until=NOW + 180)
        self.now = NOW + 240
        self.assertEqual(self.parked(), (["fable", "nova", "opus"], True))

    def test_a_fresh_window_on_one_cap_ends_only_the_refusal_it_showed(self):
        self.read(week("weekly_all", 60), week("weekly_scoped", 100, scope="Fable"))
        self.refused("opus", "fable")
        self.now += 1
        usage.record_turn_meters(self.cfg, "acme", [
            week("weekly_scoped", 10, scope="Fable", resets_at=NOW + WEEK)], now=self.now)
        self.assertEqual(self.parked(), (["fable", "nova", "opus"], True))

    def test_a_refusal_naming_a_meter_gone_since_parks_every_model_beside_a_later_one(self):
        self.refused("fable")
        self.reads(week("weekly_scoped", 90, scope="Fable"))
        self.assertEqual(self.parked(), (["fable", "nova", "opus"], True))
        self.refused("fable")
        self.assertEqual(self.parked(), (["fable", "nova", "opus"], True))


if __name__ == "__main__":
    unittest.main()
