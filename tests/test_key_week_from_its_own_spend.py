"""`ak usage --json` fits what a week of each plan holds in listed dollars, `week_listed_usd`
from `plan_points` and `plan_listed_usd`, from each login's readings of its shared week as
tests/test_key_week_price.py has it, each rise priced with what was spent during it alone:

- A login's readings of one plan and one week are cut, in time order, between any two between
  which a turn of unknown tokens on that login ran, its span overlapping the time from one to
  the next.  Each stretch rose from its earliest reading to its highest, bought with what the
  login spent from that reading to the first at the highest.
- A turn of unknown tokens is a worker turn that kept no `turn_usage` row and is either one its
  run's `counted_turns` names or one of a run that has not ended (`finished_at` null).  It is the
  provider's when its `harness` receipt names a harness running that provider's models alone,
  the login's its `account` receipt names, the usual one where it names none, and its span runs
  from its `harness` receipt's time to its `events.jsonl`'s.
- A turn row counts the share of its span, from its `began` to its `at`, within the stretch; one
  with no `began` counts at its `at`, as a seat row does.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on
tests/fixtures/meters.py's harness, `echo` running acme's models and a copy, `chime`, brine's,
with an invented board, plans, readings, runs, token rows and turn directories written into its
Home.  Fails against /bin/false.
"""

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, meters
from fixtures.akbin import Home
from test_key_week_price import BOARD

NOW = time.time()
HOUR, DAY = 3600, 86400
WEEK = NOW + 3 * DAY    # the week's reset, far from the one the meter fixture reads now
PLANS = {"default": "Max", "second": "Pro"}
# each table's columns this test writes, as history.db names them
TABLES = {"runs": "run_id, started_at, finished_at, counted_turns",
          "turn_usage": "turn, run_id, role, account, model, began, at, input, cache_write, "
                        "cache_read, output",
          "seat_usage": "event, at, tokens, account, model, input, cache_write, cache_read, output",
          "meter_readings": "provider, account, meter, used, resets_at, window_secs, at, source, "
                            "plan, PRIMARY KEY (provider, account, meter, at)"}


class WeekFromItsOwnSpend(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for suffix in (".sh", ".toml"):
            shutil.copy2(meter.dir / f"echo{suffix}", meter.dir / f"chime{suffix}")
        for account in PLANS:
            meter.week("acme", account, used=50)
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"},
                                   "bolt": {"harness": "chime", "provider": "brine"}},
                       providers={provider: {"mode": "subscription",
                                             "accounts": list(PLANS)}
                                  for provider in ("acme", "brine")})
        self.home.write(".agentkit/state/boards.json", BOARD)
        self.home.write(".agentkit/state/logins.json", {"acme": {
            account: {"email": f"{account}@acme.test", "ends": None, "plan": plan,
                      "checked_at": NOW} for account, plan in PLANS.items()}})
        self.rows = {table: [] for table in TABLES}
        self.counted, self.running, self.made = {}, set(), 0   # each run's counted turns

    def read(self, account, used, ago):
        """A probe's reading of the login's shared week, `ago` hours ago, kept with its plan."""
        self.rows["meter_readings"].append(("acme", account, "weekly", used, WEEK, 7 * DAY,
                                            NOW - ago * HOUR, "probe", PLANS[account]))

    def spent(self, account, dollars, ago):
        """A seat's row of the login `ago` hours ago: `dollars` million input tokens."""
        self.rows["seat_usage"].append((f"echo:event-{len(self.rows['seat_usage'])}",
                                        NOW - ago * HOUR, dollars * 1e6, account, "anvil-1",
                                        dollars * 1e6, 0, 0, 0))

    def turn(self, began, last, *, run="fix-api", running=False, harness="echo",
             account="default", counted=True, rows=()):
        """A worker turn of `run`, which has not ended where any of its turns is `running`, from
        `began` hours ago to its last event `last` hours ago: its `harness` receipt naming
        `harness`, its `account` receipt `account` (None: none), `counted_turns` naming it where
        `counted`.  Each of `rows`, (dollars, began, at) hours ago, `began` None for none, is a
        `turn_usage` row of it: `dollars` million input tokens."""
        turns = self.counted.setdefault(run, [])
        if running:
            self.running.add(run)
        self.made += 1
        turn = self.home.path / f".agentkit/runs/{run}/round-1/executor-{self.made}"
        turn.mkdir(parents=True)
        turn = turn.resolve()
        for receipt, text, ago in (("account", account, began), ("harness", harness, began),
                                   ("events.jsonl", "{}\n", last)):
            if text is not None:
                (turn / receipt).write_text(text)
                os.utime(turn / receipt, (NOW - ago * HOUR,) * 2)
        if counted:
            turns.append(str(turn))
        self.rows["turn_usage"] += [
            (str(turn), run, "executor", account, "anvil-1",
             None if start is None else NOW - start * HOUR, NOW - at * HOUR, dollars * 1e6, 0, 0,
             0) for dollars, start, at in rows]

    def weeks(self):
        """Each login's (plan, week_listed_usd, plan_points, plan_listed_usd), the rows written
        into history.db first."""
        for run, turns in self.counted.items():
            self.rows["runs"].append((run, NOW - 3 * DAY,
                                      None if run in self.running else NOW - 60,
                                      json.dumps(turns)))
        with closing(sqlite3.connect(self.home.path / ".agentkit/history.db")) as db, db:
            for table, columns in TABLES.items():
                db.execute(f"CREATE TABLE {table} ({columns})")
                for row in self.rows[table]:
                    db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        accounts = json.loads(done.out)["providers"]["acme"]["accounts"]
        return {account: tuple(accounts[account][key] for key in (
            "plan", "week_listed_usd", "plan_points", "plan_listed_usd")) for account in PLANS}

    def assertWeek(self, got, plan, week, points, dollars):
        self.assertEqual(got[0], plan)
        self.assertAlmostEqual(got[1], week)
        self.assertAlmostEqual(got[2], points)
        self.assertAlmostEqual(got[3], dollars)

    def test_a_rise_during_a_counted_turn_that_kept_no_rows_counts_for_nothing(self):
        self.read("default", 10, 40)
        self.spent("default", 2, 35)
        self.read("default", 20, 30)
        self.turn(27, 24)                       # counted, no row: what it spent is unknown
        self.spent("default", 30, 25)
        self.read("default", 50, 20)
        self.spent("default", 1, 15)
        self.turn(14, 12, rows=[(1, 14, 12)])   # counted with its row: it cuts nothing
        self.read("default", 60, 10)
        weeks = self.weeks()
        # 10 -> 20 for $2, and 50 -> 60 for $2
        self.assertWeek(weeks["default"], "Max", 20, 20, 4)

    def test_a_turn_of_a_run_not_ended_cuts_from_its_start_and_no_other_turn_does(self):
        self.read("default", 10, 40)
        self.turn(35, 30, run="add-ui", rows=[(2, 35, 30)])    # its run's turn that ended
        self.read("default", 30, 20)
        # its run's turn still going, with no account receipt: the usual login's
        self.turn(15, 0, run="add-ui", running=True, account=None, counted=False)
        self.spent("default", 9, 12)
        self.read("default", 45, 10)
        self.spent("default", 9, 7)
        self.read("default", 50, 5)
        # the other login: turns of no rows on the usual login, and of brine, cut nothing
        self.read("second", 20, 60)
        self.turn(57, 53, account="default")
        self.turn(56, 54, harness="chime", account="second")
        self.spent("second", 4, 55)
        self.read("second", 40, 50)
        weeks = self.weeks()
        self.assertWeek(weeks["default"], "Max", 10, 20, 2)
        self.assertWeek(weeks["second"], "Pro", 20, 20, 4)

    def test_a_turn_row_straddling_a_stretchs_ends_counts_its_share_within(self):
        self.read("default", 10, 40)
        self.turn(44, 36, rows=[(8, 44, 36)])   # half after the first reading: $4
        self.turn(30, 30, rows=[(1, None, 30)])  # no began: whole, at its at
        self.turn(22, 18, rows=[(2, 22, 18)])   # half before the highest: $1
        self.read("default", 30, 20)
        self.read("default", 25, 10)
        weeks = self.weeks()
        self.assertWeek(weeks["default"], "Max", 30, 20, 6)


if __name__ == "__main__":
    unittest.main()
