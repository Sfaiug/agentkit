"""A subscription's week is measured in tokens, from ak's own worker turns; offline.

Each turn that spent a known number of tokens and moved a weekly meter of its subscription
within one window records the pair under `state/capacity.json`, per subscription and meter;
a turn that moved nothing records its tokens against zero percent.  The week holds the sum
of the tokens over the sum of the percent moved, over the meter's current and previous
window, and `ak usage` shows it after `left` as `week ≈ 310M tokens`, `-` with no pair that
moved it; `--json` carries `capacity_tokens` and `capacity_pairs`.  A temporary HOME,
invented readings and fake turn event logs: no real login, endpoint or state.
"""

from contextlib import redirect_stdout
import io
import json
import os
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, turns, usage

NOW = 10000
WEEK = 604800
SESSION = 18000
RESETS = NOW + 3 * 86400


class SubscriptionCapacity(Sandbox):
    def setUp(self):
        super().setUp()
        self.now = NOW
        self.stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now))
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(usage, "_probe",
                                              side_effect=AssertionError("probe")))
        self.cfg["providers"]["anthropic"]["accounts"] = ["default", "second"]
        self.cache()

    def meter(self, name, used, resets_at=RESETS, window=WEEK):
        return usage._normalized({"name": name, "used": used, "resets_at": resets_at,
                                  "window_secs": window}, self.now)

    def cache(self, first=40, second=20):
        def record(provider, *meters):
            return {"provider": provider, "meters": list(meters), "error": None, "resets": 0.0,
                    "probed_at": self.now}
        claude = {"default": record("anthropic", self.meter("weekly_all", first),
                                    self.meter("weekly_scoped", 30),
                                    self.meter("session", 10, NOW + 3600, SESSION)),
                  "second": record("anthropic", self.meter("weekly_all", second))}
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": self.now, "providers": {
                "anthropic": {"provider": "anthropic", "accounts": claude},
                "openai": record("openai", self.meter("weekly", 30))}}))

    def turn(self, model, account, tokens, weekly=None, resets_at=RESETS, took=60):
        """One worker turn as `call_retrying` makes it: the reading before, then its log."""
        provider = config.model(self.cfg, model)["provider"]
        before = usage.reading(provider, account)
        self.now += took
        target = self.root / f"out-{self.now}"
        target.mkdir()
        events = [{"type": "result", "result": "done",
                   "usage": {"input_tokens": tokens, "output_tokens": 0}}]
        if weekly is not None:
            events.insert(0, {"type": "rate_limit_event", "rate_limit_info": {
                "status": "allowed", "unifiedWindows": {
                    "five_hour": {"utilization": 0.1, "resetsAt": NOW + 3600},
                    "seven_day": {"utilization": weekly / 100, "resetsAt": resets_at}}}})
        (target / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        turns.note_turn_meters(self.cfg, model, target, account, before)

    def pairs(self, provider="anthropic", account="default", meter="weekly_all"):
        try:
            blob = json.loads((config.STATE / "capacity.json").read_text())
        except FileNotFoundError:
            return []
        return blob.get(provider, {}).get(account, {}).get(meter, [])

    def row(self, label):
        rows = [dict(zip(usage.HEADERS, row))
                for row in usage.rows(self.cfg, usage.collect(self.cfg))]
        return next(row for row in rows if row["provider"] == label)

    def test_three_turns_give_the_estimate_on_their_subscriptions_row(self):
        self.turn("opus", "default", 3_100_000, weekly=41)
        self.turn("opus", "default", 5_000_000, weekly=43)
        self.turn("opus", "default", 1_200_000, weekly=43)
        self.assertEqual([(p["tokens"], p["moved"]) for p in self.pairs()],
                         [(3_100_000, 1), (5_000_000, 2), (1_200_000, 0)])
        # the 5-hour session is no week, and the turn carried no reading of Fable's cap
        self.assertEqual(self.pairs(meter="session"), [])
        self.assertEqual(self.pairs(meter="weekly_scoped"), [])
        self.assertEqual(usage.capacity("anthropic", "default", "weekly_all"), (310_000_000, 3))
        self.assertEqual(self.row("anthropic I")["capacity"], "week ≈ 310M tokens")
        # the column follows `left`, and each subscription has its own: the other has no pair
        self.assertEqual(usage.HEADERS[usage.HEADERS.index("left") + 1], "capacity")
        self.assertEqual(self.row("anthropic II")["capacity"], "-")

    def test_a_pair_across_a_reset_is_not_recorded(self):
        # the week before the turn resets during it: the turn's reading is the next week's
        self.cache(first=90)
        blob = json.loads((config.STATE / "usage.json").read_text())
        meters = blob["providers"]["anthropic"]["accounts"]["default"]["meters"]
        meters[0]["resets_at"] = NOW + 30
        (config.STATE / "usage.json").write_text(json.dumps(blob))
        self.turn("opus", "default", 4_000_000, weekly=95, resets_at=NOW + 30 + WEEK)
        self.assertEqual(self.pairs(), [])
        self.assertEqual(self.row("anthropic I")["capacity"], "-")

    def test_a_turn_that_moved_no_meter_counts_its_tokens_against_zero(self):
        self.turn("opus", "default", 2_000_000, weekly=40)
        self.assertEqual([(p["tokens"], p["moved"]) for p in self.pairs()], [(2_000_000, 0)])
        # alone, it moved nothing, so there is nothing to divide by
        self.assertEqual(usage.capacity("anthropic", "default", "weekly_all"), (None, 1))
        self.assertEqual(self.row("anthropic I")["capacity"], "-")
        self.turn("opus", "default", 4_000_000, weekly=42)
        self.assertEqual(usage.capacity("anthropic", "default", "weekly_all"), (300_000_000, 2))

    def test_a_turn_without_its_own_reading_pairs_with_the_probe_after_it(self):
        def probe(cfg, provider, now, account=None):
            return {"provider": provider, "meters": [self.meter("weekly", 32)], "error": None,
                    "resets": 0.0, "probed_at": now}
        with patch.object(usage, "_probe", side_effect=probe):
            self.turn("astra", None, 8_000_000)
        self.assertEqual([(p["tokens"], p["moved"])
                          for p in self.pairs("openai", meter="weekly")], [(8_000_000, 2)])
        # Inside the probe's cadence the answer is the reading from before the turn: no pair.
        with patch.object(usage, "_probe", side_effect=probe):
            self.turn("astra", None, 8_000_000, took=usage.PROBE_EVERY / 2)
        self.assertEqual(len(self.pairs("openai", meter="weekly")), 1)
        self.assertEqual(self.row("openai")["capacity"], "week ≈ 400M tokens")

    def test_pairs_older_than_the_previous_window_are_dropped(self):
        def week(n, used):
            return [{"name": "weekly_all", "used": used, "resets_at": NOW + n * WEEK,
                     "window_secs": WEEK}]
        for n in (1, 2, 3):
            # a turn in each of three weeks in a row, at its own week's start
            usage.record_capacity(self.cfg, "opus", "default", week(n, 10), 1_000_000,
                                  week(n, 10 + n), now=NOW + (n - 1) * WEEK + 60)
            kept = [p["resets_at"] for p in self.pairs()]
            self.assertEqual(kept, [NOW + k * WEEK for k in (1, 2, 3) if n - 1 <= k <= n])
        self.assertEqual(usage.capacity("anthropic", "default", "weekly_all"), (40_000_000, 2))

    def test_usage_json_carries_the_estimate_and_its_pairs(self):
        self.turn("opus", "default", 3_100_000, weekly=41)
        self.turn("opus", "default", 3_100_000, weekly=43)
        out = io.StringIO()
        with patch.object(config, "load", return_value=self.cfg), \
                patch.object(usage, "pick_order", return_value=[]), \
                patch.object(usage, "review_pair", return_value=None), redirect_stdout(out):
            self.assertEqual(usage.main(["--json"]), 0)
        providers = json.loads(out.getvalue())["providers"]
        claude = providers["anthropic"]["accounts"]
        self.assertEqual((claude["default"]["capacity_tokens"],
                          claude["default"]["capacity_pairs"]), (206_666_667, 2))
        self.assertEqual((claude["second"]["capacity_tokens"],
                          claude["second"]["capacity_pairs"]), (None, 0))
        self.assertEqual((providers["openai"]["capacity_tokens"],
                          providers["openai"]["capacity_pairs"]), (None, 0))

    def test_no_pair_shows_a_dash(self):
        self.assertFalse((config.STATE / "capacity.json").exists())
        self.assertEqual(self.row("anthropic I")["capacity"], "-")
        self.assertEqual(self.row("openai")["capacity"], "-")


if __name__ == "__main__":
    unittest.main()
