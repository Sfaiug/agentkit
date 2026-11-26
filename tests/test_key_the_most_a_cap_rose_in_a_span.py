"""The most a model's own cap has been seen to rise in a span of time (`cap_share.most`): the
largest rise between two readings of one login on the plan no further apart than `seconds`, with
no reading between them in which the cap fell, or None where no login's kept readings reach
`seconds` apart.

In a Home of tests/fixtures/akbin.py with a read-only history.db of invented readings, a child
python3 asks `cap_share.most`.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, REPO

NOW = time.time()
HOUR, DAY = 3600, 86400
SCHEMA = ("CREATE TABLE meter_readings (provider TEXT, account TEXT, meter TEXT, used REAL, "
          "resets_at REAL, window_secs REAL, at REAL, source TEXT, plan TEXT, scope TEXT, "
          "PRIMARY KEY (provider, account, meter, at))")
ASK = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import cap_share; "
       "print(json.dumps(cap_share.most(sys.argv[2], sys.argv[3], sys.argv[4], "
       "json.loads(sys.argv[5]))))")


class TheMostACapRoseInASpan(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rows = []

    def reading(self, hour, used, *, plan="Max", scope="Anvil", account="default",
                meter="weekly_cap", source="probe"):
        """One row of `meter` at `hour`."""
        self.rows.append(("acme", account, meter, used, NOW + DAY, 7 * DAY,
                          NOW - (100 - hour) * HOUR, source, plan, scope))

    def most(self, plan, seconds, scope="Anvil"):
        """`cap_share.most('acme', plan, scope, seconds)` against a read-only history.db."""
        path = self.home.path / ".agentkit/history.db"
        if path.exists():
            path.chmod(0o644)
            path.unlink()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(SCHEMA)
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 10)})", self.rows)
        path.chmod(0o444)
        done = self.home.run(sys.executable, "-c", ASK, str(REPO),
                             "acme", plan, scope, json.dumps(seconds))
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)

    def test_largest_rise_within_the_span_wins_not_a_larger_one_over_a_longer_span(self):
        # 0->5h rises 55 and 0->7h rises 70, both longer than 4h; 3->7h (exactly 4h, from a flat
        # reading) rises 50, and 3->5h (2h) rises 35
        for hour, used in ((0, 0), (1, 20), (3, 20), (5, 55), (7, 70)):
            self.reading(hour, used)
        self.assertEqual(self.most("Max", 4 * HOUR), 50)
        self.assertEqual(self.most("Max", 2 * HOUR), 35)

    def test_no_rise_is_counted_across_a_reading_where_the_cap_fell(self):
        # a small fall kept by a turn at 2h: crossing 0->3h would give 65 instead of 36
        for hour, used, source in (
                (0, 10, "probe"), (1, 40, "probe"), (2, 39, "turn"), (3, 75, "probe")):
            self.reading(hour, used, plan="Max", source=source)
        # a reset from 80 to 5 at 2h
        for hour, used in ((0, 60), (1, 80), (2, 5), (3, 20)):
            self.reading(hour, used, plan="Pro", account="second")
        # a second meter row at the same timestamp does not erase a recorded fall (60 -> 20)
        for meter, hour, used in (("weekly_cap", 10, 0), ("weekly_cap", 11, 60),
                                  ("weekly_cap", 12, 20), ("cap", 12, 70), ("cap", 13, 75)):
            self.reading(hour, used, plan="Plus", meter=meter)
        self.assertEqual(self.most("Max", 3 * HOUR), 36)
        self.assertEqual(self.most("Pro", 3 * HOUR), 20)
        self.assertEqual(self.most("Plus", 3 * HOUR), 60)

    def test_most_over_two_logins_of_one_plan_ignores_other_plans_and_scopes(self):
        for hour, used in ((0, 0), (2, 20), (4, 25)):
            self.reading(hour, used, plan="Max", account="default")
        for hour, used in ((0, 10), (2, 55), (4, 60)):
            self.reading(hour, used, plan="Max", account="second", source="turn")
        for hour, used in ((10, 0), (11, 90), (14, 90)):
            self.reading(hour, used, plan="Pro", account="default")
        for hour, used in ((0, 0), (1, 95), (4, 95)):
            self.reading(hour, used, plan="Max", scope="Bellows",
                         meter="bellows_cap", account="default")
        for hour, used in ((0, 0), (1, 99), (4, 99)):
            self.reading(hour, used, plan="Max", scope=None, meter="weekly", account="default")
        self.assertEqual(self.most("Max", 3 * HOUR), 45)
        self.assertEqual(self.most("Pro", 3 * HOUR), 90)
        self.assertEqual(self.most("Max", 3 * HOUR, scope="Bellows"), 95)

    def test_readings_reaching_less_than_seconds_apart_give_none(self):
        # each login reaches 3h apart (together 13h, which does not count across logins)
        for hour, used in ((0, 0), (3, 40)):
            self.reading(hour, used, plan="Max", account="default")
        for hour, used in ((10, 0), (13, 50)):
            self.reading(hour, used, plan="Max", account="second")
        self.assertIsNone(self.most("Max", 4 * HOUR))
        self.assertIsNone(self.most("Max", 10**309))
        self.assertEqual(self.most("Max", 3 * HOUR), 50)
        self.assertIsNone(self.most("Plus", 1 * HOUR))


if __name__ == "__main__":
    unittest.main()
