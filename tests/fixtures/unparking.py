"""A Home where a Stop can unpark a login: a provider with two logins and room on every meter,
and an orchestrator seat on the second.

Black-box: Claude Code's hooks fired in a seat's pane (tests/fixtures/hookdrive.py,
tests/fixtures/akseat.py) with no harness behind it (tests/fixtures/fakeadapter.py).  Each
refusal is made by `usage.mark_exhausted` itself in a child python3, at the moment
tests/fixtures/clock.py stands it at; what is parked is read back by `ak usage --json`.  No real
login or meter is reached.
"""

import json
from pathlib import Path
import sys
import time
import unittest

from . import akconfig, fakeadapter
from .akbin import REAL_TMUX, Home
from .akseat import Seat
from .hookdrive import Hooks, conversation

TESTS = Path(__file__).resolve().parents[1]
LOGINS = ["default", "second"]
SECOND = {"AGENTKIT_ACCOUNT": "second"}     # the seat's harness, as ak launched it on that login
# A refusal of Opus on the login named that no meter showed, at the moment named.
MARK = ("import sys; sys.path[:0] = sys.argv[1:3]; from agentkit import config, usage; "
        "from fixtures.clock import Clock; usage.time = clock = Clock(None); "
        "clock.time = lambda: float(sys.argv[4]); "
        "usage.mark_exhausted(config.load(), 'anthropic', account=sys.argv[3], model='opus')")


@unittest.skipUnless(REAL_TMUX, "no tmux")
class Unparking(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"], providers={
            "anthropic": {"mode": "subscription", "accounts": LOGINS}})
        fakeadapter.install(home, claude="pass")
        now = time.time()
        room = {"provider": "anthropic", "resets": 0, "meters": [
            {"name": "session", "used": 25, "window_secs": 18000, "resets_at": now + 10800},
            {"name": "weekly_all", "used": 25, "window_secs": 604800,
             "resets_at": now + 3 * 86400}]}
        home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {"anthropic": {
            **room, "accounts": {login: room for login in LOGINS}}}})
        self.hooks = Hooks(home)

    def mark(self, login, at=None):
        """A refusal on `login` at `at`, now where None."""
        done = self.home.run(sys.executable, "-c", MARK, str(TESTS.parent), str(TESTS), login,
                             repr(time.time() if at is None else at))
        self.assertEqual(done.code, 0, done.err)

    def parked(self):
        """{login: whether it is parked}, as `ak usage --json` shows it."""
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        logins = json.loads(done.out)["providers"]["anthropic"]["accounts"]
        return {login: logins[login]["exhausted"] for login in LOGINS}

    def seat(self, name):
        """A seat whose record names the second login, and an open line in its plan: its Stop
        goes back, which says something."""
        return Seat(self.home, name, record={"account": "second"}, planned=True)

    def prompt(self, seat):
        fired = self.hooks.prompt("fix the api", seat, env=SECOND, finished=True)
        self.assertEqual(fired.code, 0, fired)

    def stop(self, seat, *said, env=SECOND, **payload):
        """The turn ends on `said`, the entries its record then holds, its Stop heard in `env`
        with `payload`; what the hook printed."""
        path = conversation(self.home, seat)
        with path.open("a") as kept:
            kept.write("".join(json.dumps(entry) + "\n" for entry in said))
        fired = self.hooks.fire("Stop", {"background_tasks": [], "transcript_path": str(path),
                                         **payload},
                                seat=seat.name, pane=seat, env=env, finished=True)
        self.assertEqual(fired.code, 0, fired)
        return fired
