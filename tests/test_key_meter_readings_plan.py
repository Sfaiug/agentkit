"""Each kept meter reading names the plan its login was on.

A coming fit measures, for each plan, how many points of a week a listed dollar of tokens takes,
pooling every login on that plan, and an upgrade or a downgrade must start a fit of its own
rather than blend two plans (owner, 5 Nov 2026).  So each row of history.db's `meter_readings`
keeps `plan`: the login's plan as state/logins.json names it when the reading is kept, NULL
where it names none.

The tick asks a login's plan (`login-end`) at most once an hour and reads its meters at most
once per probe interval, so the key moves past each by dating its last ask back where it is
written down: the login's `checked_at` in state/logins.json, and the provider's
`state/<provider>-probe.lock`.  Black-box: the program `AK_BIN` names ticks from outside through
tests/fixtures/akbin.py, the provider's meters and its login's plan answered through
tests/fixtures/fakeadapter.py, and the database is read with sqlite3; this test fails against
`/bin/false`.
"""

import json
import sqlite3
import sys
from pathlib import Path
import time
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import boxable, Home

DATABASE = ".agentkit/history.db"
LOGINS = ".agentkit/state/logins.json"
LOCK = ".agentkit/state/anthropic-probe.lock"     # the provider of Claude's shipped models
ASK_EVERY = 3600
NOW = int(time.time())


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Plans(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fake = fakeadapter.install(self.home, claude="pass")["claude"]
        akconfig.write(self.home, {"anvil": {"harness": "claude"}},
                       providers={"anthropic": {"mode": "subscription"}})

    def tick(self):
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)

    def on(self, plan):
        """A tick learns the login is on `plan` now, reading no meters: the provider's usage is
        refused until `read`, and asked again only past its probe interval."""
        self.fake.answer("login-end", json.dumps(
            {"email": "owner@acme.test", "ends": None, "plan": plan}))
        if (self.home.path / LOGINS).exists():
            logins = json.loads((self.home.path / LOGINS).read_text())
            for login in logins["anthropic"].values():
                login["checked_at"] -= ASK_EVERY + 5
            self.home.write(LOGINS, logins)
        self.tick()

    def read(self, session, week):
        """A tick past the probe interval reads the provider's meters at these percentages."""
        self.fake.answer("usage", json.dumps({"meters": [
            {"name": "session", "used": session, "resets_at": NOW + 3600, "window_secs": 18000},
            {"name": "weekly_all", "used": week, "resets_at": NOW + 3 * 86400,
             "window_secs": 604800}]}))
        every = tomllib.loads(self.fake.manifest.read_text())["usage"]["probe_every"]
        self.home.write(LOCK, repr(time.time() - every - 5))
        self.tick()

    def kept(self):
        """Each kept row's meter, used% and plan, oldest first."""
        connection = sqlite3.connect(self.home.path / DATABASE)
        try:
            return connection.execute(
                "SELECT meter, used, plan FROM meter_readings ORDER BY at, meter").fetchall()
        finally:
            connection.close()

    def test_each_reading_keeps_the_plan_its_login_was_on_when_it_was_kept(self):
        self.on("pro")
        self.read(20, 30)
        first = [("session", 20, "pro"), ("weekly_all", 30, "pro")]
        self.assertEqual(self.kept(), first)

        self.on("max 20x")
        self.read(25, 40)
        self.assertEqual(self.kept(), first + [("session", 25, "max 20x"),
                                               ("weekly_all", 40, "max 20x")])

    def test_a_login_whose_plan_is_not_known_keeps_null(self):
        self.on(None)
        self.read(20, 30)
        self.assertEqual(self.kept(), [("session", 20, None), ("weekly_all", 30, None)])


if __name__ == "__main__":
    unittest.main()
