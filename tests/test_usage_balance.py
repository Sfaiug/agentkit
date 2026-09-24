"""Split weekly allowance regressions, with fake meters and no model calls."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, usage


class WeeklyBalance(unittest.TestCase):
    def setUp(self):
        self.cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        # weekly/scoped/reset mechanics are metered-provider mechanics: every scenario below
        # answers for three companies, so grok and gemini, the meterless subscriptions, are
        # scoped out.  mimo stays configured: the cache test counts the probe it adds.
        # `usage.main` reads config.load(), so that has to be this fixture and not the home file.
        for model, provider in (("grok", "xai"), ("gemini", "google")):
            self.cfg["models"].pop(model, None)
            self.cfg["providers"].pop(provider, None)
        # Every scenario is a Fable seat's: Fable orchestrates by default and the rest work.
        self.cfg["defaults"] = {"orchestrator": "fable",
                                "workers": [m for m in self.cfg["models"] if m != "fable"]}
        # mimo's mode is its OpenCode endpoint's, and this fixture's config names none, never
        # the caller's: payg, so it stays out while any subscription is at or behind pace.
        opencode = tempfile.TemporaryDirectory(prefix=".usage-opencode-", dir=REPO)
        self.addCleanup(opencode.cleanup)
        env = patch.dict(os.environ, {"OPENCODE_CONFIG_DIR": opencode.name})
        env.start()
        self.addCleanup(env.stop)
        self.now = 10000
        self.clock = patch.object(usage.time, "time", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.workers = ["opus", "astra", "spark"]
        self.stack = patch.object(config, "load", lambda: self.cfg)
        self.stack.start()
        self.addCleanup(self.stack.stop)
        self.session = patch.object(config, "active_session", return_value=None)
        self.session.start()
        self.addCleanup(self.session.stop)

    def meter(self, name, used, window=604800):
        return {"name": name, "used": used, "window_secs": window,
                "resets_at": self.now + window / 2, "elapsed": 50, "pace": used - 50}

    def providers(self, all_used, scoped_used):
        def provider(name, meters):
            return {"provider": name, "meters": meters, "resets": 0, "error": None}
        return usage._gate_flags({
            "anthropic": provider("anthropic", [self.meter("weekly_all", all_used),
                                                self.meter("weekly_scoped", scoped_used)]),
            "openai": provider("openai", [self.meter("primary_window", 50)]),
            "meta": provider("meta", [self.meter("weekly", 55)]),
        }, self.now, self.cfg)

    def owner_week(self, resets=1):
        """The owner's 2026-09-14 reading: openai 68% used with 65% of its week still to go."""
        providers = self.providers(28, 28)
        week = self.meter("primary_window", 68)
        week["resets_at"] = self.now + 0.65 * 604800
        providers["openai"].update(meters=[week], resets=resets)
        for meter in providers["anthropic"]["meters"]:
            meter["resets_at"] = self.now + 0.53 * 604800
        return usage._gate_flags(providers, self.now, self.cfg)

    def test_v5b_long_window_ranks_below_week_with_more_slack(self):
        providers = self.providers(50, 50)
        month = self.meter("primary_window", 50, 30 * 86400)
        month["resets_at"] = self.now + 29 * 86400
        providers["openai"]["meters"] = [month]
        for meter in providers["anthropic"]["meters"]:
            meter["resets_at"] = self.now + 86400
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertAlmostEqual(usage.model_budget(self.cfg, "astra", providers)[0], 15 / 29)
        self.assertEqual(usage.model_budget(self.cfg, "opus", providers), (3.5, None))
        for role in ("executor", "reviewer"):
            self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"], role=role),
                             ["opus", "astra"])
        self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                         ("opus", "spark"))
        self.assertEqual(orch.choose(self.cfg, providers)[0], "fable")

    def test_v5b_equal_fractions_and_windows_keep_worker_order(self):
        providers = self.providers(50, 50)
        providers["meta"]["meters"][0]["used"] = 50
        for workers in (self.workers, list(reversed(self.workers))):
            for role in ("executor", "reviewer"):
                self.assertEqual(usage.pick_order(self.cfg, providers, workers, role=role), workers)

    def test_v5b_unknown_ranks_last_and_logs_probe_reason(self):
        for meters in ([], [self.meter("primary_window", 1)]):
            with self.subTest(meters=meters), redirect_stderr(io.StringIO()) as err:
                providers = self.providers(50, 50)
                providers["openai"].update(meters=meters, error="probe timed out", resets=10)
                self.assertEqual(usage.model_budget(self.cfg, "astra", providers),
                                 (0.0, "probe timed out"))
                self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"]),
                                 ["opus", "astra"])
                self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                                 ("opus", "spark"))
                self.assertIn("astra (openai) budget 0 unknown: probe timed out", err.getvalue())
        providers["openai"].update(meters=[], error=None)
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"]),
                             ["opus", "astra"])
        self.assertIn("no weekly meter reported", err.getvalue())

    def test_v5b_full_meter_without_reset_is_excluded_until_new_reading(self):
        providers = self.providers(50, 50)
        meter = providers["openai"]["meters"][0]
        meter.update(used=100, exhausted=False)
        del meter["resets_at"]
        for advance in (0, 604800):
            self.now += advance
            usage._gate_flags(providers, self.now, self.cfg)
            self.assertTrue(usage.model_exhausted(self.cfg, "astra", providers)[0])
            self.assertTrue(meter["exhausted"])
            self.assertTrue(providers["openai"]["exhausted"])
            self.assertEqual(usage.outlook(providers["openai"]), "exhausted")
            for role in ("executor", "reviewer"):
                with redirect_stderr(io.StringIO()) as err:
                    self.assertNotIn("astra", usage.pick_order(self.cfg, providers, self.workers, role=role))
                self.assertIn("astra excluded: primary_window 100% used >= 100", err.getvalue())
        # Tier A still uses the original flags; v5b changes worker gates only.
        self.assertFalse(usage.model_spent(self.cfg, "astra", providers)[0])
        meter.update(used=99, resets_at=self.now + 302400)
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertFalse(meter["exhausted"])
        self.assertFalse(providers["openai"]["exhausted"])
        self.assertEqual(usage.pick_order(self.cfg, providers, ["astra"]), ["astra"])

    def test_v5h_each_reset_adds_one_whole_allowance_never_a_percentage(self):
        providers = self.providers(20, 20)      # anthropic: 0.8 left of half a week, budget 1.6
        meter = providers["openai"]["meters"][0]
        meter.update(used=60, resets_at=self.now + 604800)     # a whole window still to go
        for resets, budget, order in ((0, 0.4, ["opus", "astra"]), (1, 1.4, ["opus", "astra"]),
                                      (2, 2.4, ["astra", "opus"]), (100, 100.4, ["astra", "opus"])):
            with self.subTest(resets=resets):
                providers["openai"]["resets"] = resets
                usage._gate_flags(providers, self.now, self.cfg)
                self.assertEqual(usage.model_budget(self.cfg, "astra", providers), (budget, None))
                # the count itself, because this window has all of its time left
                self.assertEqual(providers["openai"]["budget_from_resets"], float(resets))
                self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"]), order)

    def test_v5h_a_reset_in_hand_ranks_the_week_it_is_held_against(self):
        providers = self.owner_week()
        budget, reason = usage.model_budget(self.cfg, "astra", providers)
        self.assertIsNone(reason)
        self.assertAlmostEqual(budget, 2.03, delta=0.02)
        self.assertEqual(providers["openai"]["budget"], 2.031)
        self.assertAlmostEqual(usage.model_budget(self.cfg, "opus", providers)[0], 1.36, delta=0.02)
        for role in ("executor", "reviewer"):
            self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"], role=role),
                             ["astra", "opus"])
        self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                         ("astra", "opus"))

    def test_v5h_the_same_week_without_a_reset_is_picked_last(self):
        providers = self.owner_week(resets=0)
        self.assertAlmostEqual(usage.model_budget(self.cfg, "astra", providers)[0], 0.49,
                               delta=0.005)
        self.assertEqual(providers["openai"]["budget_from_resets"], 0)
        self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"]),
                         ["opus", "astra"])
        self.assertNotIn("in hand", usage.render(self.cfg, providers, ["opus", "astra"]))

    def test_v5h_an_uncountable_reset_adds_nothing_and_is_not_unknown(self):
        providers = self.owner_week(resets=None)
        budget, reason = usage.model_budget(self.cfg, "astra", providers)
        self.assertIsNone(reason)
        self.assertAlmostEqual(budget, 0.49, delta=0.005)
        self.assertIsNone(providers["openai"]["budget_reason"])
        self.assertEqual(providers["openai"]["budget_from_resets"], 0)
        self.assertEqual(usage.pick_order(self.cfg, providers, ["astra", "opus"]),
                         ["opus", "astra"])
        self.assertNotIn("in hand", usage.render(self.cfg, providers, ["opus", "astra"]))

    def test_v5h_a_spent_meter_holding_a_reset_is_still_excluded(self):
        providers = self.providers(20, 20)
        providers["openai"].update(resets=2)
        providers["openai"]["meters"][0]["used"] = 100
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertTrue(usage.model_exhausted(self.cfg, "astra", providers)[0])
        for role in ("executor", "reviewer"):
            with redirect_stderr(io.StringIO()) as err:
                self.assertNotIn("astra", usage.pick_order(self.cfg, providers, self.workers,
                                                           role=role))
            self.assertIn("astra excluded: primary_window 100% used >= 100", err.getvalue())
        # only the read that follows the spent reset -- a fresh week -- ranks on it
        providers["openai"]["meters"][0]["used"] = 0
        providers["openai"]["resets"] = 1
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertEqual(usage.pick_order(self.cfg, providers, self.workers)[0], "astra")

    def test_v5h_usage_output_names_the_reset_and_ranks_with_it(self):
        providers = self.owner_week()
        with patch.object(usage, "collect", return_value=providers), \
                patch.object(usage.terminal, "width", return_value=200), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(usage.main([]), 0)
        rendered = out.getvalue()
        row = next(line for line in rendered.splitlines() if line.startswith("openai "))
        self.assertIn("2.0 slack", row)
        self.assertIn("openai: 1 reset in hand counted as one full week (budget 0.5 without it)",
                      rendered)
        self.assertEqual(sum("in hand" in line for line in rendered.splitlines()), 1)
        self.assertIn("pick order: astra, opus, spark", rendered)
        providers["openai"]["resets"] = 2
        usage._gate_flags(providers, self.now, self.cfg)
        for width in (40, 100):
            with patch.object(usage.terminal, "width", return_value=width):
                rendered = usage.render(self.cfg, providers, ["astra", "opus", "spark"])
            self.assertLessEqual(max(map(len, rendered.splitlines())), width)
            self.assertIn("2 resets in hand counted as 2 full weeks", rendered.replace("\n", " "))

    def test_v5h_a_reset_in_hand_is_named_even_when_no_budget_can_be_read(self):
        for raw, shown, spoil in (
                ("unknown: probe timed out", "probe timed out",
                 lambda prov: prov.update(error="unknown: probe timed out")),
                ("gate meter has no valid reset time or window length",
                 "gate meter has no valid reset time or window length",
                 lambda prov: prov["meters"][0].pop("resets_at"))):
            for resets, held in ((1, "1 reset in hand counted as one full week"),
                                 (2, "2 resets in hand counted as 2 full weeks")):
                with self.subTest(reason=shown, resets=resets):
                    providers = self.owner_week(resets=resets)
                    spoil(providers["openai"])
                    usage._gate_flags(providers, self.now, self.cfg)
                    # the credit is confirmed; what it is worth here is not
                    self.assertEqual(providers["openai"]["budget"], 0)
                    self.assertEqual(providers["openai"]["budget_from_resets"], 0)
                    self.assertEqual(providers["openai"]["budget_reason"], raw)
                    with redirect_stderr(io.StringIO()):
                        order = usage.pick_order(self.cfg, providers)
                    self.assertEqual(order[-1], "astra")
                    with patch.object(usage.terminal, "width", return_value=200):
                        rendered = usage.render(self.cfg, providers, order)
                    self.assertIn(f"openai: {held} (budget unknown: {shown})", rendered)
                    self.assertIn("unknown", next(line for line in rendered.splitlines()
                                                  if line.startswith("openai ")))

    def test_v5h_usage_json_carries_the_budget_the_resets_added(self):
        providers = self.owner_week()
        with patch.object(usage, "collect", return_value=providers), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(usage.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        openai = data["providers"]["openai"]
        self.assertEqual(openai["budget"], 2.031)
        self.assertEqual(openai["budget_from_resets"], 1.538)
        self.assertAlmostEqual(openai["budget"] - openai["budget_from_resets"], 0.49, delta=0.005)
        self.assertEqual(data["providers"]["anthropic"]["budget_from_resets"], 0)
        self.assertEqual(data["pick_order"], ["astra", "opus", "spark"])

    def test_v5h_usage_json_names_every_meter_reset_time(self):
        """`--json` promises `reset_at` on every meter, whatever wrote the cache it read."""
        providers = self.providers(28, 28)
        for prov in providers.values():
            for meter in prov["meters"]:
                meter.pop("reset_at")                     # a cache from before the key existed
        providers["meta"]["meters"][0].pop("resets_at")   # and an adapter that named no moment
        self.assertNotIn("reset_at", json.dumps(providers))
        with patch.object(usage, "collect", side_effect=lambda cfg, **kw:
                          usage._gate_flags(providers, self.now, self.cfg)), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(usage.main(["--json"]), 0)
        meters = {meter["name"]: meter for prov in json.loads(out.getvalue())["providers"].values()
                  for meter in prov["meters"]}
        self.assertTrue(all("reset_at" in meter for meter in meters.values()), meters)
        self.assertIsNone(meters["weekly"]["reset_at"])   # `null`, never a missing key
        self.assertEqual({name: meter["reset_at"] for name, meter in meters.items()
                          if name != "weekly"},
                         {"weekly_all": self.now + 302400, "weekly_scoped": self.now + 302400,
                          "primary_window": self.now + 302400})

    def test_v5b_usage_output_shows_budget_for_each_provider(self):
        providers = self.providers(30, 30)
        providers["openai"]["meters"][0]["used"] = 70
        providers["meta"].update(meters=[], error="probe failed")
        usage._gate_flags(providers, self.now, self.cfg)
        with patch.object(usage, "collect", return_value=providers), \
                patch.object(usage.terminal, "width", return_value=200), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(usage.main([]), 0)
        rendered = out.getvalue()
        self.assertIn("budget", rendered.splitlines()[0])
        for name, label in (("anthropic", "1.4 slack"), ("openai", "0.6 ahead"), ("meta", "unknown")):
            row = next(line for line in rendered.splitlines() if line.startswith(name + " "))
            self.assertIn(label, row)
        self.assertIn("pick order: opus, astra, spark", rendered)
        self.assertIn("note: meta probe failed", rendered)
        with patch.object(usage, "collect", return_value=providers), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.assertEqual(usage.main(["--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["providers"]["meta"]["budget"], 0)
        self.assertEqual(data["pick_order"], ["opus", "astra", "spark"])
        for width in (40, 100):
            with patch.object(usage.terminal, "width", return_value=width):
                rendered = usage.render(self.cfg, providers, self.workers)
            self.assertLessEqual(max(map(len, rendered.splitlines())), width)
            self.assertIn("1.4 slack", rendered)
            self.assertIn("0.6 ahead", rendered)

    def test_v5b_json_remains_parseable_with_stderr_merged(self):
        for error, missing_timing in (("probe failed", False), (None, True)):
            with self.subTest(error=error, missing_timing=missing_timing):
                providers = self.providers(80, 53)
                providers["anthropic"]["error"] = error
                if missing_timing:
                    for meter in providers["anthropic"]["meters"]:
                        meter.pop("resets_at")
                providers["meta"].update(meters=[], error="no usage endpoint")
                usage._gate_flags(providers, self.now, self.cfg)
                # Smoke and other callers use `ak usage --json >snapshot.json 2>&1`.
                # The Fable preference also retries the order here; that must stay quiet.
                with patch.object(usage, "collect", return_value=providers), \
                        redirect_stdout(io.StringIO()) as output, redirect_stderr(output):
                    self.assertEqual(usage.main(["--json"]), 0)
                data = json.loads(output.getvalue())
                self.assertEqual(data["pick_order"], ["astra", "opus", "spark"])
                self.assertEqual(data["providers"]["anthropic"]["budget"], 0)
                self.assertEqual(data["providers"]["meta"]["budget_reason"], "no usage endpoint")
                self.assertEqual(data["providers"]["anthropic"]["budget_reason"],
                                 error or "gate meter has no valid reset time or window length")

    def test_v5b_budget_uses_model_gate_and_current_time(self):
        providers = self.providers(40, 70)
        self.assertEqual(usage.model_budget(self.cfg, "opus", providers), (1.2, None))
        self.assertEqual(usage.model_budget(self.cfg, "fable", providers), (0.6, None))
        rendered = usage.render(self.cfg, providers, self.workers)
        self.assertIn("opus 1.2 slack", rendered)
        self.assertIn("fable 0.6 ahead", rendered)
        providers["anthropic"]["meters"].append(self.meter("session", 99, usage.SESSION_SECS))
        self.assertEqual(usage.model_budget(self.cfg, "opus", providers), (1.2, None))
        self.now += 604800 / 4
        self.assertEqual(usage.model_budget(self.cfg, "opus", providers), (2.4, None))
        self.assertEqual(usage.model_budget(self.cfg, "fable", providers), (1.2, None))

    def test_v5b_invalid_or_expired_window_is_unknown_and_fractions_are_clamped(self):
        providers = self.providers(50, 50)
        meter = providers["openai"]["meters"][0]
        for key in ("resets_at", "window_secs"):
            original = meter[key]
            for value in (None, True, "unknown", 0, -1, float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    meter[key] = value
                    budget, reason = usage.model_budget(self.cfg, "astra", providers)
                    self.assertEqual(budget, 0)
                    self.assertIsNotNone(reason)
            meter[key] = original
        meter["resets_at"] = self.now
        self.assertEqual(usage.model_budget(self.cfg, "astra", providers)[0], 0)
        meter.update(used=-10, resets_at=self.now + 2 * 604800)
        self.assertEqual(usage.model_budget(self.cfg, "astra", providers), (1.0, None))
        meter["used"] = 110
        self.assertEqual(usage.model_budget(self.cfg, "astra", providers), (0.0, None))

    def test_v5b_unknown_fable_cannot_take_executor_preference(self):
        providers = self.providers(80, 53)
        providers["anthropic"]["error"] = "partial probe failed"
        with redirect_stderr(io.StringIO()):
            self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                             ("astra", "spark"))
        # Legacy readings may have allowance but no timing for any provider. All budgets
        # are then unknown; retain the existing Fable preference until a known budget exists.
        providers["anthropic"]["error"] = None
        for prov in providers.values():
            for meter in prov["meters"]:
                meter.pop("resets_at")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                             ("fable", "astra"))
            providers["openai"]["meters"][0]["resets_at"] = self.now + 302400
            self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                             ("astra", "opus"))

    def test_v5b_smallest_budget_binds_when_gate_reset_times_differ(self):
        providers = self.providers(30, 40)
        shared, scoped = providers["anthropic"]["meters"]
        shared["resets_at"] = self.now + 6 * 86400
        scoped["resets_at"] = self.now + 86400
        self.assertAlmostEqual(usage.model_budget(self.cfg, "fable", providers)[0], 49 / 60)
        self.assertAlmostEqual(usage.provider_budget(providers["anthropic"])[0], 49 / 60)
        for role in ("executor", "reviewer"):
            self.assertEqual(usage.pick_order(self.cfg, providers, ["fable", "astra", "spark"],
                                              role=role), ["astra", "spark", "fable"])
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertEqual(providers["anthropic"]["budget"], 0.817)
        self.assertIn("0.8 ahead", usage.rows(self.cfg, providers)[0])

        # A primary limit whose window is not the standard 5h still participates.
        providers["openai"]["meters"] = [self.meter("primary_window", 40, 21600),
                                           {**shared, "name": "secondary_window"},
                                           self.meter("session", 99, usage.SESSION_SECS)]
        providers["openai"]["meters"][0]["resets_at"] = self.now + 3600
        self.assertAlmostEqual(usage.model_budget(self.cfg, "astra", providers)[0], 49 / 60)
        providers["openai"]["meters"][1].pop("resets_at")
        budget, reason = usage.model_budget(self.cfg, "astra", providers)
        self.assertEqual(budget, 0)
        self.assertIsNotNone(reason)

    def test_v5b_partial_reviewer_probe_preserves_fable_preference(self):
        providers = self.providers(80, 53)
        providers["openai"]["error"] = "unknown: one malformed meter"
        providers["meta"]["meters"] = []
        with redirect_stderr(io.StringIO()):
            self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                             ("fable", "astra"))

    def test_v5b_pick_reason_has_one_unknown_prefix(self):
        providers = self.providers(50, 50)
        providers["meta"].update(meters=[], error="unknown: no usage endpoint")
        with redirect_stderr(io.StringIO()) as err:
            usage.pick_order(self.cfg, providers)
        self.assertIn("budget 0 unknown: no usage endpoint; ranked last", err.getvalue())
        self.assertNotIn("unknown: unknown:", err.getvalue())

    def test_v5b_budget_label_agrees_with_rounded_number(self):
        for value, expected in ((0.94, "0.9 ahead"), (0.98, "1.0 in step"),
                                (1.0, "1.0 in step"), (1.04, "1.0 in step"),
                                (1.06, "1.1 slack")):
            with self.subTest(value=value):
                self.assertEqual(usage._budget_label(value, None), expected)
        # Display rounding must not turn a real budget difference into a ranking tie.
        providers = self.providers(51, 51)
        providers["openai"]["meters"][0]["used"] = 48
        self.assertEqual(usage.pick_order(self.cfg, providers, ["opus", "astra"]),
                         ["astra", "opus"])

    def test_requested_balance_cases(self):
        for all_used, scoped, order, verdict in (
            (80, 53, ["astra", "spark", "opus"],
             "fable behind by 27: preferring Fable as executor"),
            (40, 70, ["opus", "astra", "spark"], "fable ahead by 30: Opus preferred"),
            (60, 60, ["astra", "spark", "opus"], "in step"),
        ):
            with self.subTest(all_used=all_used, scoped=scoped):
                providers = self.providers(all_used, scoped)
                prov = providers["anthropic"]
                real_meters = copy.deepcopy(prov["meters"])
                self.assertNotIn("effective_used", prov)
                self.assertEqual(prov["gap"], all_used - scoped)
                self.assertEqual(prov["headroom"], (100 - max(all_used, scoped)) / 100)
                self.assertEqual(prov["pace"], max(all_used, scoped) - 50)
                for name, used in (("opus", all_used), ("fable", max(all_used, scoped))):
                    self.assertEqual(usage.model_headroom(self.cfg, name, providers),
                                     (100 - used) / 100)
                    self.assertEqual(usage.model_pace(self.cfg, name, providers)[0], used - 50)
                    self.assertFalse(usage.model_exhausted(self.cfg, name, providers)[0])
                self.assertEqual(usage.pick_order(self.cfg, providers, self.workers), order)
                self.assertEqual(orch.choose(self.cfg, providers)[0], "fable")
                rendered = usage.render(self.cfg, providers, usage.pick_order(self.cfg, providers))
                self.assertIn(f"weekly_all {100 - all_used}% left, weekly_scoped {100 - scoped}% left, "
                              f"gap {all_used - scoped}", rendered)
                self.assertIn(verdict, rendered)
                self.assertNotIn("held back", rendered)
                self.assertLessEqual(max(map(len, rendered.splitlines())), 100)
                self.assertEqual(prov["meters"], real_meters)

    def test_only_real_meters_exhaust_models(self):
        for all_used, scoped, opus_spent, fable_spent in (
            (100, 30, True, True),
            (30, 100, False, True),
            (90, 10, False, False),
            (10, 90, False, False),
        ):
            with self.subTest(all_used=all_used, scoped=scoped):
                providers = self.providers(all_used, scoped)
                self.assertNotIn("effective_used", providers["anthropic"])
                for name, spent in (("opus", opus_spent), ("fable", fable_spent)):
                    self.assertEqual(usage.model_exhausted(self.cfg, name, providers)[0], spent)
                    self.assertEqual(usage.model_spent(self.cfg, name, providers)[0], spent)
                    self.assertEqual(name in usage.pick_order(self.cfg, providers, [name]), not spent)
                self.assertEqual(orch.choose(self.cfg, providers)[0],
                                 "fable" if not fable_spent else "opus" if not opus_spent else "astra")
                if all_used >= 100:
                    rendered = usage.render(self.cfg, providers, [])
                    self.assertIn("weekly_all exhausted", rendered)
                    self.assertNotIn("preferring Fable", rendered)

    def test_session_still_gates_and_contributes_to_pace(self):
        providers = self.providers(40, 70)
        providers["anthropic"]["meters"].append(self.meter("session", 99, usage.SESSION_SECS))
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertEqual(usage.model_pace(self.cfg, "opus", providers)[0], 49)
        self.assertEqual(usage.model_headroom(self.cfg, "opus", providers), 0.6)
        self.assertEqual(orch.choose(self.cfg, providers)[0], "fable")
        providers["anthropic"]["meters"][-1]["used"] = 100
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertTrue(usage.model_exhausted(self.cfg, "opus", providers)[0])
        self.assertEqual(orch.choose(self.cfg, providers)[0], "astra")

    def test_real_pace_controls_payg_overflow(self):
        self.cfg["providers"]["meta"]["mode"] = "payg"
        for all_used, scoped, allowed in ((70, 41, True), (40, 70, False)):
            providers = self.providers(all_used, scoped)
            order = usage.pick_order(self.cfg, providers, ["opus", "spark"])
            self.assertEqual("spark" in order, allowed)

    def test_single_meter_and_real_outlook_unchanged(self):
        providers = self.providers(70, 41)
        prov = providers["openai"]
        self.assertNotIn("effective_used", prov)
        self.assertEqual(usage.provider_headroom(prov, self.cfg), 0.5)
        self.assertEqual(usage.model_headroom(self.cfg, "astra", providers), 0.5)
        self.assertEqual(usage.model_pace(self.cfg, "astra", providers)[0], 0)
        self.assertEqual(usage.outlook(prov), "on track")
        self.assertEqual(usage.outlook(providers["anthropic"]), "runs out in ~2d")
        # A scoped meter can still run out first while Opus has headroom of its own.
        # This is the existing usage-table smoke fixture.
        providers = self.providers(52, 94)
        for meter in providers["anthropic"]["meters"]:
            meter["elapsed"] = 86.3
        self.assertEqual(usage.provider_headroom(providers["anthropic"], self.cfg), 0.06)
        self.assertEqual(usage.outlook(providers["anthropic"]), "runs out in ~1d")

    def test_split_comes_from_config_and_requires_both_meters(self):
        providers = self.providers(70, 41)
        prov = providers.pop("anthropic")
        prov["provider"] = "renamed"
        providers["renamed"] = prov
        self.cfg["providers"]["renamed"] = self.cfg["providers"].pop("anthropic")
        for entry in self.cfg["models"].values():
            if entry["provider"] == "anthropic":
                entry["provider"] = "renamed"
        self.cfg["models"]["fable"]["meter"] = "private_week"
        prov["meters"][1]["name"] = "private_week"
        self.assertEqual(usage.model_headroom(self.cfg, "opus", providers), 0.3)
        self.assertEqual(usage.pick_order(self.cfg, providers)[0], "fable")
        for missing in ("weekly_all", "private_week"):
            partial = {**prov, "meters": [m for m in prov["meters"] if m["name"] != missing]}
            self.assertIsNone(usage._split_week(self.cfg, "renamed", partial))
            self.assertNotIn("fable", usage.pick_order(self.cfg, {**providers, "renamed": partial}))
        del self.cfg["models"]["fable"]["meter"]
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertNotIn("effective_used", prov)
        self.assertNotIn("gap", prov)
        self.assertEqual(usage.model_headroom(self.cfg, "opus", providers), 0.3)

    def test_cached_and_fresh_reads_drop_effective_without_changing_real_meters(self):
        providers = self.providers(70, 41)
        # the fourth configured provider reports no meter at all, like the harvest it stands for
        providers["mimo"] = {"provider": "mimo", "meters": [], "resets": 0,
                             "error": "unknown: no usage source"}
        providers = usage._gate_flags(providers, self.now, self.cfg)
        raw = copy.deepcopy(providers)
        for prov in raw.values():
            prov.pop("effective_used", None)
            prov.pop("gap", None)
        with tempfile.TemporaryDirectory(prefix=".usage-test-", dir=REPO) as tmp:
            with patch.object(config, "STATE", Path(tmp)), patch.object(config, "ensure_dirs"), \
                    patch.object(usage.time, "time", return_value=self.now), \
                    patch.object(usage, "_probe", side_effect=lambda cfg, name, now: raw[name]) as probe:
                fresh = usage.collect(self.cfg)
                self.assertEqual(fresh, providers)
                self.assertEqual(probe.call_count, 4)
                cache = Path(tmp) / "usage.json"
                # An older/stale derived verdict must not be trusted on a warm read.
                raw["anthropic"]["effective_used"] = 12
                raw["anthropic"]["headroom"] = 0.88
                cache.write_text(json.dumps({"fetched_at": self.now, "providers": raw}))
                self.assertEqual(usage.collect(self.cfg), providers)
                self.assertEqual(probe.call_count, 4)
                # Older handwritten caches need only the provider's dictionary key.
                for prov in raw.values():
                    prov.pop("provider")
                cache.write_text(json.dumps({"fetched_at": self.now, "providers": raw}))
                cached = usage.collect(self.cfg)
                self.assertEqual(cached["anthropic"]["headroom"], 0.3)
                self.assertNotIn("effective_used", cached["anthropic"])
                self.assertIn("gap 29", usage.render(self.cfg, cached, self.workers))
                self.assertEqual(probe.call_count, 4)

    def test_behind_prefers_fable_executor_with_cross_provider_reviewer(self):
        for session in (None, {"name": "fable-seat", "orchestrator": "fable",
                               "workers": self.workers},
                        {"name": "fable-seat", "orchestrator": "fable",
                         "workers": [*self.workers, "fable"]}):
            for spent, reviewer in ((None, "astra"), ("openai", "spark"), ("meta", "astra")):
                with self.subTest(session=session, spent=spent), \
                        patch.object(config, "active_session", return_value=session):
                    providers = self.providers(80, 53)
                    if spent:
                        providers[spent]["meters"][0]["used"] = 100
                        usage._gate_flags(providers, self.now, self.cfg)
                    pair = run.pick_models(self.cfg, providers, None, None, lambda _: None)
                    expected = ((reviewer, "spark" if spent is None else "opus")
                                if session and "fable" not in session["workers"] else
                                ("fable", reviewer))
                    self.assertEqual(pair, expected)
                    self.assertNotEqual(*run.review_providers(self.cfg, *pair))

    def test_behind_keeps_opus_selectable_for_normal_cross_provider_pick(self):
        providers = self.providers(80, 53)
        self.assertFalse(usage.model_exhausted(self.cfg, "opus", providers)[0])
        self.assertEqual(usage.model_headroom(self.cfg, "opus", providers), 0.2)
        self.assertIn("opus", usage.pick_order(self.cfg, providers))
        session = {"name": "astra-seat", "orchestrator": "astra", "workers": ["astra", "opus"]}
        with patch.object(config, "active_session", return_value=session):
            self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                             ("astra", "opus"))
        self.assertEqual(run.pick_models(self.cfg, providers, "fable", "opus", lambda _: None),
                         ("fable", "opus"))
        with self.assertRaisesRegex(config.Error, "same model"):
            run.pick_models(self.cfg, providers, "fable", "fable", lambda _: None)

    def test_ahead_in_step_and_margin_use_normal_selection(self):
        for all_used, scoped, executor, reviewer in (
            (40, 70, "opus", "astra"), (60, 60, "astra", "spark"),
            (60, 59, "astra", "spark"), (60, 58, "astra", "spark"),
        ):
            for workers in (self.workers, [*self.workers, "fable"]):
                with self.subTest(all_used=all_used, scoped=scoped, workers=workers), \
                        patch.object(config, "active_session", return_value={
                            "name": "fable-seat", "orchestrator": "fable", "workers": workers}):
                    providers = self.providers(all_used, scoped)
                    self.assertEqual(run.pick_models(self.cfg, providers, None, None, lambda _: None),
                                     (executor, reviewer))
                    if abs(all_used - scoped) <= usage.FABLE_GAP_MARGIN:
                        self.assertIn("in step", usage.render(self.cfg, providers, []))
        self.assertEqual(usage.pick_order(self.cfg, self.providers(60, 57.9))[0], "fable")

    def test_same_provider_headroom_allows_fable_with_opus_review(self):
        for used in (100, None):
            for workers in (self.workers, [*self.workers, "fable"]):
                with self.subTest(used=used, workers=workers), \
                        patch.object(config, "active_session", return_value={
                            "name": "fable-seat", "orchestrator": "fable", "workers": workers}):
                    providers = self.providers(80, 53)
                    for provider in ("openai", "meta"):
                        providers[provider]["meters"] = ([] if used is None else
                                                         [self.meter("weekly", used)])
                    usage._gate_flags(providers, self.now, self.cfg)
                    if "fable" not in workers:
                        self.assertEqual(usage.pick_order(self.cfg, providers)[0], "opus")
                        if used == 100:
                            with self.assertRaises(run.QuotaDry):
                                run.pick_models(self.cfg, providers, None, None, lambda _: None)
                        else:
                            self.assertEqual(run.pick_models(self.cfg, providers, None, None,
                                                             lambda _: None), ("opus", "astra"))
                        continue
                    self.assertEqual(usage.pick_order(self.cfg, providers)[0], "fable")
                    pair = run.pick_models(self.cfg, providers, None, None, lambda _: None)
                    self.assertEqual(pair, ("fable", "opus" if used == 100 else "astra"))
                    with self.assertRaisesRegex(config.Error, "reviews_own_provider"):
                        run.review_providers(self.cfg, "opus", "fable")

    def test_preference_respects_worker_selection_payg_and_real_session_gate(self):
        providers = self.providers(80, 53)
        self.assertEqual(usage.pick_order(self.cfg, providers, self.workers), self.workers[1:] + ["opus"])
        self.assertEqual(usage.pick_order(self.cfg, providers, ["fable", "opus"]), ["fable", "opus"])
        self.cfg["providers"]["meta"]["mode"] = "payg"
        providers["openai"]["meters"] = []
        self.assertEqual(usage.pick_order(self.cfg, providers)[0], "fable")
        with patch.object(config, "active_session", return_value={
                "name": "fable-seat", "orchestrator": "fable", "workers": ["spark"]}):
            self.assertEqual(usage.pick_order(self.cfg, self.providers(20, 10)), ["spark"])
        providers = self.providers(80, 53)
        providers["anthropic"]["meters"].append(self.meter("session", 100, usage.SESSION_SECS))
        usage._gate_flags(providers, self.now, self.cfg)
        self.assertNotIn("fable", usage.pick_order(self.cfg, providers))

    def test_reviewers_keep_normal_order_when_fable_is_behind(self):
        providers = self.providers(80, 53)
        for session in (None, {"name": "fable-seat", "orchestrator": "fable",
                               "workers": self.workers}):
            with self.subTest(session=session), \
                    patch.object(config, "active_session", return_value=session):
                self.assertEqual(usage.pick_order(self.cfg, providers, role="reviewer"),
                                 ["astra", "spark", "opus"])
                self.assertEqual(run.pick_models(self.cfg, providers, "astra", None, lambda _: None),
                                 ("astra", "spark"))

    def test_fable_seat_resume_keeps_executor_after_meters_catch_up(self):
        session = {"name": "fable-seat", "orchestrator": "fable",
                   "workers": [*self.workers, "fable"]}
        with patch.object(config, "active_session", return_value=session):
            for scoped in (53, 80, 90):
                with self.subTest(scoped=scoped):
                    providers = self.providers(80, scoped)
                    self.assertEqual(run.pick_models(self.cfg, providers, "fable", "astra",
                                                     lambda _: None, resuming=True,
                                                     workers=session["workers"]), ("fable", "astra"))
                    for executor, reviewer in (("fable", "astra"), ("astra", "fable")):
                        with self.assertRaisesRegex(config.Error, "not a worker"):
                            run.pick_models(self.cfg, providers, executor, reviewer, lambda _: None,
                                            resuming=True, workers=self.workers)

    def test_launch_banner_matches_the_new_seats_executor_order(self):
        providers = self.providers(80, 53)
        # Launching a seat can happen outside one or from a seat with another selection.
        for parent in (None, {"orchestrator": "astra", "workers": ["opus", "spark"]}):
            for model, first in (("fable", "astra"), ("astra", "astra")):
                with self.subTest(parent=parent, model=model), \
                        tempfile.TemporaryDirectory(prefix=".usage-banner-", dir=REPO) as tmp, \
                        patch.object(config, "active_session", return_value=parent), \
                        patch.object(config, "notify_path", return_value=Path(tmp) / "notice"), \
                        patch.object(config, "save_session"), \
                        patch.object(orch, "alias_names", return_value=[]), \
                        patch.object(orch, "select", return_value=(model, "selected", self.workers)), \
                        patch.object(usage, "collect", return_value=providers), \
                        patch.object(orch, "fresh_command", return_value=(["echo", "seat"], None)), \
                        patch.object(orch, "fix_term", return_value=None), redirect_stdout(io.StringIO()) as out:
                    orch.create(self.cfg, "new-seat", REPO, dry_run=True)
                    self.assertNotIn("pick order:", out.getvalue())
                    rendered = usage.render(self.cfg, providers, usage.pick_order(
                        self.cfg, providers, self.workers, orchestrator=model))
                    self.assertIn(f"pick order: {first},", rendered)
                    self.assertNotIn("preferring Fable", rendered)
                    with patch.object(config, "active_session", return_value={
                            "name": "new-seat", "orchestrator": model, "workers": self.workers}):
                        self.assertEqual(usage.pick_order(self.cfg, providers)[0], first)

    def test_verdict_reports_normal_selection_when_preference_cannot_apply(self):
        for reason in ("reviewers spent", "reviewers unknown", "session spent", "not selected"):
            with self.subTest(reason=reason):
                providers = self.providers(80, 53)
                session = None
                if reason.startswith("reviewers"):
                    # No same-company alternative in this selection either.
                    session = {"name": "fable-seat", "orchestrator": "fable",
                               "workers": ["astra", "spark", "fable"]}
                    for provider in ("openai", "meta"):
                        providers[provider]["meters"] = ([self.meter("weekly", 100)]
                                                         if reason.endswith("spent") else [])
                elif reason == "session spent":
                    providers["anthropic"]["meters"].append(self.meter("session", 100, usage.SESSION_SECS))
                else:
                    session = {"name": "astra-seat", "orchestrator": "astra", "workers": self.workers}
                usage._gate_flags(providers, self.now, self.cfg)
                with patch.object(config, "active_session", return_value=session):
                    order = usage.pick_order(self.cfg, providers)
                    rendered = usage.render(self.cfg, providers, order)
                    self.assertIn("fable behind by 27: normal selection", rendered)
                    self.assertNotIn("preferring Fable", rendered)


if __name__ == "__main__":
    unittest.main()
