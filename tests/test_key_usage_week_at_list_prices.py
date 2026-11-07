"""`ak usage`'s `holds` says what each login's shared week holds at list prices,
`week ≈ $2010 at list prices`: its plan's `week_listed_usd` (tests/test_key_week_price.py) in
whole dollars, a week named `week` and any other window by its length, `30d`; `-` while the plan
has none.  `a month` says the price on the provider's table alone, `200`.  No week is counted
in tokens: `ak usage --json` carries no `capacity_tokens`, `capacity_pairs` or `price_per_1m`.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, with an invented board, plans, readings and token rows
written into its Home, on a terminal wide enough for the whole table.  Fails against /bin/false.
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
PLANS = {"default": "Max", "second": "Max", "third": "Pro"}     # acme I, II and III
WIDE = {"COLUMNS": "200"}


class UsageWeekAtListPrices(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.meter = meters.install(self.home)
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription", "accounts": list(PLANS),
                                           "price": 200}})
        self.home.write(".agentkit/state/boards.json", BOARD)
        self.home.write(".agentkit/state/logins.json", {"acme": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": plan,
                      "checked_at": NOW} for account, plan in PLANS.items()}})

    def usage(self, window=7 * DAY):
        """`ak usage`'s text and `ak usage --json`'s acme logins, each login's shared meter
        `window` seconds long.  Max's week is read off acme I alone: from 10 to 40 for 603.13
        million input tokens at Anvil's listed dollar a million, $2010.43 a whole window; Pro
        has no reading."""
        for account in PLANS:
            self.meter.week("acme", account, used=50, window=window)
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            db.execute(SEAT_USAGE)
            db.execute(METER_READINGS)
            db.execute(f"INSERT INTO seat_usage VALUES ({', '.join('?' * 10)})",
                       ("echo:event-0", "acme-repo", NOW - 35 * HOUR, 603_130_000, "default",
                        "anvil-1", 603_130_000, 0, 0, 0))
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 9)})",
                           [("acme", "default", "weekly", used, NOW + 3 * DAY, window,
                             NOW - ago * HOUR, "probe", "Max") for used, ago in ((10, 40),
                                                                                (40, 30))])
        text = self.home.ak("usage", env=WIDE)
        self.assertEqual(text.code, 0, text.out + text.err)
        data = self.home.ak("usage", "--json")
        self.assertEqual(data.code, 0, data.out + data.err)
        return text.out, json.loads(data.out)["providers"]["acme"]["accounts"]

    def test_each_login_of_a_plan_with_a_week_says_it_in_whole_listed_dollars(self):
        out, accounts = self.usage()
        self.assertAlmostEqual(accounts["second"]["week_listed_usd"], 2010.4333, places=3)
        for label in ("acme I", "acme II"):
            self.assertEqual(meters.cell(out, label, "holds"), "week ≈ $2010 at list prices")
        self.assertEqual(meters.cell(out, "acme III", "holds"), "-")
        for label in ("acme I", "acme II", "acme III"):
            self.assertEqual(meters.cell(out, label, "a month"), "200")

    def test_a_window_of_thirty_days_says_its_length(self):
        out, _ = self.usage(window=30 * DAY)
        self.assertEqual(meters.cell(out, "acme I", "holds"), "30d ≈ $2010 at list prices")

    def test_usage_json_counts_no_week_in_tokens(self):
        _, accounts = self.usage()
        for account, record in accounts.items():
            with self.subTest(account):
                self.assertEqual({"capacity_tokens", "capacity_pairs", "price_per_1m"}
                                 & set(record), set())
                self.assertEqual(record["price"], 200)


if __name__ == "__main__":
    unittest.main()
