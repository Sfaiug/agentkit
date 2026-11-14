"""A seat on a login its provider lists no more leaves it at the next tick, between turns, for a
listed one with room, which its record then names as its account and, its home gone too, its
home; a provider listing no `accounts` has its one usual login, and its seat stays.

On 12 Nov 2026 a subscription removed on `c`, which signs it out, kept four seats on it and five
more homed on it: the tick read its meters as empty, so never spent and never low.  Neither what
the removed login said last holds a seat there: a usage refusal the tick already handled, nor
`Please run /login` where the usual login is the one removed and its `auth` says no.
Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, beside seats of tests/fixtures/akseat.py, on fake harnesses of
fakeadapter.py and the usage readings the test writes.
"""

import json
import os
import re
import shlex
import socket
import sys
import time
import unittest
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
USED = {"max": 100, "second": 10}       # each listed login's windows, used%: one spent
# before the fake itself: the usual login, removed too, is signed out
SIGNED_OUT = """if [ "$1" = auth ] && [ -z "$AGENTKIT_ACCOUNT" ]; then
  echo "claude: no OAuth credentials in /home/acme/.claude ... run /login"; exit 1
fi
"""
REFUSED, LOGGED_OUT = "Usage limit reached", "Login expired · Please run /login"


def reading(provider, used, now):
    """A provider's or login's meters, `used`% into each window."""
    return {"provider": provider, "resets": 0, "meters": [
        {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
        {"name": "weekly_all", "used": used, "window_secs": 604800,
         "resets_at": now + 3 * 86400}]}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASeatLeavesARemovedSubscription(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, {"opus": "claude",
                              "anvil": {"harness": "claude", "provider": "brine"}},
                       providers={"anthropic": {"mode": "subscription", "accounts": list(USED)},
                                  "brine": {"mode": "subscription"}})
        self.fake = fakeadapter.install(home, claude="pass")["claude"]
        self.fake.script.write_text(self.fake.script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + SIGNED_OUT, 1))
        # the removed `pro` keeps its conversations where the usual login keeps them
        (home.path / ".claude-pro").mkdir()
        (home.path / ".claude-pro/projects").symlink_to(home.path / ".claude/projects")

    def seat(self, name, account, model="opus", said=None):
        """A seat at its prompt on `account`, its home, with a conversation of its own whose
        last turn ended on the error `said`, else on the owner's word."""
        conversation = str(uuid.uuid4())
        seat = Seat(self.home, name, model=model, record={
            "account": account, "home_account": account, "conversation": conversation})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        turn = ({"type": "assistant", "isApiErrorMessage": True, "message": {
                    "role": "assistant", "content": [{"type": "text", "text": said}]}} if said
                else {"type": "user", "message": {"role": "user", "content": "hello"}})
        self.home.write(f".claude/projects/{folder}/{conversation}.jsonl", json.dumps(turn) + "\n")
        tty = self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (time.time() - 600,) * 2)      # its terminal untouched for ten minutes
        return seat

    def record(self, name):
        record = json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())
        return record.get("account"), record.get("home_account")

    def test_one_tick_moves_each_seat_off_the_removed_login_and_homes_it_there(self):
        seat = self.seat("acme", "pro")
        self.seat("acme-login", "default", said=LOGGED_OUT)
        self.seat("acme-refused", "pro", said=REFUSED)
        self.seat("brine-fix", "pro", model="anvil")
        self.fake.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        now = time.time()
        self.home.write(".agentkit/state/seat-acme-refused.json", {
            "state": "at_prompt", "opened_at": now - 1000,
            "usage_refusal": {"line": REFUSED, "at": now - 600, "handled": True}})
        # the readings of a moment ago, which a tick reads again only once they are stale
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {
                "anthropic": {**reading("anthropic", USED["second"], now), "accounts": {
                    account: reading("anthropic", used, now) for account, used in USED.items()}},
                "brine": reading("brine", 10, now)}})
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual({name: self.record(name) for name in
                          ("acme", "acme-login", "acme-refused", "brine-fix")},
                         {"acme": ("second", "second"), "acme-login": ("second", "second"),
                          "acme-refused": ("second", "second"), "brine-fix": ("pro", "pro")})
        self.assertEqual([call["env"].get("AGENTKIT_ACCOUNT")
                          for call in self.fake.calls("interactive")], ["second"] * 3)


if __name__ == "__main__":
    unittest.main()
