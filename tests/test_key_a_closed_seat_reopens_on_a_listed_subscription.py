"""A closed seat recorded on a login its provider lists no more reopens on the first listed one
its harness opens a seat on, which its record then names as its account and its home; the
removed login is asked nothing.  Where its harness opens a seat on none of them, the reopen
refuses in one line and the record stays as it was.

On 14 Nov 2026 `ak orch acme --dry-run`, for a closed seat recorded on a removed subscription,
printed `env AGENTKIT_ACCOUNT=<removed> …`: its harness would have started signed out, on its
login screen.  Black-box: the program `AK_BIN` names runs `ak orch` from outside through
tests/fixtures/akbin.py, the seat only its record (tests/fixtures/akseat.py), on the fake
harness of fakeadapter.py, whose `auth` says no for `max`.
"""

import json
import sys
from pathlib import Path
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

SIGNED_OUT = "claude: no OAuth credentials in /home/acme/.claude-max ... run /login"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AClosedSeatReopensOnAListedSubscription(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"], providers={
            "anthropic": {"mode": "subscription", "accounts": ["max", "second"]}})
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        self.fake.answer("auth", SIGNED_OUT, 1, account="max")
        Seat(home, "acme", alive=False, record={
            "account": "pro", "home_account": "pro", "conversation": str(uuid.uuid4())})
        self.path = home.path / ".agentkit/state/session-acme.json"

    def logins(self, verb=None):
        return [call["env"].get("AGENTKIT_ACCOUNT") for call in self.fake.calls(verb)]

    def recorded(self):
        record = json.loads(self.path.read_text())
        return record["account"], record["home_account"]

    def test_it_reopens_on_the_first_listed_login_its_harness_opens_a_seat_on(self):
        done = self.home.ak("orch", "acme")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.recorded(), ("second", "second"))
        self.assertEqual(self.logins("interactive"), ["second"])
        self.assertNotIn("pro", self.logins())

    def test_with_no_listed_login_opening_a_seat_it_refuses_and_keeps_the_record(self):
        self.fake.answer("auth", SIGNED_OUT, 1, account="second")
        done = self.home.ak("orch", "acme")
        self.assertNotEqual(done.code, 0, done.out)
        self.assertEqual(len(done.err.splitlines()), 1, done.err)
        self.assertEqual(self.recorded(), ("pro", "pro"))
        self.assertEqual(self.logins("interactive"), [])
        self.assertNotIn("pro", self.logins())


if __name__ == "__main__":
    unittest.main()
