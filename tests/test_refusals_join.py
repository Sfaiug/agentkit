"""Each refusal on a login parks the models it can have been meant for until it ends itself.

Turns already running refuse one after another.  A refused Opus turn parks every model of the
login, and a Fable turn refused after it frees none of them; a refusal marked without a model
parks every model, whatever was marked before.  Each refusal ends at its own deadline or at a
fresh window on the meter that showed it, and neither ends another: Fable's refusals alone, or
Fable's and Nova's, leave Opus to its own meters, however often a reading holds Fable's cap.
A refusal recorded before marks named a meter's scope parks every model its names can mean.
Caps of one name and two scopes are two meters: a refusal of Fable's ends on Fable's alone, a
turn's ask of Opus's is none of Fable's while its ask of Fable's is, a probe's ask of Opus's
outlives a turn reading Fable's, and a turn reading Fable's leaves Opus's as it was, as it does
a cap whose name is Fable's name and scope.  A refusal recorded before `exhausted_by` named a
scope resolves its cap from `exhausted_meters` where that carries one, and recovers from `100%`
where another scope overwrote its starting level; one naming no scope anywhere ends on its name's
fresh window.

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

    def test_a_refusal_naming_meters_by_name_alone_parks_what_those_names_say(self):
        self.refused("fable")
        cache = config.STATE / "usage.json"
        blob = json.loads(cache.read_text())
        mark = blob["providers"]["acme"]
        mark["exhausted_meters"] = [name for name, _scope in mark["exhausted_meters"]]
        cache.write_text(json.dumps(blob))
        self.assertEqual(self.parked(), (["fable"], False))
        self.reads(week("weekly_all", 60), week("weekly_scoped", 90, scope="Fable"),
                   week("weekly_scoped", 30, scope="Opus"))
        self.assertEqual(self.parked(), (["fable", "opus"], False))

    def test_a_refusal_of_a_cap_read_twice_parks_only_its_model(self):
        fable = week("weekly_scoped", 90, scope="Fable")
        self.reads(week("weekly_all", 60), fable, fable, week("weekly_scoped", 30, scope="Opus"))
        self.refused("fable")
        self.assertEqual(self.parked(), (["fable"], False))

    def fable_refused_beside_opus(self):
        """The login's record once Fable is refused at 100, Opus's cap of the same name at 30."""
        self.read(week("weekly_all", 60), week("weekly_scoped", 100, scope="Fable"),
                  week("weekly_scoped", 30, scope="Opus"))
        self.refused("fable")
        return json.loads((config.STATE / "usage.json").read_text())["providers"]["acme"]

    def test_a_new_window_on_another_scope_keeps_the_refusal(self):
        prov = self.fable_refused_beside_opus()
        mark = usage._marks(prov)[0]
        prov["meters"][2]["resets_at"] += 86400
        self.assertEqual(usage._in_force(prov, [mark], NOW), [mark])

    def test_an_asked_fall_of_the_refused_cap_ends_it_beside_another_scope(self):
        prov = self.fable_refused_beside_opus()
        mark = usage._marks(prov)[0]
        prov["meters"][1]["used"] = 90
        prov["probed_meters"] = {"weekly_scoped": NOW + 1}
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [])

    def test_a_turn_reading_one_scope_keeps_the_other(self):
        self.read(week("weekly_all", 60), week("weekly_scoped", 90, scope="Fable"),
                  week("weekly_scoped", 30, scope="Opus"))
        self.now += 1
        usage.record_turn_meters(self.cfg, "acme", [week("weekly_scoped", 95, scope="Fable")],
                                 now=self.now)
        meters = usage.collect(self.cfg)["acme"]["meters"]
        self.assertEqual(sorted((m["scope"], m["used"]) for m in meters
                                if m["name"] == "weekly_scoped"), [("Fable", 95), ("Opus", 30)])

    def test_a_turn_s_ask_is_of_the_caps_it_read_alone(self):
        self.fable_refused_beside_opus()
        for used, scope, asked, parked in ((90, "Fable", False, ["fable"]),
                                           (31, "Opus", True, ["fable"]),
                                           (90, "Fable", True, [])):
            self.now += 1
            usage.record_turn_meters(self.cfg, "acme", [week("weekly_scoped", used, scope=scope)],
                                     now=self.now, asked=asked)
            self.assertEqual(self.parked(), (parked, False))

    def test_a_probe_s_ask_of_opus_s_cap_outlives_a_turn_reading_fable_s(self):
        self.read(week("weekly_all", 60), week("weekly_scoped", 90, scope="Fable"),
                  week("weekly_scoped", 100, scope="Opus"))
        self.refused("opus")
        cache = config.STATE / "usage.json"
        blob = json.loads(cache.read_text())
        blob["providers"]["acme"]["meters"][2]["used"] = 90
        blob["providers"]["acme"]["probed_meters"] = {"weekly_scoped": NOW + 1}
        cache.write_text(json.dumps(blob))
        self.now += 2
        usage.record_turn_meters(self.cfg, "acme", [week("weekly_scoped", 91, scope="Fable")],
                                 now=self.now)
        self.assertEqual(self.parked(), ([], False))

    def test_a_cap_named_as_fable_s_name_and_scope_is_a_cap_of_its_own(self):
        self.read(week("weekly_all", 60), week("weekly_scoped", 100, scope="Fable"),
                  week("weekly_scoped Fable", 30))
        self.refused("fable")
        self.now += 1
        usage.record_turn_meters(self.cfg, "acme", [week("weekly_scoped", 95, scope="Fable")],
                                 now=self.now, asked=True)
        self.assertEqual(self.parked(), ([], False))
        self.assertEqual([(m["name"], m.get("scope"), m["used"])
                          for m in usage.collect(self.cfg)["acme"]["meters"]],
                         [("weekly_all", None, 60), ("weekly_scoped", "Fable", 95),
                          ("weekly_scoped Fable", None, 30)])

    def test_a_mark_naming_its_cap_by_name_alone_ends_on_that_name_s_fresh_window(self):
        self.read(week("weekly_all", 60), week("weekly_scoped", 100, scope="Fable"))
        self.refused("fable")
        cache = config.STATE / "usage.json"
        blob = json.loads(cache.read_text())
        mark = blob["providers"]["acme"]
        mark["exhausted_by"] = "weekly_scoped"
        mark["exhausted_meters"] = ["weekly_scoped"]
        mark["exhausted_used"] = {"weekly_all": 60, "weekly_scoped": 100}
        cache.write_text(json.dumps(blob))
        self.now += 1
        usage.record_turn_meters(self.cfg, "acme", [
            week("weekly_scoped", 10, scope="Fable", resets_at=NOW + WEEK)], now=self.now)
        self.assertEqual(self.parked(), ([], False))

    def inherited_fable_mark(self, opus=30):
        """A mark in the format written before `exhausted_by` carried a scope: `exhausted_meters`
        names Fable's cap, while `exhausted_used` holds Opus's overwritten level."""
        prov = self.fable_refused_beside_opus()
        mark = usage._marks(prov)[0]
        mark["exhausted_by"] = "weekly_scoped"
        mark["exhausted_meters"] = [["weekly_scoped", "Fable"]]
        mark["exhausted_used"] = {"weekly_all": 60, "weekly_scoped": opus}
        mark["exhausted_ends"] = {"weekly_all": NOW + 3 * 86400,
                                  "weekly_scoped": NOW + 3 * 86400}
        return prov, mark

    def test_an_inherited_mark_ignores_another_scope_s_reset_or_fall_and_jitter(self):
        prov, mark = self.inherited_fable_mark()
        prov["meters"][1]["used"] = 99
        prov["meters"][2]["resets_at"] += 86400
        self.assertEqual(usage._in_force(prov, [mark], NOW), [mark])
        prov, mark = self.inherited_fable_mark()
        prov["meters"][1]["used"] = 99
        prov["meters"][2]["used"] = 10
        prov["probed_meters"] = {"weekly_scoped": NOW + 1}
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [mark])
        prov["meters"][1]["used"] = 90
        prov.pop("probed_meters")
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [mark])

    def test_an_inherited_mark_ends_on_its_recorded_cap_s_asked_fall_or_reset(self):
        for opus in (30, 95):
            prov, mark = self.inherited_fable_mark(opus=opus)
            prov["meters"][1]["used"] = 90
            prov["probed_meters"] = {"weekly_scoped": NOW + 1}
            self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [])
        prov, mark = self.inherited_fable_mark()
        prov["meters"] = [prov["meters"][0], {**prov["meters"][1], "used": 90}]
        prov["probed_meters"] = {"weekly_scoped": NOW + 1}
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [])
        prov, mark = self.inherited_fable_mark()
        prov["meters"][1]["used"] = 99
        prov["meters"][1]["resets_at"] += 86400
        self.assertEqual(usage._in_force(prov, [mark], NOW), [])

    def test_an_unscoped_legacy_mark_waits_for_every_scope_of_its_name_to_clear(self):
        prov, mark = self.inherited_fable_mark()
        mark["exhausted_meters"] = ["weekly_scoped"]
        prov["meters"][1]["used"] = 99
        prov["meters"][2]["resets_at"] += 86400
        self.assertEqual(usage._in_force(prov, [mark], NOW), [mark])
        prov, mark = self.inherited_fable_mark()
        mark["exhausted_meters"] = ["weekly_scoped"]
        prov["probed_meters"] = {"weekly_scoped": NOW + 1}
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [mark])
        prov["meters"][1]["used"] = 99
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [mark])
        prov["meters"][1]["used"] = 90
        self.assertEqual(usage._in_force(prov, [mark], NOW + 1), [])


if __name__ == "__main__":
    unittest.main()
