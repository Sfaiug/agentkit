"""A refusal no meter showed ends an hour after it was made.

Such a refusal names no time and no meter of its account reads 100%; the soonest window to
reset can be a week's, where no 5-hour window is reported.  A window with room did not refuse,
so its reset is no deadline: the account comes back after `DRY_FOR` and is refused again if it
truly has nothing.  A refusal a meter showed, or one that named its own time, keeps its
deadline.

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

NOW = 1000000.0
WEEK = 604800

CONFIG = """
[tiers]
A = ["one"]
B = ["one", "two"]

[models.one]
harness = "fake"
model = "m-one"
effort = "high"
provider = "alpha"

[models.two]
harness = "other"
model = "m-two"
effort = "high"
provider = "beta"

[providers.alpha]
mode = "subscription"

[providers.beta]
mode = "subscription"
"""


class UnshownRefusalEnds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-unshown-refusal-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        self.now = NOW
        stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now))
        stack.enter_context(patch.object(usage, "_probe", side_effect=self.fake_probe))
        self.cfg = config.load()
        self.week_ends = NOW + 3 * 86400
        self.meters = {"alpha": self.week(used=60), "beta": self.week(used=10)}

    def week(self, used):
        return [{"name": "weekly", "used": used, "resets_at": self.week_ends,
                 "window_secs": WEEK}]

    def fake_probe(self, cfg, provider, now, account=None):
        harness, via = config.provider_harness(cfg, provider)
        meters = [usage._normalized(dict(meter), now) for meter in self.meters[provider]]
        return {"provider": provider, "harness": harness, "via": via, "meters": meters,
                "error": None, "pace": None, "resets": 0.0, "exhausted": False,
                "probed_at": now}

    def read_at(self, when):
        """Everything `collect` answers at `when`, read afresh from the probe."""
        self.now = when
        cache = config.STATE / "usage.json"
        blob = json.loads(cache.read_text())
        blob["fetched_at"] = when - usage.CACHE_TTL - 1
        cache.write_text(json.dumps(blob))
        return usage.collect(self.cfg)

    def assert_parked(self, providers, parked):
        self.assertEqual(providers["alpha"]["exhausted"], parked)
        self.assertEqual(usage.model_exhausted(self.cfg, "one", providers)[0], parked)
        order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
        (self.assertNotIn if parked else self.assertIn)("one", order)

    def test_a_refusal_beside_a_week_with_room_ends_an_hour_on(self):
        self.assertEqual(usage.mark_exhausted(self.cfg, "alpha"), NOW + usage.DRY_FOR)
        providers = self.read_at(NOW + usage.DRY_FOR - 1)
        self.assert_parked(providers, True)
        self.assertEqual(providers["alpha"]["exhausted_until"], NOW + usage.DRY_FOR)
        providers = self.read_at(NOW + usage.DRY_FOR)
        self.assert_parked(providers, False)
        self.assertNotIn("exhausted_until", providers["alpha"])

    def test_a_refusal_a_meter_showed_keeps_its_deadline(self):
        self.meters["alpha"] = self.week(used=100)
        self.assertEqual(usage.mark_exhausted(self.cfg, "alpha"), self.week_ends)
        self.meters["alpha"] = self.week(used=99)
        providers = self.read_at(NOW + 2 * usage.DRY_FOR)
        self.assert_parked(providers, True)
        self.assertEqual(providers["alpha"]["exhausted_until"], self.week_ends)

    def test_a_deadline_the_refusal_named_is_kept(self):
        named = NOW + 2 * 86400
        usage.mark_exhausted(self.cfg, "alpha", until=named)
        providers = self.read_at(NOW + 2 * usage.DRY_FOR)
        self.assert_parked(providers, True)
        self.assertEqual(providers["alpha"]["exhausted_until"], named)


if __name__ == "__main__":
    unittest.main()
