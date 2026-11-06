"""Every fresh reading of a login's meters is kept in history.db, five weeks back.

state/usage.json holds only each login's latest reading.  history.db's `meter_readings` keeps
each one a probe or a worker turn took, a row per meter: its provider, account (`default` for
the usual login), name, used%, reset and window, the moment it was measured, and `probe` or
`turn` for what read it.  A tick within the provider's probe interval reads nothing new, so it
keeps nothing; a probe the provider refuses keeps nothing either.  A write that keeps readings
drops the rows past five weeks.

The interval is the harness's own `[usage] probe_every`, on the program's clock, so the key
moves past it by dating the last ask back where it is written down, the provider's
`state/<provider>-probe.lock`, and ages a row by moving its moment back.  Black-box: the
program `AK_BIN` names ticks and runs from outside through tests/fixtures/akbin.py, the
provider answering through tests/fixtures/fakeadapter.py, and the database is read with
sqlite3, as any other program reads it; this test fails against `/bin/false`.
"""

import json
import sqlite3
import sys
from pathlib import Path
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import boxable, Home
from fixtures.gitrig import Rig

DATABASE = ".agentkit/history.db"
LOCK = ".agentkit/state/anthropic-probe.lock"     # the provider of Claude's shipped models
WEEK = 604800
FIVE_WEEKS = 5 * WEEK
NOW = int(time.time())
FIRST = {"session": (20, NOW + 3600, 18000), "weekly_all": (30, NOW + 3 * 86400, WEEK)}
LATER = {"session": (25, NOW + 3600, 18000), "weekly_all": (40, NOW + 3 * 86400, WEEK)}
# no route anywhere: nothing a run asks leaves the host
OFFLINE = {name: "http://127.0.0.1:9" for name in (
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def answer(fake, meters):
    """What the provider answers for its usage from now on: {name: (used, resets_at, window)}."""
    fake.answer("usage", json.dumps({"meters": [
        {"name": name, "used": used, "resets_at": resets, "window_secs": window}
        for name, (used, resets, window) in meters.items()]}))


def readings(home):
    """Every kept row, oldest first."""
    connection = sqlite3.connect(home.path / DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM meter_readings ORDER BY at, account, meter")]
    finally:
        connection.close()


def rows(meters, account="default", source="probe"):
    """The rows a reading of `meters` keeps, less its moment: the fake names no plan."""
    return [{"provider": "anthropic", "account": account, "meter": name, "used": used,
             "resets_at": resets, "window_secs": window, "source": source, "plan": None}
            for name, (used, resets, window) in meters.items()]


def timed(act, *args, **kwargs):
    """`act(*args)`'s outcome, once it exited 0, and the moments it ran between."""
    before = time.time()
    done = act(*args, **kwargs)
    after = time.time()
    assert done.code == 0, done.out + done.err
    return before, after


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ProbedReadings(unittest.TestCase):
    def home(self, accounts=None):
        home = Home()
        self.addCleanup(home.close)
        fake = fakeadapter.install(home, claude="pass")["claude"]
        akconfig.write(home, {"anvil": {"harness": "claude"}}, providers={"anthropic": {
            "mode": "subscription", **({"accounts": accounts} if accounts else {})}})
        return home, fake

    def assertKept(self, home, expected, before, after):
        """The rows since `before` are `expected`, each measured while the tick ran."""
        kept = [row for row in readings(home) if row["at"] >= before]
        self.assertEqual([row["at"] for row in kept if row["at"] > after], [], kept)
        self.assertCountEqual([{key: value for key, value in row.items() if key != "at"}
                               for row in kept], expected)
        return kept

    def test_each_tick_past_the_probe_interval_keeps_what_it_read_and_none_within_it(self):
        home, fake = self.home()
        answer(fake, FIRST)
        first = self.assertKept(home, rows(FIRST), *timed(home.tick))
        self.assertEqual(len({row["at"] for row in first}), 1, "one reading, one moment")

        answer(fake, LATER)
        timed(home.tick)
        self.assertEqual(readings(home), first, "a tick within the probe interval kept more")

        connection = sqlite3.connect(home.path / DATABASE)
        with connection:
            connection.execute("UPDATE meter_readings SET at = at - ? WHERE meter = 'session'",
                               (FIVE_WEEKS + 60,))
        connection.close()
        every = tomllib.loads(fake.manifest.read_text())["usage"]["probe_every"]
        home.write(LOCK, repr(time.time() - every - 5))
        later = self.assertKept(home, rows(LATER), *timed(home.tick))
        self.assertEqual(readings(home), [row for row in first if row["meter"] != "session"]
                         + later, "the earlier week kept, the session aged past five weeks gone")

    def test_each_account_s_readings_are_kept_under_its_own_name(self):
        home, fake = self.home(["default", "second"])
        answer(fake, FIRST)
        self.assertKept(home, rows(FIRST) + rows(FIRST, "second"), *timed(home.tick))


class TurnReadings(unittest.TestCase):
    def test_a_turn_s_streamed_meters_are_kept_as_the_turn_s(self):
        home = Home()
        self.addCleanup(home.close)
        fake = fakeadapter.install(home, claude="pass")["claude"]
        akconfig.write(home, {"anvil": {"harness": "claude"}})
        rig = Rig(home, "widgets")
        # Claude streams its account's limits as it works: five hours and seven days
        windows = {"five_hour": {"utilization": .25, "resetsAt": NOW + 3600},
                   "seven_day": {"utilization": .5, "resetsAt": NOW + 3 * 86400}}
        events = json.dumps({"type": "rate_limit_event", "rate_limit_info": {
            "status": "allowed", "unifiedWindows": windows}}) + "\n"
        fake.behave({**fakeadapter.WORK, "events": events}, fakeadapter.PASS)
        before, after = timed(home.ak, "run", str(taskfile.write(home, rig.path)), "--no-merge",
                              env=OFFLINE, timeout=300)
        kept = readings(home)
        # the fake's usage call is refused, so the turn's reading is the only one
        self.assertCountEqual([{key: value for key, value in row.items() if key != "at"}
                               for row in kept],
                              rows({"session": (25, NOW + 3600, 18000),
                                    "weekly_all": (50, NOW + 3 * 86400, WEEK)}, source="turn"))
        self.assertEqual([row["at"] for row in kept if not before <= row["at"] <= after], [])


if __name__ == "__main__":
    unittest.main()
