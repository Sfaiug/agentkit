"""AK_BIN prices role picks in measured subscription usage, scaling every unmeasured row.

Invented boards, logins' weeks and finished runs in a temporary HOME; models and usage output
is observed. Shares retain task_usage's units; prices multiply them only for a full lineup.
"""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, EVALUATIONS, aa, boards
from test_key_config_save_keeps import UNKNOWN
from test_key_role_cost_from_runs import NOW, History

# release, effort, provider, quality's coding share, board dollars
ROWS = [("anvil", "low", "acme", .60, 1), ("anvil", "high", "acme", .80, 2),
        ("bloom", "high", "acme", .89, 50), ("crown", "high", "acme", .90, 100),
        ("dune", "high", "bolt", .65, 10), ("echo", "high", "crux", .70, 20)]
# each provider's harness, running its models alone, so its seats' spend fits its week
HARNESSES = {"acme": "claude", "bolt": "codex", "crux": "opencode"}


class PicksPricedInUsage(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakes = fakeadapter.install(home, **dict.fromkeys(HARNESSES.values(), "pass"))
        self.fake = fakes["claude"]
        for provider, harness in HARNESSES.items():
            fakes[harness].answer("models", "".join(
                f"{name}-1\t{name}\tlow high\n"
                for name in dict.fromkeys(row[0] for row in ROWS if row[2] == provider)))
        # Crown is on the boards and harness, but has no configured alias or measurement.
        self.models = {name: {"harness": HARNESSES[provider], "model": f"{name}-1",
                              "provider": provider}
                       for name, _, provider, *_ in ROWS if name != "crown"}
        self.providers = {name: {"mode": "subscription", "maker": name.title()}
                          for name in ("acme", "bolt", "crux")}
        held = boards()
        for board in held.values():
            board["rows"] = [row for row in board["rows"] if row["model"] == "Old 1"]
        for name, effort, provider, share, dollars in ROWS:
            row = aa(f"{name}-1", name.title(), effort, {
                "aa.intelligenceIndex": 50, "aa.frontierCode20": share,
                "aa.terminalBench40": share, "aa.omniscience": 100 * share,
                "aa.automationBenchPartialScore": share, "aa.price1mInputTokens": 1,
                "aa.price1mOutputTokens": 1,
                **{f"aa.intelligenceIndexEvaluations.{slug}.costPerTask": dollars
                   for slug in EVALUATIONS}})
            row["maker"] = provider.title()
            held["artificialanalysis.ai"]["rows"].append(row)
            held["arena.ai"]["rows"].append({"model": name.title(), "effort": effort,
                                            "values": {"arena.agent": share}})
        home.write(".agentkit/state/boards.json", held)
        home.write(".agentkit/state/usage.json", {"providers": {provider: {"meters": [
            {"name": "weekly", "used": 40, "window_secs": 604800, "resets_at": NOW + 86400}]}
            for provider in ("acme", "bolt")}})
        history = History(home)
        # each week $100 at a dollar a million tokens, so a run's points are its dollars
        for provider, model in (("acme", "anvil-1"), ("bolt", "dune-1")):
            history.week(provider, "default", HARNESSES[provider], model, 50e6, 50)
        spent = lambda model, points: [[("default", f"{model}-1", (points * 1e6, 0, 0, 0))]]
        for model, points in (("anvil", .2), ("bloom", .3), ("dune", 2)):
            history.run((model, "high"), built=spent(model, points))
        for model, points in (("anvil", 4), ("bloom", 6)):
            history.run(None, model, ["high"], reviewed=spent(model, points))
        history.save()

    def command(self, compare=None, prices=None, *args):
        akconfig.write(self.home, self.models, settings={"compare": compare} if compare else {},
                       providers={name: {**entry, **({"price": prices[name]} if prices
                                                    and name in prices else {})}
                                  for name, entry in self.providers.items()})
        done = self.home.ak("models", *args, env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def answer(self, compare=None, prices=None):
        return json.loads(self.command(compare, prices, "--json"))

    def row(self, model, role="execute", effort="high", prices=None):
        return next(row for row in self.answer([f"{model}-1"], prices)[role]["front"]
                    if row["effort"] == effort)

    def test_measured_cost_and_provider_pool_include_only_this_role_and_exact_effort(self):
        self.models["anvil-copy"] = dict(self.models["anvil"])
        answer = self.answer(["anvil-1"])
        self.assertEqual(answer["execute"]["cost_unit"], "share")
        high, low = answer["execute"]["front"]
        self.assertAlmostEqual(high["cost"], answer["task_usage"]["anvil"]["high"]["executor"])
        self.assertEqual((high["board_cost"], high["cost_rule"]), (2, "measured"))
        self.assertAlmostEqual(low["cost"], .5 / 52)
        self.assertEqual(low["cost_rule"], "provider")
        crown = self.row("crown")
        self.assertAlmostEqual(crown["cost"], 100 * .5 / 52)
        self.assertEqual((crown["board_cost"], crown["cost_rule"]), (100, "provider"))
        self.assertAlmostEqual(self.row("anvil", "review")["cost"], 4)

    def test_unmeasured_provider_uses_the_role_pool_of_shares_over_board_dollars(self):
        echo = self.row("echo")
        self.assertAlmostEqual(echo["cost"], 20 * 2.5 / 62)
        self.assertEqual((echo["board_cost"], echo["cost_rule"]), (20, "global"))
        self.assertAlmostEqual(self.row("dune", "review")["cost"], 10 * 10 / 52)

    def test_unlisted_models_keep_their_measurements_and_conversion_pools(self):
        before = self.row("anvil")
        self.fake.answer("models", "bloom-1\tBloom\thigh\n")
        (self.home.path / ".agentkit/state/matrix.json").unlink()
        after = self.row("anvil")
        self.assertEqual((after["cost"], after["cost_rule"]), (before["cost"], "measured"))
        self.assertAlmostEqual(self.row("crown")["cost"], 100 * .5 / 52)
        self.assertAlmostEqual(self.row("echo")["cost"], 20 * 2.5 / 62)

    def test_pricing_cache_accepts_unrelated_toml_dates_and_times(self):
        text = ("at = 12:34:56\nstamp = 2026-10-01T12:34:56Z\n" + UNKNOWN).replace(
            "custom_flag = true", "custom_when = 2026-10-01").replace(
                "accounts = []", "accounts = []\ncustom_at = 12:34:56")
        self.home.write(".agentkit/config.toml", text)
        self.home.write(".agentkit/state/matrix.json", {"matrix": {"lineup": []}})
        done = self.home.ak("usage", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)

    def test_missing_board_creators_keep_known_models_measured_and_unknown_models_scaled(self):
        path = self.home.path / ".agentkit/state/boards.json"
        held = json.loads(path.read_text())
        for row in held["artificialanalysis.ai"]["rows"]:
            row["maker"] = None
        self.home.write(".agentkit/state/boards.json", held)
        self.assertAlmostEqual(self.row("anvil")["cost"], .2)
        self.assertEqual(self.row("crown")["cost_rule"], "global")
        History(self.home).save()
        self.assertEqual(self.row("anvil")["cost"], 2)

    def test_no_measurements_keep_board_dollars_and_say_so(self):
        answer = self.answer()
        self.assertEqual(answer["orchestrate"]["cost_unit"], "board_dollars")
        for row in answer["orchestrate"]["front"]:
            self.assertEqual((row["cost"], row["cost_rule"]), (row["board_cost"], "board"))
        History(self.home).save()
        self.assertTrue(all(role["cost_unit"] == "board_dollars"
                            for name, role in self.answer().items()
                            if name in ("orchestrate", "execute", "review")))

    def test_a_low_measured_share_per_dollar_changes_the_pick(self):
        pick = lambda answer: next(row["release"] for row in answer["execute"]["front"]
                                   if "pick" in row["notes"])
        self.assertEqual(pick(self.answer()), "bloom-1")
        History(self.home).save()
        self.assertEqual(pick(self.answer()), "anvil-1")

    def test_prices_apply_only_when_every_lineup_provider_has_one(self):
        self.assertAlmostEqual(self.row("anvil", prices={"acme": 10})["cost"], .2)
        prices = {"acme": 10, "bolt": 20, "crux": 30}
        self.assertEqual(self.answer(prices=prices)["execute"]["cost_unit"], "money")
        self.assertAlmostEqual(self.row("anvil", prices=prices)["cost"], .2 * 10)
        self.assertAlmostEqual(self.row("crown", prices=prices)["cost"], 100 * .5 / 52 * 10)
        self.assertAlmostEqual(self.row("echo", prices=prices)["cost"], 20 * 2.5 / 62 * 30)

    def test_the_models_column_names_each_roles_unit(self):
        shown = self.command()
        self.assertRegex(shown, "quality +a task")
        self.assertRegex(shown, "quality +week %")
        self.assertIn("0.30%", shown)


if __name__ == "__main__":
    unittest.main()
