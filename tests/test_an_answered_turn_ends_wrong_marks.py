"""A turn answered on a login ends the refusals parked there that no meter showed, made before
the turn began, whose every meter gates the turn's model; every other mark stays.

Fake meters in a temporary HOME: nothing here reaches a real usage endpoint or a real
credential.  Provider names are invented.
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
sys.path.insert(0, str(REPO / "tests"))
from agentkit import config, usage  # noqa: E402
from fixtures.clock import Clock  # noqa: E402

NOW = 1_800_000_000.0
WEEK = 604800

ONE = """
[models.one]
harness = "fake"
model = "m-one"
effort = "high"
provider = "acme"
"""

CONFIG = ONE + """
[models.two]
harness = "fake"
model = "m-two"
effort = "high"
provider = "acme"
meter = "weekly_two"

[models.three]
harness = "fake"
model = "m-three"
effort = "high"
provider = "beta"

[providers.acme]
mode = "subscription"
accounts = ["default", "second"]

[providers.beta]
mode = "subscription"
"""


class AnsweredTurnEndsWrongMarks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-answered-", dir=REPO)
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
        clock = Clock(None)
        clock.time = lambda: self.now
        stack.enter_context(patch.object(usage, "time", clock))
        stack.enter_context(patch.object(usage, "_probe", side_effect=self.fake_probe))
        self.cfg = config.load()
        room = self.week("weekly_all", "weekly_two")
        self.meters = {("acme", "default"): room, ("acme", "second"): room, ("beta", None): room}

    def week(self, *names, used=20):
        return [{"name": name, "used": used, "resets_at": NOW + WEEK / 2, "window_secs": WEEK}
                for name in names]

    def fake_probe(self, cfg, provider, now, account=None):
        harness, via = config.provider_harness(cfg, provider)
        meters = [usage._normalized(dict(m), now) for m in self.meters[provider, account]]
        return {"provider": provider, "harness": harness, "via": via, "meters": meters,
                "error": None, "pace": None, "resets": 0.0, "exhausted": False,
                "probed_at": now}

    def refuse(self, account, model, at):
        """That login of acme refuses a turn of `model` at `at`, naming no time."""
        self.now = at
        usage.mark_exhausted(self.cfg, "acme", account=account, model=model)

    def stored(self):
        return json.loads((config.STATE / "usage.json").read_text())["providers"]

    def login(self, account):
        return self.stored()["acme"]["accounts"][account]

    def made(self, record):
        return [mark["exhausted_at"] for mark in usage._marks(record)]

    def test_a_turn_begun_after_an_unshown_refusal_ends_it_on_that_login_alone(self):
        self.refuse("default", "one", NOW)
        self.refuse("second", "one", NOW + 10)
        first = self.login("default")
        self.assertTrue(usage.answered(self.cfg, "acme", "second", "one", NOW + 20))
        self.assertEqual(self.made(self.login("second")), [])
        self.assertEqual(self.login("default"), first)

    def test_a_turn_begun_before_the_refusal_leaves_it(self):
        self.refuse("default", "one", NOW)
        self.refuse("second", "one", NOW + 10)
        self.assertFalse(usage.answered(self.cfg, "acme", "second", "one", NOW + 5))
        self.assertEqual(self.made(self.login("second")), [NOW + 10])

    def assert_stays(self, model="one"):
        before = self.login("second")
        self.assertEqual(self.made(before), [NOW])
        self.assertFalse(usage.answered(self.cfg, "acme", "second", model, self.now + 10))
        self.assertEqual(self.login("second"), before)

    def test_a_refusal_a_meter_showed_stays(self):
        self.meters["acme", "second"] = [*self.week("weekly_all", used=100),
                                         *self.week("weekly_two")]
        self.refuse("second", "one", NOW)
        self.assertIsNotNone(self.login("second")["exhausted_by"])
        self.assert_stays()

    def test_a_refusal_made_without_a_model_goes(self):
        self.refuse("second", None, NOW)
        self.assertEqual(self.login("second")["exhausted_meters"], [])
        self.assertTrue(usage.answered(self.cfg, "acme", "second", "one", self.now + 10))
        self.assertEqual(self.made(self.login("second")), [])

    def test_a_refusal_whose_meters_are_no_list_stays(self):
        self.refuse("second", "one", NOW)
        cache = config.STATE / "usage.json"
        held = json.loads(cache.read_text())
        del held["providers"]["acme"]["accounts"]["second"]["exhausted_meters"]
        cache.write_text(json.dumps(held))
        self.assert_stays()

    def test_a_refusal_of_a_model_one_of_whose_meters_does_not_gate_the_turns_stays(self):
        self.refuse("second", "two", NOW)
        self.assert_stays()

    def test_a_refusal_naming_a_meter_the_reading_no_longer_holds_stays(self):
        self.meters["acme", "second"] = self.week("weekly_all", "weekly_two", "weekly_extra")
        self.refuse("second", "one", NOW)
        self.assertIn(["weekly_extra", None], self.login("second")["exhausted_meters"])
        self.meters["acme", "second"] = self.week("weekly_all", "weekly_two")
        self.now += usage.PROBE_EVERY + 1
        usage.collect(self.cfg, refresh=True)
        self.assertNotIn("weekly_extra", [m["name"] for m in self.login("second")["meters"]])
        self.assert_stays()

    def test_of_two_refusals_only_the_one_before_the_turn_goes(self):
        self.refuse("second", "one", NOW)
        self.refuse("second", "one", NOW + 10)
        self.assertTrue(usage.answered(self.cfg, "acme", "second", "one", NOW + 5))
        self.assertEqual(self.made(self.login("second")), [NOW + 10])

    def test_the_usual_login_of_a_provider_listing_no_accounts(self):
        usage.mark_exhausted(self.cfg, "beta", model="three")
        self.assertTrue(usage.answered(self.cfg, "beta", None, "three", NOW + 1))
        self.assertEqual(self.made(self.stored()["beta"]), [])

    def assert_raises_leaving_the_snapshot(self, error):
        cache = config.STATE / "usage.json"
        before = cache.read_bytes()
        with self.assertRaises(error):
            usage.answered(self.cfg, "acme", "second", "one", NOW + 1)
        self.assertEqual(cache.read_bytes(), before)

    def test_a_model_config_toml_no_longer_holds_raises_and_leaves_the_snapshot(self):
        self.refuse("second", "one", NOW)
        # ... the caller's copy still holding it, and so where config.toml no longer loads
        for toml in (CONFIG.replace(ONE, ""), "[models]\n"):
            (config.HOME / config.CONFIG_NAME).write_text(toml)
            self.assert_raises_leaving_the_snapshot(config.Error)

    def test_a_config_toml_that_cannot_be_read_raises_and_leaves_the_snapshot(self):
        self.refuse("second", "one", NOW)
        path = config.HOME / config.CONFIG_NAME
        path.unlink()
        path.symlink_to(path.name)     # a loop: there, and nothing to read
        self.assert_raises_leaving_the_snapshot(OSError)

    def test_a_reading_of_another_shape_raises_and_leaves_the_snapshot(self):
        self.refuse("second", "one", NOW)
        cache = config.STATE / "usage.json"
        marked = cache.read_text()
        for shape in (lambda held: held["acme"]["accounts"]["second"]["meters"].append(None),
                      lambda held: held["acme"]["accounts"]["second"].update(meters=None),
                      lambda held: held["acme"]["accounts"].update(second=["bad"]),
                      lambda held: held["acme"].update(accounts=["bad"]),
                      lambda held: held.update(acme=["bad"])):
            blob = json.loads(marked)
            shape(blob["providers"])
            cache.write_text(json.dumps(blob))
            self.assert_raises_leaving_the_snapshot(Exception)


if __name__ == "__main__":
    unittest.main()
