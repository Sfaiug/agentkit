"""A model's own cap in a kept reading of a login holding its shared week (`weekly_all`) says the
points of that week held for it, `held`: its plan's share of the week (`cap_share.of`) of what it
has left, or of the most it has been seen to rise in the time to its reset (`cap_share.most`)
where that is less.  A cap with no share known or nothing left, or on a reading without the shared
week, carries no `held`, and nothing the probe read changes.

Black-box: in a Home of tests/fixtures/akbin.py on tests/fixtures/meters.py's harness, with a
history.db of invented readings, each login's plan in state/logins.json and its last reading in
state/usage.json, one `ak usage --json` probes every login, and state/usage.json and history.db
are read as any program reads them.  Fails against /bin/false.
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

NOW = time.time()
HOUR, DAY, WEEK = 3600, 86400, 604800
SCHEMA = ("CREATE TABLE meter_readings (provider TEXT, account TEXT, meter TEXT, used REAL, "
          "resets_at REAL, window_secs REAL, at REAL, source TEXT, plan TEXT, scope TEXT, "
          "PRIMARY KEY (provider, account, meter, at))")
# (hours ago, week used, cap used): 4 of the week beside 11 of the cap, a share of (4+1)/(11-1)
HALF = ((30, 0, 0), (20, 4, 11))
# and then a rise of 10 in two hours, the most the cap rose in any four
RISES_TEN = (*HALF, (18, 10, 21))


def week(used):
    return {"name": "weekly_all", "used": used, "resets_at": NOW + 3 * DAY, "window_secs": WEEK}


def cap(used, resets_at=NOW + 3 * DAY):
    return {"name": "weekly_scoped", "used": used, "resets_at": resets_at, "window_secs": WEEK,
            "scope": "Anvil"}


SESSION = {"name": "session", "used": 30, "resets_at": NOW + HOUR, "window_secs": 18000}


class ACapsPartIsWhatItCanStillSpend(unittest.TestCase):
    def probe(self, logins):
        """One `ak usage --json` in a Home whose logins, {account: (plan, its readings in
        history.db, the meters its probe answers)}, each last read an hour ago; the snapshot's
        meters it wrote, {account: {name: meter}}, and history.db's rows of the probe's
        readings, {account: {name: (used, resets_at, window_secs, scope, plan)}}."""
        home = Home()
        self.addCleanup(home.close)
        meter = meters.install(home)
        akconfig.write(home, {"anvil": {"harness": "echo", "provider": "acme"}},
                       providers={"acme": {"mode": "subscription", "accounts": list(logins)}})
        home.write(".agentkit/state/logins.json", {"acme": {account: {
            "email": f"{account}@acme.test", "ends": None, "plan": plan, "checked_at": NOW}
            for account, (plan, _, _) in logins.items()}})
        home.write(".agentkit/state/usage.json", {"fetched_at": NOW - HOUR, "providers": {
            "acme": {"accounts": {account: {"meters": answer, "fetched_at": NOW - HOUR}
                                  for account, (_, _, answer) in logins.items()}}}})
        rows = []
        for account, (plan, readings, _) in logins.items():
            for ago, used_week, used_cap in readings:
                at = NOW - ago * HOUR
                for read in (week(used_week), cap(used_cap)):
                    rows.append(("acme", account, read["name"], read["used"], read["resets_at"],
                                 WEEK, at, "probe", plan, read.get("scope")))
            (meter.dir / f"acme.{account}.usage.json").write_text(
                json.dumps({"meters": logins[account][2], "error": None}))
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db, db:
            db.execute(SCHEMA)
            db.executemany(f"INSERT INTO meter_readings VALUES ({', '.join('?' * 10)})", rows)
        done = home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        snapshot = json.loads((home.path / ".agentkit/state/usage.json").read_text())
        written = {account: {m["name"]: m for m in record["meters"]}
                   for account, record in snapshot["providers"]["acme"]["accounts"].items()}
        with closing(sqlite3.connect(home.path / ".agentkit/history.db")) as db:
            kept = db.execute("SELECT account, meter, used, resets_at, window_secs, scope, plan "
                              "FROM meter_readings WHERE at > ?", (NOW,)).fetchall()
        probed = {}
        for account, name, *columns in kept:
            probed.setdefault(account, {})[name] = tuple(columns)
        return written, probed

    def test_a_cap_read_over_less_than_its_week_left_holds_its_share_of_what_is_left(self):
        written, _ = self.probe({"default": ("Max", HALF, [week(50), cap(20)])})
        self.assertEqual(written["default"]["weekly_scoped"]["held"], 40)
        self.assertNotIn("held", written["default"]["weekly_all"])

    def test_a_cap_never_seen_to_rise_more_than_ten_in_the_time_left_holds_its_share_of_ten(self):
        written, _ = self.probe({"default": ("Max", RISES_TEN,
                                             [week(50), cap(40, resets_at=NOW + 4 * HOUR)])})
        self.assertEqual(written["default"]["weekly_scoped"]["held"], 5)

    def test_no_share_known_a_spent_cap_or_no_shared_week_holds_nothing(self):
        written, _ = self.probe({"spent": ("Max", HALF, [week(50), cap(100)]),
                                 "unknown": ("Pro", (), [week(50), cap(20)]),
                                 "capped": ("Max", (), [SESSION, cap(20)])})
        for account in ("spent", "unknown", "capped"):
            self.assertNotIn("held", written[account]["weekly_scoped"], account)

    def test_what_the_probe_read_is_kept_and_written_as_read(self):
        answer = [SESSION, week(50), cap(40, resets_at=NOW + 4 * HOUR)]
        written, probed = self.probe({"default": ("Max", RISES_TEN, answer)})
        self.assertEqual(written["default"]["weekly_scoped"]["held"], 5)
        self.assertEqual({name: m["used"] for name, m in written["default"].items()},
                         {m["name"]: m["used"] for m in answer})
        self.assertEqual(probed, {"default": {
            m["name"]: (m["used"], m["resets_at"], m["window_secs"], m.get("scope"), "Max")
            for m in answer}})


if __name__ == "__main__":
    unittest.main()
