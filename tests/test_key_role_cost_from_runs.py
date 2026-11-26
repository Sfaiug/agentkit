"""`ak models --json` prices a model's role at an effort (`task_usage`, its row's measured `cost`)
at the mean over the task runs that ended where it did it of the points of a week its `turn_usage`
rows took: at listed prices, times 100 over each row's login's `week_listed_usd` (`ak usage
--json`).  A counted turn with no row, or rows counting a token none of which names the model
its entry runs, or a row with no listed price, leaves its run out of the role, reviews naming
two efforts out of the reviewer's, as does a run running again (resumed);
a model with no runs keeps its estimate.  Where the plans its provider's logins are on have list
prices, the role costs those points of a week of their mean plan in dollars, a week 12/52 of a
month.

Black-box through tests/fixtures/akbin.py on tests/fixtures/meters.py's harness, with invented
boards, plans, readings, seat spend and finished runs in its Home.  Fails against /bin/false.
"""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home
from test_key_models_answer import ENV, EVALUATIONS, aa, boards

NOW = time.time()
DAY = 86400
# each table's columns this test writes, as history.db names them
TABLES = {"runs": "run_id, executor, executor_effort, reviewer, kind, finished_at, counted_turns",
          "reviews": "run_id, review_id, effort",
          "turn_usage": "turn, run_id, role, account, model, began, at, input, cache_write, "
                        "cache_read, output",
          "seat_usage": "event, at, tokens, account, model, input, cache_write, cache_read, output",
          "meter_readings": "provider, account, meter, used, resets_at, window_secs, at, source, "
                            "plan, PRIMARY KEY (provider, account, meter, at)"}
# each release's listed price a million input, cache write, cache read and output tokens, its
# quality share and its board dollars
RELEASES = {"anvil-1": ((1, 1.25, .1, 5), .80, 10), "bloom-1": ((2, 2.5, .2, 10), .89, 38),
            "crown-1": ((4, 5, .4, 20), .90, 40)}
PRICED = ("aa.price1mInputTokens", "aa.cacheWritePrice", "aa.cacheHitPrice",
          "aa.price1mOutputTokens")


def board():
    """The boards holding `RELEASES` at effort `high`, and the row keeping them from being asked."""
    held = boards()
    for found in held.values():
        found["rows"] = [row for row in found["rows"] if row["model"] == "Old 1"]
    for slug, (prices, share, dollars) in RELEASES.items():
        name = slug.removesuffix("-1").title() + " 1"
        held["artificialanalysis.ai"]["rows"].append(aa(slug, name, "high", {
            "aa.intelligenceIndex": 50, "aa.frontierCode20": share, "aa.terminalBench40": share,
            "aa.omniscience": 100 * share, "aa.automationBenchPartialScore": share,
            **dict(zip(PRICED, prices)),
            **{f"aa.intelligenceIndexEvaluations.{one}.costPerTask": dollars
               for one in EVALUATIONS}}))
        held["arena.ai"]["rows"].append({"model": name, "effort": "high",
                                        "values": {"arena.agent": share}})
    return held


class History:
    """The rows a test writes into its Home's history.db, all of them by each `save`."""

    def __init__(self, home):
        self.home = home
        self.rows = {table: [] for table in TABLES}

    def week(self, provider, account, harness, model, tokens, points, plan=None):
        """Two probe readings of the login's shared week `weekly`, `points` apart, a seat of
        `harness` spending `tokens` input tokens of `model` between them."""
        for used, ago in ((10, 3 * DAY), (10 + points, 2 * DAY)):
            self.rows["meter_readings"].append((provider, account, "weekly", used, NOW + 3 * DAY,
                                                7 * DAY, NOW - ago, "probe", plan))
        self.rows["seat_usage"].append((f"{harness}:seat-{len(self.rows['seat_usage'])}",
                                        NOW - 2.5 * DAY, tokens, account, model, tokens, 0, 0, 0))

    def run(self, executor=None, reviewer=None, efforts=(), *, built=(), reviewed=(), ended=True):
        """A task run that ended, or runs again where not `ended`: `executor` (model, effort)
        built it in a counted turn per list of `built`, `reviewer` reviewed it in one per list of
        `reviewed`, a review per effort of `efforts`.  A list holds its turn's rows, (account,
        model, counts); None, no row."""
        run, turns = f"fix-api-{len(self.rows['runs'])}", []
        for role, kept in (("executor", built), ("reviewer", reviewed)):
            for n, rows in enumerate(kept):
                turns.append(str(self.home.path / f".agentkit/runs/{run}/round-{n + 1}/{role}"))
                self.rows["turn_usage"] += [(turns[-1], run, role, account, model, NOW - DAY,
                                             NOW - DAY, *counts) for account, model, counts
                                            in rows or ()]
        self.rows["runs"].append((run, *(executor or (None, None)), reviewer, "task",
                                  NOW - DAY if ended else None, json.dumps(turns)))
        self.rows["reviews"] += [(run, f"review-{n}", one) for n, one in enumerate(efforts)]

    def save(self):
        path = self.home.path / ".agentkit/history.db"
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            for table, columns in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({columns})")
                for row in self.rows[table]:
                    db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)


class RoleCostFromRuns(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.meter = meter = meters.install(self.home)
        # the echo harness lists no models, so no [defaults] model names its company: Acme,
        # the boards' maker, is named, or no row would be compared
        akconfig.write(self.home, {name: {"harness": "echo", "model": f"{name}-1"}
                                   for name in ("anvil", "bloom", "crown")},
                       settings={"companies": ["Acme"]},
                       providers={"acme": {"mode": "subscription",
                                           "accounts": ["default", "second"]}})
        self.home.write(".agentkit/state/boards.json", board())
        self.home.write(".agentkit/state/logins.json", {"acme": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": plan,
                      "checked_at": NOW} for account, plan in (("default", "Max"),
                                                               ("second", "Pro"))}})
        self.history = History(self.home)
        # Max's week rose 20 points for $4, so it holds $20; Pro's 50 for $5, so $10
        for account, tokens, points, plan in (("default", 4e6, 20, "Max"),
                                              ("second", 5e6, 50, "Pro")):
            meter.week("acme", account, used=50)
            self.history.week("acme", account, "echo", "anvil-1", tokens, points, plan)

    def answer(self):
        """(each login's `week_listed_usd`, `ak models --json`), the history saved first."""
        self.history.save()
        usage = self.home.ak("usage", "--json", env=ENV)
        self.assertEqual(usage.code, 0, usage.out + usage.err)
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        return ({account: found["week_listed_usd"] for account, found in
                 json.loads(usage.out)["providers"]["acme"]["accounts"].items()},
                json.loads(done.out))

    def points(self, weeks, *turns):
        """The points of a week the rows of `turns` took, each at listed prices on its login's."""
        return sum(100 * sum(count * price for count, price in zip(counts, RELEASES[model][0]))
                   / 1e6 / weeks[account]
                   for rows in turns for account, model, counts in rows)

    def assertCost(self, answer, role, release, rule, cost):
        row = next(row for row in answer[role]["front"] if row["release"] == release)
        self.assertEqual(row["cost_rule"], rule)
        self.assertAlmostEqual(row["cost"], cost)

    def test_each_role_costs_the_mean_of_its_runs_points_and_a_lower_one_changes_the_pick(self):
        one = [("default", "anvil-1", (1_000_000, 0, 2_000_000, 100_000))]
        two = [("default", "anvil-1", (500_000, 200_000, 0, 0))]
        three = [("second", "anvil-1", (100_000, 0, 0, 20_000)),
                 ("second", "bloom-1", (100_000, 0, 50_000, 0))]
        review = [("second", "bloom-1", (200_000, 0, 0, 30_000))]
        self.history.run(("anvil", "high"), "bloom", ["high"], built=[one], reviewed=[review])
        self.history.run(("anvil", "high"), built=[two, three])
        weeks, answer = self.answer()
        self.assertEqual(weeks, {"default": 20, "second": 10})
        executor = (self.points(weeks, one) + self.points(weeks, two, three)) / 2
        self.assertAlmostEqual(answer["task_usage"]["anvil"]["high"]["executor"], executor)
        self.assertCost(answer, "execute", "anvil-1", "measured", executor)
        self.assertCost(answer, "review", "bloom-1", "measured", self.points(weeks, review))
        # Crown ran nothing: its board dollars, 40, scaled as Anvil's measured share scales its 10
        self.assertCost(answer, "execute", "crown-1", "provider", 40 * executor / 10)
        # ... as every row is, so the boards' dollars pick, until Bloom's run takes what Anvil's
        # do, where its board dollars said 38 to Anvil's 10
        pick = lambda answer: next(row["release"] for row in answer["execute"]["front"]
                                   if "pick" in row["notes"])
        self.assertEqual(pick(answer), "anvil-1")
        self.history.run(("bloom", "high"), built=[[("default", "bloom-1", (750_000, 0, 0, 0))]])
        self.assertEqual(pick(self.answer()[1]), "bloom-1")

    def test_a_turn_without_rows_or_a_row_without_a_price_adds_nothing(self):
        kept = [("default", "anvil-1", (2_000_000, 0, 0, 0))]
        review = [("second", "bloom-1", (100_000, 0, 0, 0))]
        self.history.run(("anvil", "high"), "bloom", ["high"], built=[kept], reviewed=[review])
        self.history.run(("anvil", "high"), built=[kept, None])
        self.history.run(("anvil", "high"), built=[kept + [("default", "easel-2", (1, 0, 0, 0))]])
        # its reviews name two efforts: no reviewer's
        self.history.run(None, "bloom", ["high", "low"], reviewed=[review + review])
        self.history.run(("anvil", "high"), built=[kept, kept], ended=False)
        weeks, answer = self.answer()
        found = answer["task_usage"]
        self.assertEqual({model: {effort: list(roles) for effort, roles in efforts.items()}
                          for model, efforts in found.items()},
                         {"anvil": {"high": ["executor"]}, "bloom": {"high": ["reviewer"]}})
        self.assertAlmostEqual(found["anvil"]["high"]["executor"], self.points(weeks, kept))
        self.assertAlmostEqual(found["bloom"]["high"]["reviewer"], self.points(weeks, review))

    def test_a_run_a_turn_of_which_ran_another_model_counts_for_nothing_in_that_role(self):
        # its first turn ran Bloom alone, of Anvil's provider, though the run names Anvil
        bloom = [("default", "bloom-1", (2_000_000, 0, 0, 0))]
        anvil = [("default", "anvil-1", (1_000_000, 0, 0, 0))]
        review = [("second", "bloom-1", (100_000, 0, 0, 0))]
        self.history.run(("anvil", "high"), "bloom", ["high"], built=[bloom, anvil],
                         reviewed=[review])
        # each turn names Anvil beside a subagent's Bloom: counted whole, as its owner left a
        # role then handed on to that subagent's model (spend.roles)
        beside = anvil + [("default", "bloom-1", (300_000, 0, 0, 0))]
        self.history.run(("anvil", "high"), built=[beside, beside])
        weeks, answer = self.answer()
        found = answer["task_usage"]
        self.assertAlmostEqual(found["anvil"]["high"]["executor"],
                               self.points(weeks, beside, beside))
        self.assertAlmostEqual(found["bloom"]["high"]["reviewer"], self.points(weeks, review))

    def test_a_measured_cost_is_in_dollars_of_the_plans_its_providers_logins_hold(self):
        with open(self.meter.dir / "echo.toml", "a") as toml:
            toml.write("\n[plans]\nMax = 100\nPro = 20\nTeam = 100\n")
        # bolt's models run on a copy of it, `chime`, as a harness's spend is a provider's only
        # where it runs that provider's models alone
        for suffix in (".sh", ".toml"):
            shutil.copy2(self.meter.dir / f"echo{suffix}", self.meter.dir / f"chime{suffix}")
        # bolt has no usual login: its one, named, is on Pro, and its week holds $20
        akconfig.write(self.home, {"anvil": {"harness": "echo", "model": "anvil-1"},
                                   "crown": {"harness": "chime", "model": "crown-1",
                                             "provider": "bolt"}},
                       settings={"companies": ["Acme"]},
                       providers={"acme": {"mode": "subscription",
                                           "accounts": ["default", "second", "third"]},
                                  "bolt": {"mode": "subscription", "accounts": ["work"]}})
        logins = json.loads((self.home.path / ".agentkit/state/logins.json").read_text())
        # acme's third login is on Team, a plan no reading has fitted a week of: out of the
        # mean until one has, as its owner left it (matrix._costs)
        logins["acme"]["third"] = {"email": "third@acme.test", "ends": None, "plan": "Team",
                                   "checked_at": NOW}
        logins["bolt"] = {"work": {"email": "work@bolt.test", "ends": None, "plan": "Pro",
                                   "checked_at": NOW}}
        self.home.write(".agentkit/state/logins.json", logins)
        self.meter.week("bolt", "work", used=50)
        self.history.week("bolt", "work", "chime", "crown-1", 2.5e6, 50, "Pro")
        self.history.run(("anvil", "high"), built=[[("default", "anvil-1", (200_000, 0, 0, 0))]])
        self.history.run(("crown", "high"), built=[[("work", "crown-1", (500_000, 0, 0, 0))]])
        answer = self.answer()[1]
        self.assertEqual(answer["execute"]["cost_unit"], "money")
        share = lambda model: answer["task_usage"][model]["high"]["executor"]
        # acme's logins with a week are on Max and Pro: $60 a month, though its usual one is on Max
        for release, model, price in (("anvil-1", "anvil", 60), ("crown-1", "crown", 20)):
            self.assertCost(answer, "execute", release, "measured",
                            share(model) / 100 * price * 12 / 52)

    def test_oversized_prices_never_crash_or_emit_infinity(self):
        def invalid_constant(value):
            raise ValueError(value)

        large_int = "0x1" + "0" * 256
        config_path = self.home.path / ".agentkit/config.toml"
        manifest_path = self.meter.dir / "echo.toml"
        base_config, base_manifest = config_path.read_text(), manifest_path.read_text()
        self.history.run(("anvil", "high"), built=[[("default", "anvil-1", (2_000_000, 0, 0, 0))]])
        self.history.save()
        for source in ("provider", "by_login", "manifest"):
            for amount, unit in ((large_int, "share"), ("1e308", "money")):
                with self.subTest(source=source, amount=amount):
                    if source == "manifest":
                        config_path.write_text(base_config)
                        manifest_path.write_text(base_manifest + f"\n[plans]\nMax = {amount}\n")
                    else:
                        manifest_path.write_text(base_manifest)
                        price = amount if source == "provider" else f"{{ default = {amount} }}"
                        header = '[providers."acme"]'
                        config_path.write_text(base_config.replace(header,
                                                                   f"{header}\nprice = {price}"))
                    usage_done = self.home.ak("usage", "--json", env=ENV)
                    self.assertEqual(usage_done.code, 0, usage_done.out + usage_done.err)
                    json.loads(usage_done.out, parse_constant=invalid_constant)
                    done = self.home.ak("models", "--json", env=ENV)
                    self.assertEqual(done.code, 0, done.out + done.err)
                    parsed = json.loads(done.out, parse_constant=invalid_constant)
                    self.assertEqual(parsed["execute"]["cost_unit"], unit)
                    anvil = next(row for row in parsed["execute"]["front"]
                                 if row["release"] == "anvil-1")
                    self.assertEqual(anvil["cost_rule"], "measured")
                    want = (10 if unit == "share" else 1e308 * (12 / 52) / 100 * 10)
                    self.assertAlmostEqual(anvil["cost"], want, delta=want * 1e-6)
        # a run whose weekly share times a huge price overflows a float leaves no Infinity in JSON
        config_path.write_text(base_config.replace('[providers."acme"]',
                                                   '[providers."acme"]\nprice = 1e308'))
        manifest_path.write_text(base_manifest)
        self.history.rows["runs"].clear()
        self.history.rows["turn_usage"].clear()
        self.history.run(("anvil", "high"),
                         built=[[("default", "anvil-1", (2_000_000_000, 0, 0, 0))]])
        self.history.save()
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        parsed = json.loads(done.out, parse_constant=invalid_constant)
        self.assertEqual(parsed["execute"]["cost_unit"], "money")
        self.assertEqual(parsed["execute"]["front"], [])
        self.assertTrue(all(row["cost"] is None for row in parsed["execute"]["others"]))


if __name__ == "__main__":
    unittest.main()
