"""A login ending within three days, or ended, pages the owner once a day; one further off
does not.

A login that runs out stops every seat on that subscription, and only the owner can log in
again, so the tick asks each subscription's harness when its login ends (`login-end`) and keeps
the answer in state/logins.json for every screen that warns of it.  Within three days of its
end, and once it has ended, the owner is paged with only the subscription's name, while the
outbox keeps the whole sentence, the day and time in the owner's own zone; further off, the end
is recorded and nobody is paged.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, its ticks asking tests/fixtures/loginend.py's harness and
paging tests/fixtures/sink.py.
"""

from datetime import datetime
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.loginend import Logins, midday, tick
from fixtures.sink import Sink

DAY = 86400


def state(home, name):
    return json.loads((home.path / ".agentkit" / "state" / name).read_text())


def events(home):
    return [json.loads(path.read_text()) for path in
            (home.path / ".agentkit/state/notification-outbox").glob("*.json")]


class LoginEnd(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home)
        self.addCleanup(self.sink.close)
        self.zone = midday(self.home)
        akconfig.write(self.home, {"beta": {"harness": "claude", "provider": "test"}},
                       providers={"test": {"mode": "subscription"}})
        self.logins = Logins(self.home)

    def ending(self, ends):
        self.logins.answer("default", "owner@acme.test", ends)
        return ends

    def at(self, ends):
        return datetime.fromtimestamp(ends, self.zone).strftime("%a %d %b %H:%M")

    def test_a_login_ending_in_two_days_is_paged_once_saying_when_it_ends(self):
        ends = self.ending(int(time.time()) + 2 * DAY)
        tick(self.home)
        tick(self.home)
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · Test login"])
        event, = events(self.home)
        self.assertIsNone(event["session"])
        self.assertEqual(event["text"], f"Test login owner@acme.test ends {self.at(ends)} "
                                        "(in 2 days). Log in again from ak.")
        login = state(self.home, "logins.json")["test"]["default"]
        self.assertEqual(sorted(login), ["checked_at", "email", "ends"])
        self.assertEqual((login["email"], login["ends"]), ("owner@acme.test", ends))
        self.assertIsInstance(login["checked_at"], (int, float))

    def test_a_login_ending_in_four_days_is_recorded_and_pages_nobody(self):
        ends = self.ending(int(time.time()) + 4 * DAY)
        tick(self.home)
        self.assertEqual(self.sink.requests, [])
        self.assertEqual(state(self.home, "logins.json")["test"]["default"]["ends"], ends)

    def test_a_login_that_has_ended_is_paged_saying_when_it_ended(self):
        ends = self.ending(int(time.time()) - DAY)
        tick(self.home)
        self.assertEqual(self.sink.pages(), ["🙋 Needs you · Test login"])
        event, = events(self.home)
        self.assertEqual(event["text"], f"Test login owner@acme.test ended {self.at(ends)}. "
                                        "Log in again from ak.")


if __name__ == "__main__":
    unittest.main()
