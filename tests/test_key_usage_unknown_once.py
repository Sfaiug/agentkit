"""`ak usage --json` prices fourteen windows of each plan's week for its checks.  On the owner's
host, 7 Nov 2026, each window read the turns whose tokens ak does not know again: 9.4 s of the
checks' 11.3.  By the kernel's count (inotify), in one `ak usage --json` the `harness` receipt
of a turn of a run still going, which kept no `turn_usage` row, is opened fewer times than the
fourteen windows the checks price.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, its Home set up as tests/test_key_usage_reads_once.py's is,
with readings, a run still going and its turn written into it.  Fails against /bin/false.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home
from test_key_usage_reads_once import opens
from test_key_week_from_its_own_spend import TABLES
from test_key_week_price import BOARD

NOW = time.time()
HOUR, DAY = 3600, 86400
WEEK = NOW + 3 * DAY    # the week's reset, far from the one the meter fixture reads now
WINDOWS = 14            # a day and the week before it, for each of the seven days checked


class UsageUnknownOnce(unittest.TestCase):
    def test_a_turn_of_a_run_still_going_is_read_fewer_times_than_the_windows_checked(self):
        home = Home()
        self.addCleanup(home.close)
        meter = meters.install(home)
        meter.week("acme", "default", used=50)
        akconfig.write(home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription", "accounts": ["default"]}})
        home.write(".agentkit/state/boards.json", BOARD)
        home.write(".agentkit/state/logins.json", {"acme": {"default": {
            "email": "default@acme.test", "ends": None, "plan": "Max", "checked_at": NOW}}})
        rows = {table: [] for table in TABLES}
        # the login's week rising over each of three days, a dollar spent during each rise
        for n, ago in enumerate((50, 26, 2)):
            for used, at in ((10 * n, ago), (10 * n + 5, ago - 1)):
                rows["meter_readings"].append(("acme", "default", "weekly", used, WEEK, 7 * DAY,
                                               NOW - at * HOUR, "probe", "Max"))
            rows["seat_usage"].append((f"echo:event-{n}", NOW - (ago - 0.5) * HOUR, 1e6,
                                       "default", "anvil-1", 1e6, 0, 0, 0))
        turn = ".agentkit/runs/fix-api/round-1/executor-1"
        home.write(f"{turn}/account", "default", ago=30 * HOUR)
        home.write(f"{turn}/events.jsonl", "{}\n", ago=HOUR)
        receipt = home.write(f"{turn}/harness", "echo", ago=30 * HOUR)
        rows["runs"].append(("fix-api", NOW - 2 * DAY, None, "[]"))
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            for table, columns in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({columns})")
                for row in rows[table]:
                    db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)

        def run():
            done = home.ak("usage", "--json")
            self.assertEqual(done.code, 0, done.out + done.err)

        [read] = opens([receipt], run)
        self.assertLess(read, WINDOWS)


if __name__ == "__main__":
    unittest.main()
