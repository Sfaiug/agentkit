"""AK_BIN prices every role's picks in one unit off measured subscription usage: dollars a task
where a provider the runs measured has a price, else points of a week; every unmeasured row,
and every row of a role no run measured, scaled off the runs' cost per board dollar.

Invented boards, logins' weeks and finished runs in a temporary HOME; models and usage output
is observed.
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
RELEASES = list(dict.fromkeys(f"{row[0]}-1" for row in ROWS))
# each provider's harness, running its models alone, so its seats' spend fits its week
HARNESSES = {"acme": "claude", "bolt": "codex", "crux": "opencode"}
PRICES = {"acme": 200, "bolt": 100, "crux": 30}     # each plan's price a month


def dollars(points, price):
    """What `points` of a week of a plan of `price` a month cost: a week is 12/52 of a month."""
    return points / 100 * price * 12 / 52


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

    def command(self, compare=None, prices=None, *args, **marks):
        """`ak models`, comparing only the releases `compare` names where given: the rest off."""
        off = [release for release in RELEASES if release not in compare] if compare else []
        akconfig.write(self.home, self.models, **marks,
                       settings={"models_off": off} if off else {},
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
        History(self.home).save()
        answer = self.answer(prices=PRICES)
        for role in ("orchestrate", "execute", "review"):
            self.assertEqual(answer[role]["cost_unit"], "board_dollars")
            for row in answer[role]["front"]:
                self.assertEqual((row["cost"], row["cost_rule"]), (row["board_cost"], "board"))

    def test_a_low_measured_share_per_dollar_changes_the_pick(self):
        pick = lambda answer: next(row["release"] for row in answer["execute"]["front"]
                                   if "pick" in row["notes"])
        self.assertEqual(pick(self.answer()), "bloom-1")
        History(self.home).save()
        self.assertEqual(pick(self.answer()), "anvil-1")

    def test_a_measured_row_costs_its_points_of_its_providers_week_in_dollars(self):
        anvil = self.row("anvil", prices=PRICES)
        self.assertAlmostEqual(anvil["cost"], dollars(.2, 200))
        self.assertEqual((anvil["board_cost"], anvil["cost_rule"]), (2, "measured"))
        self.assertAlmostEqual(self.row("dune", prices=PRICES)["cost"], dollars(2, 100))
        self.assertAlmostEqual(self.row("bloom", "review", prices=PRICES)["cost"], dollars(6, 200))

    def test_an_unmeasured_row_costs_its_board_price_at_its_runs_dollars_per_board_dollar(self):
        # on its provider's measured rows of its role, else on all of them, its own price unused
        crown = self.row("crown", prices=PRICES)
        self.assertAlmostEqual(crown["cost"], 100 * dollars(.5, 200) / 52)
        self.assertEqual(crown["cost_rule"], "provider")
        echo = self.row("echo", prices=PRICES)
        self.assertAlmostEqual(echo["cost"], 20 * (dollars(.5, 200) + dollars(2, 100)) / 62)
        self.assertEqual(echo["cost_rule"], "global")
        self.assertAlmostEqual(self.row("dune", "review", prices=PRICES)["cost"],
                               10 * dollars(10, 200) / 52)

    def test_a_role_no_run_measured_is_priced_off_the_other_roles_runs(self):
        answer = self.answer(prices=PRICES)
        self.assertEqual({answer[role]["cost_unit"] for role in ("orchestrate", "execute",
                                                                 "review")}, {"money"})
        # builds and reviews alike: half a point and ten of $200's week over $52 each
        acme = dollars(10.5, 200) / 104
        for model, cost, rule in (("crown", 100 * acme, "provider"),
                                  ("dune", 10 * dollars(2, 100) / 10, "provider"),
                                  ("echo", 20 * (104 * acme + dollars(2, 100)) / 114, "global")):
            row = self.row(model, "orchestrate", prices=PRICES)
            self.assertAlmostEqual(row["cost"], cost)
            self.assertEqual(row["cost_rule"], rule)
        self.assertAlmostEqual(self.row("crown", "orchestrate")["cost"], 100 * 10.5 / 104)

    def test_money_once_one_measured_provider_has_a_price(self):
        self.assertEqual(self.answer(prices={"crux": 30})["execute"]["cost_unit"], "share")
        answer = self.answer(prices={"acme": 200})
        self.assertEqual(answer["execute"]["cost_unit"], "money")
        # bolt, with no price, at the dollars a point of those that have one
        self.assertAlmostEqual(self.row("dune", prices={"acme": 200})["cost"], dollars(2, 200))
        self.assertAlmostEqual(self.row("echo", prices={"acme": 200})["cost"],
                               20 * dollars(2.5, 200) / 62)

    def test_a_measured_provider_has_its_price_though_the_boards_rate_none_of_its_rows(self):
        held = json.loads((self.home.path / ".agentkit/state/boards.json").read_text())
        for board in held.values():
            for row in board["rows"]:
                if row["model"] == "Dune":     # its price a token kept, so its build still counts
                    row["values"] = {key: value for key, value in row["values"].items()
                                     if key not in ("aa.frontierCode20", "aa.terminalBench40",
                                                    "aa.omniscience", "arena.agent",
                                                    "aa.automationBenchPartialScore")}
        self.home.write(".agentkit/state/boards.json", held)
        answer = self.answer(prices={"bolt": 100})
        self.assertAlmostEqual(answer["task_usage"]["dune"]["high"]["executor"], 2)
        self.assertEqual({answer[role]["cost_unit"] for role in ("orchestrate", "execute",
                                                                 "review")}, {"money"})
        anvil = next(row for row in answer["execute"]["front"] if row["release"] == "anvil-1"
                     and row["effort"] == "high")
        self.assertAlmostEqual(anvil["cost"], dollars(.2, 100))   # acme, at bolt's price

    def test_the_models_column_names_the_unit_every_role_is_in(self):
        self.assertRegex(self.command(), r"quality +week %\n +orchestrator +Anvil high +90\.0 +"
                                         r"≈0\.20%\n +executor +Anvil high +90\.0 +0\.20%\n")
        self.assertRegex(self.command(prices=PRICES), r"quality +\$ a task\n +orchestrator .*\n"
                                                      r" +executor +Anvil high +90\.0 +\$0\.09\n")

    def test_a_role_after_an_empty_one_stays_under_the_one_unit(self):
        # Echo, compared alone, lacks two of execute's three measures: no builds between
        # orchestrate's week shares and review's
        held = json.loads((self.home.path / ".agentkit/state/boards.json").read_text())
        held["arena.ai"]["rows"] = [row for row in held["arena.ai"]["rows"]
                                    if row["model"] != "Echo"]
        next(row for row in held["artificialanalysis.ai"]["rows"]
             if row["model"] == "Echo")["values"].pop("aa.terminalBench40")
        self.home.write(".agentkit/state/boards.json", held)
        shown = self.command(["echo-1"], workers=["echo"], reviewers=["bloom"])
        self.assertRegex(shown, r"quality +week %\n +orchestrator .*\n +executor .* not on the "
                                r"boards\n +reviewer ")


if __name__ == "__main__":
    unittest.main()
