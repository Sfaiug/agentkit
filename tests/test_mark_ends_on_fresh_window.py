"""A refusal's mark ends when its provider's window starts again with room.

Fake meters in a temporary HOME: the probe answers out of files this test
writes, so nothing here reaches a real usage endpoint or a real credential.
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


class FreshWindowEndsMark(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".mark-fresh-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        self.now = NOW
        self.stack.enter_context(
            patch.object(usage.time, "time", side_effect=lambda: self.now))
        self.cfg = config.load()
        self.probe_meters = {}

    # --- the fixture ------------------------------------------------------

    def set_meters(self, provider, meters):
        self.probe_meters[provider] = meters

    def fake_probe(self, cfg, provider, now):
        harness, via = config.provider_harness(cfg, provider)
        meters = [usage._normalized(dict(meter), now)
                  for meter in self.probe_meters.get(provider, [])]
        pace = None
        for meter in meters:
            value = meter.get("pace")
            if value is not None:
                pace = value if pace is None else max(pace, value)
        return {"provider": provider, "harness": harness, "via": via, "meters": meters,
                "error": None, "pace": pace, "resets": 0.0, "exhausted": False,
                "probed_at": now}

    def stale_cache(self):
        cache = config.STATE / "usage.json"
        blob = json.loads(cache.read_text())
        blob["fetched_at"] = self.now - usage.CACHE_TTL - 1
        cache.write_text(json.dumps(blob))

    def old_window(self, used=80):
        """The window the refusal was made in: begun well before the mark."""
        return [{"name": "weekly", "used": used, "resets_at": NOW + WEEK / 2,
                 "window_secs": WEEK}]

    # --- the mark ---------------------------------------------------------

    def test_fresh_window_with_room_ends_the_mark_and_picks_the_provider(self):
        self.set_meters("alpha", self.old_window())
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            until = NOW + 5 * 86400
            self.assertEqual(usage.mark_exhausted(self.cfg, "alpha", until), until)
            providers = usage.collect(self.cfg)
            self.assertTrue(providers["alpha"]["exhausted"])
            self.assertEqual(providers["alpha"]["exhausted_at"], NOW)
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertNotIn("one", order)
            # The weekly window starts again after the mark, with room: the mark is gone.
            self.now += usage.PROBE_EVERY + 1
            self.set_meters("alpha", [{"name": "weekly", "used": 0,
                                       "resets_at": self.now + WEEK, "window_secs": WEEK}])
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertNotIn("exhausted_until", providers["alpha"])
            self.assertFalse(providers["alpha"]["exhausted"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertIn("one", order)
            stored = json.loads((config.STATE / "usage.json").read_text())
            self.assertNotIn("exhausted_until", stored["providers"]["alpha"])

    def test_no_newer_window_keeps_the_provider_parked_until_the_deadline(self):
        self.set_meters("alpha", self.old_window())
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            until = NOW + 3 * 3600
            usage.mark_exhausted(self.cfg, "alpha", until)
            # The same window, still with room but begun before the mark: parked.
            self.now += usage.PROBE_EVERY + 1
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["alpha"]["exhausted_until"], until)
            self.assertTrue(providers["alpha"]["exhausted"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertNotIn("one", order)
            # Past the deadline the probe decides again, as today.
            self.now = until + 1
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertNotIn("exhausted_until", providers["alpha"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertIn("one", order)

    def test_spent_replacement_window_keeps_the_mark(self):
        self.set_meters("alpha", self.old_window())
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            until = NOW + 5 * 86400
            usage.mark_exhausted(self.cfg, "alpha", until)
            # A window begun after the mark but itself spent is no capacity.
            self.now += usage.PROBE_EVERY + 1
            self.set_meters("alpha", [{"name": "weekly", "used": 100,
                                       "resets_at": self.now + WEEK, "window_secs": WEEK}])
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["alpha"]["exhausted_until"], until)
            self.assertTrue(providers["alpha"]["exhausted"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertNotIn("one", order)

    def test_window_whose_start_is_still_in_the_future_keeps_the_mark(self):
        # A calendar-month plan on a nominal 30 days: the reset a month out implies
        # a start a day from now, after the mark, although no window restarted.
        self.set_meters("alpha", [{"name": "plan", "used": 40,
                                   "resets_at": NOW + 31 * 86400, "window_secs": 30 * 86400}])
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            until = NOW + 5 * 86400
            usage.mark_exhausted(self.cfg, "alpha", until)
            self.now += usage.PROBE_EVERY + 1
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["alpha"]["exhausted_until"], until)
            self.assertTrue(providers["alpha"]["exhausted"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertNotIn("one", order)


if __name__ == "__main__":
    unittest.main()
