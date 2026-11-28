"""`ak usage --json` gives each login under `providers.<provider>.accounts` its `plan`, as
state/logins.json names it now, and what a week of that plan holds in listed dollars,
`week_listed_usd`: 100 over the plan's points of a week a listed dollar takes, null where its
rises sum to under ten points or its spend to 0, infinite where 100 times its spend is past a
float's largest, with those two sums, `plan_points` and `plan_listed_usd`.

A plan's sums are read from the last seven days of every login of its provider: the readings
its probes kept of its shared week, a model's own cap of that name (`scope`) none of them nor
one whose `used` or `resets_at` is no number, a reading with no plan its login's plan now's,
grouped by login, plan and week, a reading's `resets_at` within ten minutes of the one before
it in the same week.  A group rose from its earliest reading to its highest, and the spend that
bought that rise is the login's rows priced at listed prices from the earliest reading to the
first at the highest; a group whose spend cannot be priced counts for nothing.  No week is
counted in tokens: a login carries no `capacity_tokens`, `capacity_pairs` or `price_per_1m`.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, with an invented board, plans, readings and token rows
written into its Home.  Fails against /bin/false.
"""

from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home

NOW = time.time()
HOUR, DAY = 3600, 86400
# two weeks' resets, both far from the one the meter fixture reads now, a day off
WEEK, LAST_WEEK = NOW + 3 * DAY, NOW - 2 * DAY
# Anvil lists a dollar a million input tokens and Forge 1e300; Easel is on no board
BOARD = {"artificialanalysis.ai": {"asked_at": NOW, "fetched_at": NOW, "error": None, "build": "",
                                   "rows": [{"model": name, "effort": "high",
                                             "maker": "Acme", "deprecated": False,
                                             "slug": slug,
                                             "values": {"aa.price1mInputTokens": price,
                                                        "aa.price1mOutputTokens": 5},
                                             "release": {"slug": slug, "name": name,
                                                         "deprecatedTo": None}}
                                            for name, slug, price in (
                                                ("Anvil 1", "anvil-1", 1),
                                                ("Forge 1", "forge-1", 1e300))]}}
SEAT_USAGE = ("CREATE TABLE seat_usage (event TEXT PRIMARY KEY, repo TEXT, at REAL, "
              "tokens INTEGER, account TEXT, model TEXT, input INTEGER, cache_write INTEGER, "
              "cache_read INTEGER, output INTEGER)")
METER_READINGS = ("CREATE TABLE meter_readings (provider TEXT, account TEXT, meter TEXT, "
                  "used REAL, resets_at REAL, window_secs REAL, at REAL, source TEXT, "
                  "plan TEXT, PRIMARY KEY (provider, account, meter, at))")
ACCOUNTS = ("default", "second", "third")


class WeekPrice(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for account in ACCOUNTS:
            meter.week("acme", account, used=50)
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription",
                                           "accounts": list(ACCOUNTS)}})
        self.home.write(".agentkit/state/boards.json", BOARD)
        self.seats, self.readings = [], []

    def plans(self, **plans):
        """Each login's plan now, as its harness last answered."""
        self.home.write(".agentkit/state/logins.json", {"acme": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": plan,
                      "checked_at": NOW} for account, plan in plans.items()}})

    def spent(self, account, dollars, ago, model="anvil-1"):
        """A seat's row of the login: `dollars` million input tokens."""
        self.seats.append((f"echo:event-{len(self.seats)}", "acme-repo", NOW - ago,
                           dollars * 1_000_000, account, model, dollars * 1_000_000, 0, 0, 0))

    def read(self, account, used, ago, resets, *, plan, source="probe", scope=None):
        """A reading of the login's shared week, kept with `plan`, or of `scope`'s own cap of
        its name."""
        self.readings.append(("acme", account, "weekly", used, resets, 7 * DAY, NOW - ago,
                              source, plan, scope))

    def weeks(self):
        """Each login's (plan, week_listed_usd, plan_points, plan_listed_usd), the rows written
        into history.db first."""
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            db.execute(SEAT_USAGE)
            db.execute(METER_READINGS)
            db.execute("ALTER TABLE meter_readings ADD COLUMN scope TEXT")
            db.executemany(f"INSERT INTO seat_usage VALUES ({', '.join('?' * 10)})", self.seats)
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 10)})",
                           self.readings)
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        accounts = json.loads(done.out)["providers"]["acme"]["accounts"]
        return {account: tuple(accounts[account][key] for key in (
            "plan", "week_listed_usd", "plan_points", "plan_listed_usd"))
                for account in ACCOUNTS}

    def assertWeek(self, got, plan, week, points, dollars):
        self.assertEqual(got[0], plan)
        if week is None:
            self.assertIsNone(got[1])
        else:
            self.assertAlmostEqual(got[1], week)
        self.assertAlmostEqual(got[2], points)
        self.assertAlmostEqual(got[3], dollars)

    def test_two_logins_on_one_plan_give_one_number_from_both(self):
        self.plans(default="Max", second="Max")
        # this week, its reset drifting minutes from one reading to the next: 10 -> 30
        self.read("default", 10, 40 * HOUR, WEEK, plan="Max")
        self.spent("default", 3, 37 * HOUR)
        self.read("default", 20, 35 * HOUR, WEEK + 400, plan="Max")
        self.spent("default", 1, 32 * HOUR)
        self.read("default", 30, 30 * HOUR, WEEK + 800, plan="Max")
        self.spent("default", 50, 25 * HOUR)    # after the highest
        self.read("default", 25, 20 * HOUR, WEEK + 900, plan="Max")
        self.read("default", 45, 19 * HOUR, WEEK + 900, plan="Max", source="turn")
        self.read("default", 28, 10 * HOUR, WEEK + 1000, plan="Max")
        # last week: 50 -> 90
        self.read("default", 50, 6.5 * DAY, LAST_WEEK, plan="Max")
        self.spent("default", 8, 5 * DAY)
        self.read("default", 90, 4 * DAY, LAST_WEEK, plan="Max")
        # the other login this week: 5 -> 25
        self.read("second", 2, 45 * HOUR, WEEK, plan="Max", source="turn")
        self.spent("second", 20, 44.5 * HOUR)   # before its first probe
        self.read("second", 5, 44 * HOUR, WEEK, plan="Max")
        self.spent("second", 6, 30 * HOUR)
        self.read("second", 25, 20 * HOUR, WEEK, plan="Max")
        self.read("second", 24, 15 * HOUR, WEEK, plan="Max")
        weeks = self.weeks()
        # 80 points for $18
        self.assertWeek(weeks["default"], "Max", 22.5, 80, 18)
        self.assertWeek(weeks["second"], "Max", 22.5, 80, 18)

    def test_a_new_plan_is_fitted_apart_and_a_reading_with_no_plan_is_its_logins_plan_now(self):
        self.plans(default="Max", second="Pro")
        # last week, before readings kept a plan: 0 -> 20 for $2, the Max it is on now
        self.read("default", 0, 6 * DAY, LAST_WEEK, plan=None)
        self.spent("default", 2, 5.5 * DAY)
        self.read("default", 20, 5 * DAY, LAST_WEEK, plan=None)
        # this week on Pro: 10 -> 40 for $3
        self.read("default", 10, 60 * HOUR, WEEK, plan="Pro")
        self.spent("default", 3, 55 * HOUR)
        self.read("default", 40, 50 * HOUR, WEEK, plan="Pro")
        self.spent("default", 100, 45 * HOUR)   # between the plans
        # ... then on Max: 40 -> 70 for $6
        self.read("default", 40, 40 * HOUR, WEEK, plan="Max")
        self.read("default", 45, 30 * HOUR, WEEK, plan="Max")
        self.spent("default", 6, 25 * HOUR)
        self.read("default", 70, 20 * HOUR, WEEK, plan="Max")
        weeks = self.weeks()
        self.assertWeek(weeks["default"], "Max", 16, 50, 8)
        # a login new to Pro has its number from the first login's readings on it
        self.assertWeek(weeks["second"], "Pro", 10, 30, 3)

    def test_a_spend_that_cannot_be_priced_counts_for_nothing_and_no_rise_gives_null(self):
        self.plans(default="Max", second="Pro")
        self.read("default", 10, 6 * DAY, LAST_WEEK, plan="Max")
        self.spent("default", 5, 5.5 * DAY)
        self.read("default", 30, 5 * DAY, LAST_WEEK, plan="Max")
        # a rise bought with a model no board prices
        self.read("default", 0, 60 * HOUR, WEEK, plan="Max")
        self.spent("default", 2, 55 * HOUR, model="easel-2")
        self.read("default", 30, 50 * HOUR, WEEK, plan="Max")
        # spent, but its week read no higher than it began
        self.read("second", 40, 50 * HOUR, WEEK, plan="Pro")
        self.spent("second", 4, 45 * HOUR)
        self.read("second", 36, 40 * HOUR, WEEK, plan="Pro")
        self.read("second", 40, 30 * HOUR, WEEK, plan="Pro")
        weeks = self.weeks()
        self.assertWeek(weeks["default"], "Max", 25, 20, 5)
        self.assertWeek(weeks["second"], "Pro", None, 0, 0)

    def test_a_models_own_cap_of_the_weeks_name_is_no_reading_of_it(self):
        self.plans(default="Max")
        # the shared week 10 -> 20 for $2, then Anvil's own cap of its name reads 50
        self.read("default", 10, 40 * HOUR, WEEK, plan="Max")
        self.spent("default", 2, 35 * HOUR)
        self.read("default", 20, 30 * HOUR, WEEK, plan="Max")
        self.spent("default", 3, 25 * HOUR)
        self.read("default", 50, 20 * HOUR, WEEK, plan="Max", scope="Anvil")
        self.assertWeek(self.weeks()["default"], "Max", 20, 10, 2)

    def test_a_reading_whose_use_or_reset_is_no_number_is_no_reading(self):
        self.plans(default="Max")
        # 10 -> 30 for $2, a probe's `nan` kept as text before, amid and after it, then 90 kept
        # with a reset of text
        self.read("default", "nan", 45 * HOUR, WEEK, plan="Max")
        self.read("default", 10, 40 * HOUR, WEEK, plan="Max")
        self.spent("default", 2, 35 * HOUR)
        self.read("default", "nan", 32 * HOUR, WEEK, plan="Max")
        self.read("default", 30, 30 * HOUR, WEEK, plan="Max")
        self.read("default", "nan", 28 * HOUR, WEEK, plan="Max")
        self.read("default", 90, 25 * HOUR, "soon", plan="Max")
        self.assertWeek(self.weeks()["default"], "Max", 10, 20, 2)

    def test_a_plan_read_from_fewer_than_ten_points_holds_no_week(self):
        self.plans(default="Max", second="Pro")
        # 10 -> 19 for $3: nine points, too few to name a week
        self.read("default", 10, 40 * HOUR, WEEK, plan="Max")
        self.spent("default", 3, 35 * HOUR)
        self.read("default", 19, 30 * HOUR, WEEK, plan="Max")
        # 10 -> 20 for $2: ten, enough
        self.read("second", 10, 40 * HOUR, WEEK, plan="Pro")
        self.spent("second", 2, 35 * HOUR)
        self.read("second", 20, 30 * HOUR, WEEK, plan="Pro")
        weeks = self.weeks()
        self.assertWeek(weeks["default"], "Max", None, 9, 3)
        self.assertWeek(weeks["second"], "Pro", 20, 10, 2)

    def test_a_spend_within_two_digits_of_a_floats_largest_holds_an_infinite_week(self):
        self.plans(default="Max", second="Max")
        # 10 -> 30 for $2e306, Easel's tokens costing what Forge's do: times 100, no float holds it
        self.read("default", 10, 40 * HOUR, WEEK, plan="Max")
        self.spent("default", 1, 36 * HOUR, model="forge-1")
        self.spent("default", 1_999_999, 35 * HOUR, model="easel-2")
        self.read("default", 30, 30 * HOUR, WEEK, plan="Max")
        self.assertWeek(self.weeks()["default"], "Max", math.inf, 20, 2e306)

    def test_no_week_is_counted_in_tokens(self):
        # a login whose week is read, one sharing that week on its plan, one whose plan has none
        self.plans(default="Max", second="Max", third="Pro")
        self.read("default", 10, 40 * HOUR, WEEK, plan="Max")
        self.spent("default", 3, 35 * HOUR)
        self.read("default", 40, 30 * HOUR, WEEK, plan="Max")
        weeks = self.weeks()
        for account in ("default", "second"):
            self.assertWeek(weeks[account], "Max", 10, 30, 3)
        self.assertWeek(weeks["third"], "Pro", None, 0, 0)
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        for account, record in json.loads(done.out)["providers"]["acme"]["accounts"].items():
            with self.subTest(account):
                self.assertEqual({"capacity_tokens", "capacity_pairs", "price_per_1m"}
                                 & set(record), set())


if __name__ == "__main__":
    unittest.main()
