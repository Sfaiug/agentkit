"""Each subscription's login is asked as its own account, at most hourly while its end is far
off, and paged once under the subscription's name, never the account's.

A provider may hold several subscriptions, each its own login: the harness is told which one a
question is for in AGENTKIT_ACCOUNT, empty for the one it has when none is named, and the owner
reads a subscription as its provider's name with its number in roman numerals (`Claude II`),
since the account's name is ak's own.  A login's end moves only when somebody logs in again, so
one more than a week off is asked again only once an hour has passed since it was last asked.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
ticks asking tests/fixtures/loginend.py's harness and paging tests/fixtures/sink.py.
"""

from datetime import datetime
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import boxable, Home
from fixtures.loginend import Logins, midday, tick
from fixtures.sink import Sink

DAY = 86400


def logins_kept(home):
    return json.loads((home.path / ".agentkit/state/logins.json").read_text())


def events(home):
    return [json.loads(path.read_text()) for path in
            (home.path / ".agentkit/state/notification-outbox").glob("*.json")]


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Accounts(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        self.zone = midday(self.home)
        self.logins = Logins(self.home)

    def test_each_account_is_asked_as_itself_and_paged_by_its_numeral(self):
        akconfig.write(self.home, {"beta": {"harness": "claude", "provider": "test"}},
                       providers={"test": {"mode": "subscription",
                                           "accounts": ["default", "second"]}})
        self.logins.answer("second", "second@acme.test", int(time.time()) + 2 * DAY)
        tick(self.home)
        self.assertEqual(sorted(self.logins.asked()), ["", "second"])
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · Test II login"])
        self.assertEqual(logins_kept(self.home)["test"]["second"]["email"], "second@acme.test")

    def test_a_login_ending_soon_is_paged_once_by_subscription_never_by_account(self):
        self.home.write(".agentkit/secrets/discord_user_id", "42\n")
        akconfig.write(self.home, {"opus": "claude"},
                       providers={"anthropic": {"mode": "subscription",
                                                "accounts": ["dock", "harbor"]}})
        ends = int(time.time()) + 2 * DAY
        self.logins.answer("dock", None, None)
        self.logins.answer("harbor", None, ends)
        tick(self.home)
        tick(self.home)
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · Claude II login <@42>"])
        for request in self.sink.requests:
            self.assertNotIn(b"harbor", request.body)
        at = datetime.fromtimestamp(ends, self.zone).strftime("%a %d %b %H:%M")
        event, = events(self.home)
        self.assertEqual(event["text"], f"Claude II login ends {at} (in 2 days). "
                                        "Log in again from ak.")
        kept = logins_kept(self.home)["anthropic"]
        self.assertEqual((kept["dock"]["ends"], kept["harbor"]["ends"]), (None, ends))


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class Cadence(unittest.TestCase):
    def test_a_login_a_month_off_is_asked_again_only_after_an_hour(self):
        with Home() as home, Sink(home) as sink:
            akconfig.write(home, {"beta": {"harness": "claude", "provider": "test"}},
                           providers={"test": {"mode": "subscription"}})
            logins = Logins(home)
            logins.answer("default", "owner@acme.test", int(time.time()) + 30 * DAY)
            tick(home)
            tick(home)
            self.assertEqual(len(logins.asked()), 1)
            kept = logins_kept(home)
            kept["test"]["default"]["checked_at"] = time.time() - 3700
            home.write(".agentkit/state/logins.json", kept)
            tick(home)
            self.assertEqual(len(logins.asked()), 2)
            self.assertEqual(sink.requests, [])


if __name__ == "__main__":
    unittest.main()
