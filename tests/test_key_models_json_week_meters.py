"""`ak models --json` names what each plan's weekly meters rose over the last 30 days, and the
tokens that ran meanwhile (`week_meters`): {provider: {plan: {"points", "tokens": {model}}}};
what a model's tokens take of them, each plan's `rates`, has its own key
(tests/test_key_a_weeks_points_per_token_from_own_meters.py).

- A login's readings are its `meter_readings` rows of source `probe` of the meter its shared week
  is, no model's own cap of that name (`scope`), whose `used` is a number from 0 to 100 and whose
  `at` a number, in the order of `at`.
- A step is two of a login's readings next to each other.  It counts where both name one plan and
  the second holds no less than the first, its points the difference; across two plans, with a
  reading naming none (none or an empty text), or downward, it counts for nothing.
- A step's tokens are the login's rows after its first reading and by its second: `seat_usage`
  rows whose event's harness runs the provider's models alone, and `turn_usage` rows whose turn's
  `harness` receipt does, one that is no text naming none; a seat row's `tokens`, a turn row's
  four counts summed, whole numbers summing above zero, any other row no row.  A step holding a
  row of no model (none or an empty text) counts for nothing.
- A plan's points are its steps' summed with `math.fsum`, to six significant digits, however many
  logins and days they span; a plan with no step that counts is not listed, nor a provider with
  none.  A history whose readings keep no plan gives `{}`, and `ak models --json` exits 0; one
  keeping a plan but no `scope` yet names no model's own cap.

Black-box: the program `AK_BIN` names, on tests/fixtures/meters.py's harness, `echo` running
acme's models and a copy, `chime`, brine's, the logins' shared weeks held in the usage cache and
the readings, token rows and turns' receipts written into its Home; judged by the output and exit
code.  Fails against /bin/false.
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
from test_key_models_answer import ENV, boards

NOW = time.time()
HOUR, DAY = 3600, 86400
# what each row's hours ago count back from: inside the 30 days, outside the week `ak usage` fits
# a plan's dollars from, which takes a reading's `used` for a number; at noon UTC, so the hours
# just before it are one day
THEN = (NOW // DAY - 8) * DAY + 12 * HOUR
# each table's columns this test writes, as history.db names them
TABLES = {"seat_usage": "event, at, tokens, account, model",
          "turn_usage": "turn, account, model, at, input, cache_write, cache_read, output",
          "meter_readings": "provider, account, meter, used, resets_at, window_secs, at, source, "
                            "plan, scope, PRIMARY KEY (provider, account, meter, at)"}
LOGINS = {"acme": ["default", "second"], "brine": ["default"]}


class WeekMeters(unittest.TestCase):
    """A Home whose logins' readings and token rows a test writes, and its `week_meters`."""

    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        meter = meters.install(self.home)
        for suffix in (".sh", ".toml"):
            shutil.copy2(meter.dir / f"echo{suffix}", meter.dir / f"chime{suffix}")
        akconfig.write(self.home, {"anvil": {"harness": "echo", "provider": "acme"},
                                   "bolt": {"harness": "chime", "provider": "brine"}},
                       providers={provider: {"mode": "subscription", "accounts": accounts}
                                  for provider, accounts in LOGINS.items()})
        self.home.write(".agentkit/state/boards.json", boards())
        week = {"name": "weekly", "used": 50, "window_secs": 7 * DAY, "resets_at": NOW + DAY}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": NOW, "providers": {
            provider: {"accounts": {account: {"meters": [week]} for account in accounts}}
            for provider, accounts in LOGINS.items()}})
        self.rows = {table: [] for table in TABLES}

    def read(self, ago, used, plan="Max", account="default", provider="acme", meter="weekly",
             source="probe", scope=None):
        """A reading of the login's meter `ago` hours before THEN."""
        self.rows["meter_readings"].append((provider, account, meter, used, THEN + DAY, 7 * DAY,
                                            THEN - ago * HOUR, source, plan, scope))

    def seat(self, ago, tokens, model="anvil-1", account="default", harness="echo"):
        """A seat's row of the login `ago` hours before THEN, on `harness`."""
        self.rows["seat_usage"].append((f"{harness}:event-{len(self.rows['seat_usage'])}",
                                        THEN - ago * HOUR, tokens, account, model))

    def turn(self, ago, counts, model="anvil-1", account="default", harness="echo"):
        """A worker turn's row of the login ending `ago` hours before THEN, its `harness` receipt
        naming `harness`."""
        turn = (self.home.path / ".agentkit/runs/fix-api/round-1"
                / f"executor-{len(self.rows['turn_usage'])}")
        turn.mkdir(parents=True)
        (turn / "harness").write_text(harness)
        self.rows["turn_usage"].append((str(turn), account, model, THEN - ago * HOUR, *counts))

    def week_meters(self, tables=TABLES):
        """`ak models --json`'s `week_meters`, the rows written into history.db first, read-only
        so that no migration ahead of the read changes the tables as written."""
        path = self.home.path / ".agentkit/history.db"
        with closing(sqlite3.connect(path)) as db, db:
            for table, columns in tables.items():
                db.execute(f"CREATE TABLE {table} ({columns})")
                for row in self.rows[table]:
                    db.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)
        path.chmod(0o444)
        done = self.home.ak("models", "--json", env=ENV)
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["week_meters"]


class ModelsJsonWeekMeters(WeekMeters):
    def week_meters(self, tables=TABLES):
        """Each plan but its `rates`, which have their own key."""
        return {provider: {plan: {key: value for key, value in found.items() if key != "rates"}
                           for plan, found in plans.items()}
                for provider, plans in super().week_meters(tables).items()}

    def test_each_plan_sums_its_logins_steps_and_the_tokens_they_held(self):
        self.seat(60, 7_000)                        # before the login's first reading
        self.read(50, 10)
        self.seat(45, 1_000)
        self.turn(42, (100, None, 50, 0))
        self.seat(41, "500", model=None)            # a text: no row, though it names no model
        self.seat(41, 0, model=None)                # no token: no row
        self.seat(44, 3_000, model="bolt-1", harness="chime")   # brine's, on a login so named
        self.turn(43, (2_000, 0, 0, 0), model="bolt-1", harness="chime")
        self.turn(42, (4_000, 0, 0, 0))             # its receipt no text: no harness's
        Path(self.rows["turn_usage"][-1][0], "harness").write_bytes(b"\xff")
        self.read(40, 20)
        self.read(39, 80, scope="anvil")            # anvil's own cap of the name: no reading
        self.read(38, "nan")                        # no reading: 20 to 25 is one step
        self.read(37, 101)
        self.read(36, 15, source="turn")
        self.read(35, 15, meter="weekly_fable")
        self.turn(34, (300, 0, 0, 0))
        self.read(30, 25)
        self.seat(20, 9_000)                        # after the login's last reading
        self.read(50, 0, account="second")
        self.seat(45, 200, model="bloom-1", account="second")
        self.read(40, 5, account="second")
        self.read(50, 30, plan="Plus", provider="brine")
        self.read(40, 32, plan="Plus", provider="brine")
        self.assertEqual(self.week_meters(), {
            "acme": {"Max": {"points": 20, "tokens": {"anvil-1": 1_450, "bloom-1": 200}}},
            "brine": {"Plus": {"points": 2, "tokens": {"bolt-1": 5_000}}}})

    def test_a_step_across_plans_of_no_plan_downward_or_of_a_row_of_no_model_counts_for_nothing(self):
        steps = [(10, "Max"), (20, "Pro"), (30, "Pro"), (40, None), (50, "Pro"), (5, "Pro"),
                 (15, "Pro"), (18, "Pro"), (25, "Pro")]
        for n, (used, plan) in enumerate(steps):
            self.read(100 - 10 * n, used, plan)
            self.seat(95 - 10 * n, 10 ** n)         # a row in each step but after the last
        self.seat(44, 1, model=None)                # in 5 to 15: that step counts for nothing
        self.seat(24, 1, model="")                  # nor 18 to 25
        # nor a login the cache holds no week for, of readings naming no meter
        self.read(50, 10, account="archived", meter=None)
        self.read(40, 20, account="archived", meter=None)
        # the steps of a week begun again, 9.5, 0.1, 0.2 and 0.2, sum to 10 points
        for n, used in enumerate((0, 9.5, 0, 0.1, 0, 0.2, 0, 0.2)):
            self.read(100 - 10 * n, used, plan="Ultra", account="second")
        # a provider whose steps count for nothing is not listed
        self.read(50, 30, plan=None, provider="brine")
        self.read(40, 32, plan=None, provider="brine")
        self.read(30, 34, plan="", provider="brine")
        self.read(20, 36, plan="", provider="brine")
        self.assertEqual(self.week_meters(), {
            "acme": {"Pro": {"points": 13, "tokens": {"anvil-1": 10 + 1_000_000}},
                     "Ultra": {"points": 10, "tokens": {}}}})

    def test_a_plan_s_points_are_its_steps_summed_once_across_logins_and_days(self):
        # 10 and 0.1 on one login's day, 0.00025 on another's: 10.10025, to six digits 10.1003,
        # where each day summed first gives 10.1002
        for ago, used in enumerate((0.1, 0, 10, 0)):
            self.read(ago, used)
        self.read(1, 0, account="second")
        self.read(0, 0.00025, account="second")
        self.assertEqual(self.week_meters(),
                         {"acme": {"Max": {"points": 10.1003, "tokens": {}}}})

    def test_a_history_whose_readings_keep_a_plan_but_no_scope_names_no_cap(self):
        self.read(50, 10)
        self.seat(47, 5)
        self.read(46, 20)
        self.rows["meter_readings"] = [row[:-1] for row in self.rows["meter_readings"]]
        self.assertEqual(self.week_meters({**TABLES, "meter_readings": TABLES[
            "meter_readings"].replace("scope, ", "")}),
            {"acme": {"Max": {"points": 10, "tokens": {"anvil-1": 5}}}})

    def test_a_history_whose_readings_keep_no_plan_gives_none(self):
        self.read(50, 10)
        self.read(40, 20)
        # made before a reading kept its plan, and so its scope
        self.rows["meter_readings"] = [row[:-2] for row in self.rows["meter_readings"]]
        self.assertEqual(self.week_meters({**TABLES, "meter_readings": (
            "provider, account, meter, used, resets_at, window_secs, at, source, "
            "PRIMARY KEY (provider, account, meter, at)")}), {})


if __name__ == "__main__":
    unittest.main()
