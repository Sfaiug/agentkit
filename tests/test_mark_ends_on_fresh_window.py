"""A refusal's mark ends when its provider's window starts again with room.

Fake meters in a temporary HOME: nothing here reaches a real usage endpoint
or a real credential.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
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

    def two_accounts(self):
        self.cfg["providers"]["alpha"]["accounts"] = ["first", "second"]
        self.set_meters("alpha", self.old_window(), account="first")
        self.set_meters("alpha", self.old_window(), account="second")
        self.set_meters("beta", self.old_window(used=10))

    def stored_account(self, account):
        stored = json.loads((config.STATE / "usage.json").read_text())
        return stored["providers"]["alpha"]["accounts"][account]

    def mark_first_while_reading(self, stale):
        """What a read returns when `first` refuses a worker while it is still asking `second`.

        That worker's process marks `first`; its own read finds the snapshot fresh, so it asks
        no adapter.  `stale`: the read is of a whole stale snapshot, else of a fresh one whose
        `first` session meter rolled over.
        """
        self.two_accounts()
        self.set_meters("alpha", [{"name": "session", "used": 40, "resets_at": NOW + 100,
                                   "window_secs": usage.SESSION_SECS}, *self.old_window()],
                        account="first")
        until = NOW + 5 * 86400
        refused = []

        def probe(cfg, provider, now, account=None):
            if account == "second" and self.now > NOW and not refused:
                cache = config.STATE / "usage.json"
                with patch.object(usage, "collect", side_effect=lambda cfg: usage.Readings(
                        json.loads(cache.read_text())["providers"])):
                    refused.append(usage.mark_exhausted(self.cfg, "alpha", until,
                                                        account="first"))
            return self.fake_probe(cfg, provider, now, account)

        self.stack.enter_context(patch.object(usage, "_probe", side_effect=probe))
        self.assertEqual(usage.collect(self.cfg)["alpha"]["account"], "first")
        self.now = NOW + usage.PROBE_EVERY + 41
        self.set_meters("alpha", self.old_window(), account="first")
        if stale:
            self.stale_cache()
        read = usage.collect(self.cfg)
        self.assertEqual(refused, [until])
        return read, until

    def test_an_account_marked_during_its_rollover_read_stays_marked(self):
        _, until = self.mark_first_while_reading(stale=False)
        providers = usage.collect(self.cfg)
        self.assertEqual(providers["alpha"]["accounts"]["first"]["exhausted_until"], until)
        self.assertTrue(providers["alpha"]["accounts"]["first"]["exhausted"])
        self.assertEqual(self.stored_account("first")["exhausted_until"], until)
        self.assertEqual(usage.account(self.cfg, "alpha"), ("second", True))

    def test_a_read_returns_an_account_mark_made_during_it_as_written(self):
        marks = ("exhausted_until", "exhausted_at", "exhausted_ends")
        for stale in (False, True):
            with self.subTest(stale=stale):
                shutil.rmtree(config.STATE)
                config.ensure_dirs()
                self.now = NOW
                read, until = self.mark_first_while_reading(stale)
                first = read["alpha"]["accounts"]["first"]
                self.assertEqual(first.get("exhausted_until"), until)
                self.assertEqual({key: first.get(key) for key in marks},
                                 {key: self.stored_account("first").get(key) for key in marks})
                self.assertTrue(first["exhausted"])
                # ... so the read itself sends the next turn to the other subscription
                self.assertEqual(read["alpha"]["account"], "second")
                self.assertFalse(read["alpha"]["exhausted"])

    def test_a_mark_made_between_a_probes_read_and_its_clock_survives_its_write(self):
        self.two_accounts()
        until = NOW + 5 * 86400
        real, marked = usage._cached_provider, []

        def cached(provider, account=None):
            record = real(provider, account)
            if account == "first" and self.now > NOW and not marked:
                # `first` refuses a worker just after its own probe read the snapshot, and the
                # probe reads the clock a moment after that
                marked.append(usage.mark_exhausted(self.cfg, "alpha", until, account="first"))
                self.now += 1
            return record

        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            usage.collect(self.cfg)
            self.now = NOW + usage.PROBE_EVERY + 1
            with patch.object(usage, "_cached_provider", side_effect=cached):
                usage._probe_gently(self.cfg, "alpha", "first")
            self.assertEqual(marked, [until])
            self.assertEqual(self.stored_account("first").get("exhausted_until"), until)
            self.assertEqual(usage.account(self.cfg, "alpha"), ("second", True))

    def test_a_mark_written_while_the_snapshot_is_replaced_survives_it(self):
        self.two_accounts()
        until = NOW + 5 * 86400
        cache, marked = config.STATE / "usage.json", []
        marker = threading.Thread(target=lambda: marked.append(
            usage.mark_exhausted(self.cfg, "alpha", until, account="first")))
        real = Path.replace

        def replace(path, target):
            if target == cache and marker.ident is None:
                # `first` refuses a worker just as probing `second` replaces the snapshot:
                # that worker's process writes its mark now, or as soon as it may
                marker.start()
                marker.join(1)
            return real(path, target)

        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            usage.collect(self.cfg)
            self.now = NOW + usage.PROBE_EVERY + 1
            with patch.object(Path, "replace", replace):
                usage._probe_gently(self.cfg, "alpha", "second")
                marker.join()
            self.assertEqual(marked, [until])
            self.assertEqual(self.stored_account("first").get("exhausted_until"), until)
            self.assertEqual(usage.account(self.cfg, "alpha"), ("second", True))

    def test_a_credit_spent_after_a_mark_made_during_its_read_lifts_it(self):
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "fake.toml").write_text("[usage]\nreset = true\n")
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.set_meters("alpha", self.old_window())
        self.set_meters("beta", self.old_window(used=10))
        marked = []

        def probe(cfg, provider, now, account=None):
            if provider == "alpha" and self.now > NOW and not marked:
                # alpha refuses another worker while the refused one's replenish is asking it
                cache = config.STATE / "usage.json"
                with patch.object(usage, "collect", side_effect=lambda cfg: usage.Readings(
                        json.loads(cache.read_text())["providers"])):
                    marked.append(usage.mark_exhausted(self.cfg, "alpha", NOW + 5 * 86400))
            return {**self.fake_probe(cfg, provider, now, account), "resets": 1.0}

        with patch.object(usage, "_probe", side_effect=probe), \
                patch.object(usage, "_adapter_json", side_effect=lambda harness, verb, *_a, **_kw:
                             {"code": "reset", "available": 0} if verb == "reset" else None):
            usage.collect(self.cfg)
            self.now = NOW + usage.PROBE_EVERY + 1
            self.assertEqual(usage.replenish(self.cfg, "alpha"), (True, 0.0))
            self.assertEqual(marked, [NOW + 5 * 86400])
            providers = usage.collect(self.cfg)
            self.assertNotIn("exhausted_until", providers["alpha"])
            self.assertFalse(providers["alpha"]["exhausted"])

    def reset_adapter(self, **said):
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "fake.toml").write_text("[usage]\nreset = true\n")
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.stack.enter_context(patch.object(
            usage, "_adapter_json", side_effect=lambda harness, verb, *_a, **_kw:
            {"code": "reset", "available": 0, **said} if verb == "reset" else None))

    def while_writing(self, asked, other):
        """Probe `asked`, and run `other` as another process would the moment that probe's
        write reads the snapshot it starts from: at once where nothing stops it, else as soon
        as it may."""
        cache, answered, real = config.STATE / "usage.json", [], Path.read_text
        writer = threading.Thread(target=other)

        def probe(cfg, provider, now, account=None):
            answered.append((provider, account))
            return {**self.fake_probe(cfg, provider, now, account), "resets": 1.0}

        def read_text(path, *a, **kw):
            try:
                return real(path, *a, **kw)
            finally:
                if (path == cache and asked in answered and writer.ident is None
                        and threading.current_thread() is threading.main_thread()):
                    writer.start()
                    writer.join(1)

        with patch.object(usage, "_probe", side_effect=probe):
            with patch.object(Path, "read_text", read_text):
                usage._probe_gently(self.cfg, *asked)
                writer.join()
            self.assertIn(asked, answered)

    def test_a_write_begun_before_a_credit_never_brings_back_the_mark_it_lifted(self):
        self.reset_adapter()
        self.set_meters("alpha", self.old_window())
        self.set_meters("beta", self.old_window(used=10))
        until, spent = NOW + 5 * 86400, []
        with patch.object(usage, "_probe", side_effect=lambda *a, **kw: {
                **self.fake_probe(*a, **kw), "resets": 1.0}):
            usage.collect(self.cfg)
            usage.mark_exhausted(self.cfg, "alpha", until)
        self.now += usage.PROBE_EVERY + 1
        # beta's probe writes a snapshot it read before alpha's refused worker spent a credit
        self.while_writing(("beta", None),
                           lambda: spent.append(usage.replenish(self.cfg, "alpha")))
        self.assertEqual(spent, [(True, 0.0)])
        stored = json.loads((config.STATE / "usage.json").read_text())["providers"]["alpha"]
        self.assertNotIn("exhausted_until", stored)
        providers = usage.collect(self.cfg)
        self.assertFalse(providers["alpha"]["exhausted"])
        self.assertIn("one", usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True))

    def test_records_written_while_a_probe_writes_keep_their_marks(self):
        self.two_accounts()
        until, cache = NOW + 5 * 86400, config.STATE / "usage.json"

        def others():
            # `first` and beta are read and then refuse a worker each, all in other processes
            usage._probe_gently(self.cfg, "alpha", "first")
            usage._probe_gently(self.cfg, "beta")
            with patch.object(usage, "collect", side_effect=lambda cfg: usage.Readings(
                    json.loads(cache.read_text())["providers"])):
                usage.mark_exhausted(self.cfg, "alpha", until, account="first")
                usage.mark_exhausted(self.cfg, "beta", until)

        # No snapshot yet: `second`'s probe starts its write from nothing
        self.while_writing(("alpha", "second"), others)
        stored = json.loads(cache.read_text())["providers"]
        self.assertEqual(stored["alpha"]["accounts"].get("first", {}).get("exhausted_until"), until)
        self.assertEqual(stored.get("beta", {}).get("exhausted_until"), until)
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            providers = usage.collect(self.cfg)
            self.assertTrue(providers["beta"]["exhausted"])
            self.assertEqual(usage.account(self.cfg, "alpha"), ("second", True))

    def test_a_credit_spent_on_an_account_refills_that_accounts_reading(self):
        self.reset_adapter(weekly_used=0, resets_at=NOW + WEEK)
        self.two_accounts()
        for account in ("first", "second"):
            self.set_meters("alpha", self.old_window(used=100), account=account)
        with patch.object(usage, "_probe", side_effect=lambda *a, **kw: {
                **self.fake_probe(*a, **kw), "resets": 1.0}):
            # Both spent: the credit goes to `first`, the account a turn would run on next.
            self.assertEqual(usage.replenish(self.cfg, "alpha"), (True, 0.0))
            providers = usage.collect(self.cfg)
        first = providers["alpha"]["accounts"]["first"]
        self.assertEqual([meter["used"] for meter in first["meters"]], [0])
        self.assertEqual(first["resets"], 0)
        self.assertFalse(first["exhausted"])
        self.assertTrue(providers["alpha"]["accounts"]["second"]["exhausted"])
        self.assertFalse(providers["alpha"]["exhausted"])
        self.assertIn("one", usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True))

    def test_a_mark_written_with_its_deadline_alone_survives_later_writes(self):
        # Marks written before `exhausted_at` existed hold the deadline alone.
        self.two_accounts()
        until = NOW + 5 * 86400
        cache = config.STATE / "usage.json"
        with patch.object(usage, "_probe", side_effect=self.fake_probe):
            usage.collect(self.cfg)
            usage.mark_exhausted(self.cfg, "alpha", until, account="first")
            usage.mark_exhausted(self.cfg, "beta", until)
            blob = json.loads(cache.read_text())
            for record in (blob["providers"]["alpha"]["accounts"]["first"],
                           blob["providers"]["beta"]):
                del record["exhausted_at"], record["exhausted_ends"]
            cache.write_text(json.dumps(blob))
            self.now = NOW + usage.PROBE_EVERY + 1
            usage._probe_gently(self.cfg, "alpha", "first")
            self.assertEqual(usage.replenish(self.cfg, "beta"), (False, 0.0))
            self.assertEqual(self.stored_account("first").get("exhausted_until"), until)
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["alpha"]["account"], "second")
            self.assertEqual(providers["beta"].get("exhausted_until"), until)
            self.assertTrue(providers["beta"]["exhausted"])

    def test_a_credit_spent_on_an_account_lifts_that_accounts_mark(self):
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "fake.toml").write_text("[usage]\nreset = true\n")
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        self.two_accounts()
        until = NOW + 5 * 86400
        with patch.object(usage, "_probe", side_effect=lambda *a, **kw: {
                    **self.fake_probe(*a, **kw), "resets": 1.0}), \
                patch.object(usage, "_adapter_json", side_effect=lambda harness, verb, *_a, **_kw:
                             {"code": "reset", "available": 0} if verb == "reset" else None):
            usage.collect(self.cfg)
            usage.mark_exhausted(self.cfg, "alpha", until, account="first")
            usage.mark_exhausted(self.cfg, "alpha", until, account="second")
            # Both refused: the credit goes to `first`, the account a turn would run on next.
            self.assertTrue(usage.replenish(self.cfg, "alpha")[0])
            accounts = usage.collect(self.cfg)["alpha"]["accounts"]
            self.assertNotIn("exhausted_until", accounts["first"])
            self.assertFalse(accounts["first"]["exhausted"])
            self.assertEqual(accounts["second"]["exhausted_until"], until)
            self.assertNotIn("exhausted_until", self.stored_account("first"))
            self.assertEqual(usage.account(self.cfg, "alpha"), ("first", True))


if __name__ == "__main__":
    unittest.main()
