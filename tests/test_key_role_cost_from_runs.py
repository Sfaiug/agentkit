"""`ak models --json` prices a model's role at an effort (`task_usage`, its row's measured `cost`)
at the mean over the task runs that ended where it did it of the points of a week its `turn_usage`
rows took: at listed prices, times 100 over each row's login's `week_listed_usd` (`ak usage
--json`).  A counted turn with no row, or a row with no listed price, leaves its run out of the
role, reviews naming two efforts out of the reviewer's; a model with no runs keeps its estimate.

Black-box through tests/fixtures/akbin.py on tests/fixtures/meters.py's harness, with invented
boards, plans, readings, seat spend and finished runs in its Home.  Fails against /bin/false.
"""

from contextlib import closing
import json
from pathlib import Path
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

    def run(self, executor=None, reviewer=None, efforts=(), *, built=(), reviewed=()):
        """A task run that ended: `executor` (model, effort) built it in a counted turn per list
        of `built`, `reviewer` reviewed it in one per list of `reviewed`, a review per effort of
        `efforts`.  A list holds its turn's rows, (account, model, counts); None, no row."""
        run, turns = f"fix-api-{len(self.rows['runs'])}", []
        for role, kept in (("executor", built), ("reviewer", reviewed)):
            for n, rows in enumerate(kept):
                turns.append(str(self.home.path / f".agentkit/runs/{run}/round-{n + 1}/{role}"))
                self.rows["turn_usage"] += [(turns[-1], run, role, account, model, NOW - DAY,
                                             NOW - DAY, *counts) for account, model, counts
                                            in rows or ()]
        self.rows["runs"].append((run, *(executor or (None, None)), reviewer, "task", NOW - DAY,
                                  json.dumps(turns)))
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
        meter = meters.install(self.home)
        akconfig.write(self.home, {name: {"harness": "echo", "model": f"{name}-1"}
                                   for name in ("anvil", "bloom", "crown")},
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
        weeks, answer = self.answer()
        found = answer["task_usage"]
        self.assertEqual({model: {effort: list(roles) for effort, roles in efforts.items()}
                          for model, efforts in found.items()},
                         {"anvil": {"high": ["executor"]}, "bloom": {"high": ["reviewer"]}})
        self.assertAlmostEqual(found["anvil"]["high"]["executor"], self.points(weeks, kept))
        self.assertAlmostEqual(found["bloom"]["high"]["reviewer"], self.points(weeks, review))


if __name__ == "__main__":
    unittest.main()
