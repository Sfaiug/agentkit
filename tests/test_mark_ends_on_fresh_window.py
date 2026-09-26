"""A refusal's mark ends when its provider's window starts again with room.

Fake meters in a temporary HOME: nothing here reaches a real usage endpoint
or a real credential.
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

    def set_meters(self, provider, meters, account=None):
        self.probe_meters[provider, account] = meters

    def fake_probe(self, cfg, provider, now, account=None):
        harness, via = config.provider_harness(cfg, provider)
        meters = [usage._normalized(dict(meter), now)
                  for meter in self.probe_meters.get((provider, account), [])]
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

    def test_unchanged_reset_on_a_nominal_month_keeps_the_mark(self):
        # A calendar-month plan on a nominal 30 days: the reset a month out implies
        # a start a day from now, after the mark, although no window restarted.
        self.set_meters("alpha", [{"name": "plan", "used": 40,
                                   "resets_at": NOW + 31 * 86400, "window_secs": 30 * 86400}])
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            until = NOW + 5 * 86400
            usage.mark_exhausted(self.cfg, "alpha", until)
            self.assertEqual(usage.collect(self.cfg)["alpha"]["exhausted_ends"],
                             {"plan": NOW + 31 * 86400})
            self.now += usage.PROBE_EVERY + 1
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["alpha"]["exhausted_until"], until)
            self.assertTrue(providers["alpha"]["exhausted"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertNotIn("one", order)
            # Past the implied start, with the meter itself unchanged and the
            # deadline still pending: the same window, still parked.
            self.now = NOW + 86401
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["alpha"]["exhausted_until"], until)
            self.assertTrue(providers["alpha"]["exhausted"])
            order = usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True)
            self.assertNotIn("one", order)

    def test_later_reset_needs_no_window_length_or_inferred_start(self):
        self.set_meters("alpha", self.old_window())
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            usage.mark_exhausted(self.cfg, "alpha", NOW + 5 * 86400)
            cache = config.STATE / "usage.json"
            marked = json.loads(cache.read_text())
            self.now += usage.PROBE_EVERY + 1
            # No length, an implied start before the mark, and a nominal month
            # implying a start still in the future all describe a later reset.
            for window, end in ((None, self.now + WEEK), (2 * WEEK, self.now + WEEK),
                                (30 * 86400, self.now + 31 * 86400)):
                for cached in (False, True):
                    with self.subTest(window=window, cached=cached):
                        meter = {"name": "weekly", "used": 0, "resets_at": end}
                        if window is not None:
                            meter["window_secs"] = window
                        self.set_meters("alpha", [meter])
                        blob = json.loads(json.dumps(marked))
                        if cached:
                            blob["providers"]["alpha"]["meters"] = [
                                usage._normalized(meter, self.now)]
                        else:
                            blob["fetched_at"] = self.now - usage.CACHE_TTL - 1
                            (config.STATE / "alpha-probe.lock").unlink(missing_ok=True)
                        cache.write_text(json.dumps(blob))
                        if cached:
                            # Picks can also receive a snapshot before collect has
                            # re-derived its flags, so they must agree with the table.
                            self.assertIn("one", usage.pick_order(
                                self.cfg, blob["providers"], ["one", "two"], quiet=True))
                        providers = usage.collect(self.cfg)
                        self.assertFalse(providers["alpha"]["exhausted"])
                        for key in ("exhausted_until", "exhausted_at", "exhausted_ends"):
                            self.assertNotIn(key, providers["alpha"])
                        self.assertNotEqual(usage.outlook(providers["alpha"]), "exhausted")
                        self.assertIn("one", usage.pick_order(
                            self.cfg, providers, ["one", "two"], quiet=True))

    def test_no_recorded_reset_keeps_the_mark_until_its_deadline(self):
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            for meters in ([], [{"name": "weekly", "used": 80, "window_secs": WEEK}]):
                with self.subTest(meters=meters):
                    self.now += usage.CACHE_TTL + 1
                    self.set_meters("alpha", meters)
                    until = self.now + 3 * 3600
                    usage.mark_exhausted(self.cfg, "alpha", until)
                    self.assertEqual(usage.collect(self.cfg)["alpha"]["exhausted_ends"], {})
                    self.now += usage.PROBE_EVERY + 1
                    self.set_meters("alpha", [{"name": "weekly", "used": 0,
                                               "resets_at": self.now + WEEK,
                                               "window_secs": WEEK}])
                    self.stale_cache()
                    providers = usage.collect(self.cfg)
                    self.assertEqual(providers["alpha"]["exhausted_until"], until)
                    self.assertTrue(providers["alpha"]["exhausted"])
                    self.assertNotIn("one", usage.pick_order(
                        self.cfg, providers, ["one", "two"], quiet=True))
                    self.now = until
                    self.stale_cache()
                    providers = usage.collect(self.cfg)
                    self.assertNotIn("exhausted_until", providers["alpha"])
                    self.assertIn("one", usage.pick_order(
                        self.cfg, providers, ["one", "two"], quiet=True))

    def test_a_fresh_account_window_leaves_the_other_accounts_mark_intact(self):
        self.cfg["providers"]["alpha"]["accounts"] = ["first", "second"]
        self.set_meters("alpha", self.old_window(), account="first")
        self.set_meters("alpha", [{"name": "weekly", "used": 10,
                                   "resets_at": NOW + WEEK / 4, "window_secs": WEEK}],
                        account="second")
        self.set_meters("beta", self.old_window(used=10))
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            until = NOW + 5 * 86400
            usage.mark_exhausted(self.cfg, "alpha", until, account="first")
            self.assertEqual(usage.account(self.cfg, "alpha"), ("second", True))
            usage.mark_exhausted(self.cfg, "alpha", until, account="second")
            providers = usage.collect(self.cfg)
            accounts = providers["alpha"]["accounts"]
            self.assertEqual(accounts["first"]["exhausted_ends"], {"weekly": NOW + WEEK / 2})
            self.assertEqual(accounts["second"]["exhausted_ends"], {"weekly": NOW + WEEK / 4})
            self.assertNotIn("one", usage.pick_order(
                self.cfg, providers, ["one", "two"], quiet=True))

            self.now += usage.PROBE_EVERY + 1
            self.set_meters("alpha", [{"name": "weekly", "used": 0,
                                       "resets_at": self.now + WEEK, "window_secs": WEEK}],
                            account="first")
            self.stale_cache()
            providers = usage.collect(self.cfg)
            self.assertFalse(providers["alpha"]["exhausted"])
            self.assertIn("one", usage.pick_order(
                self.cfg, providers, ["one", "two"], quiet=True))
            stored = json.loads((config.STATE / "usage.json").read_text())
            accounts = stored["providers"]["alpha"]["accounts"]
            self.assertNotIn("exhausted_until", accounts["first"])
            self.assertEqual(accounts["second"]["exhausted_until"], until)
            self.assertTrue(accounts["second"]["exhausted"])
            self.assertEqual(usage.account(self.cfg, "alpha"), ("first", True))


if __name__ == "__main__":
    unittest.main()
