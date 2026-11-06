"""`ak usage --json` checks each plan's week against the meter day by day: each login under
`providers.<provider>.accounts` has `plan_checks`, oldest first, one of each of the last seven
days, the 24 hours up to its `until` a whole number of days before now, that its plan rose and
had a week in the seven days before:

- `rose`: the points its plan's meters rose by that day, as tests/test_key_week_price.py reads
  `plan_points` from that day's readings alone;
- `predicted`: what that rise was bought with that day (`plan_listed_usd`), times 100, over the
  plan's `week_listed_usd` from the seven days before that day.

A day its plan rose by nothing, or had no week in the seven days before, counts for nothing;
a login whose plan no day checks has an empty list.  Each plan is checked against its own week,
so an upgrade's days are checked only once the new plan has a week.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, with an invented board, plans, readings and token rows
written into its Home.  Fails against /bin/false.
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
from test_key_week_price import BOARD, METER_READINGS, SEAT_USAGE

NOW = time.time()
HOUR, DAY = 3600, 86400
# two weeks' resets, the later far from the one the meter fixture reads now; every reading below
# is hours from a day's end
WEEK, LAST_WEEK = NOW + 3 * DAY, NOW - 4 * DAY


class WeekChecked(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for account in ("default", "second"):
            meter.week("acme", account, used=50)
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription",
                                           "accounts": ["default", "second"]}})
        self.home.write(".agentkit/state/boards.json", BOARD)
        self.seats, self.readings = [], []

    def plans(self, **plans):
        """Each login's plan now, as its harness last answered."""
        self.home.write(".agentkit/state/logins.json", {"acme": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": plan,
                      "checked_at": NOW} for account, plan in plans.items()}})

    def spent(self, account, dollars, ago):
        """A seat's row of the login `ago` hours ago: `dollars` million input tokens."""
        self.seats.append((f"echo:event-{len(self.seats)}", "acme-repo", NOW - ago * HOUR,
                           dollars * 1_000_000, account, "anvil-1", dollars * 1_000_000, 0, 0, 0))

    def read(self, account, used, ago, *, plan):
        """A probe's reading of the login's shared week `ago` hours ago, kept with `plan`."""
        resets = LAST_WEEK if NOW - ago * HOUR < LAST_WEEK else WEEK
        self.readings.append(("acme", account, "weekly", used, resets, 7 * DAY,
                              NOW - ago * HOUR, "probe", plan))

    def checks(self):
        """Each login's checks as (days before now its day ended, rose, predicted), the rows
        written into history.db first."""
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            db.execute(SEAT_USAGE)
            db.execute(METER_READINGS)
            db.executemany(f"INSERT INTO seat_usage VALUES ({', '.join('?' * 10)})", self.seats)
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 9)})",
                           self.readings)
        started = time.time()
        done = self.home.ak("usage", "--json")
        ended = time.time()
        self.assertEqual(done.code, 0, done.out + done.err)
        accounts = json.loads(done.out)["providers"]["acme"]["accounts"]
        found = {}
        for account in ("default", "second"):
            found[account] = []
            for check in accounts[account]["plan_checks"]:
                days = round((started - check["until"]) / DAY)
                # its day ended that many days before a now ak took while it ran
                self.assertTrue(started < check["until"] + days * DAY < ended, check)
                found[account].append((days, check["rose"], check["predicted"]))
        return found

    def assertChecks(self, got, *want):
        self.assertEqual([days for days, *_ in got], [days for days, *_ in want], got)
        for (_, rose, predicted), (_, risen, foretold) in zip(got, want):
            self.assertAlmostEqual(rose, risen)
            self.assertAlmostEqual(predicted, foretold)

    def test_each_day_is_its_rise_against_its_spend_at_the_week_before_it(self):
        self.plans(default="Max", second="Pro")
        # nine days ago: 0 -> 20 for $4
        self.read("default", 0, 234, plan="Max")
        self.spent("default", 4, 228)
        self.read("default", 20, 222, plan="Max")
        # six days ago: 20 -> 32 for $2, at the week of 20 points for $4 before it: 10
        self.read("default", 20, 162, plan="Max")
        self.spent("default", 2, 156)
        self.read("default", 32, 150, plan="Max")
        # three days ago, its week anew: 0 -> 15 for $3, at 32 points for $6 before it: 16
        self.read("default", 0, 90, plan="Max")
        self.spent("default", 3, 84)
        self.read("default", 15, 78, plan="Max")
        # a day ago: 15 -> 40 for $5, at 12 + 15 points for $2 + $3 before it: 27
        self.read("default", 15, 42, plan="Max")
        self.spent("default", 5, 36)
        self.read("default", 40, 30, plan="Max")
        checks = self.checks()
        self.assertChecks(checks["default"], (6, 12, 10), (3, 15, 16), (1, 25, 27))
        self.assertChecks(checks["second"])

    def test_a_day_its_plan_rose_by_nothing_or_had_no_week_before_counts_for_nothing(self):
        self.plans(default="Max", second="Pro")
        # a week of 20 points for $4, then a day spent that read no higher than it began
        self.read("default", 0, 234, plan="Max")
        self.spent("default", 4, 228)
        self.read("default", 20, 222, plan="Max")
        self.read("default", 20, 138, plan="Max")
        self.spent("default", 1, 132)
        self.read("default", 19, 126, plan="Max")
        # a rise of 20 for $2 two days ago with no week before it, then 8 for $1 today at it: 10
        self.read("second", 10, 66, plan="Pro")
        self.spent("second", 2, 60)
        self.read("second", 30, 54, plan="Pro")
        self.read("second", 30, 18, plan="Pro")
        self.spent("second", 1, 12)
        self.read("second", 38, 6, plan="Pro")
        checks = self.checks()
        self.assertChecks(checks["default"])
        self.assertChecks(checks["second"], (0, 8, 10))

    def test_each_plan_is_checked_against_its_own_week(self):
        self.plans(default="Max", second="Pro")
        # on Pro: a week of 20 points for $4, then 20 -> 32 for $2 four days ago at it: 10
        self.read("default", 0, 234, plan="Pro")
        self.spent("default", 4, 228)
        self.read("default", 20, 222, plan="Pro")
        self.read("default", 20, 114, plan="Pro")
        self.spent("default", 2, 108)
        self.read("default", 32, 102, plan="Pro")
        # upgraded to Max: 0 -> 30 for $3 three days ago, with no week of Max before it ...
        self.read("default", 0, 90, plan="Max")
        self.spent("default", 3, 84)
        self.read("default", 30, 78, plan="Max")
        # ... then 30 -> 55 for $5 a day ago at Max's 30 points for $3: 50, where Pro's would
        # say 30
        self.read("default", 30, 42, plan="Max")
        self.spent("default", 5, 36)
        self.read("default", 55, 30, plan="Max")
        checks = self.checks()
        self.assertChecks(checks["default"], (1, 25, 50))
        self.assertChecks(checks["second"], (4, 12, 10))


if __name__ == "__main__":
    unittest.main()
