"""What a point of a model's own cap takes from its login's shared week (`cap_share.of`): the least
`(a + 1) / (f - 1)` over every stretch of every login on the plan whose cap rose `f` above 1 beside
a week rise `a`, with no reading between the stretch's ends where either meter fell.

In a Home of tests/fixtures/akbin.py with a read-only history.db of invented readings, a child
python3 asks `cap_share.of`.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, REPO

NOW = time.time()
HOUR, DAY = 3600, 86400
SCHEMA = ("CREATE TABLE meter_readings (provider TEXT, account TEXT, meter TEXT, used REAL, "
          "resets_at REAL, window_secs REAL, at REAL, source TEXT, plan TEXT, scope TEXT, "
          "PRIMARY KEY (provider, account, meter, at))")
ASK = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import cap_share; "
       "print(json.dumps(cap_share.of(sys.argv[2], sys.argv[3], sys.argv[4])))")


class ACapsShareOfItsWeek(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription",
                                           "accounts": ["default", "second"]}})
        week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
        cap = {"name": "weekly_cap", "used": 20, "window_secs": 7 * DAY, "resets_at": NOW + DAY,
               "scope": "Anvil"}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
            "acme": {"accounts": {account: {"meters": [week, cap]}
                                  for account in ("default", "second")}}}})
        self.rows = []

    def pair(self, step, week, cap, *, plan="Max", account="default", source="probe"):
        """One reading of both the login's shared week and Anvil's cap at `step`."""
        self.one(step, "weekly", week, plan=plan, account=account, scope=None, source=source)
        self.one(step, "weekly_cap", cap, plan=plan, account=account, scope="Anvil", source=source)

    def one(self, step, meter, used, *, plan="Max", account="default", scope=None, source="probe"):
        """One row of `meter` at `step`."""
        self.rows.append(("acme", account, meter, used, NOW + DAY, 7 * DAY,
                          NOW - (100 - step) * HOUR, source, plan, scope))

    def share(self, plan, scope="Anvil"):
        """`cap_share.of('acme', plan, scope)` against a read-only history.db holding `self.rows`."""
        path = self.home.path / ".agentkit/history.db"
        if path.exists():
            path.chmod(0o644)
            path.unlink()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(SCHEMA)
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 10)})", self.rows)
        path.chmod(0o444)
        done = self.home.run(sys.executable, "-c", ASK, str(REPO), "acme", plan, scope)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def test_a_stretch_beside_other_models_gives_its_ceiling(self):
        for step, (week, cap) in enumerate((
                (0, 0),
                (15, 0),    # another model ran alone
                (15, 0),    # neither meter moved
                (29, 28),   # halfway through the 28 beside 57 stretch
                (43, 57),   # 28 beside 57 from step 1
                (43, 57),   # neither meter moved
                (73, 60),   # another model ran alongside
        )):
            self.pair(step, week, cap)
        self.assertEqual(self.share("Max"), 29 / 56)

    def test_no_stretch_crosses_a_reading_where_a_meter_fell(self):
        # week and cap both fall at step 2 (kept by a turn); crossing step 0 -> step 3 gives 11/44
        for step, (week, cap, source) in enumerate((
                (50, 0, "probe"), (70, 10, "probe"), (20, 5, "turn"), (60, 45, "probe"))):
            self.pair(step, week, cap, plan="Max", source=source)
        # only the cap falls at step 2; crossing step 0 -> step 3 would give 11/20 < 11/19
        for step, (week, cap) in enumerate(((0, 0), (10, 20), (10, 19), (10, 21))):
            self.pair(step, week, cap, plan="Pro", account="second")
        # only the week falls at step 11 while the cap rises; pairing across it would be negative
        for step, (week, cap) in enumerate(((80, 10), (10, 20), (20, 30)), 10):
            self.pair(step, week, cap, plan="Plus")
        self.assertEqual(self.share("Max"), 41 / 39)
        self.assertEqual(self.share("Pro"), 11 / 19)
        self.assertEqual(self.share("Plus"), 11 / 9)

    def test_the_least_over_a_plans_logins_wins_and_another_plan_changes_nothing(self):
        self.pair(1, 0, 0, plan="Max", account="default")
        self.pair(2, 10, 10, plan="Max", account="default")
        self.pair(1, 5, 10, plan="Max", account="second", source="turn")
        self.pair(2, 19, 40, plan="Max", account="second", source="turn")
        self.pair(3, 0, 0, plan="Pro", account="default")
        self.pair(4, 0, 50, plan="Pro", account="default")
        self.assertEqual(self.share("Max"), 15 / 29)
        self.assertEqual(self.share("Pro"), 1 / 49)

    def test_missing_pair_or_cap_rise_under_two_gives_none(self):
        # never holds both meters at one moment
        self.one(1, "weekly", 10, plan="Max")
        self.one(2, "weekly", 30, plan="Max")
        self.one(3, "weekly_cap", 0, plan="Max", scope="Anvil")
        self.one(4, "weekly_cap", 40, plan="Max", scope="Anvil")
        # holds both meters, but the cap never rises above 1 in any stretch
        for step, (week, cap) in enumerate(((10, 5), (12, 6), (0, 0), (5, 1))):
            self.pair(step, week, cap, plan="Pro", account="second")
        self.assertIsNone(self.share("Max"))
        self.assertIsNone(self.share("Pro"))


if __name__ == "__main__":
    unittest.main()
